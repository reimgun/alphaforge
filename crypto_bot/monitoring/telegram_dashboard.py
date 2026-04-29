"""
Telegram Dashboard — interaktives Kommando-Interface.

Unterstützte Befehle:
  /status   → Aktuelle Position, Kapital, heutiger PnL
  /trades   → Letzte 5 Trades
  /model    → ML-Modell-Info
  /stop     → Bot graceful stoppen
  /help     → Alle Befehle

Läuft als Background-Thread, blockiert den Bot nicht.
Polling-Intervall: 10 Sekunden.
"""
import threading
import time
import requests
from datetime import datetime, timezone
from crypto_bot.monitoring.logger import log
from crypto_bot.config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

POLL_INTERVAL = 10  # Sekunden


class TelegramDashboard:
    def __init__(self, bot_state: dict):
        """
        bot_state: Gemeinsames dict das der Bot befüllt:
          {
            "capital": float,
            "daily_pnl": float,
            "position": Position | None,
            "running": bool,
            "stop_requested": bool,
            "rm_summary": dict,
          }
        """
        self._state    = bot_state
        self._offset   = 0
        self._thread   = None
        self._active   = False
        self._base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        self._exposure_ctrl = None   # wird via register_exposure_controller gesetzt

    def register_exposure_controller(self, ctrl):
        """Bindet den GlobalExposureController für Telegram-Steuerung ein."""
        self._exposure_ctrl = ctrl

    def start(self):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            log.info("Telegram-Dashboard deaktiviert (kein Token konfiguriert)")
            return

        self._active = True
        self._register_commands()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="telegram-dashboard")
        self._thread.start()
        log.info("Telegram-Dashboard gestartet")

    def _register_commands(self):
        """Registriert alle Befehle im Telegram-Menü (erscheint beim Tippen von /)."""
        commands = [
            ("start",              "Bot starten / aus Pause fortsetzen"),
            ("status",             "Aktueller Stand: Kapital, Position, PnL"),
            ("performance",        "Statistiken: Sharpe, Win-Rate, Drawdown"),
            ("trades",             "Letzte 5 Trades"),
            ("open_positions",     "Offene Position Details"),
            ("fear_greed",         "Aktueller Fear & Greed Index"),
            ("sentiment",          "Aktuelles News-Sentiment"),
            ("model",              "ML-Modell Info & Konfidenz"),
            ("rejections",         "Letzte Trade-Ablehnungen"),
            ("pause",              "Trading pausieren"),
            ("resume",             "Trading fortsetzen"),
            ("retrain_models",     "ML-Modell neu trainieren"),
            ("switch_safe_mode",   "Safe Mode ein/ausschalten"),
            ("set_mode",           "Risk Mode: conservative / balanced / aggressive"),
            ("progress",           "Fortschritt Paper→Testnet→Live anzeigen"),
            ("approve_live",       "Live-Trading bestätigen (nach Kriterien-Check)"),
            ("exposure_status",    "Kapital-Deployment & Krisenindex"),
            ("risk_off_mode",      "Manuell Risk-Off aktivieren (kein BUY)"),
            ("resume_trading",     "Risk-Off deaktivieren"),
            ("set_max_exposure",   "Max. Kapital-Deployment setzen (0.0–1.0)"),
            ("stop",               "Bot sauber stoppen"),
            ("emergency_shutdown", "NOTFALL-STOPP — sofort alles stoppen"),
            ("help",               "Alle Befehle anzeigen"),
        ]
        try:
            import requests as _req
            _req.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
                json={"commands": [{"command": c, "description": d} for c, d in commands]},
                timeout=10,
            )
        except Exception:
            pass

    def stop(self):
        self._active = False

    def _poll_loop(self):
        while self._active:
            try:
                self._process_updates()
            except Exception as e:
                log.debug(f"Telegram-Poll-Fehler: {e}")
            time.sleep(POLL_INTERVAL)

    def _get_updates(self) -> list:
        try:
            resp = requests.get(
                f"{self._base_url}/getUpdates",
                params={"offset": self._offset, "timeout": 5},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("result", [])
        except Exception:
            pass
        return []

    def _send(self, text: str):
        if not TELEGRAM_CHAT_ID:
            return
        try:
            requests.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            log.debug(f"Telegram-Send-Fehler: {e}")

    def _process_updates(self):
        for update in self._get_updates():
            self._offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = msg.get("text", "").strip().lower()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # Nur eigenen Chat beantworten
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue

            if text == "/start":
                self._handle_start()
            elif text == "/help":
                self._send(self._build_help())
            elif text == "/status":
                self._send(self._build_status())
            elif text == "/trades":
                self._send(self._build_trades())
            elif text == "/model":
                self._send(self._build_model_info())
            elif text == "/performance":
                self._send(self._build_performance())
            elif text == "/open_positions":
                self._send(self._build_open_positions())
            elif text in ("/retrain", "/retrain_models"):
                self._send("🔄 Modell-Retraining wird gestartet...")
                self._state["retrain_requested"] = True
                log.info("Retraining via Telegram angefordert")
            elif text == "/switch_safe_mode":
                self._toggle_safe_mode()
            elif text == "/pause":
                self._state["paused"] = True
                self._send("⏸ <b>Bot pausiert</b>\nKein Trading bis /resume.")
                log.info("Bot pausiert via Telegram")
            elif text == "/resume":
                self._state["paused"] = False
                self._send("▶️ <b>Bot fortgesetzt</b>\nTrading wieder aktiv.")
                log.info("Bot fortgesetzt via Telegram")
            elif text == "/emergency_shutdown":
                self._state["stop_requested"] = True
                self._state["emergency_stop"] = True
                self._send("🚨 <b>NOTFALL-STOPP</b>\nBot wird sofort gestoppt!")
                log.critical("NOTFALL-STOPP via Telegram")
            elif text == "/stop":
                self._state["stop_requested"] = True
                self._send("⛔ <b>Stop-Befehl empfangen</b>\nBot wird nach aktuellem Zyklus sauber beendet.")
                log.warning("Stop-Befehl via Telegram empfangen")
            elif text == "/fear_greed":
                self._send(self._build_fear_greed())
            elif text == "/sentiment":
                self._send(self._build_sentiment())
            elif text == "/approve_live":
                self._handle_approve_live()
            elif text == "/rejections":
                self._send(self._build_rejections())
            elif text in ("/progress", "/phase"):
                self._send(self._build_progress())
            elif text == "/exposure_status":
                self._send(self._build_exposure_status())
            elif text == "/risk_off_mode":
                self._handle_risk_off(True)
            elif text == "/resume_trading":
                self._handle_risk_off(False)
            elif text.startswith("/set_max_exposure"):
                self._handle_set_max_exposure(text)
            elif text.startswith("/set_mode"):
                self._handle_set_mode(text)
            elif text.startswith("/"):
                self._send(self._build_help())

    def _build_fear_greed(self) -> str:
        fg = self._state.get("fear_greed")
        if not fg:
            return "📊 Fear & Greed Index nicht verfügbar (FEATURE_FEAR_GREED=false?)"
        icons = {
            "Extreme Fear": "😱", "Fear": "😨", "Neutral": "😐",
            "Greed": "😏", "Extreme Greed": "🤑",
        }
        icon = icons.get(fg.get("label", ""), "📊")
        warning = "\n⚠️ <b>Kein neuer BUY</b> (Extreme Greed blockiert)" if fg.get("block_buy") else ""
        return (
            f"{icon} <b>Fear & Greed Index</b>\n\n"
            f"Wert:     <b>{fg.get('value', '?')}/100</b>\n"
            f"Status:   {fg.get('label', '?')}\n"
            f"Faktor:   ×{fg.get('position_factor', 1.0):.2f} auf Positionsgröße"
            f"{warning}"
        )

    def _build_sentiment(self) -> str:
        s = self._state.get("news_sentiment")
        if not s:
            return "📰 News Sentiment nicht verfügbar (FEATURE_NEWS_SENTIMENT=false?)"
        label_icons = {
            "STRONGLY_BEARISH": "🔴", "BEARISH": "🟠", "NEUTRAL": "⚪",
            "BULLISH": "🟢", "STRONGLY_BULLISH": "💚",
        }
        icon = label_icons.get(s.get("label", ""), "⚪")
        headlines = s.get("headlines", [])
        headlines_text = ""
        if headlines:
            headlines_text = "\n\n<b>Aktuelle Schlagzeilen:</b>\n" + "\n".join(f"• {h}" for h in headlines[:3])
        warning = "\n⚠️ <b>Kein neuer BUY</b> (stark bearishes Sentiment)" if s.get("block_buy") else ""
        return (
            f"{icon} <b>News Sentiment</b>\n\n"
            f"Score:    <b>{s.get('score', 0):+.2f}</b> ({s.get('label', '?')})\n"
            f"Faktor:   ×{s.get('position_factor', 1.0):.2f}\n"
            f"Methode:  {s.get('method', '?')}\n\n"
            f"📝 {s.get('summary', '–')}"
            f"{headlines_text}"
            f"{warning}"
        )

    def _build_status(self) -> str:
        capital   = self._state.get("capital", 0)
        daily_pnl = self._state.get("daily_pnl", 0)
        position  = self._state.get("position")
        now       = datetime.now(timezone.utc).strftime("%H:%M UTC")

        pos_text = "Keine offene Position"
        if position:
            from crypto_bot.config.settings import SYMBOL
            unreal = self._state.get("unrealized_pnl", 0)
            pos_text = (
                f"📌 {SYMBOL}\n"
                f"  Entry: ${position.entry_price:,.2f}\n"
                f"  Stop:  ${position.stop_loss:,.2f}\n"
                f"  Unr. PnL: {unreal:+.2f} USDT"
            )

        # Fear & Greed + Sentiment Zeile
        fg = self._state.get("fear_greed")
        ns = self._state.get("news_sentiment")
        market_ctx = ""
        if fg:
            fg_icons = {"Extreme Fear": "😱", "Fear": "😨", "Neutral": "😐", "Greed": "😏", "Extreme Greed": "🤑"}
            market_ctx += f"\n{fg_icons.get(fg.get('label',''), '📊')} F&G: {fg.get('value','?')} — {fg.get('label','?')}"
        if ns:
            s_icons = {"STRONGLY_BEARISH": "🔴", "BEARISH": "🟠", "NEUTRAL": "⚪", "BULLISH": "🟢", "STRONGLY_BULLISH": "💚"}
            market_ctx += f"\n{s_icons.get(ns.get('label',''), '⚪')} Sentiment: {ns.get('label','?')} ({ns.get('score',0):+.2f})"

        # Pause-Status
        pause_hint = "\n⏸ <b>BOT PAUSIERT</b> — /resume zum Fortsetzen" if self._state.get("paused") else ""

        icon = "📈" if daily_pnl >= 0 else "📉"
        return (
            f"{icon} <b>Bot Status [{now}]</b>\n\n"
            f"💰 Kapital: <b>${capital:,.2f}</b>\n"
            f"📊 Tages-PnL: <b>{daily_pnl:+.2f} USDT</b>\n"
            f"{market_ctx}\n\n"
            f"{pos_text}"
            f"{pause_hint}"
        )

    def _build_trades(self) -> str:
        try:
            from crypto_bot.monitoring.logger import get_recent_trades
            trades = get_recent_trades(5)
            if not trades:
                return "Noch keine Trades aufgezeichnet."

            lines = ["<b>Letzte 5 Trades:</b>\n"]
            for t in trades:
                icon = "✅" if (t.get("pnl") or 0) >= 0 else "🔴"
                lines.append(
                    f"{icon} {t.get('side','?').upper()} | "
                    f"PnL: {(t.get('pnl') or 0):+.2f} USDT | "
                    f"{t.get('reason','')}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Fehler beim Laden der Trades: {e}"

    def _build_performance(self) -> str:
        try:
            from crypto_bot.monitoring.logger import get_performance_summary
            s = get_performance_summary()
            rm = self._state.get("rm_summary", {})
            return (
                f"📊 <b>Performance</b>\n\n"
                f"Trades total:  {s.get('total_trades', 0)}\n"
                f"Win / Loss:    {s.get('wins', 0)} / {s.get('losses', 0)}\n"
                f"Win-Rate:      {rm.get('win_rate', 0):.1f}%\n"
                f"Gesamt PnL:    {(s.get('total_pnl') or 0):+.2f} USDT\n"
                f"Ø Gewinn:      {(s.get('avg_win') or 0):+.2f} USDT\n"
                f"Ø Verlust:     {(s.get('avg_loss') or 0):+.2f} USDT\n"
                f"Profit Factor: {rm.get('profit_factor', 0):.2f}\n"
                f"Sortino:       {rm.get('sortino', 0):.2f}\n"
                f"Kapital:       ${rm.get('final_capital', self._state.get('capital', 0)):,.2f}"
            )
        except Exception as e:
            return f"Performance-Fehler: {e}"

    def _build_open_positions(self) -> str:
        position = self._state.get("position")
        if not position:
            return "📭 <b>Keine offene Position</b>"
        from crypto_bot.config.settings import SYMBOL
        current_price = self._state.get("current_price", position.entry_price)
        unreal = (current_price - position.entry_price) * position.quantity
        unreal_pct = (current_price - position.entry_price) / position.entry_price * 100
        return (
            f"📌 <b>Offene Position — {SYMBOL}</b>\n\n"
            f"Entry:     ${position.entry_price:,.2f}\n"
            f"Aktuell:   ${current_price:,.2f}\n"
            f"Menge:     {position.quantity:.6f}\n"
            f"Stop-Loss: ${position.stop_loss:,.2f}\n"
            f"Take-Profit: ${position.take_profit:,.2f}\n"
            f"Unreal. PnL: {unreal:+.2f} USDT ({unreal_pct:+.2f}%)"
        )

    def _handle_start(self):
        """
        /start — Verhalten je nach Bot-Zustand:
          - Bot pausiert  → fortsetzen (wie /resume)
          - Bot läuft     → Statusmeldung zurückgeben
          - Bot gestoppt  → start_requested setzen (bot.py oder API starten ihn)
        """
        if self._state.get("paused"):
            self._state["paused"] = False
            self._send(
                "▶️ <b>Bot fortgesetzt</b>\n"
                "Trading wieder aktiv."
            )
            log.info("Bot via Telegram /start aus Pause fortgesetzt")
        elif self._state.get("running"):
            capital = self._state.get("capital", 0)
            self._send(
                f"✅ <b>Bot läuft bereits</b>\n"
                f"💰 Kapital: ${capital:,.2f}\n"
                f"Nutze /status für Details."
            )
        else:
            self._state["start_requested"] = True
            self._send(
                "🚀 <b>Bot-Start angefordert</b>\n"
                "Der Bot wird gestartet sobald der Prozess bereit ist."
            )
            log.info("Bot-Start via Telegram /start angefordert")

    def _handle_approve_live(self):
        """
        /approve_live — Bestätigt den Wechsel von Paper zu Live-Trading.
        Nur aktiv wenn bot_state["live_transition_pending"] = True.
        """
        if not self._state.get("live_transition_pending"):
            self._send(
                "ℹ️ <b>Kein Live-Wechsel ausstehend</b>\n\n"
                "Der Bot hat die Performance-Kriterien noch nicht erreicht\n"
                "oder der Wechsel wurde bereits vollzogen."
            )
            return

        self._state["approve_live"] = True
        self._send(
            "✅ <b>Live-Trading bestätigt!</b>\n\n"
            "Der Bot wechselt beim nächsten Zyklus zu Live-Trading.\n"
            "⚠️ Ab jetzt wird mit echtem Kapital gehandelt.\n\n"
            "Zum Stoppen: /emergency_shutdown"
        )
        log.warning("Live-Transition via Telegram /approve_live bestätigt")

    def _toggle_safe_mode(self):
        current = self._state.get("safe_mode", False)
        self._state["safe_mode"] = not current
        status = "aktiviert 🛡️" if not current else "deaktiviert"
        self._send(f"🔧 <b>Safe Mode {status}</b>\n"
                   f"Positionsgröße {'auf 50% reduziert' if not current else 'wieder normal'}.")
        log.info(f"Safe Mode via Telegram: {not current}")

    def _build_rejections(self) -> str:
        try:
            from crypto_bot.monitoring.logger import get_recent_rejections
            rejs = get_recent_rejections(5)
            if not rejs:
                return "📭 <b>Keine abgelehnten Trades aufgezeichnet</b>"
            lines = ["🚫 <b>Letzte 5 Trade-Ablehnungen:</b>\n"]
            for r in rejs:
                lines.append(
                    f"⛔ {r.get('signal','?')} | "
                    f"${(r.get('price') or 0):,.0f} | "
                    f"{r.get('reason','?')}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Fehler: {e}"

    def _handle_set_mode(self, text: str):
        """
        /set_mode conservative|balanced|aggressive
        Setzt Risk Personality Mode zur Laufzeit.
        """
        parts = text.strip().split()
        if len(parts) < 2 or parts[1] not in ("conservative", "balanced", "aggressive"):
            self._send(
                "❌ Ungültiger Modus.\n"
                "Verwendung: /set_mode conservative|balanced|aggressive\n\n"
                "  conservative — kleines Risiko, enger Drawdown-Stopp\n"
                "  balanced     — Standard (2% / 20%)\n"
                "  aggressive   — höheres Risiko, weiterer Drawdown-Stopp"
            )
            return
        mode = parts[1]
        import os
        import crypto_bot.config.settings as cfg
        os.environ["RISK_MODE"] = mode
        cfg.RISK_MODE = mode
        self._state["risk_mode"] = mode
        icons = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}
        self._send(
            f"{icons.get(mode, '🔧')} <b>Risk Mode: {mode.upper()}</b>\n"
            f"Positionsgröße und Drawdown-Limits angepasst."
        )
        log.info(f"Risk Mode via Telegram gesetzt: {mode}")

    def _process_updates_with_text(self, text: str, state: dict):
        """Hilfsmethode für Tests: verarbeitet einen einzelnen Befehl."""
        if text == "/emergency_shutdown":
            state["stop_requested"] = True
            state["emergency_stop"] = True
            self._send("🚨 <b>NOTFALL-STOPP</b>")

    def _build_model_info(self) -> str:
        try:
            from crypto_bot.ai.retrainer import AutoRetrainer
            info = AutoRetrainer().get_model_info()
            return (
                f"🤖 <b>ML-Modell</b>\n\n"
                f"Status:   {info.get('status','?')}\n"
                f"Val F1:   {info.get('val_f1','?')}\n"
                f"Trainiert:{info.get('trained_on','?')}\n"
                f"Features: {info.get('features','?')}\n"
                f"Größe:    {info.get('file_size','?')}"
            )
        except Exception as e:
            return f"Modell-Info Fehler: {e}"

    def _build_progress(self) -> str:
        try:
            from crypto_bot.ai.confidence_monitor import get_phase_progress, TESTNET_SUGGESTION_PCT
            from crypto_bot.monitoring.logger import get_recent_trades, get_performance_summary
            from crypto_bot.config.settings import TRADING_MODE

            perf            = get_performance_summary()
            all_trades_list = get_recent_trades(limit=9999)
            trade_count     = len(all_trades_list)
            sharpe      = perf.get("sharpe_ratio", 0.0) or 0.0
            win_rate    = perf.get("win_rate", 0.0) or 0.0
            drawdown    = perf.get("max_drawdown", 0.0) or 0.0
            try:
                from crypto_bot.ai.retrainer import AutoRetrainer
                f1 = AutoRetrainer().get_model_info().get("val_f1", 0.0) or 0.0
            except Exception:
                f1 = 0.0

            # Datum des ersten Trades für ETA-Schätzung
            first_trade_date = None
            if all_trades_list:
                oldest = min(
                    (t.get("created_at") or t.get("timestamp") or "" for t in all_trades_list),
                    default=None,
                )
                if oldest:
                    first_trade_date = oldest

            prog = get_phase_progress(
                paper_trades=trade_count, sharpe=sharpe,
                win_rate_pct=win_rate, max_drawdown_pct=drawdown,
                model_f1=f1, trading_mode=TRADING_MODE,
                first_trade_date=first_trade_date,
            )

            phase_icon = {"PAPER": "📄", "TESTNET": "🧪", "LIVE": "🚀"}.get(prog.phase, "📊")
            bar_filled = int(prog.overall_pct / 5)   # 20 Zeichen = 100%
            bar_empty  = 20 - bar_filled
            bar = "█" * bar_filled + "░" * bar_empty

            lines = [
                f"{phase_icon} <b>Trading Phase: {prog.phase} → {prog.next_phase}</b>\n",
                f"Gesamt: [{bar}] <b>{prog.overall_pct:.0f}%</b>",
                f"{prog.passed_count}/{prog.total_count} Kriterien erfüllt",
                f"📝 {prog.next_phase_hint}\n",
                "<b>Kriterien:</b>",
            ]
            for c in prog.criteria:
                icon    = "✅" if c.passed else "⏳"
                bar_c   = "█" * int(c.pct / 10) + "░" * (10 - int(c.pct / 10))
                lines.append(
                    f"{icon} {c.label}: {c.current}{c.unit} / {c.target}{c.unit}"
                    f"  [{bar_c}] {c.pct:.0f}%"
                )

            if prog.eta_label:
                lines.append(f"\n⏱ <i>{prog.eta_label}</i>")

            if trade_count == 0:
                running = self._state.get("running", True)
                status_icon = "✅ läuft" if running else "⛔ gestoppt"
                last_cycle  = self._state.get("last_cycle_time")
                cycle_str   = ""
                if last_cycle:
                    try:
                        from datetime import datetime, timezone
                        if isinstance(last_cycle, str):
                            lc_dt = datetime.fromisoformat(last_cycle.replace("Z", "+00:00"))
                        else:
                            lc_dt = last_cycle
                        mins_ago = int((datetime.now(timezone.utc) - lc_dt.astimezone(timezone.utc)).total_seconds() / 60)
                        cycle_str = f" · letzter Zyklus vor {mins_ago} Min."
                    except Exception:
                        pass
                lines.append(
                    f"\nℹ️ <i>Bot {status_icon}{cycle_str}\n"
                    f"Warum kein Trade?\n"
                    f"• Bot kauft nur bei passendem Marktregime (Bull/Trend)\n"
                    f"• ML-Modell muss ausreichend Konfidenz haben\n"
                    f"• Risiko- und Drawdown-Grenzen müssen eingehalten sein\n"
                    f"In ruhigen oder bärischen Phasen kann das Tage dauern — das ist gewollt.</i>"
                )

            if prog.overall_pct >= TESTNET_SUGGESTION_PCT and prog.phase == "PAPER":
                lines.append(
                    "\n🧪 <b>Testnet empfohlen!</b>\n"
                    "Setze in .env: TRADING_MODE=testnet\n"
                    "Keys von: testnet.binance.vision"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ Fortschritt nicht verfügbar: {e}"

    def _build_exposure_status(self) -> str:
        exp = self._state.get("exposure", {})
        if not exp:
            return "ℹ️ <b>Exposure Controller</b>\n\nNoch keine Daten (erster Zyklus läuft noch)."

        mode          = exp.get("mode", "?")
        factor        = exp.get("factor", 1.0)
        crisis        = exp.get("crisis_score", 0.0)
        recovery      = exp.get("recovery_score", 0.0)
        risk_off      = exp.get("risk_off", False)
        reason        = exp.get("reason", "")
        alloc         = exp.get("allocation", {})

        mode_icon = {
            "NORMAL": "🟢", "CAUTIOUS": "🟡",
            "RISK_OFF": "🔴", "EMERGENCY": "🚨", "RECOVERY": "🔵"
        }.get(mode, "⚪")

        lines = [
            f"📊 <b>Global Exposure Controller</b>\n",
            f"{mode_icon} Modus: <b>{mode}</b>",
            f"💰 Kapital-Deployment: <b>{factor:.0%}</b>",
            f"⚠️ Krisenindex: {crisis:.0%}",
            f"🔄 Recovery-Index: {recovery:.0%}",
            f"🛑 Risk-Off: {'<b>AKTIV</b>' if risk_off else 'nein'}",
            f"📝 Grund: {reason}",
        ]
        if alloc:
            lines += [
                "\n<b>Strategie-Allokation:</b>",
                f"  Trend:          {alloc.get('trend', 0):.0%}",
                f"  Mean Reversion: {alloc.get('mean_reversion', 0):.0%}",
                f"  Volatility:     {alloc.get('volatility', 0):.0%}",
                f"  Arbitrage:      {alloc.get('arbitrage', 0):.0%}",
            ]
        return "\n".join(lines)

    def _handle_risk_off(self, activate: bool):
        if self._exposure_ctrl is None:
            self._send("⚠️ Global Exposure Controller ist nicht aktiv (FEATURE_GLOBAL_EXPOSURE=false).")
            return
        self._exposure_ctrl.set_risk_off(activate)
        if activate:
            self._send(
                "🔴 <b>Risk-Off Modus aktiviert</b>\n\n"
                "Keine neuen BUY-Orders bis du /resume_trading sendest.\n"
                "Offene Positionen werden weiter gehalten."
            )
        else:
            self._send(
                "🟢 <b>Trading fortgesetzt</b>\n\n"
                "Manueller Risk-Off deaktiviert.\n"
                "Exposure Controller läuft wieder automatisch."
            )

    def _handle_set_max_exposure(self, text: str):
        if self._exposure_ctrl is None:
            self._send("⚠️ Global Exposure Controller ist nicht aktiv.")
            return
        parts = text.split()
        if len(parts) < 2:
            self._send("Verwendung: /set_max_exposure 0.5\n(0.0 = kein Trading, 1.0 = voll)")
            return
        try:
            value = float(parts[1])
            self._exposure_ctrl.set_max_exposure(value)
            self._send(f"✅ Max-Exposure auf <b>{value:.0%}</b> gesetzt.")
        except ValueError:
            self._send("⚠️ Ungültiger Wert. Beispiel: /set_max_exposure 0.5")

    def _build_help(self) -> str:
        return (
            "<b>Trading Bot — Befehle</b>\n\n"
            "/start                — Bot starten / aus Pause fortsetzen\n"
            "/stop                 — Bot graceful stoppen\n"
            "/pause                — Trading pausieren\n"
            "/resume               — Trading fortsetzen\n"
            "/status               — Aktueller Stand (Kapital, Position)\n"
            "/trades               — Letzte 5 Trades\n"
            "/performance          — Detaillierte Statistiken\n"
            "/open_positions       — Offene Position Details\n"
            "/model                — ML-Modell Info\n"
            "/rejections           — Letzte Trade-Ablehnungen\n"
            "/retrain_models       — Modell neu trainieren\n"
            "/switch_safe_mode     — Safe Mode ein/aus\n"
            "/set_mode &lt;mode&gt; — Risk Mode setzen (conservative/balanced/aggressive)\n"
            "/fear_greed           — Aktueller Fear & Greed Index\n"
            "/sentiment            — Aktuelles News-Sentiment\n"
            "/progress             — Fortschritt Paper→Testnet→Live\n"
            "/approve_live         — Live-Trading bestätigen (nach Kriterien-Check)\n"
            "/exposure_status      — Kapital-Deployment & Krisenindex\n"
            "/risk_off_mode        — Manuell Risk-Off aktivieren (kein BUY)\n"
            "/resume_trading       — Risk-Off deaktivieren\n"
            "/set_max_exposure     — Max. Kapital-Deployment setzen (0.0–1.0)\n"
            "/emergency_shutdown   — Sofort stoppen\n"
            "/help                 — Diese Hilfe"
        )
