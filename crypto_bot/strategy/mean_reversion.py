"""
Mean Reversion Strategy — Bollinger Bands + RSI Extremes.

BUY:  Preis berührt unteres BB + RSI überverkauft
SELL: Preis berührt oberes BB + RSI überkauft
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from crypto_bot.strategy.momentum import Signal, calculate_rsi


@dataclass
class MeanReversionSignal:
    signal: Signal
    price: float
    reason: str
    bb_upper: float
    bb_lower: float
    bb_pct: float   # Position im Band (0=unten, 1=oben)
    rsi: float


def add_bb_indicators(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    df["bb_mid"]   = df["close"].rolling(period).mean()
    bb_std         = df["close"].rolling(period).std()
    df["bb_upper"] = df["bb_mid"] + std_dev * bb_std
    df["bb_lower"] = df["bb_mid"] - std_dev * bb_std
    bb_width       = df["bb_upper"] - df["bb_lower"]
    df["bb_pct"]   = (df["close"] - df["bb_lower"]) / bb_width.replace(0, np.nan)
    df["rsi"]      = calculate_rsi(df["close"])
    return df


def generate_mean_reversion_signal(df: pd.DataFrame, period: int = 20,
                                    rsi_oversold: float = 35,
                                    rsi_overbought: float = 65) -> MeanReversionSignal:
    df = add_bb_indicators(df, period)
    df.dropna(inplace=True)
    if len(df) < 2:
        return MeanReversionSignal(Signal.HOLD, 0, "Nicht genug Daten", 0, 0, 0.5, 50)

    latest   = df.iloc[-1]
    price    = float(latest["close"])
    upper    = float(latest["bb_upper"])
    lower    = float(latest["bb_lower"])
    bb_pct   = float(latest["bb_pct"]) if not np.isnan(latest["bb_pct"]) else 0.5
    rsi      = float(latest["rsi"])   if not np.isnan(latest["rsi"])    else 50.0

    # Überverkauft: Preis am/unter unterem Band
    if bb_pct <= 0.05 and rsi < rsi_oversold:
        return MeanReversionSignal(
            Signal.BUY, price,
            f"BB Oversold (bb%={bb_pct:.2f}, RSI={rsi:.1f})",
            upper, lower, bb_pct, rsi,
        )

    # Überkauft: Preis am/über oberem Band
    if bb_pct >= 0.95 and rsi > rsi_overbought:
        return MeanReversionSignal(
            Signal.SELL, price,
            f"BB Overbought (bb%={bb_pct:.2f}, RSI={rsi:.1f})",
            upper, lower, bb_pct, rsi,
        )

    return MeanReversionSignal(Signal.HOLD, price, "Kein Reversion-Signal",
                                upper, lower, bb_pct, rsi)
