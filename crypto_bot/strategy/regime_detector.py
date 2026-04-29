"""
Marktregime-Erkennung — bestimmt den aktuellen Markttyp.

Regime:
  BULL_TREND      → Starker Aufwärtstrend, Momentum-Strategie optimal
  BEAR_TREND      → Starker Abwärtstrend, keine Long-Positionen
  SIDEWAYS        → Seitwärtsmarkt, reduzierte Positionsgröße
  HIGH_VOLATILITY → Extreme Schwankungen, Stopp enger, Größe kleiner

Beeinflusst: Position Sizing, Signal-Filter, Stop-Loss-Breite
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from crypto_bot.monitoring.logger import log


@dataclass
class MarketRegime:
    regime: str          # "BULL_TREND" | "BEAR_TREND" | "SIDEWAYS" | "HIGH_VOLATILITY"
    adx: float           # Trendstärke 0-100 (>25 = trending)
    atr_pct: float       # ATR als % des Preises
    atr_percentile: float  # ATR vs historischem ATR (0-100)
    position_size_factor: float  # Multiplikator für Positionsgröße (0.5 - 1.0)
    description: str


def _calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Berechnet den ADX (Average Directional Index) manuell."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movements
    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),   index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    atr14      = tr.ewm(span=period, adjust=False).mean()
    plus_di14  = 100 * plus_dm.ewm(span=period,  adjust=False).mean() / atr14.replace(0, np.nan)
    minus_di14 = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr14.replace(0, np.nan)

    dx  = 100 * (plus_di14 - minus_di14).abs() / (plus_di14 + minus_di14).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()

    return float(adx.iloc[-1]) if not adx.empty else 0.0


def detect_regime(df: pd.DataFrame) -> MarketRegime:
    """
    Analysiert den aktuellen Marktregime anhand der letzten Candles.
    Benötigt mindestens 100 Candles für zuverlässige Berechnung.
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    current_price = float(close.iloc[-1])

    # ATR berechnen
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1])
    atr_pct = atr14 / current_price * 100

    # ATR-Perzentile (aktuell vs letzten 100 Perioden)
    atr_series = tr.rolling(14).mean().dropna()
    if len(atr_series) >= 20:
        atr_percentile = float((atr_series < atr14).mean() * 100)
    else:
        atr_percentile = 50.0

    # MA-Trend
    ma50  = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else current_price
    ma20  = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else current_price

    # ADX für Trendstärke
    adx = _calculate_adx(df) if len(df) >= 30 else 20.0

    # Bollinger Band Breite (Squeeze-Erkennung)
    std20 = float(close.rolling(20).std().iloc[-1])
    bb_width_pct = (4 * std20 / ma20 * 100) if ma20 > 0 else 5.0

    # ── Regime-Klassifikation ─────────────────────────────────────────────────
    is_trending   = adx > 22
    is_high_vol   = atr_percentile > 80 or atr_pct > 3.5
    is_bullish    = current_price > ma50 and ma20 > ma50
    is_bearish    = current_price < ma50 and ma20 < ma50

    if is_high_vol:
        regime = "HIGH_VOLATILITY"
        size_factor = 0.5      # Halbe Positionsgröße
        desc = f"Extreme Volatilität (ATR={atr_pct:.1f}%, p{atr_percentile:.0f})"

    elif is_trending and is_bullish:
        regime = "BULL_TREND"
        size_factor = 1.0      # Volle Positionsgröße
        desc = f"Aufwärtstrend (ADX={adx:.1f}, Preis>{ma50:.0f})"

    elif is_trending and is_bearish:
        regime = "BEAR_TREND"
        size_factor = 0.5      # Nur Shorts erlaubt, Longs halbiert
        desc = f"Abwärtstrend (ADX={adx:.1f}, Preis<{ma50:.0f})"

    else:
        regime = "SIDEWAYS"
        size_factor = 0.6      # Reduzierte Größe im Seitwärtsmarkt
        desc = f"Seitwärtsmarkt (ADX={adx:.1f}, BB-Breite={bb_width_pct:.1f}%)"

    log.debug(f"Regime: {regime} | ADX={adx:.1f} | ATR={atr_pct:.2f}% | {desc}")

    return MarketRegime(
        regime=regime,
        adx=adx,
        atr_pct=atr_pct,
        atr_percentile=atr_percentile,
        position_size_factor=size_factor,
        description=desc,
    )
