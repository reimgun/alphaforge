"""
Market Regime Detection.

Classifies the current market environment before allowing a trade.

Regimes:
  TREND_UP        — strong upward trend (only BUY trades allowed)
  TREND_DOWN      — strong downward trend (only SELL trades allowed)
  SIDEWAYS        — ranging / no clear trend (no trades)
  HIGH_VOLATILITY — ATR is unusually large (no trades — risk too high)

The detection is based on:
  - ATR percentage of price  → HIGH_VOLATILITY if > 0.8%
  - EMA spread (fast-slow) / price → SIDEWAYS if < 0.05%
  - EMA alignment (fast > slow > trend) → TREND_UP / TREND_DOWN
"""
import logging

import pandas as pd

log = logging.getLogger("forex_bot")

# Thresholds
_ATR_VOLATILITY_PCT  = 0.008   # 0.8% of price
_EMA_SPREAD_MIN_PCT  = 0.0005  # 0.05% of price — below this = sideways


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def detect_regime(df: pd.DataFrame) -> str:
    """
    Classify the market regime from a DataFrame of OHLCV candles.

    The DataFrame must contain at minimum the columns: open, high, low, close.
    At least 210 rows are recommended for reliable EMA200 computation.

    Returns
    -------
    "TREND_UP" | "TREND_DOWN" | "SIDEWAYS" | "HIGH_VOLATILITY"
    """
    if len(df) < 30:
        return "SIDEWAYS"

    closes = df["close"].astype(float)
    highs  = df["high"].astype(float)
    lows   = df["low"].astype(float)

    # ATR (14-period exponential)
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    last_close = float(closes.iloc[-1])
    last_atr   = float(atr.iloc[-1])

    if last_close <= 0:
        return "SIDEWAYS"

    atr_pct = last_atr / last_close

    # ── HIGH_VOLATILITY check ─────────────────────────────────────────────────
    if atr_pct > _ATR_VOLATILITY_PCT:
        log.debug(f"Regime: HIGH_VOLATILITY (ATR {atr_pct*100:.3f}% > {_ATR_VOLATILITY_PCT*100:.1f}%)")
        return "HIGH_VOLATILITY"

    # ── EMA values ────────────────────────────────────────────────────────────
    ema_fast  = float(_ema(closes, 20).iloc[-1])
    ema_slow  = float(_ema(closes, 50).iloc[-1])
    ema_trend = float(_ema(closes, 200).iloc[-1]) if len(df) >= 200 else float(_ema(closes, 50).iloc[-1])

    ema_spread_pct = abs(ema_fast - ema_slow) / last_close

    # ── SIDEWAYS check ────────────────────────────────────────────────────────
    if ema_spread_pct < _EMA_SPREAD_MIN_PCT:
        log.debug(
            f"Regime: SIDEWAYS (EMA spread {ema_spread_pct*100:.4f}% "
            f"< {_EMA_SPREAD_MIN_PCT*100:.3f}%)"
        )
        return "SIDEWAYS"

    # ── TREND check ───────────────────────────────────────────────────────────
    if ema_fast > ema_slow > ema_trend:
        log.debug(
            f"Regime: TREND_UP (EMA20={ema_fast:.5f} > EMA50={ema_slow:.5f} "
            f"> EMA200={ema_trend:.5f})"
        )
        return "TREND_UP"

    if ema_fast < ema_slow < ema_trend:
        log.debug(
            f"Regime: TREND_DOWN (EMA20={ema_fast:.5f} < EMA50={ema_slow:.5f} "
            f"< EMA200={ema_trend:.5f})"
        )
        return "TREND_DOWN"

    return "SIDEWAYS"


def detect_regime_transition(df: pd.DataFrame) -> str:
    """
    Erkennt BEVORSTEHENDE Regime-Wechsel (frühzeitige Warnung).

    Reaktive Regime-Detektion erkennt Wechsel erst NACH dem Ereignis.
    Diese Funktion erkennt ADX-Beschleunigung und EMA-Konvergenz/-Divergenz
    die auf einen Regime-Wechsel HINDEUTEN.

    Returns
    -------
    "EMERGING_TREND_UP"   — SIDEWAYS → TREND_UP bricht aus
    "EMERGING_TREND_DOWN" — SIDEWAYS → TREND_DOWN bricht aus
    "TREND_WEAKENING"     — TREND → SIDEWAYS (Trend verliert Momentum)
    "STABLE"              — kein Übergang erkennbar
    """
    if len(df) < 30:
        return "STABLE"

    closes = df["close"].astype(float)
    highs  = df["high"].astype(float)
    lows   = df["low"].astype(float)

    # ── ADX berechnen (letzten 3 Werte für Slope) ────────────────────────────
    try:
        import numpy as np
        prev_c = closes.shift(1)
        tr = pd.concat([
            highs - lows,
            (highs - prev_c).abs(),
            (lows  - prev_c).abs(),
        ], axis=1).max(axis=1)

        up_move  = highs.diff()
        dn_move  = -lows.diff()
        plus_dm  = pd.Series(
            np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0),
            index=df.index,
        )
        minus_dm = pd.Series(
            np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0),
            index=df.index,
        )

        atr      = tr.ewm(span=14, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=14, adjust=False).mean() / (atr + 1e-10)
        minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / (atr + 1e-10)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx_ser  = dx.ewm(span=14, adjust=False).mean()

        adx_now  = float(adx_ser.iloc[-1])
        adx_prev = float(adx_ser.iloc[-3])
        adx_slope = adx_now - adx_prev   # positiv = ADX steigt (Trend baut sich auf)
    except Exception:
        return "STABLE"

    # ── EMA-Spread Veränderungsrate ───────────────────────────────────────────
    ema20_now  = float(_ema(closes, 20).iloc[-1])
    ema50_now  = float(_ema(closes, 50).iloc[-1])
    ema20_prev = float(_ema(closes, 20).iloc[-4])
    ema50_prev = float(_ema(closes, 50).iloc[-4])
    price      = float(closes.iloc[-1])

    spread_now  = (ema20_now - ema50_now) / price
    spread_prev = (ema20_prev - ema50_prev) / price
    spread_delta = spread_now - spread_prev   # positiv = Divergenz (Trend entsteht)

    # ── Plus-DI / Minus-DI Dominanz ──────────────────────────────────────────
    pdi_now  = float(plus_di.iloc[-1])
    mdi_now  = float(minus_di.iloc[-1])

    # ── Entscheidungslogik ────────────────────────────────────────────────────
    # Schwellwerte
    ADX_ACCELERATION = 3.0    # ADX-Anstieg um 3+ Punkte in 3 Bars
    SPREAD_WIDENING  = 0.0002  # EMA-Spread weitet sich um 0.02% des Preises
    ADX_WEAKENING    = -4.0   # ADX fällt um 4+ Punkte → Trend schwächt

    if adx_slope > ADX_ACCELERATION and spread_delta > SPREAD_WIDENING:
        if pdi_now > mdi_now:
            log.debug(
                f"Regime Transition: EMERGING_TREND_UP "
                f"(ADX slope={adx_slope:+.1f}, spread_delta={spread_delta*100:+.4f}%)"
            )
            return "EMERGING_TREND_UP"
        else:
            log.debug(
                f"Regime Transition: EMERGING_TREND_DOWN "
                f"(ADX slope={adx_slope:+.1f}, spread_delta={spread_delta*100:+.4f}%)"
            )
            return "EMERGING_TREND_DOWN"

    if adx_slope < ADX_WEAKENING and adx_now < 25:
        log.debug(
            f"Regime Transition: TREND_WEAKENING "
            f"(ADX slope={adx_slope:+.1f}, ADX={adx_now:.1f})"
        )
        return "TREND_WEAKENING"

    return "STABLE"


def regime_allows_trade(regime: str, direction: str) -> tuple[bool, str]:
    """
    Decide whether the current market regime allows the proposed trade.

    Parameters
    ----------
    regime:    one of "TREND_UP", "TREND_DOWN", "SIDEWAYS", "HIGH_VOLATILITY"
    direction: "BUY" or "SELL"

    Returns
    -------
    (allowed: bool, reason: str)
    """
    if regime == "TREND_UP":
        if direction == "BUY":
            return True, "TREND_UP regime — BUY aligned"
        return False, "TREND_UP regime — SELL trades not allowed"

    if regime == "TREND_DOWN":
        if direction == "SELL":
            return True, "TREND_DOWN regime — SELL aligned"
        return False, "TREND_DOWN regime — BUY trades not allowed"

    if regime == "SIDEWAYS":
        return False, "SIDEWAYS regime — no directional trades"

    if regime == "HIGH_VOLATILITY":
        return False, "HIGH_VOLATILITY regime — risk too high"

    # unknown regime fallback
    return False, f"Unknown regime '{regime}' — skipping"
