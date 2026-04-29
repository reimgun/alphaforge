"""
RSIBBStrategy — RSI-Umkehr mit Bollinger-Band-Bestätigung.

Logik:
  - BUY:  RSI < 30 (überverkauft) UND Preis berührt unteres BB → Bounce erwartet
  - SELL: RSI > 70 (überkauft)  UND Preis berührt oberes BB → Reversion erwartet

Geeignet für: Seitwärtsmärkte, Range-Trading, 15m–1h Timeframe.

Verwendung:
    STRATEGY=RSIBBStrategy
"""
from __future__ import annotations

import pandas as pd

from crypto_bot.strategy.interface import IStrategy


class RSIBBStrategy(IStrategy):

    timeframe   = "1h"
    min_bars    = 50
    description = "RSI-Überverkauf/-Überkauf mit Bollinger-Band-Bestätigung. Gut für Range-Märkte."
    author      = "trading_bot builtin"

    rsi_period:   int   = 14
    rsi_os:       float = 30.0   # oversold
    rsi_ob:       float = 70.0   # overbought
    bb_period:    int   = 20
    bb_std:       float = 2.0

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # RSI
        delta = df["close"].diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_g = gain.ewm(span=self.rsi_period, adjust=False).mean()
        avg_l = loss.ewm(span=self.rsi_period, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        sma          = df["close"].rolling(self.bb_period).mean()
        std          = df["close"].rolling(self.bb_period).std()
        df["bb_mid"] = sma
        df["bb_up"]  = sma + self.bb_std * std
        df["bb_low"] = sma - self.bb_std * std
        df["bb_pct"] = (df["close"] - df["bb_low"]) / (df["bb_up"] - df["bb_low"]).replace(0, 1e-9)

        return df

    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["buy"] = (
            (df["rsi"] < self.rsi_os) & (df["bb_pct"] < 0.1)
        ).astype(int)
        return df

    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["sell"] = (
            (df["rsi"] > self.rsi_ob) | (df["bb_pct"] > 0.95)
        ).astype(int)
        return df

    def confirm_trade_entry(self, df, signal, confidence):
        # Nur einsteigen wenn BB-Wert wirklich niedrig (Preis am unteren Band)
        last = df.iloc[-1]
        return float(last.get("bb_pct", 0)) < 0.15
