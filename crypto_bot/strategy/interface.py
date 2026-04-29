"""
IStrategy — Pluggable Strategy Interface.

Jede Trading-Strategie erbt von IStrategy und implementiert die drei
Pflicht-Methoden. Optionale Callbacks werden nur überschrieben wenn nötig.

Aktivierung:
    STRATEGY=MACrossStrategy          # eingebaut
    STRATEGY=MyCoolStrategy           # Custom, aus strategies/ Verzeichnis
    STRATEGY_PATH=/pfad/strategy.py   # absoluter Pfad

Beispiel:
    class MyCoolStrategy(IStrategy):
        timeframe = "1h"

        def populate_indicators(self, df):
            df["ema20"] = df["close"].ewm(span=20).mean()
            return df

        def populate_entry_signal(self, df):
            df["buy"] = (df["close"] > df["ema20"]).astype(int)
            return df

        def populate_exit_signal(self, df):
            df["sell"] = (df["close"] < df["ema20"]).astype(int)
            return df
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class IStrategy(ABC):
    """Basisklasse für alle Trading-Strategien."""

    # Subklassen können überschreiben
    timeframe: str = "1h"
    min_bars:  int = 50

    # ── Pflicht-Methoden ──────────────────────────────────────────────────────

    @abstractmethod
    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Technische Indikatoren berechnen und als neue Spalten hinzufügen.
        Muss df (mit neuen Spalten) zurückgeben.
        """
        ...

    @abstractmethod
    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Kauf-Signal erzeugen.
        Muss df["buy"] = 1 (Signal) oder 0 (kein Signal) setzen.
        """
        ...

    @abstractmethod
    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Verkauf-Signal erzeugen.
        Muss df["sell"] = 1 (Signal) oder 0 (kein Signal) setzen.
        """
        ...

    # ── Optionale Callbacks ───────────────────────────────────────────────────

    def custom_stoploss(
        self,
        current_price: float,
        entry_price: float,
        current_profit_pct: float,
        trade_duration_candles: int,
    ) -> Optional[float]:
        """
        Custom Stop-Loss Preis zurückgeben, oder None für ATR-basiertes SL.

        Beispiel — Break-Even Stop nach +3% Gewinn:
            if current_profit_pct >= 0.03:
                return entry_price * 1.001
            return None
        """
        return None

    def confirm_trade_entry(
        self,
        df: pd.DataFrame,
        signal: str,
        confidence: float,
    ) -> bool:
        """
        Letzte Chance einen Trade zu blockieren.
        True = Trade ausführen, False = Trade überspringen.

        Beispiel — nur bei Mindest-Konfidenz einsteigen:
            return confidence >= 0.60
        """
        return True

    def confirm_trade_exit(
        self,
        df: pd.DataFrame,
        trade: dict,
        reason: str,
    ) -> bool:
        """
        Kann Exit-Signal blockieren.
        True = Exit ausführen, False = Position halten.
        """
        return True

    def on_trade_opened(self, trade: dict) -> None:
        """Callback direkt nach Trade-Öffnung."""
        pass

    def on_trade_closed(self, trade: dict) -> None:
        """
        Callback nach Trade-Schließung.
        trade enthält: entry_price, exit_price, pnl, reason, duration_candles
        """
        pass

    def on_bot_start(self) -> None:
        """Einmalig beim Bot-Start aufgerufen (z.B. für Vorberechnungen)."""
        pass

    def custom_stake_amount(
        self,
        capital: float,
        regime: str,
        confidence: float,
    ) -> Optional[float]:
        """
        Custom Positions-Größe in USDT zurückgeben.
        None = ATR-basiertes Sizing aus RiskManager verwenden.

        Beispiel — bei hoher Konfidenz mehr riskieren:
            if confidence >= 0.70:
                return capital * 0.05
            return None
        """
        return None

    def informative_pairs(self) -> list[tuple[str, str]]:
        """
        Zusätzliche Paare für informative Indikatoren.
        Wird beim Laden der OHLCV-Daten berücksichtigt.

        Beispiel:
            return [("BTC/USDT", "4h"), ("ETH/USDT", "1h")]
        """
        return []

    def adjust_trade_position(
        self,
        df: pd.DataFrame,
        trade: dict,
        current_profit_pct: float,
    ) -> Optional[float]:
        """
        DCA / Scale-Out: Positions-Anpassung während offenem Trade.
        Positiver Wert = mehr kaufen (USDT), negativer Wert = teilweise verkaufen (USDT).
        None = keine Änderung.

        Beispiel — DCA bei -3% Verlust:
            if current_profit_pct <= -0.03:
                return trade.get("stake_amount", 0) * 0.5
            return None
        """
        return None

    # ── Metadata ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def description(self) -> str:
        return ""

    @property
    def author(self) -> str:
        return ""

    def __repr__(self) -> str:
        return f"{self.name} v{self.version} (tf={self.timeframe})"
