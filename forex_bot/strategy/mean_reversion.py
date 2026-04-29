"""
Mean Reversion Strategy — Bollinger Bands + RSI.

Geeignet für:
  - SIDEWAYS Regime (seitwärts laufende Märkte)
  - Asia Session (00–07 UTC) für nicht-JPY Paare
  - Ruhige London-Hauptphase bei engen Bollinger Bändern

Signal:
  BUY:  Preis berührt unteres BB UND RSI < 35 (überverkauft)
         Take-Profit = BB-Mitte (Rückkehr zum Mittelwert)

  SELL: Preis berührt oberes BB UND RSI > 65 (überkauft)
         Take-Profit = BB-Mitte

Wichtig: Diese Strategie ist NICHT für Trending-Märkte gedacht.
Sie wird nur aktiv wenn das Regime SIDEWAYS ist.
"""
import logging

import pandas as pd

from forex_bot.strategy.forex_strategy import ForexSignal, compute_indicators

log = logging.getLogger("forex_bot")

_RSI_OVERSOLD        = 35
_RSI_OVERBOUGHT      = 65
_BB_TOUCH_THRESHOLD  = 0.12  # Preis muss innerhalb 12% der BB-Breite von der Band sein


def generate_mean_reversion_signal(
    candles:        list,
    instrument:     str,
    atr_multiplier: float = 1.2,   # engeres SL für Mean Reversion
    rr_ratio:       float = 1.5,   # niedrigeres RR, da TP nur die Mitte ist
) -> ForexSignal:
    """
    Erzeugt ein Mean-Reversion-Signal aus Bollinger Bands + RSI.

    Returns ForexSignal mit direction BUY / SELL / HOLD.
    """
    if len(candles) < 30:
        return ForexSignal(instrument, "HOLD", 0, 0, 0, 0, 0, 0.0, "Zu wenig Daten")

    df   = compute_indicators(candles)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price    = float(last["close"])
    atr      = float(last["atr"])
    pip_size = 0.01 if "JPY" in instrument else 0.0001

    bb_upper = float(last["bb_upper"])
    bb_lower = float(last["bb_lower"])
    bb_mid   = float(last["bb_mid"])
    bb_range = bb_upper - bb_lower

    if bb_range <= 0:
        return ForexSignal(instrument, "HOLD", 0, 0, 0, 0, 0, 0.0, "BB Range = 0")

    rsi = float(last["rsi"])

    direction  = "HOLD"
    confidence = 0.0
    reason     = "Kein Mean-Reversion-Signal"
    tp         = bb_mid
    sl_dist    = atr * atr_multiplier

    dist_from_lower = (price - bb_lower) / bb_range
    dist_from_upper = (bb_upper - price) / bb_range

    # ── BUY: Preis nahe unterem BB + überverkauft ─────────────────────────────
    if dist_from_lower < _BB_TOUCH_THRESHOLD and rsi < _RSI_OVERSOLD:
        direction  = "BUY"
        confidence = 0.55

        if rsi < 30:               confidence += 0.10
        if dist_from_lower < 0.05: confidence += 0.08
        # MACD verliert Abwärtsmomentum → gut für Umkehr
        if last["macd_h"] > prev["macd_h"]: confidence += 0.07

        tp     = bb_mid
        sl     = price - sl_dist
        reason = (
            f"Mean Reversion ↑ | BB-Tief berührt | "
            f"RSI {rsi:.0f} | Ziel BB-Mitte {bb_mid:.5f}"
        )

    # ── SELL: Preis nahe oberem BB + überkauft ───────────────────────────────
    elif dist_from_upper < _BB_TOUCH_THRESHOLD and rsi > _RSI_OVERBOUGHT:
        direction  = "SELL"
        confidence = 0.55

        if rsi > 70:               confidence += 0.10
        if dist_from_upper < 0.05: confidence += 0.08
        if last["macd_h"] < prev["macd_h"]: confidence += 0.07

        tp     = bb_mid
        sl     = price + sl_dist
        reason = (
            f"Mean Reversion ↓ | BB-Hoch berührt | "
            f"RSI {rsi:.0f} | Ziel BB-Mitte {bb_mid:.5f}"
        )
    else:
        sl = price - sl_dist
        tp = price + sl_dist * rr_ratio

    # Mindest-RR 1:0.8 prüfen (TP muss zumindest 80% des SL-Abstands entfernt sein)
    if direction != "HOLD":
        tp_dist = abs(tp - price)
        if tp_dist < sl_dist * 0.8:
            direction  = "HOLD"
            confidence = 0.0
            reason     = (
                f"Mean Reversion: RR zu niedrig "
                f"(TP={abs(tp-price)/pip_size:.0f}pip vs SL={sl_dist/pip_size:.0f}pip)"
            )

    pips_sl = round(sl_dist / pip_size, 1)

    log.debug(
        f"{instrument} MeanRev: {direction} conf={confidence:.2f} "
        f"RSI={rsi:.0f} BB=[{bb_lower:.5f},{bb_upper:.5f}]"
    )

    return ForexSignal(
        instrument  = instrument,
        direction   = direction,
        entry_price = round(price, 5),
        stop_loss   = round(sl, 5),
        take_profit = round(tp, 5),
        atr         = round(atr, 5),
        pips_sl     = pips_sl,
        confidence  = round(min(confidence, 1.0), 2),
        reason      = reason,
    )
