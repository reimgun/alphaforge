"""
Rollover-Zeit-Erkennung — Forex Daily Rollover (17:00 NYC).

Forex-Positionen die über 17:00 NYC-Zeit gehalten werden, akkumulieren
Overnight-Swaps. Das kann:
  1. Kosten: negative Swaps für kontra-carry Paare
  2. Slippage: Broker weiten Spreads um 17:00 aus
  3. Rollover-Spike: kurze Liquiditätslücke um 17:00 exakt

Was dieser Guard macht:
  - Erkennt das 30-Minuten-Fenster VOR und NACH 17:00 NYC
  - Blockiert NEUE Trades in diesem Fenster (zu viel Spread-Risiko)
  - Gibt Warnungen für laufende Positionen die über Rollover gehalten werden
  - Keine Auto-Schließung (das ist Aufgabe des Traders / Carry-Strategie)

NYC-Zeit: UTC - 5 (EST) oder UTC - 4 (EDT während Sommerzeit)
  - DST-Erkennung: März 2. Sonntag bis November 1. Sonntag

Verwendung:
    from forex_bot.execution.rollover_guard import (
        is_rollover_window, minutes_to_rollover, check_open_trade_rollover_risk,
    )

    if is_rollover_window():
        # Kein neuer Trade
        pass

    mins = minutes_to_rollover()  # -30 bis +30 (negativ = vor Rollover)
"""
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("forex_bot")

# Fenster vor und nach Rollover in Minuten
PRE_ROLLOVER_MINUTES  = 30   # 30 Min vor 17:00 NYC
POST_ROLLOVER_MINUTES = 15   # 15 Min nach 17:00 NYC (Spreads normalisieren sich schnell)


def _is_dst_nyc(dt: datetime) -> bool:
    """
    Bestimmt ob EDT (UTC-4) oder EST (UTC-5) aktiv ist.
    DST: zweiter Sonntag im März bis erster Sonntag im November.
    """
    year  = dt.year
    month = dt.month
    day   = dt.day

    # Zweiter Sonntag im März
    march_start = datetime(year, 3, 1)
    days_to_sun = (6 - march_start.weekday()) % 7   # Tage bis zum 1. Sonntag
    dst_start_day = 8 + days_to_sun  # zweiter Sonntag = +7
    dst_start = datetime(year, 3, dst_start_day, 2, 0, 0)

    # Erster Sonntag im November
    nov_start     = datetime(year, 11, 1)
    days_to_sun   = (6 - nov_start.weekday()) % 7
    dst_end_day   = 1 + days_to_sun
    dst_end       = datetime(year, 11, dst_end_day, 2, 0, 0)

    # Vergleich ohne Timezone
    dt_naive = dt.replace(tzinfo=None)
    return dst_start <= dt_naive < dst_end


def _utc_to_nyc(utc_dt: datetime) -> datetime:
    """Konvertiert UTC Zeit zu NYC Zeit (EDT/EST automatisch)."""
    utc_naive = utc_dt.replace(tzinfo=None)
    if _is_dst_nyc(utc_naive):
        offset = timedelta(hours=-4)   # EDT
    else:
        offset = timedelta(hours=-5)   # EST
    return (utc_dt + offset).replace(tzinfo=None)


def minutes_to_rollover(now_utc: datetime | None = None) -> float:
    """
    Berechnet Minuten bis (positiv) oder seit (negativ) 17:00 NYC.

    Returns
    -------
    float: Minuten bis Rollover (negativ = Rollover ist in der Vergangenheit innerhalb des Fensters)
           None = kein relevantes Fenster aktiv
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    nyc_now  = _utc_to_nyc(now_utc)
    rollover = nyc_now.replace(hour=17, minute=0, second=0, microsecond=0)

    delta_minutes = (rollover - nyc_now).total_seconds() / 60
    return delta_minutes


def is_rollover_window(now_utc: datetime | None = None) -> bool:
    """
    Gibt True zurück wenn wir im Rollover-Fenster sind
    (30 Min vor oder 15 Min nach 17:00 NYC).

    KEIN Trading in diesem Fenster (erhöhte Spreads, Liquiditätslücke).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    mins = minutes_to_rollover(now_utc)

    # Wochenende: kein Rollover
    nyc_now = _utc_to_nyc(now_utc)
    if nyc_now.weekday() >= 5:  # Sa=5, So=6
        return False

    # Fenster: -PRE bis +POST Minuten um 17:00
    in_window = -POST_ROLLOVER_MINUTES <= mins <= PRE_ROLLOVER_MINUTES
    return in_window


def get_rollover_status(now_utc: datetime | None = None) -> dict:
    """
    Vollständiger Rollover-Status für Dashboard und Logging.

    Returns
    -------
    dict:
        in_window:      bool
        mins_to_roll:   float (negativ = danach)
        nyc_time:       str
        message:        str
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    nyc_now  = _utc_to_nyc(now_utc)
    mins     = minutes_to_rollover(now_utc)
    in_win   = is_rollover_window(now_utc)

    if in_win:
        if mins > 0:
            msg = f"⚠️ Rollover in {mins:.0f} Min (17:00 NYC) — kein neuer Trade"
        else:
            msg = f"⚠️ Rollover vor {abs(mins):.0f} Min — Spreads normalisieren sich"
    else:
        msg = f"✅ Außerhalb Rollover-Fenster ({mins:.0f} Min)"

    return {
        "in_window":    in_win,
        "mins_to_roll": round(mins, 1),
        "nyc_time":     nyc_now.strftime("%H:%M"),
        "message":      msg,
    }


def check_open_trade_rollover_risk(
    open_trades:  list,
    now_utc:      datetime | None = None,
) -> list[dict]:
    """
    Prüft ob laufende Trades ein Rollover-Risiko haben.

    Gibt Liste von Warnungen zurück für Trades die über 17:00 NYC
    gehalten werden und negative Swaps haben könnten.

    Parameters
    ----------
    open_trades: Liste von ForexTrade-Objekten oder Dicts mit 'instrument', 'direction'

    Returns
    -------
    list[dict]: Warnungen mit 'instrument', 'direction', 'warning'
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    mins  = minutes_to_rollover(now_utc)
    # Nur warnen wenn Rollover in den nächsten 60 Minuten
    if mins < 0 or mins > 60:
        return []

    # Paare mit bekannt negativen Swaps (Richtung: Long/Short)
    # Bei positiven Carry-Differentials (carry_trade.py) ignorieren
    _NEGATIVE_SWAP_RISK = {
        "EUR_USD": {"BUY"},    # EUR usually negative carry
        "EUR_JPY": {"BUY"},
        "EUR_GBP": {"BUY"},
        "GBP_USD": {"BUY"},
        "USD_CHF": {"SELL"},   # CHF usually negative carry
    }

    warnings = []
    for trade in open_trades:
        if hasattr(trade, "instrument"):
            instrument = trade.instrument
            direction  = getattr(trade, "direction", "")
        elif isinstance(trade, dict):
            instrument = trade.get("instrument", "")
            direction  = trade.get("direction", "")
        else:
            continue

        risk_dirs = _NEGATIVE_SWAP_RISK.get(instrument, set())
        if direction in risk_dirs:
            warnings.append({
                "instrument": instrument,
                "direction":  direction,
                "warning":    f"Rollover in {mins:.0f} Min — möglicher negativer Swap für {direction} {instrument}",
            })

    return warnings
