"""
Forex Telegram Bot — Befehle & Alerts.

Befehle:
  /status         Kapital, offene Trades, PnL
  /trades         Letzte 5 Trades
  /news           Heutige High-Impact Events
  /performance    Statistiken
  /pause          Trading pausieren
  /resume         Trading fortsetzen
  /set_mode       Risk Mode ändern (conservative|balanced|aggressive)
  /progress       Phase Progress (Paper→Live)
  /approve_live   Live-Trading bestätigen
  /regime         Aktuelles Market Regime pro Instrument
  /correlations   Aktive Korrelationswarnungen
  /help           Alle Befehle
"""
import logging
import threading
import time
from typing import Callable, Optional

import requests

log = logging.getLogger("forex_bot")

POLL_INTERVAL = 10


class ForexTelegramBot:
    def __init__(self, bot_state: dict):
        self._state    = bot_state
        self._offset   = 0
        self._thread   = None
        self._active   = False
        self._rm       = None        # ForexRiskManager — set via start_with_rm()
        self._mode_cb: Optional[Callable] = None  # callback to change risk mode

    def _token(self) -> str:
        from forex_bot.config import settings as cfg
        return cfg.TELEGRAM_TOKEN

    def _chat_id(self) -> str:
        from forex_bot.config import settings as cfg
        return cfg.TELEGRAM_CHAT_ID

    @property
    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self._token()}"

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        """Start polling thread without risk manager reference."""
        self._start_polling()

    def start_with_rm(self, rm):
        """Start polling thread with risk manager reference (for /progress etc.)."""
        self._rm = rm
        self._start_polling()

    def _start_polling(self):
        from forex_bot.config import settings as cfg
        if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_CHAT_ID:
            log.info("Forex Telegram Bot deaktiviert (kein Token)")
            return
        self._active = True
        if not cfg.TELEGRAM_POLLING:
            log.info("Forex Telegram Bot gestartet (alerts-only, kein Polling — "
                     "FOREX_TELEGRAM_POLLING=true für Kommandos)")
            return
        self._register_commands()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="forex-telegram"
        )
        self._thread.start()
        log.info("Forex Telegram Bot gestartet (mit Kommando-Polling)")

    def stop(self):
        self._active = False

    def send(self, text: str):
        if not self._token() or not self._chat_id():
            return
        try:
            requests.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id":    self._chat_id(),
                    "text":       text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception as e:
            log.warning(f"Telegram senden fehlgeschlagen: {e}")

    # ── Polling ───────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._active:
            try:
                self._poll()
            except Exception as e:
                log.debug(f"Telegram poll error: {e}")
            time.sleep(POLL_INTERVAL)

    def _poll(self):
        r = requests.get(
            f"{self._base_url}/getUpdates",
            params={"offset": self._offset, "timeout": 5},
            timeout=10,
        )
        for update in r.json().get("result", []):
            self._offset = update["update_id"] + 1
            msg  = update.get("message", {})
            text = (msg.get("text") or "").strip()
            if text:
                self._handle(text)

    def _handle(self, text: str):
        parts   = text.split()
        command = parts[0].lower()
        args    = parts[1:] if len(parts) > 1 else []

        handlers = {
            "/status":       lambda: self._cmd_status(),
            "/trades":       lambda: self._cmd_trades(),
            "/news":         lambda: self._cmd_news(),
            "/performance":  lambda: self._cmd_performance(),
            "/pause":        lambda: self._cmd_pause(),
            "/resume":       lambda: self._cmd_resume(),
            "/set_mode":     lambda: self._cmd_set_mode(args),
            "/progress":     lambda: self._cmd_progress(),
            "/approve_live": lambda: self._cmd_approve_live(),
            "/regime":       lambda: self._cmd_regime(),
            "/correlations": lambda: self._cmd_correlations(),
            "/macro":        lambda: self._cmd_macro(),
            "/help":         lambda: self._cmd_help(),
        }
        fn = handlers.get(command)
        if fn:
            self.send(fn())

    def _register_commands(self):
        commands = [
            ("status",       "Kapital, offene Trades, PnL"),
            ("trades",       "Letzte 5 Trades"),
            ("news",         "Heutige Wirtschafts-Events"),
            ("performance",  "Statistiken: Win-Rate, Pips, PnL"),
            ("pause",        "Trading pausieren"),
            ("resume",       "Trading fortsetzen"),
            ("set_mode",     "Risk Mode: conservative|balanced|aggressive"),
            ("progress",     "Phase Progress (Paper→Live)"),
            ("approve_live", "Live-Trading bestätigen"),
            ("regime",       "Marktregime pro Instrument"),
            ("correlations", "Aktive Korrelationswarnungen"),
            ("macro",        "Makro-Kontext: DXY, VIX, Zinsen, Carry"),
            ("help",         "Alle Befehle"),
        ]
        try:
            requests.post(
                f"{self._base_url}/setMyCommands",
                json={"commands": [{"command": c, "description": d} for c, d in commands]},
                timeout=10,
            )
        except Exception:
            pass

    # ── Command Handlers ──────────────────────────────────────────────────────

    def _cmd_status(self) -> str:
        s        = self._state
        capital  = s.get("capital", 0)
        pnl      = s.get("daily_pnl", 0)
        open_cnt = s.get("open_trades", 0)
        mode     = s.get("trading_mode", "paper").upper()
        risk_mode= s.get("risk_mode", "balanced").upper()
        paused   = "⏸ PAUSIERT" if s.get("paused") else "▶️ aktiv"

        lines = [
            "💱 <b>Forex Bot Status</b>\n",
            f"Modus:        {mode} {paused}",
            f"Risk Mode:    {risk_mode}",
            f"Kapital:      ${capital:,.2f}",
            f"Tages-PnL:    {pnl:+.2f} USD",
            f"Offene Trades:{open_cnt}",
        ]

        ml_info = s.get("ml_model_info", {})
        if ml_info.get("loaded"):
            lines.append(f"ML Modell:    geladen (F1={ml_info.get('val_f1', 0):.3f})")
        else:
            lines.append("ML Modell:    nicht geladen")

        positions = s.get("positions", [])
        if positions:
            lines.append("\n<b>Offene Positionen:</b>")
            for p in positions:
                lines.append(
                    f"  {p.get('instrument')} {p.get('direction')} "
                    f"{p.get('units')} @ {p.get('entry_price'):.5f}"
                )
        return "\n".join(lines)

    def _cmd_trades(self) -> str:
        from forex_bot.monitoring.logger import get_recent_trades
        trades = get_recent_trades(limit=5)
        if not trades:
            return "💱 <b>Letzte Trades</b>\n\nNoch keine Trades."

        lines = ["💱 <b>Letzte 5 Trades</b>\n"]
        for t in trades:
            icon = "✅" if (t.get("pnl_pips") or 0) > 0 else "❌"
            lines.append(
                f"{icon} {t.get('instrument')} {t.get('direction')} — "
                f"{t.get('pnl_pips', 0):+.1f} Pips / "
                f"${t.get('pnl_usd', 0):+.2f}"
            )
        return "\n".join(lines)

    def _cmd_news(self) -> str:
        from forex_bot.calendar.economic_calendar import get_today_events, format_events_telegram
        from forex_bot.config import settings as cfg
        events = get_today_events(cfg.NEWS_CURRENCIES)
        header = "📰 <b>Wirtschafts-Events heute</b>\n\n"
        return header + format_events_telegram(events)

    def _cmd_performance(self) -> str:
        from forex_bot.monitoring.logger import get_performance_summary
        p = get_performance_summary()
        if not p:
            return "📊 <b>Performance</b>\n\nNoch keine abgeschlossenen Trades."

        return (
            f"📊 <b>Forex Performance</b>\n\n"
            f"Trades:     {p.get('trades', 0)}\n"
            f"Win-Rate:   {p.get('win_rate', 0):.1f}%\n"
            f"Total Pips: {p.get('total_pips', 0):+.1f}\n"
            f"Total PnL:  ${p.get('total_pnl', 0):+.2f}"
        )

    def _cmd_pause(self) -> str:
        self._state["paused"] = True
        return "⏸ <b>Forex Trading pausiert.</b>\n/resume zum Fortsetzen."

    def _cmd_resume(self) -> str:
        self._state["paused"] = False
        self._state["consecutive_loss_notified"] = False
        return "▶️ <b>Forex Trading fortgesetzt.</b>"

    def _cmd_set_mode(self, args: list) -> str:
        """Change risk mode: /set_mode conservative|balanced|aggressive"""
        valid_modes = ("conservative", "balanced", "aggressive")
        if not args or args[0].lower() not in valid_modes:
            return (
                "⚙️ <b>Risk Mode setzen</b>\n\n"
                "Verwendung: /set_mode &lt;modus&gt;\n\n"
                "Verfügbare Modi:\n"
                "  conservative — 0.5% Risiko, strenge Filter\n"
                "  balanced     — 1.0% Risiko, ausgewogen\n"
                "  aggressive   — 2.0% Risiko, wenige Filter"
            )

        new_name = args[0].lower()
        # Try to call the callback in bot.py
        try:
            from forex_bot.bot import set_current_mode_manual as set_current_mode
            mode = set_current_mode(new_name)
            return (
                f"⚙️ <b>Risk Mode geändert: {mode.name.upper()}</b>\n\n"
                f"Risiko/Trade:   {mode.risk_per_trade*100:.1f}%\n"
                f"Max Trades:     {mode.max_open_trades}\n"
                f"Min Confidence: {mode.min_confidence:.0%}\n"
                f"Spread Limit:   {mode.spread_limit_pips:.1f} Pips\n"
                f"Daily Loss:     {mode.daily_loss_limit*100:.1f}%\n"
                f"MTF Required:   {'Ja' if mode.require_mtf else 'Nein'}\n"
                f"Session Strict: {'Ja' if mode.session_strict else 'Nein'}"
            )
        except Exception as e:
            return f"❌ Fehler beim Ändern des Risk Mode: {e}"

    def _cmd_progress(self) -> str:
        """Phase progress check."""
        try:
            from forex_bot.ai.phase_progress import get_forex_phase_progress
            from forex_bot.config import settings as cfg

            if self._rm is None:
                return "📊 <b>Phase Progress</b>\n\nRisk Manager nicht verfügbar."

            summary  = self._rm.summary()
            trades   = summary.get("trades", 0)
            sharpe   = summary.get("sharpe", 0.0)
            win_rate = summary.get("win_rate", 0.0)
            drawdown = summary.get("drawdown_pct", 0.0)
            mode_name= self._state.get("risk_mode", "balanced")

            # ML F1
            ml_info = self._state.get("ml_model_info", {})
            model_f1 = ml_info.get("val_f1", 0.0) if ml_info.get("loaded") else 0.0

            progress = get_forex_phase_progress(
                trades=trades,
                sharpe=sharpe,
                win_rate=win_rate,
                drawdown=drawdown,
                model_f1=model_f1,
                mode=mode_name,
            )
            return progress.telegram_summary()
        except Exception as e:
            return f"❌ Phase Progress Fehler: {e}"

    def _cmd_approve_live(self) -> str:
        """Confirm live trading transition."""
        try:
            from forex_bot.ai.phase_progress import get_forex_phase_progress
            from forex_bot.config import settings as cfg

            if self._rm is None:
                return "❌ Risk Manager nicht verfügbar."

            summary  = self._rm.summary()
            ml_info  = self._state.get("ml_model_info", {})
            model_f1 = ml_info.get("val_f1", 0.0) if ml_info.get("loaded") else 0.0

            progress = get_forex_phase_progress(
                trades=    summary.get("trades", 0),
                sharpe=    summary.get("sharpe", 0.0),
                win_rate=  summary.get("win_rate", 0.0),
                drawdown=  summary.get("drawdown_pct", 0.0),
                model_f1=  model_f1,
                mode=      self._state.get("risk_mode", "balanced"),
            )

            if not progress.all_passed:
                return (
                    f"⛔ <b>Live-Freigabe verweigert</b>\n\n"
                    f"{progress.recommendation}\n\n"
                    f"Erfüllt: {progress.passed_count}/{progress.total_checks}"
                )

            return (
                f"✅ <b>Live-Trading freigegeben!</b>\n\n"
                f"Alle {progress.total_checks} Kriterien erfüllt.\n"
                f"Setze FOREX_TRADING_MODE=live in der .env und "
                f"starte den Bot neu."
            )
        except Exception as e:
            return f"❌ Fehler: {e}"

    def _cmd_regime(self) -> str:
        """Show current market regime per instrument."""
        regime_map = self._state.get("regime", {})
        if not regime_map:
            return (
                "📈 <b>Market Regime</b>\n\n"
                "Noch keine Regime-Daten. Warte auf den nächsten Zyklus."
            )

        icons = {
            "TREND_UP":        "📈",
            "TREND_DOWN":      "📉",
            "SIDEWAYS":        "➡️",
            "HIGH_VOLATILITY": "⚡",
        }
        lines = ["📊 <b>Market Regime</b>\n"]
        for instrument, regime in sorted(regime_map.items()):
            icon = icons.get(regime, "❓")
            lines.append(f"{icon} {instrument}: <b>{regime}</b>")
        return "\n".join(lines)

    def _cmd_correlations(self) -> str:
        """Show active correlation warnings for open positions."""
        try:
            from forex_bot.risk.correlation import get_correlation, correlation_adjusted_exposure
            from forex_bot.config import settings as cfg

            if self._rm is None:
                return "❌ Risk Manager nicht verfügbar."

            open_trades = self._rm.get_open_trades()
            if not open_trades:
                return "🔗 <b>Korrelationen</b>\n\nKeine offenen Trades."

            lines = ["🔗 <b>Korrelations-Analyse</b>\n"]
            mode_name = self._state.get("risk_mode", "balanced")
            from forex_bot.risk.risk_modes import get_mode
            mode = get_mode(mode_name)

            for i, t1 in enumerate(open_trades):
                for t2 in open_trades[i+1:]:
                    corr = get_correlation(t1.instrument, t2.instrument)
                    if abs(corr) >= 0.60:
                        same_dir = t1.direction == t2.direction
                        # positive corr + same dir = amplified risk
                        if corr > 0 and same_dir:
                            lines.append(
                                f"⚠️ {t1.instrument} {t1.direction} ↔ "
                                f"{t2.instrument} {t2.direction}: "
                                f"corr={corr:+.2f} (amplifiziert)"
                            )
                        elif corr > 0 and not same_dir:
                            lines.append(
                                f"✅ {t1.instrument} {t1.direction} ↔ "
                                f"{t2.instrument} {t2.direction}: "
                                f"corr={corr:+.2f} (teilweise Hedge)"
                            )
                        elif corr < 0 and same_dir:
                            lines.append(
                                f"✅ {t1.instrument} {t1.direction} ↔ "
                                f"{t2.instrument} {t2.direction}: "
                                f"corr={corr:+.2f} (teilweise Hedge)"
                            )
                        else:
                            lines.append(
                                f"⚠️ {t1.instrument} {t1.direction} ↔ "
                                f"{t2.instrument} {t2.direction}: "
                                f"corr={corr:+.2f} (neg. korr., amplifiziert)"
                            )

            if len(lines) == 1:
                lines.append("Keine signifikanten Korrelationen (|corr| < 0.60).")

            return "\n".join(lines)

        except Exception as e:
            return f"❌ Korrelations-Fehler: {e}"

    def _cmd_macro(self) -> str:
        """Show current macro context: DXY, VIX, rates, carry signals."""
        macro = self._state.get("macro", {})
        if not macro:
            try:
                from forex_bot.ai.macro_signals import get_macro_context
                macro = get_macro_context()
            except Exception as e:
                return f"❌ Macro-Daten nicht verfügbar: {e}"

        usd_regime  = macro.get("usd_regime",  "NEUTRAL")
        risk_regime = macro.get("risk_regime", "UNCERTAIN")
        vix         = macro.get("vix",         0)
        dxy         = macro.get("usd_index",   0)
        spread      = macro.get("yield_spread", 0)
        cached      = macro.get("cached", False)
        ts          = macro.get("timestamp", "")[:16]

        icons_usd  = {"STRONG": "💪", "WEAK": "⬇️", "NEUTRAL": "➡️"}
        icons_risk = {"ON": "🟢", "OFF": "🔴", "UNCERTAIN": "🟡"}

        lines = [
            f"🌍 <b>Makro-Kontext</b>{'  (cached)' if cached else ''}\n",
            f"USD Regime:   {icons_usd.get(usd_regime, '')} {usd_regime}  (DXY={dxy})",
            f"Risk Regime:  {icons_risk.get(risk_regime, '')} {risk_regime}",
            f"VIX:          {vix}",
            f"2y-10y Spread:{spread:+.2f}%",
        ]

        rates = macro.get("rates", {})
        if rates:
            lines.append("\n<b>Leitzinsen:</b>")
            for ccy, rate in sorted(rates.items()):
                lines.append(f"  {ccy}: {rate:.2f}%")

        carry = macro.get("carry", {})
        if carry:
            top_carry = sorted(carry.items(), key=lambda x: abs(x[1].get("differential", 0)), reverse=True)[:5]
            lines.append("\n<b>Top Carry Signale:</b>")
            for pair, info in top_carry:
                sig  = info.get("carry_signal", "NEUTRAL")
                diff = info.get("differential", 0)
                icon = "📈" if sig == "BUY" else ("📉" if sig == "SELL" else "➡️")
                lines.append(f"  {icon} {pair}: {diff:+.2f}% → {sig}")

        lines.append(f"\n<i>Stand: {ts} UTC</i>")
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return (
            "💱 <b>Forex Bot Befehle</b>\n\n"
            "/status         — Kapital &amp; offene Trades\n"
            "/trades         — Letzte 5 Trades\n"
            "/news           — Heutige News-Events\n"
            "/performance    — Statistiken\n"
            "/pause          — Trading pausieren\n"
            "/resume         — Trading fortsetzen\n"
            "/set_mode &lt;m&gt; — Risk Mode (conservative|balanced|aggressive)\n"
            "/progress       — Phase Progress (Paper→Live)\n"
            "/approve_live   — Live-Trading freigeben\n"
            "/regime         — Marktregime pro Instrument\n"
            "/correlations   — Korrelationscheck offener Positionen\n"
            "/macro          — Makro-Kontext: DXY, VIX, Zinsen, Carry"
        )

    # ── Alert-Helpers ─────────────────────────────────────────────────────────

    def alert_trade_opened(self, instrument: str, direction: str, units: int,
                           entry: float, sl: float, tp: float, reason: str):
        icon = "📈" if direction == "BUY" else "📉"
        self.send(
            f"{icon} <b>Trade eröffnet</b>\n\n"
            f"Paar:        {instrument}\n"
            f"Richtung:    {direction} ({units:,} Units)\n"
            f"Einstieg:    {entry:.5f}\n"
            f"Stop Loss:   {sl:.5f}\n"
            f"Take Profit: {tp:.5f}\n"
            f"<i>{reason}</i>"
        )

    def alert_trade_closed(self, instrument: str, direction: str,
                           pnl_pips: float, pnl_usd: float, reason: str = ""):
        icon = "✅" if pnl_pips > 0 else "❌"
        self.send(
            f"{icon} <b>Trade geschlossen</b>\n\n"
            f"Paar:   {instrument} {direction}\n"
            f"PnL:    {pnl_pips:+.1f} Pips / ${pnl_usd:+.2f}\n"
            f"<i>{reason}</i>"
        )

    def alert_news_pause(self, reason: str):
        self.send(f"📰 <b>News Pause</b>\n\n{reason}\nKein Trading für ±{reason}.")

    def alert_circuit_breaker(self, drawdown_pct: float):
        self.send(
            f"🚨 <b>Circuit Breaker aktiv!</b>\n\n"
            f"Drawdown: {drawdown_pct:.1f}%\n"
            f"Trading gestoppt. Manueller /resume nötig."
        )
