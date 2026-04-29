"""
Volatility Expansion Strategie — handelt explosive Bewegungen bei ATR-Ausweitung.

Signal-Logik:
  BUY  → Preis bricht über oberes Keltner-Band + ATR expandiert (> 1.5x 20-Perioden-Ø)
  SELL → Preis fällt unter unteres Keltner-Band + ATR expandiert
  HOLD → ATR im Normalbereich (kein Expansion-Event)

Geeignet für: HIGH_VOLATILITY-Regime, ausbruchstarke Märkte.
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np

from crypto_bot.strategy.momentum import Signal


@dataclass
class VolatilityExpansionSignal:
    signal: Signal
    price: float
    reason: str
    atr: float
    atr_ratio: float       # aktueller ATR / Ø-ATR
    upper_keltner: float
    lower_keltner: float


def add_volatility_expansion_indicators(df: pd.DataFrame,
                                         keltner_period: int = 20,
                                         keltner_atr_mult: float = 2.0) -> pd.DataFrame:
    """Berechnet Keltner-Channel und ATR-Expansion-Ratio."""
    d = df.copy()

    # ATR (True Range)
    prev_close = d["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"]        = tr.rolling(14).mean()
    d["atr_avg20"]  = d["atr"].rolling(keltner_period).mean()
    d["atr_ratio"]  = d["atr"] / d["atr_avg20"].replace(0, np.nan)

    # Keltner-Channel: EMA ± ATR_mult × ATR
    ema_mid             = d["close"].ewm(span=keltner_period, adjust=False).mean()
    d["keltner_mid"]    = ema_mid
    d["keltner_upper"]  = ema_mid + keltner_atr_mult * d["atr"]
    d["keltner_lower"]  = ema_mid - keltner_atr_mult * d["atr"]

    return d


def generate_volatility_expansion_signal(df: pd.DataFrame,
                                          atr_expansion_threshold: float = 1.4
                                          ) -> VolatilityExpansionSignal:
    """
    Erzeugt Volatility-Expansion-Signal.

    Args:
        df: OHLCV DataFrame
        atr_expansion_threshold: ATR muss mindestens X-fach des Ø-ATR sein
    """
    d = add_volatility_expansion_indicators(df)

    price          = float(d["close"].iloc[-1])
    atr            = float(d["atr"].fillna(0).iloc[-1])
    atr_ratio      = float(d["atr_ratio"].fillna(1.0).iloc[-1])
    upper_keltner  = float(d["keltner_upper"].fillna(price * 1.02).iloc[-1])
    lower_keltner  = float(d["keltner_lower"].fillna(price * 0.98).iloc[-1])

    is_expanding = atr_ratio >= atr_expansion_threshold

    if not is_expanding:
        return VolatilityExpansionSignal(
            signal=Signal.HOLD, price=price,
            reason=f"VolExp: ATR-Ratio={atr_ratio:.2f} — keine Expansion (min {atr_expansion_threshold})",
            atr=atr, atr_ratio=atr_ratio,
            upper_keltner=upper_keltner, lower_keltner=lower_keltner,
        )

    if price > upper_keltner:
        return VolatilityExpansionSignal(
            signal=Signal.BUY, price=price,
            reason=f"VolExp: Preis ${price:,.0f} > Keltner-Oben ${upper_keltner:,.0f} | ATR×{atr_ratio:.1f}",
            atr=atr, atr_ratio=atr_ratio,
            upper_keltner=upper_keltner, lower_keltner=lower_keltner,
        )

    if price < lower_keltner:
        return VolatilityExpansionSignal(
            signal=Signal.SELL, price=price,
            reason=f"VolExp: Preis ${price:,.0f} < Keltner-Unten ${lower_keltner:,.0f} | ATR×{atr_ratio:.1f}",
            atr=atr, atr_ratio=atr_ratio,
            upper_keltner=upper_keltner, lower_keltner=lower_keltner,
        )

    return VolatilityExpansionSignal(
        signal=Signal.HOLD, price=price,
        reason=f"VolExp: ATR expandiert aber Preis innerhalb Keltner",
        atr=atr, atr_ratio=atr_ratio,
        upper_keltner=upper_keltner, lower_keltner=lower_keltner,
    )
