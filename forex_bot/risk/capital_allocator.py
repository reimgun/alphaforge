"""
Autonomer Capital Allocator — Portfolio-Level Meta-Allocator für Forex.

  SignalStrengthAggregator:    Aggregiert Signalqualität aus Session, Makro, Regime
  RegimeExposureController:    Exposure-Tabelle nach Regime-Qualität (4 Tiers)
  MarketParticipationController: Gesamte Marktbeteiligung steuern (0.25–1.0)
  AutonomousCapitalAllocator:  Wrapper — gibt risk_scale zurück (0.25–1.0)

Forex-spezifische Anpassungen:
  - Regimes: TREND_UP, TREND_DOWN, SIDEWAYS, HIGH_VOLATILITY
  - microstructure_score = Session-Qualitätsscore (BIS-basiert)
  - cross_market_score   = Makro-Kontext (VIX, Carry, Cross-Asset)
  - regime_score         = Regime-Persistenz + Transition-Konfidenz

Usage:
    from forex_bot.risk.capital_allocator import get_capital_allocator
    result = get_capital_allocator().allocate(regime="TREND_UP", ...)
    adjusted_risk = mode.risk_per_trade * result.risk_scale
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("forex_bot")


# ── Signal Quality Score ──────────────────────────────────────────────────────

@dataclass
class SignalQualityScore:
    session_score:     float   # 0.0–1.0  (BIS-Liquiditätsscore)
    macro_score:       float   # 0.0–1.0  (VIX invers, Carry, Cross-Asset)
    regime_score:      float   # 0.0–1.0  (Persistenz + Konfidenz)
    aggregate:         float   # Gewichteter Durchschnitt
    tier:              int     # 1 (stark) bis 4 (schwach)
    reason:            str


class SignalStrengthAggregator:
    """
    Aggregiert Signalstärke aus drei forex-spezifischen Dimensionen.

    Tier-Einteilung:
      Tier 1: aggregate ≥ 0.75 → volle Allokation
      Tier 2: aggregate ≥ 0.50 → reduzierte Allokation
      Tier 3: aggregate ≥ 0.25 → stark reduziert
      Tier 4: aggregate < 0.25 → Minimalallokation
    """
    WEIGHTS = {
        "session": 0.30,    # Forex: Session-Liquidität ist kritisch
        "macro":   0.35,    # Makro-Kontext schlägt Microstructure
        "regime":  0.35,
    }

    TIER_THRESHOLDS = [(0.75, 1), (0.50, 2), (0.25, 3), (0.0, 4)]

    def aggregate(
        self,
        session_score: float,
        macro_score:   float,
        regime_score:  float,
    ) -> SignalQualityScore:
        ss  = max(0.0, min(1.0, session_score))
        ms  = max(0.0, min(1.0, macro_score))
        rs  = max(0.0, min(1.0, regime_score))

        agg = (
            ss * self.WEIGHTS["session"] +
            ms * self.WEIGHTS["macro"] +
            rs * self.WEIGHTS["regime"]
        )
        agg = round(agg, 4)

        tier = 4
        for threshold, t in self.TIER_THRESHOLDS:
            if agg >= threshold:
                tier = t
                break

        reason = (
            f"Session {ss:.0%} + Makro {ms:.0%} + Regime {rs:.0%} "
            f"→ Aggregat {agg:.0%} (Tier {tier})"
        )
        return SignalQualityScore(
            session_score = ss,
            macro_score   = ms,
            regime_score  = rs,
            aggregate     = agg,
            tier          = tier,
            reason        = reason,
        )


# ── Regime Exposure Controller ────────────────────────────────────────────────

@dataclass
class RegimeExposureResult:
    regime:     str
    tier:       int
    risk_scale: float   # Multiplikator für risk_per_trade (0.25–1.0)
    reason:     str


class RegimeExposureController:
    """
    Bestimmt Risk-Scaling-Faktor basierend auf Regime + Signal-Qualität.

    4-Tier-Tabelle je Forex-Regime:
      [Tier1_scale, Tier2_scale, Tier3_scale, Tier4_scale]
    """
    EXPOSURE_TABLE: dict[str, list[float]] = {
        "TREND_UP":          [1.00, 0.75, 0.50, 0.30],
        "TREND_DOWN":        [1.00, 0.75, 0.50, 0.30],
        "SIDEWAYS":          [0.75, 0.55, 0.35, 0.25],
        "HIGH_VOLATILITY":   [0.50, 0.35, 0.25, 0.25],
    }
    DEFAULT_EXPOSURE = [0.60, 0.45, 0.30, 0.25]

    def compute(
        self,
        regime: str,
        signal_quality: SignalQualityScore,
    ) -> RegimeExposureResult:
        tier  = signal_quality.tier
        row   = self.EXPOSURE_TABLE.get(regime, self.DEFAULT_EXPOSURE)
        scale = row[tier - 1]   # Tier ist 1-basiert

        reason = f"Regime '{regime}' + Tier {tier} → Risk-Scale {scale:.0%}"
        return RegimeExposureResult(
            regime     = regime,
            tier       = tier,
            risk_scale = scale,
            reason     = reason,
        )


# ── Market Participation Controller ──────────────────────────────────────────

@dataclass
class ParticipationResult:
    participation: float   # 0.25–1.0
    vol_pen:       float
    dd_pen:        float
    reason:        str


class MarketParticipationController:
    """
    Gesamte Marktbeteiligung basierend auf:
      1. Realisierte Volatilität (ATR%)
      2. Aktueller Drawdown
    """
    MIN_PARTICIPATION = 0.25
    MAX_PARTICIPATION = 1.00

    # ATR% > 0.15% pro Stunde → Penalty beginnt (für H1 Forex)
    VOL_PENALTY_START = 0.15
    VOL_PENALTY_MAX   = 0.50   # ATR% 0.5% → min participation

    DD_PENALTY_START  = 0.05   # 5% Drawdown → Penalty beginnt
    DD_PENALTY_MAX    = 0.20   # 20% Drawdown → min participation

    def compute(
        self,
        atr_pct:      float,   # ATR als % des Preises (H1)
        drawdown_pct: float,   # Aktueller Drawdown 0.0–1.0
    ) -> ParticipationResult:
        # 1. ATR-Volatilität
        if atr_pct <= self.VOL_PENALTY_START:
            vol_pen = 1.0
        else:
            over   = (atr_pct - self.VOL_PENALTY_START) / (self.VOL_PENALTY_MAX - self.VOL_PENALTY_START)
            vol_pen = max(self.MIN_PARTICIPATION, 1.0 - over * 0.5)

        # 2. Drawdown
        if drawdown_pct <= self.DD_PENALTY_START:
            dd_pen = 1.0
        else:
            over   = (drawdown_pct - self.DD_PENALTY_START) / (self.DD_PENALTY_MAX - self.DD_PENALTY_START)
            dd_pen = max(self.MIN_PARTICIPATION, 1.0 - over * 0.6)

        participation = max(
            self.MIN_PARTICIPATION,
            min(self.MAX_PARTICIPATION, vol_pen * dd_pen),
        )
        reason = (
            f"ATR {atr_pct:.3f}% (×{vol_pen:.2f}) × "
            f"DD {drawdown_pct:.1%} (×{dd_pen:.2f}) → {participation:.0%}"
        )
        return ParticipationResult(
            participation = round(participation, 4),
            vol_pen       = round(vol_pen, 3),
            dd_pen        = round(dd_pen, 3),
            reason        = reason,
        )


# ── Allocation Result ──────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    signal_quality: SignalQualityScore
    regime_exposure: RegimeExposureResult
    participation:   ParticipationResult
    risk_scale:      float   # Finaler Multiplikator für risk_per_trade (0.10–1.0)
    reason:          str


# ── Autonomous Capital Allocator ──────────────────────────────────────────────

class AutonomousCapitalAllocator:
    """
    Meta-Allocator für Forex.

    risk_scale = min(regime_exposure.risk_scale, participation.participation)

    Verwendung in bot.py:
        adjusted_risk = mode.risk_per_trade * allocator_result.risk_scale
    """

    def __init__(self):
        self.signal_agg    = SignalStrengthAggregator()
        self.regime_ctrl   = RegimeExposureController()
        self.participation = MarketParticipationController()

    def allocate(
        self,
        regime:         str,
        session_score:  float = 0.6,   # aus session_quality()
        macro_score:    float = 0.5,   # aus macro_context
        regime_score:   float = 0.5,   # aus regime_forecaster
        atr_pct:        float = 0.10,
        drawdown_pct:   float = 0.0,
    ) -> AllocationResult:
        sq   = self.signal_agg.aggregate(session_score, macro_score, regime_score)
        re   = self.regime_ctrl.compute(regime, sq)
        part = self.participation.compute(atr_pct, drawdown_pct)

        risk_scale = min(re.risk_scale, part.participation)
        risk_scale = max(0.10, round(risk_scale, 4))   # Mindestens 10%

        reason = (
            f"RiskScale {risk_scale:.0%} = "
            f"min(RegimeMax {re.risk_scale:.0%}, Teilnahme {part.participation:.0%}) | "
            f"Signal Tier {sq.tier}"
        )
        if risk_scale < 0.35:
            log.info(f"Capital Allocator: Reduzierte Allokation {risk_scale:.0%} — {reason}")

        return AllocationResult(
            signal_quality  = sq,
            regime_exposure = re,
            participation   = part,
            risk_scale      = risk_scale,
            reason          = reason,
        )

    def get_macro_score(self, macro_ctx: dict) -> float:
        """Hilfsmethode: Makro-Kontext → Score 0.0–1.0."""
        try:
            vix = macro_ctx.get("vix", 18.0)
            # VIX: 10=1.0, 20=0.7, 30=0.4, 40+=0.1
            vix_score = max(0.1, min(1.0, 1.0 - (vix - 10) / 30.0))
            risk_regime = macro_ctx.get("risk_regime", "NEUTRAL")
            regime_score = {"RISK_ON": 0.85, "NEUTRAL": 0.55, "RISK_OFF": 0.20}.get(risk_regime, 0.5)
            return round((vix_score * 0.5 + regime_score * 0.5), 3)
        except Exception:
            return 0.5


_capital_allocator: AutonomousCapitalAllocator | None = None


def get_capital_allocator() -> AutonomousCapitalAllocator:
    global _capital_allocator
    if _capital_allocator is None:
        _capital_allocator = AutonomousCapitalAllocator()
    return _capital_allocator
