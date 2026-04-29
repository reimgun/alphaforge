"""
Forex Bot — Hauptschleife.

Zyklus (stündlich):
  0. Midnight reset (daily tracking, manual-override clear)
  1. Paper: SL/TP prüfen  |  Live: Trade-Sync
  2. Trailing Stop
  3. Auto-Mode (Volatility-based risk mode switching) — Feature 2
  4. Daily Loss Limit — Feature 1
  5. Consecutive Loss Stop — Feature 1
  6. Drawdown Recovery Factor — Feature 3 (adjusts position size)
  7. Session-Filter
  8. Macro Event Lockdown — Feature 7 (FOMC 24h, ECB 12h, CPI/NFP 4h)
  9. News Pause (regular ±30min window)
  10. Circuit Breaker
  11. Max open trades
  12. Per-instrument:
      a. Market Regime — Feature 5 (skip SIDEWAYS/HIGH_VOLATILITY)
      b. Spread check + Spread Shock detector — Feature 8
      c. Signal generieren
      d. Macro Trade Filter — Feature 1 (Risk-OFF, carry)
      e. GARCH Vol Filter — Feature 5
      f. Trend Persistence boost/reduce — Feature 10
      g. ML prediction
      h. Confidence threshold
      i. Multi-Timeframe confirmation — Feature 4
      j. Correlation exposure — Feature 3
      k. USD Concentration — Feature 9
      l. Swap Filter — Feature 4
      m. Drawdown-adjusted position sizing — Feature 3
      n. Trade platzieren

Starten:
  python -m forex_bot.bot
"""
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from forex_bot.monitoring.logger import setup_logging

log = setup_logging()

from forex_bot.config import settings as cfg
from forex_bot.execution.broker_factory import create_broker_client
from forex_bot.strategy.forex_strategy import generate_signal, compute_indicators
from forex_bot.risk.risk_manager import ForexRiskManager, ForexTrade
from forex_bot.risk.risk_modes import get_mode, RiskMode
from forex_bot.risk.correlation import correlation_blocked, usd_concentration_blocked
from forex_bot.risk.auto_mode import (
    auto_switch_mode, mark_manual_override, clear_manual_override,
)
from forex_bot.risk.shared_exposure import (
    update_forex_state, check_global_exposure, get_global_state,
)
from forex_bot.strategy.strategy_selector import select_and_generate
from forex_bot.strategy.strategy_tracker import ForexStrategyTracker
from forex_bot.strategy.multi_timeframe import mtf_confirmation
from forex_bot.strategy.regime import detect_regime, regime_allows_trade
from forex_bot.strategy.trend_persistence import trend_persistence_score, apply_persistence_boost
from forex_bot.calendar.economic_calendar import is_news_pause, get_today_events
from forex_bot.calendar.macro_lockdown import macro_lockdown_active
from forex_bot.execution.spread_monitor import is_spread_shock, update_spread
from forex_bot.execution.session_quality import session_quality, SKIP_THRESHOLD
from forex_bot.execution.swap_filter import swap_filter
from forex_bot.monitoring.telegram_bot import ForexTelegramBot
from forex_bot.ai.model import ForexMLModel
from forex_bot.ai.macro_signals import get_macro_context, macro_trade_filter
from forex_bot.ai.volatility_forecast import vol_filter
from forex_bot.ai.online_learner import OnlineLearningPipeline
from forex_bot.ai.cot_signals import get_cot_context, cot_confidence_adjustment
from forex_bot.ai.llm_filter import llm_confidence_filter
from forex_bot.ai.cross_asset import get_cross_asset_context, cross_asset_modifier
from forex_bot.ai.fred_rates import get_rate_expectation_modifier
from forex_bot.strategy.pair_selector import rank_instruments
from forex_bot.strategy.carry_trade import (
    get_carry_trade_signals, should_exit_carry, CarrySignal,
)
from forex_bot.strategy.regime import detect_regime_transition
from forex_bot.risk.pyramid import (
    check_pyramid_opportunities, mark_pyramided,
    clear_closed_pyramids, PyramidOpportunity,
)
from forex_bot.risk.correlation import update_rolling_correlation
from forex_bot.risk.emergency_exit import (
    check_emergency_conditions, execute_emergency_exit,
    is_emergency_active, reset_emergency_mode, get_emergency_state,
)
from forex_bot.ai.economic_surprise import get_surprise_modifier
from forex_bot.ai.news_sentiment_forex import get_news_sentiment_modifier
from forex_bot.ai.fred_rates import get_rate_differential_modifier
from forex_bot.ai.regime_forecaster import get_regime_forecaster
from forex_bot.execution.rollover_guard import is_rollover_window, get_rollover_status
# ── Tier 1–3 neue Features ────────────────────────────────────────────────────
from forex_bot.risk.kelly import KellyOptimizer
from forex_bot.risk.capital_allocator import get_capital_allocator
from forex_bot.risk.risk_parity import get_rp_sizing_factor
from forex_bot.ai.inflation_regime import get_inflation_regime_modifier
from forex_bot.ai.lstm_model import ForexLSTMEnsemble
from forex_bot.ai.strategy_lifecycle import get_lifecycle_manager
from forex_bot.ai.model_governance import get_model_governance
from forex_bot.execution.resilience import OandaResilienceMonitor
from forex_bot.execution.microstructure import get_microstructure_bias
# ── Tier A neue Features ──────────────────────────────────────────────────────
from forex_bot.ai.portfolio_optimizer import get_portfolio_weights
from forex_bot.strategy.macro_pair_selector import filter_pairs_by_macro
from forex_bot.ai.retrainer import get_retrainer
from forex_bot.ai.dynamic_params import get_dynamic_params
from forex_bot.risk.black_swan import get_black_swan_detector
from forex_bot.risk.stress_tester import run_stress_test
from forex_bot.ai.confidence_monitor import get_confidence_monitor
from forex_bot.ai.explainability import TradeContext, log_trade_narrative
from forex_bot.risk.shared_exposure import publish_regime, get_shared_regime
# ── Tier B neue Features ──────────────────────────────────────────────────────
from forex_bot.execution.entry_timer import get_refined_entry
from forex_bot.risk.trailing_tp import TrailingTPManager
from forex_bot.ai.options_iv import get_iv_modifier
from forex_bot.ai.cb_parser import get_cb_modifier
from forex_bot.ai.regime_forecaster import check_regime_change_warning

import pandas as pd

CYCLE_SECONDS = 3600   # 1 Stunde

# ── Shared State (Dashboard + Telegram lesen daraus) ─────────────────────────
bot_state: dict = {
    "running":       True,
    "paused":        False,
    "capital":       cfg.INITIAL_CAPITAL,
    "daily_pnl":     0.0,
    "open_trades":   0,
    "positions":     [],
    "trading_mode":  cfg.TRADING_MODE,
    "last_cycle":    None,
    "risk_mode":     cfg.RISK_MODE,
    "regime":        {},
    "ml_model_info": {},
    "macro":         {},
    "spread_ema":    {},
    "data_warnings":    {},
    "broker_connected": False,
    "broker_error":     "",
    "broker_env":       "",
    "daily_loss_notified": False,
}

_current_mode:      RiskMode              = get_mode(cfg.RISK_MODE)
_ml_model:          ForexMLModel          = ForexMLModel()
_strategy_tracker:  ForexStrategyTracker  = ForexStrategyTracker()
_online_learner:    OnlineLearningPipeline = OnlineLearningPipeline()

# ── Tier 1–3 Komponenten ──────────────────────────────────────────────────────
_kelly_optimizer:   KellyOptimizer        = KellyOptimizer()
_lstm_ensemble:     ForexLSTMEnsemble     = ForexLSTMEnsemble()
_resilience:        OandaResilienceMonitor = OandaResilienceMonitor()
# ── Tier A Komponenten ────────────────────────────────────────────────────────
_retrainer          = get_retrainer()
_black_swan         = get_black_swan_detector()
_confidence_monitor = get_confidence_monitor()
# ── Tier B Komponenten ────────────────────────────────────────────────────────
_trailing_tp        = TrailingTPManager()
# Portfolio weights (recalculated every N cycles)
_portfolio_weights: dict[str, float] = {}
_portfolio_weights_cycle: int = 0
_PORTFOLIO_REFRESH_CYCLES = 24   # Stündlicher Zyklus → alle 24h neu berechnen

# Trade-Features für Online-Learner (instrument → features bei Trade-Öffnung)
_pending_features: dict[str, list] = {}   # instrument → [features, strategy, confidence]

# COT-Kontext (wöchentlich gecacht)
_cot_ctx: dict = {}

# Cross-Asset Kontext (4h gecacht)
_cross_asset_ctx: dict = {}

# Equity-Kurven-History für Equity Curve Filter (letzten 30 Kapitalwerte)
_equity_history: list[float] = []

# Vorberechnete Candles / DFs für das aktuelle Zyklen (pair_selector + pyramid)
_candles_cache: dict[str, list]   = {}

# Pending limit orders: instrument → {"order_id": str, "expires": float}
_pending_limit_orders: dict[str, dict] = {}

# Vorheriges Regime pro Instrument (für Regime-Forecaster Update)
_prev_regimes: dict[str, str] = {}
_df_cache:      dict[str, object] = {}


def get_current_mode() -> RiskMode:
    return _current_mode


def set_current_mode(name: str) -> RiskMode:
    global _current_mode
    _current_mode = get_mode(name)
    bot_state["risk_mode"] = _current_mode.name
    log.info(f"Risk mode changed to: {_current_mode.name}")
    return _current_mode


def set_current_mode_manual(name: str) -> RiskMode:
    """Set mode from Telegram / API — disables auto-switching."""
    mark_manual_override()
    return set_current_mode(name)


# ── Live Broker Switching ─────────────────────────────────────────────────────

_active_client = None   # set in main()


def switch_broker(broker_name: str, creds: dict | None = None) -> None:
    """
    Swap the active broker client at runtime (called from dashboard API).

    creds: optional credential overrides from the dashboard form.
      These override .env values for the running session only —
      they are NOT written back to the .env file.
    """
    global _active_client
    import forex_bot.config.settings as _cfg_module
    from forex_bot.execution.broker_factory import create_broker_client

    _cfg_module.FOREX_BROKER = broker_name
    new_client = create_broker_client(creds)   # raises on connection failure

    _active_client = new_client
    bot_state["broker"] = broker_name
    log.info(f"Broker gewechselt zu: {broker_name} ({'mit Credentials' if creds else 'aus .env'})")


# ── Session helpers ───────────────────────────────────────────────────────────

def _is_session_active(mode: RiskMode) -> bool:
    hour = datetime.now(timezone.utc).hour
    if mode.session_strict:
        return 13 <= hour < 15   # London/NY overlap only
    if not cfg.SESSION_FILTER:
        return True
    return cfg.SESSION_START_H <= hour < cfg.SESSION_END_H


# ── Midnight reset ────────────────────────────────────────────────────────────

_last_midnight_date: datetime | None = None


def _midnight_check(rm: ForexRiskManager, telegram: ForexTelegramBot):
    global _last_midnight_date
    today = datetime.now(timezone.utc).date()
    if _last_midnight_date is None:
        _last_midnight_date = today
        return
    if today > _last_midnight_date:
        _last_midnight_date = today
        rm.reset_daily_tracking()
        clear_manual_override()   # re-enable auto-mode at midnight
        bot_state["daily_loss_notified"] = False
        bot_state["consecutive_loss_notified"] = False
        log.info("UTC midnight — daily tracking reset, auto-mode re-enabled")
        # Kein Telegram am Wochenende — Forex-Märkte geschlossen (Sa/So)
        if today.weekday() < 5:
            telegram.send("🌙 <b>Neuer Handelstag</b> — Daily-Tracking zurückgesetzt.")


# ── Trailing Stop ─────────────────────────────────────────────────────────────

def _compute_adx_from_df(df) -> float:
    """Berechnet ADX aus einem DataFrame — für Dynamic TP und Pyramid."""
    try:
        import numpy as np
        highs  = df["high"].astype(float)
        lows   = df["low"].astype(float)
        closes = df["close"].astype(float)
        prev_c = closes.shift(1)
        tr = pd.concat([
            highs - lows, (highs - prev_c).abs(), (lows - prev_c).abs(),
        ], axis=1).max(axis=1)
        up   = highs.diff()
        dn   = -lows.diff()
        pdm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
        mdm  = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
        atr  = tr.ewm(span=14, adjust=False).mean()
        pdi  = 100 * pdm.ewm(span=14, adjust=False).mean() / (atr + 1e-10)
        mdi  = 100 * mdm.ewm(span=14, adjust=False).mean() / (atr + 1e-10)
        dx   = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
        adx  = dx.ewm(span=14, adjust=False).mean()
        return float(adx.iloc[-1])
    except Exception:
        return 20.0


def _check_scale_out(client, rm: ForexRiskManager, telegram: ForexTelegramBot):
    """
    Scale-Out: schließt 50% der Position wenn Price 1:1 RR erreicht,
    verschiebt SL auf Breakeven. Läuft nur einmal pro Trade (scaled_out flag).
    """
    for trade in rm.get_open_trades():
        if trade.scaled_out or not trade.trade_id:
            continue
        try:
            price    = client.get_price(trade.instrument)
            pip_sz   = 0.01 if "JPY" in trade.instrument else 0.0001
            sl_dist  = abs(trade.entry_price - trade.stop_loss)
            if sl_dist < pip_sz:
                continue

            # 1:1 RR erreicht?
            if trade.direction == "BUY":
                target_1r = trade.entry_price + sl_dist
                reached   = price >= target_1r
            else:
                target_1r = trade.entry_price - sl_dist
                reached   = price <= target_1r

            if not reached:
                continue

            # Halbe Position schließen (IG MINI: Schritte à 1.000)
            half_units = max(1_000, (trade.units // 2 // 1_000) * 1_000)

            if cfg.TRADING_MODE == "live":
                try:
                    client.close_partial_trade(trade.trade_id, half_units, trade.direction)
                except Exception as e:
                    log.warning(f"Scale-Out Partial Close fehlgeschlagen ({trade.instrument}): {e}")
                    continue

            # SL auf Breakeven
            breakeven_sl = trade.entry_price
            if cfg.TRADING_MODE == "live":
                try:
                    client.modify_stop_loss(trade.trade_id, breakeven_sl)
                except Exception as e:
                    log.warning(f"Scale-Out SL-Anpassung fehlgeschlagen: {e}")

            trade.stop_loss   = breakeven_sl
            trade.scaled_out  = True
            # Annähernde PnL für den geschlossenen Teil
            part_pips         = sl_dist / pip_sz
            part_pnl          = part_pips * pip_sz * half_units
            trade.partial_pnl_usd = part_pnl
            rm._save_trade(trade)

            log.info(
                f"Scale-Out: {trade.instrument} {trade.direction} "
                f"— {half_units:,} Units @ 1:1 RR ({price:.5f}), "
                f"SL → Breakeven {breakeven_sl:.5f}"
            )
            telegram.send(
                f"📤 <b>Scale-Out: {trade.instrument}</b>\n\n"
                f"{half_units:,} Units @ 1:1 RR geschlossen\n"
                f"SL → Breakeven: {breakeven_sl:.5f}\n"
                f"Restposition läuft weiter (risikofrei)"
            )
        except Exception as e:
            log.warning(f"Scale-Out Fehler ({trade.instrument}): {e}")


def _expire_limit_orders(client):
    """Storniert abgelaufene Limit-Orders (älter als 1 Stunde)."""
    now_ts = time.time()
    expired = [instr for instr, o in _pending_limit_orders.items()
               if now_ts > o.get("expires", 0)]
    for instr in expired:
        order_id = _pending_limit_orders[instr].get("order_id", "")
        if order_id and cfg.TRADING_MODE == "live":
            try:
                client.cancel_order(order_id)
                log.info(f"Limit-Order abgelaufen + storniert: {instr} (id={order_id})")
            except Exception as e:
                log.debug(f"Limit-Order Cancel fehlgeschlagen ({instr}): {e}")
        del _pending_limit_orders[instr]


def _update_trailing_stop(client, rm: ForexRiskManager, telegram: ForexTelegramBot):
    for trade in rm.get_open_trades():
        if not trade.trade_id:
            continue
        try:
            price  = client.get_price(trade.instrument)
            pip_sz = 0.01 if "JPY" in trade.instrument else 0.0001
            new_sl = None

            if trade.direction == "BUY":
                min_new_sl = price - (trade.entry_price - trade.stop_loss)
                if min_new_sl > trade.stop_loss + pip_sz:
                    new_sl = min_new_sl
            elif trade.direction == "SELL":
                max_new_sl = price + (trade.entry_price - trade.stop_loss)
                if max_new_sl < trade.stop_loss - pip_sz:
                    new_sl = max_new_sl

            if new_sl:
                client.modify_stop_loss(trade.trade_id, new_sl)
                trade.stop_loss = round(new_sl, 5)
                log.info(f"Trailing SL: {trade.instrument} → {new_sl:.5f}")

            # ── Trailing Take-Profit (ADX-basiert) ───────────────────────────
            try:
                if not cfg.LEAN_MODE:
                    _df_t = _df_cache.get(trade.instrument)
                    if _df_t is not None and len(_df_t) >= 20:
                        tp_update = _trailing_tp.update(trade, _df_t)
                        if tp_update.new_tp and cfg.TRADING_MODE == "live":
                            # OANDA unterstützt TP-Modifikation via orders endpoint
                            client._put(
                                f"/accounts/{client.account_id}/trades/{trade.trade_id}/orders",
                                {"takeProfit": {"price": f"{tp_update.new_tp:.5f}"}},
                            )
                            trade.take_profit = tp_update.new_tp
                            log.info(
                                f"Trailing TP: {trade.instrument} → {tp_update.new_tp:.5f} "
                                f"({tp_update.reason})"
                            )
                        if tp_update.new_sl and tp_update.new_sl != new_sl:
                            if cfg.TRADING_MODE == "live":
                                client.modify_stop_loss(trade.trade_id, tp_update.new_sl)
                            trade.stop_loss = tp_update.new_sl
            except Exception as _tp_err:
                log.debug(f"Trailing TP [{trade.instrument}]: {_tp_err}")

        except Exception as e:
            log.warning(f"Trailing SL Fehler ({trade.instrument}): {e}")


# ── Trade sync ────────────────────────────────────────────────────────────────

def _sync_closed_trades(client, rm: ForexRiskManager, telegram: ForexTelegramBot):
    if cfg.TRADING_MODE != "live":
        return
    try:
        oanda_trades = {t["id"]: t for t in client.get_open_trades()}
        for trade in rm.get_open_trades():
            if trade.trade_id and trade.trade_id not in oanda_trades:
                closed = client.get_closed_trades(count=10)
                for ct in closed:
                    if ct["id"] == trade.trade_id:
                        exit_price = float(ct.get("averageClosePrice", trade.entry_price))
                        rm.record_close(trade, exit_price)
                        _ml_model.maybe_retrain(1, cfg.RETRAIN_AFTER_TRADES)
                        _on_trade_closed(trade)
                        telegram.alert_trade_closed(
                            trade.instrument, trade.direction,
                            trade.pnl_pips, trade.pnl_usd, "SL/TP ausgelöst",
                        )
                        break
    except Exception as e:
        log.warning(f"Trade-Sync Fehler: {e}")


def _paper_check_sl_tp(rm: ForexRiskManager, client, telegram: ForexTelegramBot):
    for trade in rm.get_open_trades():
        try:
            price = client.get_price(trade.instrument)
        except Exception:
            continue

        hit = False
        if trade.direction == "BUY":
            if price <= trade.stop_loss:
                rm.record_close(trade, trade.stop_loss);  hit = True
            elif price >= trade.take_profit:
                rm.record_close(trade, trade.take_profit); hit = True
        else:
            if price >= trade.stop_loss:
                rm.record_close(trade, trade.stop_loss);  hit = True
            elif price <= trade.take_profit:
                rm.record_close(trade, trade.take_profit); hit = True

        if hit:
            _ml_model.maybe_retrain(1, cfg.RETRAIN_AFTER_TRADES)
            telegram.alert_trade_closed(
                trade.instrument, trade.direction,
                trade.pnl_pips, trade.pnl_usd,
            )
            # Online Learner + Strategy Tracker nach Trade-Abschluss
            _on_trade_closed(trade)


# ── Trade-Closed Callback (Online Learner + Strategy Tracker) ────────────────

def _execute_pyramid(
    client,
    rm:       ForexRiskManager,
    telegram: ForexTelegramBot,
    mode:     "RiskMode",
) -> None:
    """
    Prüft alle offenen Trades auf Pyramidierungs-Gelegenheiten und führt sie aus.
    Wird nach dem Trailing-Stop-Update aufgerufen.
    """
    if not mode.allow_pyramiding:
        return

    open_trades = rm.get_open_trades()
    if not open_trades:
        return

    # Preise für alle offenen Instruments holen
    prices: dict[str, float] = {}
    for trade in open_trades:
        try:
            prices[trade.instrument] = client.get_price(trade.instrument)
        except Exception:
            pass

    # Aktive Trade-IDs für Cleanup
    active_ids = {t.trade_id for t in open_trades if t.trade_id}
    clear_closed_pyramids(active_ids)

    opportunities = check_pyramid_opportunities(
        open_trades, prices, _df_cache or None
    )

    for opp in opportunities:
        # Prüfe ob Max-Trades schon erreicht
        if rm.open_trade_count() >= mode.max_open_trades + 1:  # +1 für Pyramid erlaubt
            log.info("Pyramid: max_open_trades erreicht — übersprungen")
            break

        try:
            signed_units = opp.add_units if opp.direction == "BUY" else -opp.add_units

            # SL des Original-Trades auf Breakeven ziehen
            if opp.trade_id:
                try:
                    client.modify_stop_loss(opp.trade_id, opp.new_sl)
                    # Original-Trade SL im lokalen State updaten
                    for t in open_trades:
                        if t.trade_id == opp.trade_id:
                            t.stop_loss = opp.new_sl
                except Exception as e:
                    log.warning(f"Pyramid: SL-Anpassung fehlgeschlagen: {e}")

            # Pyramiden-Trade öffnen
            pyramid_trade = ForexTrade(
                instrument  = opp.instrument,
                direction   = opp.direction,
                units       = opp.add_units,
                entry_price = opp.current_price,
                stop_loss   = opp.new_sl,
                take_profit = opp.new_tp,
                reason      = f"PYRAMID: Original-Trade {opp.trade_id}",
            )

            if cfg.TRADING_MODE == "live":
                result    = client.place_market_order(
                    opp.instrument, signed_units, opp.new_sl, opp.new_tp
                )
                fill      = result.get("orderFillTransaction", {})
                pyramid_trade.trade_id    = fill.get("tradeOpened", {}).get("tradeID", "")
                pyramid_trade.entry_price = float(fill.get("price", opp.current_price))

            rm.record_open(pyramid_trade)
            mark_pyramided(opp.trade_id)

            telegram.send(
                f"📈 <b>Pyramidierung: {opp.instrument}</b>\n\n"
                f"Direction: {opp.direction}\n"
                f"Units: +{opp.add_units:,}\n"
                f"SL → Breakeven: {opp.new_sl:.5f}\n"
                f"TP erweitert: {opp.new_tp:.5f}"
            )
            log.info(
                f"Pyramid ausgeführt: {opp.instrument} +{opp.add_units} "
                f"SL={opp.new_sl:.5f} TP={opp.new_tp:.5f}"
            )

        except Exception as e:
            log.error(f"Pyramid Fehler ({opp.instrument}): {e}")


def _on_trade_closed(trade: ForexTrade) -> None:
    """Wird nach jedem abgeschlossenen Trade aufgerufen."""
    was_win = trade.pnl_pips > 0
    pending = _pending_features.get(trade.instrument)

    strategy     = "ema_crossover"
    stored_probs = None
    if pending:
        features, strategy, raw_conf, *_extra_probs = pending
        stored_probs = _extra_probs[0] if _extra_probs else None
        _online_learner.process_trade_outcome(
            features       = features,
            signal         = trade.direction,
            source         = strategy,
            raw_confidence = raw_conf,
            was_profitable = was_win,
        )
        _strategy_tracker.record_trade(strategy, trade.pnl_pips, was_win)
        del _pending_features[trade.instrument]
    else:
        _strategy_tracker.record_trade("ema_crossover", trade.pnl_pips, was_win)

    # ── Strategy Lifecycle Update ─────────────────────────────────────────────
    try:
        get_lifecycle_manager().record_trade(strategy, trade.pnl_pips)
    except Exception:
        pass

    # ── Model Governance: Kalibrierungs-Update ────────────────────────────────
    try:
        actual_signal = trade.direction
        if stored_probs and isinstance(stored_probs, dict):
            probs = stored_probs
        else:
            # Fallback: Konfidenz als Proxy für die tatsächlich ausgeführte Richtung
            conf = getattr(trade, "confidence", 0.65)
            remaining = (1.0 - conf) / 2
            probs = {"BUY": remaining, "HOLD": remaining, "SELL": remaining}
            probs[actual_signal] = conf
        get_model_governance().update_calibration(probs, actual_signal)
    except Exception:
        pass

    # ── Retrainer: Trade-Counter ──────────────────────────────────────────────
    try:
        _retrainer.record_trade()
    except Exception:
        pass


# ── ATR% helper ───────────────────────────────────────────────────────────────

def _compute_atr_pct(candles: list) -> float:
    """Return latest ATR as % of close price."""
    try:
        closes = [float(c["close"]) for c in candles if c.get("close")]
        highs  = [float(c["high"])  for c in candles if c.get("high")]
        lows   = [float(c["low"])   for c in candles if c.get("low")]
        if len(closes) < 15:
            return 0.05
        tr_vals = [
            max(highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i]  - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr = sum(tr_vals[-14:]) / 14
        return atr / (closes[-1] + 1e-10) * 100
    except Exception:
        return 0.05


# ── Rejection / Signal tracking ───────────────────────────────────────────────

def _record_rejection(instrument: str, reason: str) -> None:
    from forex_bot.dashboard.api import _bot_state
    entry = {
        "instrument": instrument,
        "reason":     reason,
        "time":       datetime.now(timezone.utc).isoformat(),
    }
    lst = _bot_state.setdefault("recent_rejections", [])
    lst.insert(0, entry)
    del lst[20:]


def _record_signal(instrument: str, direction: str, confidence: float, reason: str) -> None:
    from forex_bot.dashboard.api import _bot_state
    entry = {
        "instrument": instrument,
        "direction":  direction,
        "confidence": round(confidence, 3),
        "reason":     reason,
        "time":       datetime.now(timezone.utc).isoformat(),
    }
    lst = _bot_state.setdefault("recent_signals", [])
    lst.insert(0, entry)
    del lst[20:]


# ── Main cycle ────────────────────────────────────────────────────────────────

def run_cycle(client, rm: ForexRiskManager, telegram: ForexTelegramBot):
    global _cot_ctx
    now  = datetime.now(timezone.utc)
    mode = get_current_mode()
    log.info(f"── Zyklus {now.strftime('%Y-%m-%d %H:%M UTC')} — mode={mode.name} ──")

    macro_ctx: dict = {}

    # ── 0. API Resilience Check ───────────────────────────────────────────────
    if _resilience.is_circuit_open():
        log.warning("OANDA API Circuit Breaker offen — Zyklus übersprungen")
        return

    # ── 0a. Emergency Exit Check ─────────────────────────────────────────────
    if is_emergency_active():
        em = get_emergency_state()
        log.critical(f"EMERGENCY EXIT AKTIV — kein Trading. Grund: {em['reason']}")
        log.critical(f"Reset: POST /control/reset_emergency oder reset_emergency_mode(confirm=True)")
        return

    # ── 0b. Emergency-Bedingungen prüfen (proaktiv) ──────────────────────────
    try:
        spread_ratios = {
            inst: bot_state.get("spread_ema", {}).get(inst, {}).get("ratio", 1.0)
            for inst in cfg.INSTRUMENTS
        }
        macro_ctx_em   = bot_state.get("macro", {})
        vix_em         = macro_ctx_em.get("vix")
        should_exit, exit_reason = check_emergency_conditions(
            capital      = rm.capital,
            peak_capital = rm._peak_capital if hasattr(rm, "_peak_capital") else rm.capital,
            vix          = vix_em,
            spread_ratios= spread_ratios,
        )
        if should_exit:
            open_trades_em = rm.get_open_trades()
            execute_emergency_exit(client, open_trades_em, exit_reason, telegram, rm.capital)
            return
    except Exception as _em_err:
        log.debug(f"Emergency check: {_em_err}")

    # ── 0. Midnight reset ─────────────────────────────────────────────────────
    _midnight_check(rm, telegram)

    # ── 1. Paper: SL/TP prüfen ───────────────────────────────────────────────
    if cfg.TRADING_MODE == "paper":
        _paper_check_sl_tp(rm, client, telegram)
    else:
        _sync_closed_trades(client, rm, telegram)

    # ── 2. Trailing Stop + Scale-Out + Carry-Exit-Check ────────────────────
    _update_trailing_stop(client, rm, telegram)
    _check_scale_out(client, rm, telegram)
    _expire_limit_orders(client)

    # Carry Trade Regime-Exit (VIX-spike)
    if macro_ctx:
        for trade in rm.get_open_trades():
            exit_carry, exit_reason = should_exit_carry(trade, macro_ctx)
            if exit_carry:
                try:
                    price = client.get_price(trade.instrument)
                    rm.record_close(trade, price)
                    _on_trade_closed(trade)
                    telegram.alert_trade_closed(
                        trade.instrument, trade.direction,
                        trade.pnl_pips, trade.pnl_usd, exit_reason,
                    )
                    log.info(f"Carry Exit: {trade.instrument} — {exit_reason}")
                except Exception as e:
                    log.warning(f"Carry Exit Fehler ({trade.instrument}): {e}")

    # ── 3. Auto-Mode (Feature 2) ─────────────────────────────────────────────
    # Compute a representative ATR% from the first configured instrument
    try:
        import time as _time
        _t0 = _time.monotonic()
        sample_candles = client.get_candles(cfg.INSTRUMENTS[0], cfg.TIMEFRAME, count=20)
        _resilience.record_call((_time.monotonic() - _t0) * 1000, success=True)
        atr_pct = _compute_atr_pct(sample_candles)
    except Exception as _api_err:
        _resilience.record_call(9999, success=False)
        atr_pct = 0.05

    macro_ctx = {}
    try:
        macro_ctx = get_macro_context()
        bot_state["macro"] = macro_ctx
    except Exception:
        pass

    vix = macro_ctx.get("vix", 18.0)

    # Count High-Impact events in next 4 hours
    try:
        upcoming = get_today_events(cfg.NEWS_CURRENCIES)
        now_ts   = datetime.now(timezone.utc)
        high_ct  = sum(
            1 for e in upcoming
            if e.get("impact") == "High"
            and 0 <= (e["time"] - now_ts).total_seconds() / 3600 <= 4
        )
    except Exception:
        high_ct = 0

    new_mode_name, switched = auto_switch_mode(
        atr_pct, vix, high_ct,
        current_mode=mode.name,
        set_mode_fn=set_current_mode,
    )
    if switched:
        mode = get_current_mode()
        telegram.send(
            f"⚙️ <b>Auto-Mode aktiviert: {mode.name.upper()}</b>\n"
            f"VIX={vix:.1f}, ATR%={atr_pct:.3f}, Events={high_ct}"
        )

    # ── 4. Daily Loss Limit ───────────────────────────────────────────────────
    if rm.daily_loss_limit_reached(mode.daily_loss_limit):
        if not bot_state.get("daily_loss_notified"):
            telegram.send(
                f"🛑 <b>Daily Loss Limit erreicht!</b>\n\n"
                f"Verlust heute: ${rm.daily_loss_usd:.2f}\n"
                f"Limit ({mode.daily_loss_limit*100:.1f}%): "
                f"${rm.initial_capital * mode.daily_loss_limit:.2f}\n"
                f"Kein Trading bis Mitternacht UTC."
            )
            bot_state["daily_loss_notified"] = True
        log.warning("Daily loss limit reached — skipping cycle")
        return

    # ── 5. Consecutive Loss Stop ──────────────────────────────────────────────
    if rm.consecutive_loss_stop_reached(mode.consecutive_loss_stop):
        if not bot_state.get("consecutive_loss_notified"):
            bot_state["paused"] = True
            telegram.send(
                f"⚠️ <b>Consecutive Loss Stop!</b>\n\n"
                f"{rm.consecutive_losses} Verluste in Folge "
                f"(Limit: {mode.consecutive_loss_stop}).\n"
                f"Trading pausiert — bitte manuell /resume."
            )
            bot_state["consecutive_loss_notified"] = True
            log.warning("Consecutive loss stop — pausing bot")
        return

    # ── 6. Drawdown Recovery Factor (Feature 3) ───────────────────────────────
    dd_factor = rm.drawdown_recovery_factor()
    dd_pct    = rm.current_drawdown_pct()
    if dd_factor < 1.0:
        log.info(
            f"Drawdown Recovery Mode: DD={dd_pct:.1f}% → "
            f"risk_factor={dd_factor:.2f}× "
            f"(effective_risk={(mode.risk_per_trade * dd_factor)*100:.2f}%)"
        )

    # ── 6b. Shared Exposure Update (Crypto+Forex Koordination) ───────────────
    try:
        summary      = rm.summary()
        open_trades  = rm.get_open_trades()
        open_risk    = len(open_trades) * mode.risk_per_trade * dd_factor
        update_forex_state(
            capital       = summary.get("capital",      cfg.INITIAL_CAPITAL),
            peak_capital  = rm._peak_capital,
            open_risk_pct = open_risk,
        )
    except Exception as e:
        log.debug(f"Shared Exposure Update: {e}")

    # ── 6c. COT-Kontext (wöchentlich, nur wenn nötig) ─────────────────────────
    if not _cot_ctx or now.weekday() == 2:   # Mittwoch = CFTC veröffentlicht
        try:
            _cot_ctx = get_cot_context()
        except Exception:
            pass

    # ── 6d2. Cross-Asset Kontext (4h gecacht) ─────────────────────────────────
    global _cross_asset_ctx
    try:
        _cross_asset_ctx = get_cross_asset_context()
    except Exception as e:
        log.debug(f"Cross-Asset: {e}")

    # ── 6d3. Kelly-Sizing-Faktor (aus Trade-Historie) ─────────────────────────
    kelly_factor = 1.0
    try:
        from forex_bot.monitoring.logger import get_recent_trades as _get_trades
        _recent = _get_trades(50)
        if _recent:
            kelly_factor = _kelly_optimizer.get_sizing_factor(
                [{"pnl": t.get("pnl_pips") or t.get("pnl", 0)} for t in _recent]
            )
            if kelly_factor != 1.0:
                log.debug(f"Kelly-Faktor: {kelly_factor:.2f}×")
    except Exception as _ke:
        log.debug(f"Kelly: {_ke}")

    # ── 6d4. Capital Allocator — Regime-adaptive Gesamt-Allokation ───────────
    _capital_alloc_factor = 1.0
    try:
        _allocator    = get_capital_allocator()
        _macro_score  = _allocator.get_macro_score(macro_ctx)
        # Globaler Regime: first instrument als Proxy
        _global_regime = _regime_map.get(cfg.INSTRUMENTS[0], "SIDEWAYS") if "_regime_map" in dir() else "SIDEWAYS"
        _alloc_result  = _allocator.allocate(
            regime        = _global_regime,
            session_score = 0.6,        # Wird per Instrument präzisiert
            macro_score   = _macro_score,
            regime_score  = 0.5,
            atr_pct       = atr_pct,
            drawdown_pct  = rm.current_drawdown_pct() / 100.0,
        )
        _capital_alloc_factor = _alloc_result.risk_scale
        if _capital_alloc_factor < 0.8:
            log.info(f"Capital Allocator: {_alloc_result.reason}")
    except Exception as _ce:
        log.debug(f"Capital Allocator: {_ce}")

    # ── 6e. Equity Curve Filter ────────────────────────────────────────────────
    # Wenn die eigene Kapital-Kurve unter ihrem 20-Perioden-Durchschnitt liegt,
    # halbiere das Risiko — stoppt das "Verdoppeln in Verluststrecken".
    global _equity_history
    _equity_history.append(rm.capital)
    if len(_equity_history) > 30:
        _equity_history.pop(0)

    equity_factor = 1.0
    if len(_equity_history) >= 20:
        eq_ma20 = sum(_equity_history[-20:]) / 20
        if rm.capital < eq_ma20 * 0.998:
            equity_factor = 0.50
            log.info(
                f"Equity Curve Filter: Kapital {rm.capital:.0f} < "
                f"EMA20 {eq_ma20:.0f} → Risiko halbiert (0.5×)"
            )
    bot_state["equity_factor"] = equity_factor

    # ── 6d. Freitag End-of-Week — Risikoreduktion ────────────────────────────
    is_friday_eow = (now.weekday() == 4 and now.hour >= 18)  # Freitag nach 18:00 UTC
    if is_friday_eow:
        log.info("Freitag 18:00+ UTC — kein neuer Trade (End-of-Week Risikoreduktion)")
        return

    # ── 7. Session-Filter ─────────────────────────────────────────────────────
    if not _is_session_active(mode):
        log.info("Außerhalb der Trading-Session — kein neuer Trade.")
        return

    # ── 7b. Rollover Guard (17:00 NYC ± Fenster) ─────────────────────────────
    if is_rollover_window(now):
        rollover_info = get_rollover_status(now)
        log.info(f"Rollover-Fenster aktiv — {rollover_info['message']} — kein neuer Trade")
        return

    # ── 8. Macro Event Lockdown (Feature 7) ──────────────────────────────────
    locked, lock_reason, lock_min = macro_lockdown_active(cfg.NEWS_CURRENCIES)
    if locked:
        log.info(f"Macro lockdown: {lock_reason}")
        return

    # ── 9. Regular News Pause ────────────────────────────────────────────────
    paused, news_reason = is_news_pause(cfg.NEWS_CURRENCIES, mode.news_pause_min)
    if paused:
        log.info(f"News-Pause: {news_reason}")
        telegram.alert_news_pause(news_reason)
        return

    # ── 10. Circuit Breaker ───────────────────────────────────────────────────
    if rm.circuit_breaker_active():
        log.warning("Circuit Breaker aktiv — kein Trade")
        return

    # ── 11. Max offene Trades ─────────────────────────────────────────────────
    if rm.open_trade_count() >= mode.max_open_trades:
        log.info(f"Max. {mode.max_open_trades} offene Trades — kein neuer Trade")
        return

    # ── 11a2. Macro Pair Selector — RISK_ON/OFF Filter ───────────────────────
    global _portfolio_weights, _portfolio_weights_cycle
    _active_instruments = list(cfg.INSTRUMENTS)
    try:
        _macro_sel = filter_pairs_by_macro(cfg.INSTRUMENTS, macro_ctx)
        if _macro_sel.excluded_pairs:
            log.info(f"Macro Pair Selector: {_macro_sel.regime} — {_macro_sel.reason}")
            _active_instruments = _macro_sel.active_pairs or list(cfg.INSTRUMENTS)
    except Exception as _mps_err:
        log.debug(f"Macro Pair Selector: {_mps_err}")

    # Portfolio Weights (Markowitz) — alle N Zyklen neu berechnen
    _portfolio_weights_cycle += 1
    if _portfolio_weights_cycle >= _PORTFOLIO_REFRESH_CYCLES or not _portfolio_weights:
        try:
            if not cfg.LEAN_MODE:
                _pw_result = get_portfolio_weights(_active_instruments, cfg.INITIAL_CAPITAL)
                _portfolio_weights = _pw_result.weights
                log.debug(f"Portfolio Weights: {_portfolio_weights} (Methode: {_pw_result.method})")
                _portfolio_weights_cycle = 0
        except Exception as _pw_err:
            log.debug(f"Portfolio Optimizer: {_pw_err}")

    # Retrainer: should_retrain check (non-blocking, nur trigger wenn nötig)
    try:
        if _retrainer.should_retrain():
            log.info("Retrainer: Autonomes Retraining gestartet")
            _retrainer.trigger_retrain()
    except Exception as _rt_err:
        log.debug(f"Retrainer: {_rt_err}")

    # ── 11b. Candles voraus-holen + Pair Ranking ─────────────────────────────
    # Alle Instruments in einem Zug vorab laden → Pair Ranking möglich
    global _candles_cache, _df_cache
    _candles_cache = {}
    _df_cache      = {}
    _regime_map:   dict[str, str] = {}

    _data_warnings: dict[str, str] = {}
    for _instr in cfg.INSTRUMENTS:
        try:
            _c = client.get_candles(_instr, cfg.TIMEFRAME, count=250)
            if len(_c) >= 50:
                _candles_cache[_instr] = _c
                _d = pd.DataFrame(_c)
                for _col in ("open", "high", "low", "close"):
                    _d[_col] = _d[_col].astype(float)
                _df_cache[_instr]   = _d
                _regime_map[_instr] = detect_regime(_d)
                # Rolling Correlation mit aktuellem Close updaten
                try:
                    update_rolling_correlation(_instr, float(_d["close"].iloc[-1]))
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"Pre-fetch {_instr}: {e}")
            _data_warnings[_instr] = str(e)
    bot_state["data_warnings"] = _data_warnings

    # Regime in bot_state übernehmen
    bot_state["regime"] = dict(_regime_map)

    # Regime Bus: dominantes Regime publizieren
    try:
        _regimes_list = list(_regime_map.values())
        if _regimes_list:
            _dominant_regime = max(set(_regimes_list), key=_regimes_list.count)
            publish_regime(
                regime      = _dominant_regime,
                source      = "forex",
                vix_level   = macro_ctx.get("vix"),
                risk_regime = macro_ctx.get("risk_regime"),
            )
    except Exception as _rb_err:
        log.debug(f"Regime Bus publish: {_rb_err}")

    # Nach Momentum sortieren (stärkstes Setup zuerst)
    _ranked = rank_instruments(_candles_cache, _regime_map, hour_utc=now.hour)
    _sorted_instruments = [i for i, _ in _ranked]
    # Instruments die nicht gerankt wurden (fetch-Fehler) hinten anhängen
    for _i in cfg.INSTRUMENTS:
        if _i not in _sorted_instruments:
            _sorted_instruments.append(_i)

    # ── 11c. Pyramidierungs-Check ─────────────────────────────────────────────
    _execute_pyramid(client, rm, telegram, mode)

    # ── 12. Signale pro Instrument (in Ranking-Reihenfolge) ──────────────────
    for instrument in _sorted_instruments:
        if rm.already_open(instrument):
            log.debug(f"{instrument}: bereits offen — skip")
            continue

        try:
            # Voraus-geholte Candles + DF verwenden
            candles = _candles_cache.get(instrument)
            df      = _df_cache.get(instrument)

            if candles is None or df is None:
                log.debug(f"{instrument}: keine voraus-geholten Daten — skip")
                continue
            if len(candles) < 210:
                log.warning(f"{instrument}: zu wenig Candles ({len(candles)})")
                continue

            # ── a. Market Regime (bereits vorberechnet) ───────────────────────
            regime = _regime_map.get(instrument, "SIDEWAYS")
            # bot_state["regime"] bereits oben gesetzt

            # ── a2. Black Swan Check ──────────────────────────────────────────
            try:
                _bs_event = _black_swan.check(df, instrument)
                if _bs_event.is_black_swan:
                    log.warning(
                        f"{instrument}: BLACK SWAN {_bs_event.event_type} "
                        f"z={_bs_event.z_score:.1f}σ — kein neuer Trade"
                    )
                    telegram.send(
                        f"🦢 <b>Black Swan: {instrument}</b>\n"
                        f"Typ: {_bs_event.event_type} | z={_bs_event.z_score:.1f}σ | "
                        f"Move: {_bs_event.move_pct:.2%}\nCooldown 60 Min"
                    )
                    continue
            except Exception as _bse:
                log.debug(f"Black Swan check: {_bse}")

            # ── b. Spread + Spread Shock (Feature 8) ─────────────────────────
            spread = client.get_spread_pips(instrument)
            shocked, shock_reason = is_spread_shock(instrument, spread)
            if shocked:
                log.info(f"{instrument}: {shock_reason}")
                continue
            if spread > mode.spread_limit_pips:
                log.info(
                    f"{instrument}: Spread {spread:.1f} Pips > "
                    f"Limit {mode.spread_limit_pips:.1f} — skip"
                )
                _record_rejection(instrument, f"Spread {spread:.1f} > Limit {mode.spread_limit_pips:.1f} Pips")
                continue

            # ── b2. Session Quality Multiplier ────────────────────────────────
            hour_utc = now.hour
            sess_mult, sess_name = session_quality(instrument, hour_utc)

            # ── b3. Microstructure Bias (Institutional Flow Proxy) ────────────
            micro_bias  = "NEUTRAL"
            micro_score = 0.5
            try:
                micro_bias, micro_score = get_microstructure_bias(df, instrument)
            except Exception as _me:
                log.debug(f"Microstructure {instrument}: {_me}")

            # Resilience: Preis-Update tracken
            try:
                _resilience.update_price(instrument, float(df["close"].iloc[-1]))
            except Exception:
                pass

            if cfg.SESSION_QUALITY_FILTER and sess_mult < SKIP_THRESHOLD:
                log.info(
                    f"{instrument}: Session-Qualität {sess_name} "
                    f"({sess_mult:.2f}×) zu niedrig — skip"
                )
                _record_rejection(instrument, f"Session {sess_name} Qualität {sess_mult:.2f}× zu niedrig")
                continue

            # ── b4. Strategy Lifecycle Check ──────────────────────────────────
            # Strategie überspringen wenn dormant (schlechte Performance)
            _lifecycle = get_lifecycle_manager()

            # ── b5. Dynamic Parameters — Regime-adaptive ATR-Mult + RR ────────
            _dyn_params = get_dynamic_params(
                regime       = regime,
                session      = sess_name,
                drawdown_pct = rm.current_drawdown_pct() / 100.0,
            )
            _dyn_atr_mult = _dyn_params.atr_multiplier
            _dyn_rr_ratio = _dyn_params.rr_ratio
            log.debug(
                f"{instrument}: DynParams ATR×{_dyn_atr_mult} RR {_dyn_rr_ratio}:1"
            )

            # ── c. Signal generieren (Multi-Strategy Selector) ────────────────
            if cfg.MULTI_STRATEGY:
                signal, strategy_name = select_and_generate(
                    candles        = candles,
                    instrument     = instrument,
                    regime         = regime,
                    hour           = hour_utc,
                    atr_multiplier = _dyn_atr_mult,
                    rr_ratio       = _dyn_rr_ratio,
                )
            else:
                signal        = generate_signal(candles, instrument,
                                                _dyn_atr_mult, _dyn_rr_ratio)
                strategy_name = "ema_crossover"
                # Legacy Regime-Check für nicht-Multi-Strategy Mode
                allowed_regime, regime_reason = regime_allows_trade(regime, signal.direction)
                if not allowed_regime:
                    log.info(f"{instrument}: {regime_reason}")
                    continue

            if signal.direction == "HOLD":
                log.info(f"{instrument}: kein Signal [{strategy_name}] — skip")
                continue

            # Bereits offene Limit-Order → kein neuer Trade
            if instrument in _pending_limit_orders:
                log.info(f"{instrument}: Limit-Order ausstehend — skip")
                continue

            # Lifecycle-Check: Strategie dormant?
            try:
                if not _lifecycle.is_active(strategy_name, regime):
                    log.info(f"{instrument}: Strategie {strategy_name} DORMANT — skip")
                    continue
            except Exception:
                pass

            # ── c2. Regime Transition Detection — Confidence-Boost ────────────
            try:
                transition = detect_regime_transition(df)
                if transition in ("EMERGING_TREND_UP", "EMERGING_TREND_DOWN"):
                    # Frühzeitiger Trend-Einstieg → Confidence leicht boosten
                    expected_dir = "BUY" if transition == "EMERGING_TREND_UP" else "SELL"
                    if signal.direction == expected_dir:
                        signal = signal.__class__(
                            direction   = signal.direction,
                            confidence  = min(1.0, signal.confidence * 1.05),
                            entry_price = signal.entry_price,
                            stop_loss   = signal.stop_loss,
                            take_profit = signal.take_profit,
                            reason      = signal.reason + f" | {transition}",
                        )
                        log.debug(f"{instrument}: Regime Transition {transition} → conf boost")
                elif transition == "TREND_WEAKENING":
                    # Trend schwächt sich → Confidence reduzieren
                    signal = signal.__class__(
                        direction   = signal.direction,
                        confidence  = signal.confidence * 0.85,
                        entry_price = signal.entry_price,
                        stop_loss   = signal.stop_loss,
                        take_profit = signal.take_profit,
                        reason      = signal.reason + " | TREND_WEAKENING",
                    )
            except Exception as e:
                log.debug(f"Regime transition check: {e}")

            # ── c3. Dynamic TP Extension (ADX-basiert) ────────────────────────
            # Bei sehr starkem Trend (ADX > 40): TP um 50% verlängern → 3:1 statt 2:1
            try:
                adx_val = _compute_adx_from_df(df)
                if adx_val > 40:
                    pip_sz   = 0.01 if "JPY" in instrument else 0.0001
                    tp_dist  = abs(signal.take_profit - signal.entry_price)
                    ext_mult = 1.50 if adx_val > 50 else 1.25
                    if signal.direction == "BUY":
                        new_tp = round(signal.entry_price + tp_dist * ext_mult, 5)
                    else:
                        new_tp = round(signal.entry_price - tp_dist * ext_mult, 5)
                    signal = signal.__class__(
                        direction   = signal.direction,
                        confidence  = signal.confidence,
                        entry_price = signal.entry_price,
                        stop_loss   = signal.stop_loss,
                        take_profit = new_tp,
                        reason      = signal.reason + f" | DynTP×{ext_mult:.2f}",
                    )
                    log.debug(
                        f"{instrument}: Dynamic TP ADX={adx_val:.1f} → "
                        f"TP {signal.take_profit:.5f} (×{ext_mult})"
                    )
            except Exception as e:
                log.debug(f"Dynamic TP: {e}")

            # ── d. Macro Trade Filter (Feature 1) ────────────────────────────
            if macro_ctx:
                macro_ok, macro_reason = macro_trade_filter(
                    macro_ctx, instrument, signal.direction
                )
                if not macro_ok:
                    log.info(f"{instrument}: Macro filter — {macro_reason}")
                    continue

            # ── e. GARCH Volatility Filter (Feature 5) ───────────────────────
            vol_ok, vol_reason = vol_filter(df, instrument)
            if not vol_ok:
                log.info(f"{instrument}: {vol_reason}")
                continue

            # ── f. Trend Persistence (Feature 10) ─────────────────────────────
            persistence = trend_persistence_score(df, signal.direction)
            confidence  = apply_persistence_boost(signal.confidence, persistence)

            # Strategy Tracker Multiplikator
            tracker_mult = _strategy_tracker.get_multiplier(strategy_name)
            confidence   = min(1.0, confidence * tracker_mult)
            log.debug(
                f"{instrument}: persistence={persistence}, "
                f"tracker_mult={tracker_mult:.2f}×, "
                f"conf {signal.confidence:.2f} → {confidence:.2f}"
            )

            # ── f2. COT Confidence Adjustment (Tier 2) ───────────────────────
            cot_mult   = cot_confidence_adjustment(_cot_ctx, instrument, signal.direction)
            confidence = min(1.0, confidence * cot_mult)
            if cot_mult != 1.0:
                log.debug(f"{instrument}: COT mult={cot_mult:.2f}× → conf={confidence:.2f}")

            # ── f3. Cross-Asset Signal Matrix (Tier 2) ────────────────────────
            try:
                ca_mult    = cross_asset_modifier(_cross_asset_ctx, instrument, signal.direction)
                confidence = min(1.0, confidence * ca_mult)
                if ca_mult != 1.0:
                    log.debug(f"{instrument}: Cross-Asset mult={ca_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Cross-Asset modifier: {e}")

            # ── f4. Rate Differential Modifier (BOE/BOJ/Fed live) ────────────
            try:
                rate_mult  = get_rate_differential_modifier(instrument, signal.direction)
                confidence = min(1.0, confidence * rate_mult)
                if rate_mult != 1.0:
                    log.debug(f"{instrument}: Rate Differential mult={rate_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Rate differential: {e}")

            # ── f5. Economic Surprise Index ───────────────────────────────────
            try:
                surprise_mult = get_surprise_modifier(instrument, signal.direction)
                confidence    = min(1.0, confidence * surprise_mult)
                if surprise_mult != 1.0:
                    log.debug(f"{instrument}: EconSurprise mult={surprise_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Economic surprise: {e}")

            # ── f6. News NLP Sentiment ────────────────────────────────────────
            try:
                news_mult  = get_news_sentiment_modifier(instrument, signal.direction)
                confidence = min(1.0, confidence * news_mult)
                if news_mult != 1.0:
                    log.debug(f"{instrument}: NewsSentiment mult={news_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"News sentiment: {e}")

            # ── f6a. Options IV Modifier (IV-Rank → Trend vs. Mean-Revert) ────
            try:
                iv_mult    = get_iv_modifier(instrument, signal.direction)
                confidence = min(1.0, confidence * iv_mult)
                if iv_mult != 1.0:
                    log.debug(f"{instrument}: OptionsIV mult={iv_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Options IV: {e}")

            # ── f6b. Central Bank Sentiment Modifier ──────────────────────────
            try:
                cb_mult    = get_cb_modifier(instrument, signal.direction)
                confidence = min(1.0, confidence * cb_mult)
                if cb_mult != 1.0:
                    log.debug(f"{instrument}: CB Sentiment mult={cb_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"CB Parser: {e}")

            # ── f6c. Inflation Regime Modifier ───────────────────────────────
            try:
                infl_mult  = get_inflation_regime_modifier(instrument, signal.direction)
                confidence = min(1.0, confidence * infl_mult)
                if infl_mult != 1.0:
                    log.debug(f"{instrument}: InflationRegime mult={infl_mult:.2f}× → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Inflation regime: {e}")

            # ── f7. Regime Forecaster — Markov Confidence Modifier ────────────
            try:
                forecaster = get_regime_forecaster(instrument)
                prev_r     = _prev_regimes.get(instrument)
                curr_r     = regime

                if prev_r and prev_r != curr_r:
                    forecaster.update(prev_r, curr_r)

                _prev_regimes[instrument] = curr_r

                if len(df) >= 50:
                    rf_cast     = forecaster.forecast(df, curr_r)
                    conf_mod    = rf_cast.confidence_modifier
                    confidence  = min(1.0, confidence * conf_mod)
                    if conf_mod != 1.0:
                        log.debug(
                            f"{instrument}: RegimeForecaster "
                            f"bias={rf_cast.recommended_bias} "
                            f"persist={rf_cast.persistence.persistence_pct:.0f}% "
                            f"mult={conf_mod:.2f}× → conf={confidence:.2f}"
                        )
            except Exception as e:
                log.debug(f"Regime forecaster: {e}")

            # ── g. ML Model prediction (XGBoost + LSTM Ensemble) ─────────────
            raw_probs = {"BUY": 0.33, "HOLD": 0.33, "SELL": 0.33}
            ml_importances: dict[str, float] = {}
            if _ml_model.is_loaded():
                try:
                    from forex_bot.ai.features import build_features
                    feat_df = build_features(df)
                    if len(feat_df) > 0:
                        ml_dir, ml_conf = _ml_model.predict(feat_df)

                        # LSTM Ensemble: blende LSTM (40%) mit XGBoost (60%)
                        if _lstm_ensemble.is_active:
                            ml_dir, ml_conf = _lstm_ensemble.predict_ensemble(
                                df, ml_dir, ml_conf
                            )

                        # Feature Importance für Model Governance
                        try:
                            mdl = _ml_model._model
                            if hasattr(mdl, "get_booster"):
                                scores = mdl.get_booster().get_fscore()
                                ml_importances = {k: float(v) for k, v in scores.items()}
                        except Exception:
                            pass

                        if ml_dir != "HOLD" and ml_dir == signal.direction:
                            confidence = min(1.0, confidence * 0.6 + ml_conf * 0.4)
                            raw_probs[ml_dir] = ml_conf
                            log.info(
                                f"{instrument}: ML{'(+LSTM)' if _lstm_ensemble.is_active else ''} "
                                f"confirms {ml_dir} (conf={confidence:.2f})"
                            )
                        elif ml_dir not in ("HOLD", signal.direction):
                            confidence = confidence * 0.7
                            log.info(
                                f"{instrument}: ML disagrees ({ml_dir} vs {signal.direction}) "
                                f"→ conf={confidence:.2f}"
                            )
                except Exception as e:
                    log.debug(f"ML predict error for {instrument}: {e}")

            # ── g2b. Model Governance — Entropie + Drift ──────────────────────
            _gov_size_factor = 1.0
            try:
                governance = get_model_governance()
                gov_result = governance.evaluate(
                    probs       = raw_probs,
                    importances = ml_importances if ml_importances else None,
                    base_size   = mode.risk_per_trade,
                )
                _gov_size_factor = gov_result.size_factor
                if gov_result.alerts:
                    for alert in gov_result.alerts:
                        log.warning(f"ModelGovernance [{instrument}]: {alert}")
            except Exception as e:
                log.debug(f"Model Governance: {e}")

            # Online Learner Adjustment
            try:
                ol_features = _online_learner.build_features(df, sess_mult, regime)
                adj_conf, _  = _online_learner.get_adjusted_confidence(
                    strategy_name, confidence, raw_probs
                )
                # Blende Online-Learner sanft ein (nur wenn genug Daten)
                if _online_learner.incremental.n_samples >= 20:
                    confidence = min(1.0, confidence * 0.8 + adj_conf * 0.2)
                    log.debug(f"{instrument}: OL adjustment → conf={confidence:.2f}")
            except Exception as e:
                log.debug(f"Online Learner: {e}")
                ol_features = []

            # ── g2. LLM Filter (Tier 3 — nur im Unsicherheits-Bereich) ──────────
            try:
                confidence = llm_confidence_filter(
                    instrument, signal.direction, confidence, macro_ctx, regime
                )
            except Exception as e:
                log.debug(f"LLM Filter: {e}")

            # ── h. Confidence threshold ───────────────────────────────────────
            if confidence < mode.min_confidence:
                log.info(
                    f"{instrument}: confidence {confidence:.2f} < "
                    f"min {mode.min_confidence:.2f} — skip"
                )
                _record_rejection(instrument, f"Konfidenz {confidence:.2f} < Min {mode.min_confidence:.2f} | {signal.direction}")
                continue

            # ── i. Multi-Timeframe (Feature 4) ───────────────────────────────
            if mode.require_mtf:
                mtf_ok, mtf_reason = mtf_confirmation(
                    client, instrument, signal.direction,
                    require_both=(mode.name == "conservative"),
                )
                if not mtf_ok:
                    log.info(f"{instrument}: MTF blocked — {mtf_reason}")
                    _record_rejection(instrument, f"MTF: {mtf_reason}")
                    continue

            # ── j. Korrelations-Exposure ──────────────────────────────────────
            open_trades = rm.get_open_trades()
            corr_blocked, corr_reason = correlation_blocked(
                open_trades, instrument, signal.direction,
                mode.risk_per_trade,
                max_exposure=mode.risk_per_trade * 3,
            )
            if corr_blocked:
                log.info(f"{instrument}: Correlation blocked — {corr_reason}")
                _record_rejection(instrument, f"Korrelation: {corr_reason}")
                continue

            # ── k. USD Concentration (Feature 9) ─────────────────────────────
            usd_blocked, usd_reason = usd_concentration_blocked(
                open_trades, instrument, signal.direction,
            )
            if usd_blocked:
                log.info(f"{instrument}: USD concentration — {usd_reason}")
                continue

            # ── k2. Global Exposure Check (Crypto + Forex) ───────────────────
            exposure_ok, exposure_reason = check_global_exposure(
                mode.risk_per_trade * dd_factor
            )
            if not exposure_ok:
                log.info(f"{instrument}: {exposure_reason}")
                continue

            # ── l. Swap Filter (Feature 4) ────────────────────────────────────
            swap_ok, swap_info = swap_filter(
                instrument, signal.direction, client=client,
            )
            if not swap_ok:
                log.info(f"{instrument}: Swap filter — {swap_info}")
                continue

            # ── m. Drawdown-adjusted + Session + Equity + Kelly + RiskParity +
            #        Capital Allocator + Model Governance position sizing ────────
            # Risk Parity: Faktor pro Pair (Durchschnitt = 1.0)
            rp_factor = 1.0
            try:
                rp_factor = get_rp_sizing_factor(instrument, _df_cache)
            except Exception:
                pass

            # Capital Allocator Adjustment: per-instrument mit Session-Score
            _instr_alloc = _capital_alloc_factor
            try:
                _allocator_i = get_capital_allocator()
                _sess_score  = min(1.0, sess_mult / 1.3)    # Normalisiert 0–1
                _regime_sc   = 0.7 if regime in ("TREND_UP", "TREND_DOWN") else 0.4
                _alloc_i     = _allocator_i.allocate(
                    regime        = regime,
                    session_score = _sess_score,
                    macro_score   = _allocator_i.get_macro_score(macro_ctx),
                    regime_score  = _regime_sc,
                    atr_pct       = atr_pct,
                    drawdown_pct  = rm.current_drawdown_pct() / 100.0,
                )
                _instr_alloc = _alloc_i.risk_scale
            except Exception:
                pass

            # Portfolio Weight Faktor (Markowitz): überwichtet top Pairs
            _portfolio_factor = 1.0
            if _portfolio_weights and instrument in _portfolio_weights:
                n_instr = max(1, len(_active_instruments))
                equal_w = 1.0 / n_instr
                _portfolio_factor = _portfolio_weights.get(instrument, equal_w) / equal_w
                _portfolio_factor = max(0.5, min(2.0, _portfolio_factor))

            adjusted_risk = (
                mode.risk_per_trade
                * dd_factor
                * min(sess_mult, 1.0)
                * equity_factor
                * kelly_factor          # Kelly: optimale Größe aus Win-Rate + Payoff
                * rp_factor             # Risk Parity: volatilitätsnormiert
                * _instr_alloc          # Capital Allocator: Regime × Session × Drawdown
                * _gov_size_factor      # Model Governance: Entropie + Kalibrierung
                * _portfolio_factor     # Markowitz: optimale Pair-Gewichtung
            )
            # Clamp: nicht unter 0.25% noch über 5% des Kapitals
            adjusted_risk = max(0.0025, min(0.05, adjusted_risk))

            units = client.calculate_units(
                instrument, signal.entry_price, signal.stop_loss,
                rm.capital, adjusted_risk,
            )
            if units == 0:
                log.warning(f"{instrument}: units=0, Trade übersprungen")
                continue

            signed_units = units if signal.direction == "BUY" else -units

            trade = ForexTrade(
                instrument  = instrument,
                direction   = signal.direction,
                units       = units,
                entry_price = signal.entry_price,
                stop_loss   = signal.stop_loss,
                take_profit = signal.take_profit,
                reason      = signal.reason,
            )

            # ── m2. Regime Change Warning — Trade abbrechen wenn Wechsel droht ─
            try:
                _rw = check_regime_change_warning(instrument, regime, df)
                if _rw and _rw.should_close:
                    log.warning(
                        f"{instrument}: Regime-Wechsel Frühwarnung "
                        f"({_rw.current_regime}→{_rw.next_regime} "
                        f"{_rw.probability:.0%}) — Trade abgebrochen"
                    )
                    continue
            except Exception as _rwe:
                log.debug(f"Regime Warning: {_rwe}")

            # ── m3. Entry Timer — M15 Pullback Refinement ─────────────────────
            try:
                if not cfg.LEAN_MODE:
                    _entry_result = get_refined_entry(
                        client       = client,
                        instrument   = instrument,
                        direction    = signal.direction,
                        h1_entry     = signal.entry_price,
                        h1_stop_loss = signal.stop_loss,
                    )
                    if _entry_result.mode == "pullback" and _entry_result.improvement > 0:
                        # Rebuild signal with refined entry/SL
                        signal = signal.__class__(
                            direction   = signal.direction,
                            confidence  = signal.confidence,
                            entry_price = _entry_result.entry_price,
                            stop_loss   = _entry_result.stop_loss,
                            take_profit = signal.take_profit,
                            reason      = signal.reason + f" | M15Entry(+{_entry_result.improvement:.1f}pip)",
                        )
                        log.info(
                            f"{instrument}: Entry Timer {_entry_result.reason} "
                            f"→ entry={signal.entry_price:.5f} sl={signal.stop_loss:.5f}"
                        )
            except Exception as _et_err:
                log.debug(f"Entry Timer: {_et_err}")

            # Signal accepted — record for dashboard
            _record_signal(instrument, signal.direction, confidence, signal.reason)

            # ── n0. Trade Explainability Narrative ───────────────────────────
            try:
                _indicators = compute_indicators(candles) if len(candles) >= 50 else {}
                _trade_ctx = TradeContext(
                    instrument       = instrument,
                    direction        = signal.direction,
                    confidence       = confidence,
                    regime           = regime,
                    session          = sess_name,
                    rsi              = _indicators.get("rsi"),
                    macd_hist        = _indicators.get("macd_hist"),
                    ema_cross_signal = "bullish" if signal.direction == "BUY" else "bearish",
                    micro_bias       = micro_bias,
                    micro_score      = micro_score,
                    entry_price      = signal.entry_price,
                    stop_loss        = signal.stop_loss,
                    take_profit      = signal.take_profit,
                    risk_usd         = rm.capital * adjusted_risk,
                    risk_pct         = adjusted_risk,
                    units            = float(units),
                    top_features     = sorted(ml_importances.items(), key=lambda x: -x[1])[:3] if ml_importances else [],
                    lstm_active      = _lstm_ensemble.is_active,
                    lstm_direction   = "HOLD",
                    strategy_name    = strategy_name,
                    governance_factor= _gov_size_factor,
                )
                log_trade_narrative(_trade_ctx)
            except Exception as _exp_err:
                log.debug(f"Explainability: {_exp_err}")

            # ── n. Order platzieren ───────────────────────────────────────────
            # Pullback-Signale → Limit-Order 2 Pips besser als aktueller Preis
            is_pullback = "pullback" in strategy_name.lower() or "pullback" in signal.reason.lower()
            pip_sz_n    = 0.01 if "JPY" in instrument else 0.0001

            if is_pullback and instrument not in _pending_limit_orders:
                # Limit-Order 2 Pips besser (warte auf weitere Kursschwäche/-stärke)
                limit_offset = 2 * pip_sz_n
                if signal.direction == "BUY":
                    limit_price = round(signal.entry_price - limit_offset, 5)
                else:
                    limit_price = round(signal.entry_price + limit_offset, 5)
                trade.entry_price = limit_price

                if cfg.TRADING_MODE == "live":
                    try:
                        lo_result = client.place_limit_order(
                            instrument, signed_units, limit_price,
                            signal.stop_loss, signal.take_profit,
                            gtd_seconds=3600,
                        )
                        order_id = (
                            lo_result.get("dealReference", "")
                            or lo_result.get("orderId", "")
                            or lo_result.get("workingOrderId", "")
                        )
                        _pending_limit_orders[instrument] = {
                            "order_id": order_id,
                            "expires":  time.time() + 3600,
                        }
                        log.info(
                            f"Limit-Order: {instrument} {signal.direction} "
                            f"@ {limit_price:.5f} (2pip besser, 1h GTD)"
                        )
                        rm.record_open(trade)
                    except Exception as _lo_err:
                        log.warning(f"Limit-Order fehlgeschlagen ({instrument}), verwende Market: {_lo_err}")
                        result = client.place_market_order(
                            instrument, signed_units,
                            signal.stop_loss, signal.take_profit,
                        )
                        fill = result.get("orderFillTransaction", {})
                        trade.trade_id    = fill.get("tradeOpened", {}).get("tradeID", "")
                        trade.entry_price = float(fill.get("price", signal.entry_price))
                        rm.record_open(trade)
                else:
                    # Paper: Limit direkt ausführen
                    rm.record_open(trade)
            else:
                if cfg.TRADING_MODE == "live":
                    result = client.place_market_order(
                        instrument, signed_units,
                        signal.stop_loss, signal.take_profit,
                    )
                    fill = result.get("orderFillTransaction", {})
                    trade.trade_id    = fill.get("tradeOpened", {}).get("tradeID", "")
                    trade.entry_price = float(fill.get("price", signal.entry_price))

                rm.record_open(trade)

            # Pending Features für Online Learner speichern
            _pending_features[instrument] = [ol_features, strategy_name, signal.confidence, raw_probs]

            extra = f" | DD×{dd_factor:.2f}" if dd_factor < 1.0 else ""
            sess_info = f" | {sess_name}×{sess_mult:.2f}" if sess_mult != 1.0 else ""
            telegram.alert_trade_opened(
                instrument, signal.direction, units,
                trade.entry_price, signal.stop_loss, signal.take_profit,
                f"{signal.reason} | Regime={regime} | [{strategy_name}] | "
                f"Mode={mode.name}{extra}{sess_info}",
            )

        except Exception as e:
            log.error(f"{instrument} Fehler: {e}", exc_info=True)

    # ── 12b. Carry Trade Signale (wenn Slots frei) ───────────────────────────
    if macro_ctx and rm.open_trade_count() < mode.max_open_trades:
        try:
            carry_signals = get_carry_trade_signals(macro_ctx, _cot_ctx, max_trades=1)
            for cs in carry_signals:
                if rm.already_open(cs.instrument):
                    continue
                if rm.open_trade_count() >= mode.max_open_trades:
                    break

                candles = _candles_cache.get(cs.instrument)
                if candles is None:
                    try:
                        candles = client.get_candles(cs.instrument, cfg.TIMEFRAME, count=50)
                    except Exception:
                        continue

                # Position-Sizing mit Carry-ATR-Multiplikator (weiter SL)
                try:
                    _cached = _df_cache.get(cs.instrument)
                    carry_df = _cached if _cached is not None else pd.DataFrame(candles)
                    for _c in ("open", "high", "low", "close"):
                        carry_df[_c] = carry_df[_c].astype(float)

                    from forex_bot.strategy.forex_strategy import generate_signal
                    carry_sig = generate_signal(
                        candles, cs.instrument,
                        atr_multiplier=cs.atr_mult,
                        rr_ratio=mode.rr_ratio,
                    )
                    if carry_sig.direction != cs.direction:
                        continue   # Technisches Signal widerspricht Carry-Richtung

                    units = client.calculate_units(
                        cs.instrument, carry_sig.entry_price, carry_sig.stop_loss,
                        rm.capital, mode.risk_per_trade * dd_factor * equity_factor,
                    )
                    if units == 0:
                        continue

                    signed_units = units if cs.direction == "BUY" else -units
                    carry_trade  = ForexTrade(
                        instrument  = cs.instrument,
                        direction   = cs.direction,
                        units       = units,
                        entry_price = carry_sig.entry_price,
                        stop_loss   = carry_sig.stop_loss,
                        take_profit = carry_sig.take_profit,
                        reason      = cs.reason,
                    )

                    if cfg.TRADING_MODE == "live":
                        result     = client.place_market_order(
                            cs.instrument, signed_units,
                            carry_sig.stop_loss, carry_sig.take_profit,
                        )
                        fill       = result.get("orderFillTransaction", {})
                        carry_trade.trade_id    = fill.get("tradeOpened", {}).get("tradeID", "")
                        carry_trade.entry_price = float(fill.get("price", carry_sig.entry_price))

                    rm.record_open(carry_trade)
                    telegram.alert_trade_opened(
                        cs.instrument, cs.direction, units,
                        carry_trade.entry_price, carry_sig.stop_loss, carry_sig.take_profit,
                        cs.reason,
                    )
                    log.info(f"Carry Trade eröffnet: {cs.instrument} +{cs.differential:.1f}%p.a.")

                except Exception as e:
                    log.warning(f"Carry Trade {cs.instrument}: {e}")

        except Exception as e:
            log.debug(f"Carry Trade Signale: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mode = get_current_mode()

    log.info("=" * 60)
    log.info(f"Forex Bot startet — Modus: {cfg.TRADING_MODE.upper()}")
    log.info(f"Risk Mode: {mode.name.upper()}")
    log.info(f"Instruments: {', '.join(cfg.INSTRUMENTS)}")
    log.info(f"Broker: {cfg.FOREX_BROKER}")
    log.info("=" * 60)

    rm       = ForexRiskManager(
        cfg.INITIAL_CAPITAL,
        mode.risk_per_trade,
        cfg.MAX_DRAWDOWN,
        mode.max_open_trades,
    )
    telegram = ForexTelegramBot(bot_state)

    global _active_client
    try:
        _active_client = create_broker_client()
        _env_map = {"oanda": cfg.OANDA_ENV, "ig": cfg.IG_ENV,
                    "capital": getattr(cfg, "CAPITAL_ENV", "demo"),
                    "ibkr": getattr(cfg, "IBKR_ENV", "live")}
        bot_state["broker"]           = cfg.FOREX_BROKER
        bot_state["broker_env"]       = _env_map.get(cfg.FOREX_BROKER, "")
        bot_state["broker_connected"] = True
        bot_state["broker_error"]     = ""
        log.info(f"Broker verbunden: {cfg.FOREX_BROKER}")
    except Exception as _e:
        bot_state["broker"]           = cfg.FOREX_BROKER
        bot_state["broker_connected"] = False
        bot_state["broker_error"]     = str(_e)
        bot_state["running"]          = False
        log.error(f"Broker-Verbindung fehlgeschlagen: {_e}")

    bot_state["ml_model_info"] = _ml_model.get_model_info()

    # Dashboard API
    try:
        import uvicorn, threading
        from forex_bot.dashboard.api import app as api_app, set_bot_state, set_risk_mode_callback, set_broker_callback
        set_bot_state(bot_state)
        set_risk_mode_callback(set_current_mode_manual)
        set_broker_callback(switch_broker)
        t = threading.Thread(
            target=lambda: uvicorn.run(api_app, host="0.0.0.0", port=cfg.API_PORT, log_level="warning"),
            daemon=True, name="forex-api"
        )
        t.start()
        log.info(f"Dashboard API auf Port {cfg.API_PORT}")
    except Exception as e:
        log.warning(f"Dashboard API nicht gestartet: {e}")

    telegram.start_with_rm(rm)

    def _shutdown(sig, frame):
        log.info("Shutdown Signal empfangen")
        bot_state["running"] = False
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    telegram.send(
        f"💱 <b>Forex Bot gestartet</b>\n\n"
        f"Modus: {cfg.TRADING_MODE.upper()}\n"
        f"Risk Mode: {mode.name.upper()}\n"
        f"Pairs: {', '.join(cfg.INSTRUMENTS)}\n"
        f"Kapital: ${cfg.INITIAL_CAPITAL:,.0f}\n"
        f"ML Modell: {'geladen' if _ml_model.is_loaded() else 'nicht geladen (rule-based)'}"
    )

    while bot_state["running"]:
        if not bot_state["paused"]:
            try:
                summary = rm.summary()
                bot_state["capital"]     = summary.get("capital", cfg.INITIAL_CAPITAL)
                bot_state["open_trades"] = summary.get("open_trades", 0)
                bot_state["positions"]   = [
                    {"instrument": t.instrument, "direction": t.direction,
                     "units": t.units, "entry_price": t.entry_price}
                    for t in rm.get_open_trades()
                ]
                bot_state["ml_model_info"] = _ml_model.get_model_info()

                from forex_bot.execution.spread_monitor import spread_stats
                bot_state["spread_ema"] = spread_stats()

                run_cycle(_active_client, rm, telegram)
                now_iso = datetime.now(timezone.utc).isoformat()
                bot_state["last_cycle"]     = now_iso
                bot_state["last_heartbeat"] = now_iso

            except Exception as e:
                log.error(f"Zyklus-Fehler: {e}", exc_info=True)

        # Heartbeat every 60s during the sleep window so dashboard stays green
        _sleep_remaining = CYCLE_SECONDS
        _TICK = 60
        while _sleep_remaining > 0:
            time.sleep(min(_TICK, _sleep_remaining))
            _sleep_remaining -= _TICK
            bot_state["last_heartbeat"] = datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
