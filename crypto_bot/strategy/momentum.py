import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from crypto_bot.config.settings import FAST_MA, SLOW_MA, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    signal: Signal
    price: float
    reason: str
    fast_ma: float
    slow_ma: float
    rsi: float


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Fügt technische Indikatoren zum DataFrame hinzu."""
    df = df.copy()
    df["fast_ma"] = df["close"].rolling(FAST_MA).mean()
    df["slow_ma"] = df["close"].rolling(SLOW_MA).mean()
    df["rsi"] = calculate_rsi(df["close"], RSI_PERIOD)

    # Crossover-Signal: 1 = golden cross (buy), -1 = death cross (sell)
    df["ma_above"] = (df["fast_ma"] > df["slow_ma"]).astype(int)
    df["crossover"] = df["ma_above"].diff()
    return df


def generate_signal(df: pd.DataFrame) -> TradeSignal:
    """
    Generiert ein Handelssignal basierend auf den letzten Kerzen.

    Kaufsignal:
    - Fast MA kreuzt Slow MA nach oben (Golden Cross)
    - RSI nicht überkauft (< RSI_OVERBOUGHT)

    Verkaufssignal:
    - Fast MA kreuzt Slow MA nach unten (Death Cross)
    - ODER RSI überkauft (> RSI_OVERBOUGHT)
    """
    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    price = latest["close"]
    fast_ma = latest["fast_ma"]
    slow_ma = latest["slow_ma"]
    rsi = latest["rsi"]

    # Golden Cross: Fast MA kreuzt Slow MA nach oben
    golden_cross = prev["fast_ma"] <= prev["slow_ma"] and fast_ma > slow_ma
    # Death Cross: Fast MA kreuzt Slow MA nach unten
    death_cross = prev["fast_ma"] >= prev["slow_ma"] and fast_ma < slow_ma

    if golden_cross and rsi < RSI_OVERBOUGHT:
        return TradeSignal(
            signal=Signal.BUY,
            price=price,
            reason=f"Golden Cross (MA{FAST_MA}>MA{SLOW_MA}) + RSI={rsi:.1f}",
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            rsi=rsi,
        )

    if death_cross or rsi > RSI_OVERBOUGHT:
        reason = "Death Cross" if death_cross else f"RSI überkauft ({rsi:.1f})"
        return TradeSignal(
            signal=Signal.SELL,
            price=price,
            reason=reason,
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            rsi=rsi,
        )

    return TradeSignal(
        signal=Signal.HOLD,
        price=price,
        reason="Kein Signal",
        fast_ma=fast_ma,
        slow_ma=slow_ma,
        rsi=rsi,
    )
