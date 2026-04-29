"""
Execution Optimization Engine — reduziert Handelskosten und verbessert Entry-Timing.

Gaps 7–10:
  - SlippageEstimator:      schätzt Slippage basierend auf Ordervolumen
  - SpreadMonitor:          erkennt Spread-Ausweitung vor Order-Ausführung
  - EntryTimingAdvisor:     wählt optimalen Einstiegszeitpunkt innerhalb einer Kerze
  - MakerTakerSelector:     adaptiv zwischen Limit (Maker) und Market (Taker)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
import logging

log = logging.getLogger("trading_bot")


# ── Slippage Estimator ────────────────────────────────────────────────────────

@dataclass
class SlippageEstimate:
    estimated_pct: float   # Geschätzte Slippage als Dezimal (0.001 = 0.1%)
    risk_level:    str     # "LOW" | "MEDIUM" | "HIGH"
    reason:        str


class SlippageEstimator:
    """
    Schätzt Slippage basierend auf:
      - Ordergröße relativ zum Tagesvolumen
      - Aktuelle Volatilität (ATR)
      - Volumen-Verhältnis (letzter Balken vs Durchschnitt)
    """

    def estimate(
        self,
        order_value_usdt: float,
        volume_24h_usdt:  float,
        atr_pct:          float,
        volume_ratio:     float = 1.0,  # Aktuelles Volumen / Ø Volumen
    ) -> SlippageEstimate:
        """
        Args:
            order_value_usdt: Auftragswert in USDT
            volume_24h_usdt:  24h Handelsvolumen in USDT
            atr_pct:          ATR als % des Preises
            volume_ratio:     Volumen-Verhältnis (>1 = mehr als normal)

        Returns:
            SlippageEstimate mit geschätzter Slippage
        """
        if volume_24h_usdt <= 0:
            return SlippageEstimate(0.005, "HIGH", "Kein Volumen bekannt")

        # Market Impact: O(order/volume)^0.5 — Square-Root Modell
        impact_factor = (order_value_usdt / volume_24h_usdt) ** 0.5
        base_slippage = impact_factor * atr_pct / 100

        # Low Volumen → mehr Slippage
        if volume_ratio < 0.5:
            base_slippage *= 2.0
            risk = "HIGH"
            reason = f"Volumen niedrig ({volume_ratio:.1f}× Ø)"
        elif volume_ratio > 2.0:
            base_slippage *= 0.5
            risk = "LOW"
            reason = f"Volumen hoch ({volume_ratio:.1f}× Ø)"
        elif base_slippage > 0.003:
            risk = "HIGH"
            reason = f"Ordervolumen {impact_factor:.4f}× Marktvolumen"
        elif base_slippage > 0.001:
            risk = "MEDIUM"
            reason = f"Moderate Slippage erwartet"
        else:
            risk = "LOW"
            reason = f"Niedrige Slippage erwartet"

        return SlippageEstimate(
            estimated_pct = round(max(0.0001, base_slippage), 5),
            risk_level    = risk,
            reason        = reason,
        )

    def estimate_from_df(self, df: pd.DataFrame, order_value_usdt: float) -> SlippageEstimate:
        """Schätzt Slippage direkt aus OHLCV-DataFrame."""
        try:
            volume_24h = float(df["volume"].tail(24).sum()) * float(df["close"].iloc[-1])
            atr        = self._calc_atr_pct(df)
            vol_ratio  = float(df["volume"].iloc[-1]) / float(df["volume"].tail(20).mean())
            return self.estimate(order_value_usdt, volume_24h, atr, vol_ratio)
        except Exception as e:
            log.debug(f"SlippageEstimator Fehler: {e}")
            return SlippageEstimate(0.002, "MEDIUM", f"Schätzung fehlgeschlagen: {e}")

    @staticmethod
    def _calc_atr_pct(df: pd.DataFrame) -> float:
        try:
            prev_close = df["close"].shift(1)
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"]  - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr   = float(tr.rolling(14).mean().iloc[-1])
            price = float(df["close"].iloc[-1])
            return (atr / price * 100) if price > 0 else 2.0
        except Exception:
            return 2.0


# ── Spread Monitor ────────────────────────────────────────────────────────────

@dataclass
class SpreadStatus:
    is_wide:     bool
    current_pct: float  # Aktueller Spread als % des Preises
    avg_pct:     float  # Ø Spread der letzten N Candles
    widening_factor: float  # Aktuell / Durchschnitt
    message:     str


class SpreadMonitor:
    """
    Erkennt Spread-Ausweitung über High-Low-Proxy.
    (Echten Bid/Ask-Spread haben wir ohne Level-2 Daten nicht —
     wir verwenden den HL-Range als Proxy für Spread-Qualität.)
    """
    WIDENING_THRESHOLD = 2.0   # Alert wenn Spread > 2× Durchschnitt

    def check(self, df: pd.DataFrame, window: int = 20) -> SpreadStatus:
        try:
            # Spread-Proxy: (High - Low) / Close × 100%
            spread = (df["high"] - df["low"]) / df["close"] * 100
            current_pct = float(spread.iloc[-1])
            avg_pct     = float(spread.tail(window).mean())
            factor      = current_pct / avg_pct if avg_pct > 0 else 1.0
            is_wide     = factor > self.WIDENING_THRESHOLD

            msg = (
                f"Spread {current_pct:.2f}% vs Ø {avg_pct:.2f}% "
                f"({factor:.1f}×{' — WEIT' if is_wide else ''})"
            )
            return SpreadStatus(is_wide, round(current_pct, 4),
                                round(avg_pct, 4), round(factor, 2), msg)
        except Exception as e:
            return SpreadStatus(False, 0.0, 0.0, 1.0, f"Fehler: {e}")


# ── Entry Timing Advisor ──────────────────────────────────────────────────────

@dataclass
class EntryTimingAdvice:
    should_wait:   bool    # True = auf günstigeren Einstieg warten
    ideal_price:   float   # Empfohlener Einstiegspreis
    wait_reason:   str


class EntryTimingAdvisor:
    """
    Optimiert den Einstiegszeitpunkt innerhalb eines Candle-Fensters.

    Strategie: Wenn der aktuelle Preis nahe am Candle-Hoch ist und die
    letzten N Candles einen Pullback-Muster zeigen, lieber beim nächsten
    Pullback einsteigen.
    """
    NEAR_HIGH_THRESHOLD = 0.003  # 0.3% vom Candle-Hoch

    def advise(self, df: pd.DataFrame, signal: str) -> EntryTimingAdvice:
        if signal != "BUY":
            return EntryTimingAdvice(False, float(df["close"].iloc[-1]), "Kein BUY")

        try:
            close  = float(df["close"].iloc[-1])
            high   = float(df["high"].iloc[-1])
            low    = float(df["low"].iloc[-1])
            atr    = self._calc_atr(df)

            # Preis nahe am Candle-Hoch → Pullback abwarten
            pct_from_high = (high - close) / close
            if pct_from_high < self.NEAR_HIGH_THRESHOLD:
                ideal = close - atr * 0.2  # 20% ATR Pullback-Ziel
                return EntryTimingAdvice(
                    True, round(ideal, 2),
                    f"Preis nahe Candle-Hoch ({pct_from_high:.1%} vom High) — Pullback abwarten"
                )

            # Preis nahe am Candle-Tief → guter Einstieg
            pct_from_low = (close - low) / close
            if pct_from_low < self.NEAR_HIGH_THRESHOLD * 2:
                return EntryTimingAdvice(
                    False, close,
                    f"Preis nahe Candle-Tief — guter Einstieg"
                )

            return EntryTimingAdvice(False, close, "Neutraler Einstiegspunkt")
        except Exception:
            return EntryTimingAdvice(False, float(df["close"].iloc[-1]), "Timing-Fehler")

    @staticmethod
    def _calc_atr(df: pd.DataFrame) -> float:
        try:
            tr = (df["high"] - df["low"]).tail(14).mean()
            return float(tr)
        except Exception:
            return 0.0


# ── Maker / Taker Selector ────────────────────────────────────────────────────

@dataclass
class OrderTypeAdvice:
    order_type: str    # "limit" (Maker) oder "market" (Taker)
    reason:     str
    urgency:    float  # 0.0–1.0


class MakerTakerSelector:
    """
    Entscheidet adaptiv zwischen Limit-Order (Maker, billiger) und
    Market-Order (Taker, schneller) basierend auf Spread und Dringlichkeit.

    Limit (Maker): bei normalem Spread → spart 0.05–0.1% Taker-Fee
    Market (Taker): bei weitem Spread oder hohem Momentum → vermeidet verpasstes Signal
    """

    def select(
        self,
        spread: SpreadStatus,
        slippage: SlippageEstimate,
        momentum_strong: bool = False,
    ) -> OrderTypeAdvice:
        urgency = 0.0

        # Hohes Momentum → Taker (schnell einsteigen bevor Signal weg)
        if momentum_strong:
            urgency += 0.4

        # Weiter Spread → Taker kann besser sein (Limit wird ggf. nicht gefüllt)
        if spread.is_wide:
            urgency += 0.3

        # Hohe Slippage → Limit besser (wartet auf besseren Preis)
        if slippage.risk_level == "HIGH":
            urgency -= 0.2

        if urgency >= 0.4:
            return OrderTypeAdvice("market", f"Taker: {urgency:.0%} Dringlichkeit", urgency)
        else:
            return OrderTypeAdvice("limit", f"Maker: niedriger Urgency-Score", urgency)


# ── Convenience-Wrapper ───────────────────────────────────────────────────────

class ExecutionOptimizer:
    """Fasst alle Execution-Intelligence-Komponenten zusammen."""

    def __init__(self):
        self.slippage = SlippageEstimator()
        self.spread   = SpreadMonitor()
        self.timing   = EntryTimingAdvisor()
        self.order    = MakerTakerSelector()

    def analyze(
        self,
        df: pd.DataFrame,
        signal: str,
        order_value_usdt: float = 1000.0,
        momentum_strong: bool = False,
    ) -> dict:
        """Vollständige Execution-Analyse. Gibt dict mit allen Empfehlungen zurück."""
        slip   = self.slippage.estimate_from_df(df, order_value_usdt)
        spread = self.spread.check(df)
        timing = self.timing.advise(df, signal)
        order  = self.order.select(spread, slip, momentum_strong)

        if spread.is_wide:
            log.warning(f"Spread-Ausweitung erkannt: {spread.message}")
        if slip.risk_level == "HIGH":
            log.warning(f"Hohe Slippage-Warnung: {slip.reason}")

        return {
            "slippage_pct":    slip.estimated_pct,
            "slippage_risk":   slip.risk_level,
            "spread_wide":     spread.is_wide,
            "spread_factor":   spread.widening_factor,
            "wait_for_entry":  timing.should_wait,
            "ideal_price":     timing.ideal_price,
            "order_type":      order.order_type,
            "urgency":         order.urgency,
            "summary":         f"Slippage:{slip.risk_level} Spread:{spread.widening_factor:.1f}× Order:{order.order_type}",
        }


_optimizer: ExecutionOptimizer | None = None


def get_optimizer() -> ExecutionOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = ExecutionOptimizer()
    return _optimizer
