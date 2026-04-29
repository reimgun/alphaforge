"""
Derivatives Intelligence — Perpetual Funding Rate + Liquidation Clusters.

  FundingRateMonitor:       Extreme Funding-Rates als Contrarian-Signal
  LiquidationClusterDetector: Schätzt Liquidations-Level aus Leverage-Annahmen
  SpotPerpBasisMonitor:     Spot vs Perpetual Preis-Differenz

Feature-Flag: FEATURE_DERIVATIVES_SIGNALS=true|false
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")


# ── Funding Rate Monitor ──────────────────────────────────────────────────────

@dataclass
class FundingRateSignal:
    rate:           float    # Aktueller Funding Rate (z.B. 0.001 = 0.1%)
    rate_8h_annualized: float
    regime:         str      # "EXTREME_LONG" | "HIGH_LONG" | "NEUTRAL" | "HIGH_SHORT" | "EXTREME_SHORT"
    contrarian_signal: str   # "SHORT_BIAS" | "LONG_BIAS" | "NEUTRAL"
    reason:         str


class FundingRateMonitor:
    """
    Überwacht Perpetual Funding Rates als Regime-Signal.

    Hohe positive Rate → Markt ist overlevered long → Contrarian Short-Bias
    Hohe negative Rate → Markt ist overlevered short → Contrarian Long-Bias
    Quelle: CCXT exchange.fetch_funding_rate()
    """
    EXTREME_THRESHOLD = 0.003   # > 0.3% pro 8h = Extreme (annualisiert > 328%)
    HIGH_THRESHOLD    = 0.001   # > 0.1% pro 8h

    def analyze(self, funding_rate: float) -> FundingRateSignal:
        """
        Args:
            funding_rate: 8h Funding Rate (z.B. 0.0001 = 0.01%)
        """
        annualized = funding_rate * 3 * 365   # 3× täglich × 365

        if funding_rate > self.EXTREME_THRESHOLD:
            regime   = "EXTREME_LONG"
            signal   = "SHORT_BIAS"
            reason   = f"Extreme positive Funding ({funding_rate:.4%}) → Overlevered Long"
        elif funding_rate > self.HIGH_THRESHOLD:
            regime   = "HIGH_LONG"
            signal   = "NEUTRAL"
            reason   = f"Erhöhte Funding ({funding_rate:.4%}) → Vorsicht bei Longs"
        elif funding_rate < -self.EXTREME_THRESHOLD:
            regime   = "EXTREME_SHORT"
            signal   = "LONG_BIAS"
            reason   = f"Extreme negative Funding ({funding_rate:.4%}) → Overlevered Short"
        elif funding_rate < -self.HIGH_THRESHOLD:
            regime   = "HIGH_SHORT"
            signal   = "NEUTRAL"
            reason   = f"Negative Funding ({funding_rate:.4%}) → Shorts bezahlen"
        else:
            regime   = "NEUTRAL"
            signal   = "NEUTRAL"
            reason   = f"Neutrale Funding Rate ({funding_rate:.4%})"

        return FundingRateSignal(
            rate               = round(funding_rate, 6),
            rate_8h_annualized = round(annualized * 100, 1),
            regime             = regime,
            contrarian_signal  = signal,
            reason             = reason,
        )

    def fetch_and_analyze(self, exchange=None, symbol: str = "BTC/USDT:USDT") -> FundingRateSignal:
        """Holt Funding Rate von Exchange und analysiert."""
        if exchange is None:
            return FundingRateSignal(0.0, 0.0, "NEUTRAL", "NEUTRAL", "Kein Exchange")
        try:
            data = exchange.fetch_funding_rate(symbol)
            rate = float(data.get("fundingRate", 0.0))
            return self.analyze(rate)
        except Exception as e:
            log.debug(f"FundingRate Fetch Fehler: {e}")
            return FundingRateSignal(0.0, 0.0, "NEUTRAL", "NEUTRAL", f"Fetch fehlgeschlagen: {e}")


# ── Liquidation Cluster Detector ──────────────────────────────────────────────

@dataclass
class LiquidationCluster:
    price_level:    float
    direction:      str     # "LONG_LIQ" | "SHORT_LIQ"
    leverage:       float   # Angenommene Leverage
    distance_pct:   float   # Abstand vom aktuellen Preis


class LiquidationClusterDetector:
    """
    Schätzt Liquidations-Level basierend auf typischen Leverage-Ratios.

    Strategie: Bei 10x Leverage wird eine Long-Position bei -10% liquidiert,
    eine Short-Position bei +10%. Erkennt "Liquidation Magnets".
    """
    LEVERAGE_LEVELS = [5.0, 10.0, 20.0, 50.0, 100.0]

    def detect(self, df: pd.DataFrame) -> list[LiquidationCluster]:
        """Berechnet Liquidations-Cluster um aktuellen Preis."""
        try:
            current_price = float(df["close"].iloc[-1])
            recent_high   = float(df["high"].tail(50).max())
            recent_low    = float(df["low"].tail(50).min())

            clusters = []
            for lev in self.LEVERAGE_LEVELS:
                liq_pct   = 1.0 / lev   # Liquidations-Abstand

                # Long-Liquidation: unterhalb des Einstandspreises
                liq_long  = recent_high * (1 - liq_pct)
                # Short-Liquidation: oberhalb des Einstandspreises
                liq_short = recent_low  * (1 + liq_pct)

                if 0 < liq_long < current_price:
                    dist = abs(current_price - liq_long) / current_price
                    clusters.append(LiquidationCluster(
                        round(liq_long, 2), "LONG_LIQ", lev, round(dist * 100, 2)
                    ))

                if liq_short > current_price:
                    dist = abs(liq_short - current_price) / current_price
                    clusters.append(LiquidationCluster(
                        round(liq_short, 2), "SHORT_LIQ", lev, round(dist * 100, 2)
                    ))

            # Sortiert nach Nähe zum aktuellen Preis
            return sorted(clusters, key=lambda c: c.distance_pct)[:6]
        except Exception as e:
            log.debug(f"LiquidationClusterDetector Fehler: {e}")
            return []

    def nearest_cluster(self, df: pd.DataFrame) -> LiquidationCluster | None:
        clusters = self.detect(df)
        return clusters[0] if clusters else None


# ── Spot-Perp Basis Monitor ───────────────────────────────────────────────────

@dataclass
class BasisSignal:
    basis_pct:   float    # (perp_price - spot_price) / spot_price
    regime:      str      # "CONTANGO" | "BACKWARDATION" | "NEUTRAL"
    signal:      str      # "BEARISH" | "BULLISH" | "NEUTRAL"
    reason:      str


class SpotPerpBasisMonitor:
    """
    Überwacht Spot-Perpetual Basis (Prämie/Abschlag):
      Contango   (Perp > Spot): Futures-Prämie → bullische Stimmung
      Backwardation (Perp < Spot): Futures-Abschlag → bearische Stimmung
    """
    CONTANGO_THRESHOLD     = 0.002   # > 0.2% Prämie
    BACKWARDATION_THRESHOLD = 0.002  # > 0.2% Abschlag

    def analyze(self, spot_price: float, perp_price: float) -> BasisSignal:
        if spot_price <= 0:
            return BasisSignal(0.0, "NEUTRAL", "NEUTRAL", "Ungültiger Spot-Preis")

        basis = (perp_price - spot_price) / spot_price

        if basis > self.CONTANGO_THRESHOLD:
            regime = "CONTANGO"
            signal = "NEUTRAL"   # Leicht bullisch aber aufpassen (overheated)
            reason = f"Perp {basis:.3%} über Spot — bullische Stimmung"
        elif basis < -self.BACKWARDATION_THRESHOLD:
            regime = "BACKWARDATION"
            signal = "BULLISH"   # Contrarian: Shorts bezahlen Premium
            reason = f"Perp {abs(basis):.3%} unter Spot — bearische Stimmung"
        else:
            regime = "NEUTRAL"
            signal = "NEUTRAL"
            reason = f"Basis: {basis:.4%} — Normal"

        return BasisSignal(round(basis, 5), regime, signal, reason)

    def fetch_and_analyze(
        self, exchange=None,
        spot_symbol: str = "BTC/USDT",
        perp_symbol: str = "BTC/USDT:USDT",
    ) -> BasisSignal:
        if exchange is None:
            return BasisSignal(0.0, "NEUTRAL", "NEUTRAL", "Kein Exchange")
        try:
            spot_ticker = exchange.fetch_ticker(spot_symbol)
            perp_ticker = exchange.fetch_ticker(perp_symbol)
            spot_price  = float(spot_ticker.get("last", 0))
            perp_price  = float(perp_ticker.get("last", 0))
            return self.analyze(spot_price, perp_price)
        except Exception as e:
            log.debug(f"Basis Fetch Fehler: {e}")
            return BasisSignal(0.0, "NEUTRAL", "NEUTRAL", f"Fetch fehlgeschlagen: {e}")


# ── Derivatives Signals (Wrapper) ─────────────────────────────────────────────

@dataclass
class DerivativesAnalysis:
    funding:     FundingRateSignal
    liquidations: list[LiquidationCluster]
    basis:       BasisSignal
    combined_signal: str   # "BULLISH" | "BEARISH" | "NEUTRAL"


class DerivativesSignals:
    """Wrapper — kombiniert alle Derivatives-Komponenten."""

    def __init__(self):
        self.funding    = FundingRateMonitor()
        self.liq_detect = LiquidationClusterDetector()
        self.basis      = SpotPerpBasisMonitor()

    def analyze(
        self,
        df:           pd.DataFrame,
        exchange=None,
        funding_rate: float = 0.0,
    ) -> DerivativesAnalysis:
        if exchange is not None:
            fund_sig  = self.funding.fetch_and_analyze(exchange)
            basis_sig = self.basis.fetch_and_analyze(exchange)
        else:
            fund_sig  = self.funding.analyze(funding_rate)
            basis_sig = BasisSignal(0.0, "NEUTRAL", "NEUTRAL", "Kein Exchange")

        liq_clusters = self.liq_detect.detect(df)

        # Kombiniertes Signal
        bullish = sum([
            fund_sig.contrarian_signal  == "LONG_BIAS",
            basis_sig.signal            == "BULLISH",
        ])
        bearish = sum([
            fund_sig.contrarian_signal  == "SHORT_BIAS",
            basis_sig.signal            == "BEARISH",
        ])

        combined = "BULLISH" if bullish > bearish else \
                   "BEARISH" if bearish > bullish else "NEUTRAL"

        return DerivativesAnalysis(fund_sig, liq_clusters, basis_sig, combined)


_deriv_signals: DerivativesSignals | None = None


def get_derivatives() -> DerivativesSignals:
    global _deriv_signals
    if _deriv_signals is None:
        _deriv_signals = DerivativesSignals()
    return _deriv_signals
