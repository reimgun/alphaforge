"""
Breakout Strategy — Donchian Channel + Volume Confirmation.

BUY:  Close durchbricht oberes Donchian-Band mit erhöhtem Volumen
SELL: Close fällt unter unteres Donchian-Band
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from crypto_bot.strategy.momentum import Signal


@dataclass
class BreakoutSignal:
    signal: Signal
    price: float
    reason: str
    upper_band: float
    lower_band: float
    volume_ratio: float


def add_breakout_indicators(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["donchian_upper"] = df["high"].rolling(period).max().shift(1)
    df["donchian_lower"] = df["low"].rolling(period).min().shift(1)
    df["donchian_mid"]   = (df["donchian_upper"] + df["donchian_lower"]) / 2
    df["vol_ma"]         = df["volume"].rolling(20).mean()
    df["vol_ratio"]      = df["volume"] / df["vol_ma"]
    return df


def generate_breakout_signal(df: pd.DataFrame, period: int = 20,
                              vol_threshold: float = 1.2) -> BreakoutSignal:
    df = add_breakout_indicators(df, period)
    df.dropna(inplace=True)
    if len(df) < 2:
        latest = df.iloc[-1] if len(df) == 1 else pd.Series(dtype=float)
        return BreakoutSignal(Signal.HOLD, 0, "Nicht genug Daten", 0, 0, 0)

    latest     = df.iloc[-1]
    price      = float(latest["close"])
    upper      = float(latest["donchian_upper"])
    lower      = float(latest["donchian_lower"])
    vol_ratio  = float(latest["vol_ratio"]) if not np.isnan(latest["vol_ratio"]) else 1.0

    # Upside Breakout mit Volumen-Bestätigung
    if price > upper and vol_ratio >= vol_threshold:
        return BreakoutSignal(
            Signal.BUY, price,
            f"Donchian-{period} Breakout oben (Vol={vol_ratio:.1f}x)",
            upper, lower, vol_ratio,
        )

    # Downside Breakdown
    if price < lower:
        return BreakoutSignal(
            Signal.SELL, price,
            f"Donchian-{period} Breakdown unten",
            upper, lower, vol_ratio,
        )

    return BreakoutSignal(Signal.HOLD, price, "Innerhalb Kanal", upper, lower, vol_ratio)
