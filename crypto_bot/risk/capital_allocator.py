"""
Autonomous Capital Allocation Engine — Portfolio-Level Meta-Allocator.

  SignalStrengthAggregator:    Aggregiert Signalqualität aus allen Quellen
  RegimeExposureController:    Exposure-Tabelle nach Regime-Qualität (4 Tiers)
  MarketParticipationController: Gesamte Marktbeteiligung steuern (0.25–1.0)
  AutonomousCapitalAllocator:  Wrapper — gibt final_allocation zurück

Feature-Flag: FEATURE_CAPITAL_ALLOCATOR=true|false
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("trading_bot")


# ── Signal Quality Score ──────────────────────────────────────────────────────

@dataclass
class SignalQualityScore:
    microstructure_score: float   # 0.0–1.0
    cross_market_score:   float   # 0.0–1.0
    regime_score:         float   # 0.0–1.0
    aggregate:            float   # Gewichteter Durchschnitt
    tier:                 int     # 1 (stark) bis 4 (schwach)
    reason:               str


class SignalStrengthAggregator:
    """
    Kombiniert Signalstärke aus:
      - Microstructure (CVD-Trend, Orderbook-Imbalanz)
      - Cross-Market (Sentiment, BTC-Dominanz)
      - Regime (Übergangs-Konfidenz, Persistenz)

    Tier-Einteilung:
      Tier 1: aggregate ≥ 0.75 → volle Allokation
      Tier 2: aggregate ≥ 0.50 → reduzierte Allokation
      Tier 3: aggregate ≥ 0.25 → stark reduziert
      Tier 4: aggregate < 0.25 → Minimalallokation
    """
    WEIGHTS = {
        "microstructure": 0.35,
        "cross_market":   0.30,
        "regime":         0.35,
    }

    TIER_THRESHOLDS = [(0.75, 1), (0.50, 2), (0.25, 3), (0.0, 4)]

    def aggregate(
        self,
        microstructure_score: float,
        cross_market_score:   float,
        regime_score:         float,
    ) -> SignalQualityScore:
        # Clamp inputs
        ms  = max(0.0, min(1.0, microstructure_score))
        cm  = max(0.0, min(1.0, cross_market_score))
        rs  = max(0.0, min(1.0, regime_score))

        agg = (
            ms * self.WEIGHTS["microstructure"] +
            cm * self.WEIGHTS["cross_market"] +
            rs * self.WEIGHTS["regime"]
        )
        agg = round(agg, 4)

        tier = 4
        for threshold, t in self.TIER_THRESHOLDS:
            if agg >= threshold:
                tier = t
                break

        reason = (
            f"MS {ms:.0%} + CM {cm:.0%} + Regime {rs:.0%} "
            f"→ Aggregat {agg:.0%} (Tier {tier})"
        )
        return SignalQualityScore(
            microstructure_score = ms,
            cross_market_score   = cm,
            regime_score         = rs,
            aggregate            = agg,
            tier                 = tier,
            reason               = reason,
        )


# ── Regime Exposure Controller ────────────────────────────────────────────────

@dataclass
class RegimeExposureResult:
    regime:       str
    tier:         int
    max_exposure: float   # Maximaler Anteil des Kapitals der eingesetzt werden darf
    reason:       str


class RegimeExposureController:
    """
    Bestimmt maximale Kapitalallokation basierend auf Regime + Signal-Qualität.

    4-Tier-Tabelle je Regime:
      [Tier1_max, Tier2_max, Tier3_max, Tier4_max]
    """
    EXPOSURE_TABLE: dict[str, list[float]] = {
        "BULL_TREND": [1.00, 0.75, 0.50, 0.30],
        "SIDEWAYS":   [0.75, 0.55, 0.35, 0.25],
        "BEAR_TREND": [0.40, 0.30, 0.25, 0.25],
        "HIGH_VOL":   [0.50, 0.35, 0.25, 0.25],
    }
    DEFAULT_EXPOSURE = [0.50, 0.35, 0.25, 0.25]

    def compute(
        self,
        regime: str,
        signal_quality: SignalQualityScore,
    ) -> RegimeExposureResult:
        tier = signal_quality.tier
        row  = self.EXPOSURE_TABLE.get(regime, self.DEFAULT_EXPOSURE)
        max_exp = row[tier - 1]   # Tier ist 1-basiert

        reason = (
            f"Regime '{regime}' + Tier {tier} → Max-Exposure {max_exp:.0%}"
        )
        return RegimeExposureResult(
            regime       = regime,
            tier         = tier,
            max_exposure = max_exp,
            reason       = reason,
        )


# ── Market Participation Controller ──────────────────────────────────────────

@dataclass
class ParticipationResult:
    participation:    float   # 0.25–1.0
    volatility_pen:   float   # Strafe durch hohe Volatilität
    drawdown_pen:     float   # Strafe durch aktuellen Drawdown
    stress_pen:       float   # Strafe durch Stress-Test-Ergebnis
    reason:           str


class MarketParticipationController:
    """
    Steuert den Gesamtanteil des Kapitals der aktiv im Markt ist.

    Kombiniert drei unabhängige Penalty-Faktoren:
      1. Realisierte Volatilität (annualisiert)
      2. Aktueller Drawdown
      3. Stress-Test-Ergebnis

    Finale Beteiligung = 1.0 × vol_factor × dd_factor × stress_factor
    """
    MIN_PARTICIPATION   = 0.25
    MAX_PARTICIPATION   = 1.00

    # Volatilität: annualisiert > 80% → penalty beginnt
    VOL_PENALTY_START   = 0.80
    VOL_PENALTY_MAX     = 2.0     # 200% → min participation

    # Drawdown: > 5% → penalty beginnt
    DD_PENALTY_START    = 0.05
    DD_PENALTY_MAX      = 0.25    # 25% DD → min participation

    def compute(
        self,
        volatility_30d: float,   # Annualisierte 30d realisierte Volatilität (0–2.0)
        drawdown_pct:   float,   # Aktueller Drawdown 0.0–1.0
        stress_factor:  float,   # Aus LiquidityStressTestEngine (0.25–1.0)
    ) -> ParticipationResult:
        # 1. Volatilität
        if volatility_30d <= self.VOL_PENALTY_START:
            vol_pen = 1.0
        else:
            over = (volatility_30d - self.VOL_PENALTY_START) / (self.VOL_PENALTY_MAX - self.VOL_PENALTY_START)
            vol_pen = max(self.MIN_PARTICIPATION, 1.0 - over * 0.5)

        # 2. Drawdown
        if drawdown_pct <= self.DD_PENALTY_START:
            dd_pen = 1.0
        else:
            over = (drawdown_pct - self.DD_PENALTY_START) / (self.DD_PENALTY_MAX - self.DD_PENALTY_START)
            dd_pen = max(self.MIN_PARTICIPATION, 1.0 - over * 0.6)

        # 3. Stress (direkt als Multiplikator)
        stress_pen = max(self.MIN_PARTICIPATION, stress_factor)

        participation = max(
            self.MIN_PARTICIPATION,
            min(self.MAX_PARTICIPATION, vol_pen * dd_pen * stress_pen),
        )

        reason = (
            f"Vol {volatility_30d:.0%} (×{vol_pen:.2f}) × "
            f"DD {drawdown_pct:.0%} (×{dd_pen:.2f}) × "
            f"Stress ×{stress_pen:.2f} → {participation:.0%}"
        )
        return ParticipationResult(
            participation  = round(participation, 4),
            volatility_pen = round(vol_pen, 3),
            drawdown_pen   = round(dd_pen, 3),
            stress_pen     = round(stress_pen, 3),
            reason         = reason,
        )


# ── Allocation Result ──────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    signal_quality:   SignalQualityScore
    regime_exposure:  RegimeExposureResult
    participation:    ParticipationResult
    final_allocation: float   # 0.0–1.0 → Anteil des Kapitals der eingesetzt werden soll
    reason:           str


# ── Autonomous Capital Allocator (Wrapper) ────────────────────────────────────

class AutonomousCapitalAllocator:
    """
    Meta-Allocator — kombiniert alle Allokations-Komponenten.

    final_allocation = min(regime_exposure.max_exposure, participation.participation)

    Dieser Wert ersetzt/ergänzt den regime_factor in der Risk Engine.
    """

    def __init__(self):
        self.signal_agg    = SignalStrengthAggregator()
        self.regime_ctrl   = RegimeExposureController()
        self.participation = MarketParticipationController()

    def allocate(
        self,
        regime:               str,
        microstructure_score: float = 0.5,
        cross_market_score:   float = 0.5,
        regime_score:         float = 0.5,
        volatility_30d:       float = 0.5,
        drawdown_pct:         float = 0.0,
        stress_factor:        float = 1.0,
    ) -> AllocationResult:
        sq   = self.signal_agg.aggregate(microstructure_score, cross_market_score, regime_score)
        re   = self.regime_ctrl.compute(regime, sq)
        part = self.participation.compute(volatility_30d, drawdown_pct, stress_factor)

        final = min(re.max_exposure, part.participation)
        final = max(0.10, round(final, 4))   # Mindestens 10% — Bot bleibt aktiv

        reason = (
            f"Allokation {final:.0%} = "
            f"min(RegimeMax {re.max_exposure:.0%}, Teilnahme {part.participation:.0%}) | "
            f"Signal Tier {sq.tier}"
        )
        if final < 0.35:
            log.warning(f"Capital Allocator: Sehr niedrige Allokation {final:.0%} — {reason}")

        return AllocationResult(
            signal_quality   = sq,
            regime_exposure  = re,
            participation    = part,
            final_allocation = final,
            reason           = reason,
        )

    def get_score_from_signals(
        self,
        microstructure_bias: str,
        cross_market_regime: str,
        regime_persist_pct:  float,
    ) -> tuple[float, float, float]:
        """
        Hilfsmethode — konvertiert Bot-State-Strings in normalisierte Scores (0–1).
        Vereinfacht das Wiring in bot.py.
        """
        # Microstructure
        ms_map = {"BULLISH": 0.8, "BEARISH": 0.2, "NEUTRAL": 0.5}
        ms     = ms_map.get(microstructure_bias, 0.5)

        # Cross-Market
        cm_map = {"RISK_ON": 0.8, "RISK_OFF": 0.2, "NEUTRAL": 0.5}
        cm     = cm_map.get(cross_market_regime, 0.5)

        # Regime Persistenz → Score
        rs     = max(0.0, min(1.0, regime_persist_pct / 100.0))

        return ms, cm, rs


_capital_allocator: AutonomousCapitalAllocator | None = None


def get_capital_allocator() -> AutonomousCapitalAllocator:
    global _capital_allocator
    if _capital_allocator is None:
        _capital_allocator = AutonomousCapitalAllocator()
    return _capital_allocator
