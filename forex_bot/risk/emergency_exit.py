"""
Full Market Exit Mode — Sofortiger Ausstieg bei Systemrisiko.

Trigger-Bedingungen (ANY reicht):
  - Global Drawdown > GLOBAL_DD_THRESHOLD  (Standard: 15%)
  - VIX Spike       > VIX_SPIKE_THRESHOLD  (Standard: 40)
  - Spread Schock   > SPREAD_RATIO_THRESHOLD × Normal (Standard: 3×) auf ≥ SPREAD_PAIRS_MIN Paaren

Was passiert:
  1. Alle offenen Positionen werden mit Market-Order geschlossen
  2. Bot wird in EMERGENCY_EXIT Modus versetzt
  3. Kein neuer Trade möglich bis expliziter Reset
  4. Telegram-Alert mit Grund

Unterschied zu bisherigen Schutzmechanismen:
  - Circuit Breaker:  stoppt NUR neue Trades, lässt laufende offen
  - Emergency Exit:   schließt ALLE laufenden Trades sofort

Verwendung:
    from forex_bot.risk.emergency_exit import (
        check_emergency_conditions, execute_emergency_exit,
        is_emergency_active, reset_emergency_mode,
    )
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("forex_bot")

# ── Schwellenwerte ────────────────────────────────────────────────────────────
GLOBAL_DD_THRESHOLD      = 0.15   # 15% globaler Drawdown → Exit
VIX_SPIKE_THRESHOLD      = 40.0   # VIX > 40 → Black Swan Schutz
SPREAD_RATIO_THRESHOLD   = 3.0    # Spread > 3× Normal auf mehreren Paaren
SPREAD_PAIRS_MIN         = 3      # Mindestanzahl Paare mit Spread-Schock

# ── Interner State ────────────────────────────────────────────────────────────
@dataclass
class EmergencyState:
    active:       bool  = False
    triggered_at: str   = ""
    reason:       str   = ""
    trades_closed: int  = 0
    pnl_at_exit:  float = 0.0


_state = EmergencyState()


def is_emergency_active() -> bool:
    """Gibt True zurück wenn Emergency-Exit aktiv (kein Trading möglich)."""
    return _state.active


def reset_emergency_mode(confirm: bool = False) -> bool:
    """
    Setzt Emergency-Modus zurück — explizite Bestätigung erforderlich.

    Parameters
    ----------
    confirm: Muss True sein (Sicherheitsmaßnahme gegen versehentlichen Reset)

    Returns
    -------
    True wenn zurückgesetzt, False wenn verweigert
    """
    if not confirm:
        log.warning("Emergency reset verweigert — confirm=True erforderlich")
        return False

    global _state
    _state = EmergencyState()
    log.info("Emergency Exit Mode zurückgesetzt — Trading wieder möglich")
    return True


def get_emergency_state() -> dict:
    """Gibt aktuellen Emergency-State als Dict zurück (für Dashboard)."""
    return {
        "active":        _state.active,
        "triggered_at":  _state.triggered_at,
        "reason":        _state.reason,
        "trades_closed": _state.trades_closed,
        "pnl_at_exit":   _state.pnl_at_exit,
    }


def check_emergency_conditions(
    capital:       float,
    peak_capital:  float,
    vix:           float | None,
    spread_ratios: dict[str, float],   # {instrument: current/baseline ratio}
) -> tuple[bool, str]:
    """
    Prüft ob Emergency-Exit-Bedingungen erfüllt sind.

    Parameters
    ----------
    capital:       Aktuelles Kapital
    peak_capital:  Höchstes bisheriges Kapital
    vix:           Aktueller VIX-Wert (None wenn nicht verfügbar)
    spread_ratios: Verhältnis aktuelle Spread / EMA-Baseline pro Instrument

    Returns
    -------
    (should_exit: bool, reason: str)
    """
    if peak_capital <= 0:
        return False, ""

    # ── 1. Globaler Drawdown ──────────────────────────────────────────────────
    global_dd = (peak_capital - capital) / peak_capital
    if global_dd >= GLOBAL_DD_THRESHOLD:
        return True, (
            f"Globaler Drawdown {global_dd:.1%} ≥ {GLOBAL_DD_THRESHOLD:.0%} — "
            f"Kapitalschutz aktiviert"
        )

    # ── 2. VIX Spike ──────────────────────────────────────────────────────────
    if vix is not None and vix >= VIX_SPIKE_THRESHOLD:
        return True, (
            f"VIX Spike {vix:.1f} ≥ {VIX_SPIKE_THRESHOLD:.0f} — "
            f"Black-Swan-Ereignis erkannt"
        )

    # ── 3. Spread-Schock auf mehreren Paaren ─────────────────────────────────
    shocked_pairs = [
        inst for inst, ratio in spread_ratios.items()
        if ratio >= SPREAD_RATIO_THRESHOLD
    ]
    if len(shocked_pairs) >= SPREAD_PAIRS_MIN:
        return True, (
            f"Liquiditätskrise: {len(shocked_pairs)} Paare mit Spread ≥ "
            f"{SPREAD_RATIO_THRESHOLD:.0f}× Normal: {', '.join(shocked_pairs[:5])}"
        )

    return False, ""


def execute_emergency_exit(
    client,
    open_trades:  list,
    reason:       str,
    telegram      = None,
    capital:      float = 0.0,
) -> int:
    """
    Schließt ALLE offenen Positionen mit Market-Order.

    Parameters
    ----------
    client:      OandaClient Instanz
    open_trades: Liste von ForexTrade Objekten (oder Dicts mit 'trade_id')
    reason:      Grund für den Emergency Exit
    telegram:    ForexTelegramBot Instanz (für Alert)
    capital:     Aktuelles Kapital (für State-Protokollierung)

    Returns
    -------
    int: Anzahl geschlossener Trades
    """
    global _state

    if _state.active:
        log.warning("Emergency Exit bereits aktiv — kein Doppel-Trigger")
        return 0

    _state.active        = True
    _state.triggered_at  = datetime.now(timezone.utc).isoformat()
    _state.reason        = reason
    _state.pnl_at_exit   = capital
    _state.trades_closed = 0

    log.critical(f"EMERGENCY EXIT AKTIVIERT: {reason}")

    # ── Telegram Alert ────────────────────────────────────────────────────────
    if telegram is not None:
        try:
            telegram.send(
                f"🚨 <b>EMERGENCY EXIT</b>\n"
                f"Grund: {reason}\n"
                f"Offene Trades werden geschlossen..."
            )
        except Exception:
            pass

    # ── Alle Trades schließen ─────────────────────────────────────────────────
    closed = 0
    for trade in open_trades:
        try:
            # trade kann ForexTrade-Objekt oder Dict sein
            if hasattr(trade, "trade_id"):
                trade_id   = trade.trade_id
                instrument = trade.instrument
                units      = getattr(trade, "units", None)
            elif isinstance(trade, dict):
                trade_id   = trade.get("trade_id") or trade.get("id")
                instrument = trade.get("instrument", "UNKNOWN")
                units      = trade.get("units")
            else:
                log.warning(f"Emergency exit: unbekannter Trade-Typ: {type(trade)}")
                continue

            if not trade_id:
                continue

            # Market-Close via OANDA
            client.close_trade(trade_id)
            closed += 1
            log.warning(f"Emergency closed: {instrument} trade_id={trade_id}")

        except Exception as e:
            log.error(f"Emergency exit: Fehler beim Schließen von Trade {trade}: {e}")

    _state.trades_closed = closed

    log.critical(
        f"Emergency Exit abgeschlossen: {closed} Trades geschlossen. "
        f"Grund: {reason}"
    )

    if telegram is not None:
        try:
            telegram.send(
                f"✅ <b>Emergency Exit abgeschlossen</b>\n"
                f"{closed} Trades geschlossen.\n"
                f"Trading pausiert bis manueller Reset.\n"
                f"API: POST /control/reset_emergency"
            )
        except Exception:
            pass

    return closed
