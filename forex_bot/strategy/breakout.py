"""
Breakout Strategy — 20-Perioden Kanal-Ausbruch.

Geeignet für:
  - Volatile Sessions (London Open 07–09 UTC, NY Open 13–15 UTC)
  - HIGH_VOLATILITY Regime (Momentum-Plays)
  - Trending markets nach Konsolidierung

Signal:
  BUY:  Close > 20-Perioden Hoch + 0.3×ATR Bestätigung
  SELL: Close < 20-Perioden Tief  − 0.3×ATR Bestätigung

Unterschied zu EMA-Crossover:
  - Feuert SOFORT beim Ausbruch, nicht erst nach Trendaufbau
  - Besser für das Erfassen großer Tagesbewegungen bei Marktöffnungen
  - Breiter RSI-Filter (30–70 statt 40–65)
"""
import logging

import pandas as pd

from forex_bot.strategy.forex_strategy import ForexSignal, compute_indicators

log = logging.getLogger("forex_bot")

_CHANNEL_PERIOD      = 20    # Kanal-Lookback in Candles
_BREAKOUT_ATR_FACTOR = 0.30  # Mindest-Abstand über/unter Kanal als ATR-Vielfaches


def generate_breakout_signal(
    candles:        list,
    instrument:     str,
    atr_multiplier: float = 1.5,
    rr_ratio:       float = 2.0,
) -> ForexSignal:
    """
    Erzeugt ein Breakout-Signal aus einem Preiskanal-Ausbruch.

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

    # Kanal: Hoch/Tief der letzten _CHANNEL_PERIOD Candles (letzte Candle ausgeschlossen)
    channel_slice = df.iloc[-(_CHANNEL_PERIOD + 1):-1]
    high_channel  = float(channel_slice["high"].max())
    low_channel   = float(channel_slice["low"].min())

    confirm = atr * _BREAKOUT_ATR_FACTOR

    direction  = "HOLD"
    confidence = 0.0
    reason     = "Kein Breakout"

    # ── Volume + ATR Konsolidierungs-Filter ──────────────────────────────────
    # Volume-Spike bestätigt echten Breakout (false breakouts haben meist kein Vol.)
    vol_series   = df["volume"].iloc[-21:-1].astype(float)
    avg_vol      = float(vol_series.mean()) if vol_series.mean() > 0 else 1.0
    curr_vol     = float(last["volume"]) if float(last["volume"]) > 0 else avg_vol
    vol_ratio    = curr_vol / avg_vol

    # ATR-Kompression: echte Breakouts kommen meist aus einer Seitwärtsphase
    recent_atr = float(df["atr"].iloc[-5:-1].mean())
    prior_atr  = float(df["atr"].iloc[-20:-5].mean()) if float(df["atr"].iloc[-20:-5].mean()) > 0 else recent_atr
    compressed = recent_atr < prior_atr * 0.85

    # ── BUY Breakout: Preis über 20-Perioden-Hoch ─────────────────────────────
    if price > high_channel + confirm:
        direction  = "BUY"
        confidence = 0.55
        strength   = (price - high_channel) / atr if atr > 0 else 0

        if strength > 0.5:           confidence += 0.10
        if strength > 1.0:           confidence += 0.05
        if last["macd_h"] > 0:       confidence += 0.05
        if 30 < last["rsi"] < 70:    confidence += 0.05
        if vol_ratio > 1.5:          confidence += 0.05   # Volume-Bestätigung
        if compressed:               confidence += 0.05   # Breakout aus Konsolidierung

        reason = (
            f"Breakout ↑ | Kanal {high_channel:.5f} | "
            f"Stärke {strength:.2f}× ATR | Vol {vol_ratio:.1f}× | RSI {last['rsi']:.0f}"
        )

    # ── SELL Breakout: Preis unter 20-Perioden-Tief ───────────────────────────
    elif price < low_channel - confirm:
        direction  = "SELL"
        confidence = 0.55
        strength   = (low_channel - price) / atr if atr > 0 else 0

        if strength > 0.5:           confidence += 0.10
        if strength > 1.0:           confidence += 0.05
        if last["macd_h"] < 0:       confidence += 0.05
        if 30 < last["rsi"] < 70:    confidence += 0.05
        if vol_ratio > 1.5:          confidence += 0.05   # Volume-Bestätigung
        if compressed:               confidence += 0.05   # Breakout aus Konsolidierung

        reason = (
            f"Breakout ↓ | Kanal {low_channel:.5f} | "
            f"Stärke {strength:.2f}× ATR | Vol {vol_ratio:.1f}× | RSI {last['rsi']:.0f}"
        )

    sl_dist = atr * atr_multiplier
    tp_dist = sl_dist * rr_ratio

    if direction == "BUY":
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        sl = price + sl_dist
        tp = price - tp_dist

    pips_sl = round(sl_dist / pip_size, 1)

    log.debug(
        f"{instrument} Breakout: {direction} conf={confidence:.2f} "
        f"channel=[{low_channel:.5f},{high_channel:.5f}]"
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
