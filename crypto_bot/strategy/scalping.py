"""
Scalping-Strategie — ultra-kurzfristige Trades auf Basis schneller EMA-Kreuzungen.

Signal-Logik:
  BUY  → EMA5 kreuzt EMA13 von unten + RSI(7) < 60 + Volumen-Spike
  SELL → EMA5 kreuzt EMA13 von oben  + RSI(7) > 40
  HOLD → kein klares Signal

Geeignet für: HIGH_VOLATILITY + BULL_TREND mit kurzen Timeframes (1m–15m).
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np

from crypto_bot.strategy.momentum import Signal


@dataclass
class ScalpingSignal:
    signal: Signal
    price: float
    reason: str
    ema5: float
    ema13: float
    rsi7: float
    volume_ratio: float


def add_scalping_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet EMA5, EMA13, RSI(7) und Volumen-Ratio."""
    d = df.copy()

    # EMA5 / EMA13
    d["ema5"]  = d["close"].ewm(span=5,  adjust=False).mean()
    d["ema13"] = d["close"].ewm(span=13, adjust=False).mean()

    # RSI(7)
    delta  = d["close"].diff()
    gain   = delta.clip(lower=0).ewm(com=6, min_periods=7).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=6, min_periods=7).mean()
    d["rsi7"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    d["rsi7"] = d["rsi7"].fillna(50)

    # Volumen-Ratio: aktuelles Volumen / 20-Perioden-Durchschnitt
    d["vol_ma20"]    = d["volume"].rolling(20).mean()
    d["volume_ratio"] = d["volume"] / d["vol_ma20"].replace(0, np.nan)

    return d


def generate_scalping_signal(df: pd.DataFrame,
                              vol_spike_threshold: float = 1.3) -> ScalpingSignal:
    """
    Erzeugt Scalping-Signal.

    Args:
        df: OHLCV DataFrame
        vol_spike_threshold: Mindest-Volumen-Ratio für gültige Signale
    """
    d = add_scalping_indicators(df)

    price        = float(d["close"].iloc[-1])
    ema5         = float(d["ema5"].iloc[-1])
    ema13        = float(d["ema13"].iloc[-1])
    ema5_prev    = float(d["ema5"].iloc[-2])
    ema13_prev   = float(d["ema13"].iloc[-2])
    rsi7         = float(d["rsi7"].iloc[-1])
    volume_ratio = float(d["volume_ratio"].fillna(1.0).iloc[-1])

    # EMA-Kreuzung erkennen
    bullish_cross = ema5_prev <= ema13_prev and ema5 > ema13   # Goldenes Kreuz (kurz)
    bearish_cross = ema5_prev >= ema13_prev and ema5 < ema13   # Todeskreuz (kurz)

    has_volume_spike = volume_ratio >= vol_spike_threshold

    if bullish_cross and rsi7 < 65 and has_volume_spike:
        return ScalpingSignal(
            signal=Signal.BUY,
            price=price,
            reason=f"Scalping: EMA5>{ema13:.0f} Kreuz aufwärts | RSI7={rsi7:.0f} | Vol={volume_ratio:.1f}x",
            ema5=ema5, ema13=ema13, rsi7=rsi7, volume_ratio=volume_ratio,
        )

    if bearish_cross and rsi7 > 35:
        return ScalpingSignal(
            signal=Signal.SELL,
            price=price,
            reason=f"Scalping: EMA5<{ema13:.0f} Kreuz abwärts | RSI7={rsi7:.0f}",
            ema5=ema5, ema13=ema13, rsi7=rsi7, volume_ratio=volume_ratio,
        )

    return ScalpingSignal(
        signal=Signal.HOLD,
        price=price,
        reason="Scalping: kein Kreuzungssignal",
        ema5=ema5, ema13=ema13, rsi7=rsi7, volume_ratio=volume_ratio,
    )
