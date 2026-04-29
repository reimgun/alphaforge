"""
Forex Microstructure Proxy — Institutioneller Flow-Indikator.

Da Forex-Retail-Broker kein Orderbook oder echtes Volumen bereitstellen,
approximieren wir Microstructure-Signale aus OHLC-Daten:

  1. Candle-Body-Pressure:    (Close - Low) / (High - Low) → Buyer/Seller Dominanz
  2. Wick-Ratio Asymmetrie:   Oberer vs. unterer Wick → Rejection-Signale
  3. Momentum-Konsistenz:     Konsistenz der letzten 5 Candles in einer Richtung
  4. ATR-Expansion:           Steigende ATR = wachsendes Interesse = Momentum
  5. Close-vs-EMA:            Abstand Close zu EMA20 als Trend-Stärke-Proxy

Ergebnis: microstructure_bias = BULLISH | BEARISH | NEUTRAL
          microstructure_score = 0.0 – 1.0

Verwendung in bot.py (für Capital Allocator):
    from forex_bot.execution.microstructure import get_microstructure_bias
    bias, score = get_microstructure_bias(df, instrument)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

MIN_CANDLES = 20


def _candle_body_pressure(df: pd.DataFrame, n: int = 10) -> float:
    """
    Buyer/Seller Dominanz aus Candle-Körper-Position.

    (Close - Low) / (High - Low) → 1.0 = Buyer, 0.0 = Seller, 0.5 = neutral

    Gibt gewichteten Durchschnitt der letzten N Candles zurück (neuere stärker).
    """
    subset = df.tail(n)
    highs  = subset["high"].astype(float)
    lows   = subset["low"].astype(float)
    closes = subset["close"].astype(float)

    ranges = highs - lows
    ranges = ranges.replace(0, np.nan)
    pressure = ((closes - lows) / ranges).fillna(0.5)

    weights = np.linspace(0.5, 1.0, len(pressure))
    wp = float(np.average(pressure.values, weights=weights))
    return round(wp, 4)


def _wick_asymmetry(df: pd.DataFrame, n: int = 10) -> float:
    """
    Wick-Asymmetrie:
      > 0.6 = mehr untere Wicks (Buyers dip-kaufen) → bullish
      < 0.4 = mehr obere Wicks (Sellers auf-verkaufen) → bearish
    """
    subset = df.tail(n)
    highs  = subset["high"].astype(float)
    lows   = subset["low"].astype(float)
    opens  = subset["open"].astype(float)
    closes = subset["close"].astype(float)

    body_high = pd.concat([opens, closes], axis=1).max(axis=1)
    body_low  = pd.concat([opens, closes], axis=1).min(axis=1)
    atr_proxy = (highs - lows).replace(0, 1e-10)

    upper_wick = (highs - body_high) / atr_proxy
    lower_wick = (body_low - lows)   / atr_proxy

    avg_upper = float(upper_wick.mean())
    avg_lower = float(lower_wick.mean())
    total = avg_upper + avg_lower

    if total < 1e-6:
        return 0.5

    # lower_wick dominant → bullish (0.5–1.0), upper dominant → bearish (0.0–0.5)
    return round(avg_lower / total, 4)


def _momentum_consistency(df: pd.DataFrame, n: int = 5) -> float:
    """
    Konsistenz der Candle-Richtung über N Perioden.
    +1.0 = alle Candles bullish, -1.0 = alle bearish
    """
    subset = df.tail(n)
    closes = subset["close"].astype(float)
    opens  = subset["open"].astype(float)

    directions = np.sign((closes - opens).values)
    consistency = float(directions.mean())   # -1.0 bis +1.0
    return round(consistency, 4)


def _atr_expansion(df: pd.DataFrame, n: int = 14) -> float:
    """
    Steigende ATR = wachsendes institutionelles Interesse.
    Gibt Score 0.0 (ATR fällt) bis 1.0 (ATR steigt) zurück.
    """
    if len(df) < n * 2:
        return 0.5

    closes = df["close"].astype(float)
    highs  = df["high"].astype(float)
    lows   = df["low"].astype(float)
    prev_c = closes.shift(1)

    tr  = pd.concat([
        highs - lows,
        (highs - prev_c).abs(),
        (lows  - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=n, adjust=False).mean()

    recent_atr = float(atr.iloc[-1])
    older_atr  = float(atr.iloc[-n])

    if older_atr < 1e-10:
        return 0.5

    ratio = recent_atr / older_atr
    # ratio > 1 → expanding (score > 0.5), ratio < 1 → contracting (score < 0.5)
    score = 0.5 + 0.5 * (ratio - 1.0) / max(ratio - 1.0, 0.5)
    return round(max(0.0, min(1.0, score)), 4)


def _close_vs_ema(df: pd.DataFrame) -> float:
    """
    Close-Position relativ zu EMA20.
    Close >> EMA20 → bullish (0.5–1.0)
    Close << EMA20 → bearish (0.0–0.5)
    """
    closes = df["close"].astype(float)
    ema20  = closes.ewm(span=20, adjust=False).mean()
    spread = float(closes.iloc[-1]) - float(ema20.iloc[-1])
    atr    = float(df["high"].astype(float).iloc[-14:].max() -
                   df["low"].astype(float).iloc[-14:].min()) / 14

    if atr < 1e-10:
        return 0.5

    normalized = spread / (atr * 2)   # Normalisiert auf ±1
    score = 0.5 + 0.5 * max(-1.0, min(1.0, normalized))
    return round(score, 4)


def get_microstructure_bias(
    df:         pd.DataFrame,
    instrument: str = "",
) -> tuple[str, float]:
    """
    Aggregierter Microstructure-Score aus 5 Proxies.

    Returns
    -------
    (bias, score):
        bias:  "BULLISH" | "BEARISH" | "NEUTRAL"
        score: 0.0 – 1.0 (0.5 = neutral)
    """
    if len(df) < MIN_CANDLES:
        return "NEUTRAL", 0.5

    try:
        body_p = _candle_body_pressure(df)       # 0.0–1.0, 0.5=neutral
        wick_a = _wick_asymmetry(df)              # 0.0–1.0, 0.5=neutral
        moment = (_momentum_consistency(df) + 1) / 2   # Convert -1..+1 → 0..1
        atr_ex = _atr_expansion(df)              # 0.0–1.0, 0.5=neutral
        ema_p  = _close_vs_ema(df)               # 0.0–1.0, 0.5=neutral

        # Gewichteter Durchschnitt — Momentum und Candle-Pressure stärker gewichtet
        weights     = [0.30, 0.20, 0.25, 0.10, 0.15]
        components  = [body_p, wick_a, moment, atr_ex, ema_p]
        score       = sum(w * c for w, c in zip(weights, components))
        score       = round(score, 4)

        if score >= 0.62:
            bias = "BULLISH"
        elif score <= 0.38:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        if bias != "NEUTRAL":
            log.debug(
                f"Microstructure [{instrument}]: {bias} ({score:.2f}) "
                f"body={body_p:.2f} wick={wick_a:.2f} mom={moment:.2f}"
            )

        return bias, score

    except Exception as e:
        log.debug(f"Microstructure [{instrument}]: {e}")
        return "NEUTRAL", 0.5
