"""
Trend Persistence Signal — Feature 10.

Measures how persistent and strong the current directional move is.
Used to boost or reduce trade confidence before entry.

Score components (0–100 total):
  ADX (0–40)            — trend strength (>25 = trending, >40 = strong)
  Consecutive bars (0–30) — how many of last 10 candles close in signal direction
  EMA alignment  (0–30)  — EMA20 > EMA50 > EMA200 alignment for BUY (or inverse)

Confidence adjustments:
  score ≥ 80  → +15%
  score ≥ 65  → +10%
  score ≤ 35  → -15%
  score ≤ 20  → -25%
  35 < score < 65 → no change

Usage:
    from forex_bot.strategy.trend_persistence import trend_persistence_score, apply_persistence_boost

    score = trend_persistence_score(df, direction=signal.direction)
    final_confidence = apply_persistence_boost(signal.confidence, score)
"""
import logging

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average Directional Index (ADX).

    Requires columns: high, low, close.
    Returns a Series of ADX values in the range [0, 100].
    Higher = stronger trend (irrespective of direction).
    """
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder's smoothing: alpha = 1/period
    alpha    = 1.0 / period
    atr_s    = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di  = 100 * (plus_dm.ewm(alpha=alpha, adjust=False).mean() / (atr_s + 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=alpha, adjust=False).mean() / (atr_s + 1e-10))

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx


def _consecutive_closes_in_direction(closes: pd.Series, direction: str, window: int = 10) -> int:
    """
    Count how many of the last `window` close-to-close moves match `direction`.
    """
    diffs = closes.diff().iloc[-window:]
    if direction == "BUY":
        return int((diffs > 0).sum())
    return int((diffs < 0).sum())


def trend_persistence_score(df: pd.DataFrame, direction: str = "BUY") -> int:
    """
    Compute a trend persistence score (0–100) for the current bar.

    Parameters
    ----------
    df:        H1 candle DataFrame with columns: open, high, low, close
               (ema_fast / ema_slow / ema_trend are computed if missing)
    direction: intended trade direction — "BUY" or "SELL"

    Returns
    -------
    int: 0–100 (higher = stronger persistent trend in the given direction)
    """
    if len(df) < 50:
        return 50  # neutral default

    try:
        df = df.copy()
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)

        # ── ADX component (0–40) ──────────────────────────────────────────────
        adx_series = _adx(df)
        adx_val    = float(adx_series.iloc[-1]) if not adx_series.empty else 0.0
        # ADX 40 = full 40 pts; capped
        adx_score  = int(min(40, adx_val))

        # ── Consecutive candles component (0–30) ─────────────────────────────
        consec       = _consecutive_closes_in_direction(df["close"], direction, window=10)
        consec_score = min(30, consec * 4)  # 8 candles → full 30 pts (capped)

        # ── EMA alignment component (0–30) ────────────────────────────────────
        if "ema_fast" not in df.columns:
            df["ema_fast"]  = df["close"].ewm(span=20, adjust=False).mean()
            df["ema_slow"]  = df["close"].ewm(span=50, adjust=False).mean()
            df["ema_trend"] = df["close"].ewm(span=200, adjust=False).mean()

        last      = df.iloc[-1]
        ema_fast  = float(last.get("ema_fast",  last["close"]))
        ema_slow  = float(last.get("ema_slow",  last["close"]))
        ema_trend = float(last.get("ema_trend", last["close"]))
        close_val = float(last["close"])

        ema_score = 0
        if direction == "BUY":
            if ema_fast > ema_slow:   ema_score += 10  # fast above slow
            if ema_slow > ema_trend:  ema_score += 10  # slow above trend
            if close_val > ema_fast:  ema_score += 10  # price above fast EMA
        else:
            if ema_fast < ema_slow:   ema_score += 10
            if ema_slow < ema_trend:  ema_score += 10
            if close_val < ema_fast:  ema_score += 10

        total = adx_score + consec_score + ema_score
        return min(100, max(0, total))

    except Exception as e:
        log.debug(f"Trend persistence score error: {e}")
        return 50  # neutral fallback


def apply_persistence_boost(confidence: float, score: int) -> float:
    """
    Adjust entry confidence based on the trend persistence score.

    Parameters
    ----------
    confidence: current confidence value (0.0–1.0)
    score:      trend persistence score (0–100)

    Returns
    -------
    float: adjusted confidence, capped at 1.0
    """
    if score >= 80:
        factor = 1.15
    elif score >= 65:
        factor = 1.10
    elif score <= 20:
        factor = 0.75
    elif score <= 35:
        factor = 0.85
    else:
        factor = 1.0

    return min(1.0, round(confidence * factor, 3))
