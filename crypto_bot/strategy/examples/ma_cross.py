"""
MACrossStrategy — Klassisches Moving-Average Crossover.

Logik:
  - BUY:  Fast-EMA kreuzt nach oben über Slow-EMA + RSI nicht überkauft
  - SELL: Fast-EMA kreuzt nach unten unter Slow-EMA

Parameter (via Constructor oder Subklassen-Überschreiben):
    fast_period  = 20
    slow_period  = 50
    rsi_period   = 14
    rsi_ob_limit = 70   (kein Kauf wenn RSI > 70)

Geeignet für: Trending Märkte, 1h–4h Timeframe.

Verwendung:
    STRATEGY=MACrossStrategy
"""
from __future__ import annotations

import pandas as pd

from crypto_bot.strategy.interface import IStrategy


class MACrossStrategy(IStrategy):

    timeframe   = "1h"
    min_bars    = 60
    description = "EMA-Crossover mit RSI-Filter. Gut für Trending-Märkte."
    author      = "trading_bot builtin"

    fast_period:  int   = 20
    slow_period:  int   = 50
    rsi_period:   int   = 14
    rsi_ob_limit: float = 70.0

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema_fast"] = df["close"].ewm(span=self.fast_period, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_period, adjust=False).mean()

        # RSI
        delta  = df["close"].diff()
        gain   = delta.clip(lower=0)
        loss   = (-delta).clip(lower=0)
        avg_g  = gain.ewm(span=self.rsi_period, adjust=False).mean()
        avg_l  = loss.ewm(span=self.rsi_period, adjust=False).mean()
        rs     = avg_g / avg_l.replace(0, 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # Cross-Signal
        df["cross_up"]   = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
        df["cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

        return df

    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["buy"] = (
            df["cross_up"] & (df["rsi"] < self.rsi_ob_limit)
        ).astype(int)
        return df

    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["sell"] = df["cross_down"].astype(int)
        return df

    def custom_stoploss(self, current_price, entry_price, current_profit_pct, trade_duration_candles):
        # Break-Even Stop: sobald Gewinn ≥ 2%, Stop auf Einstiegspreis ziehen
        if current_profit_pct >= 0.02:
            return entry_price * 1.001
        return None
