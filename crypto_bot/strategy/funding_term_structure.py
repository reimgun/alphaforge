"""
Funding Rate Term Structure — Carry-Analyse & Laufzeitstruktur.

  FundingTermStructure:          Modelliert Funding-Rate über mehrere Horizonte
  FundingCarryOptimizer:         Bewertet Funding-Capture-Chancen
  FundingTermStructureSignals:   Wrapper

Feature-Flag: FEATURE_FUNDING_TERM_STRUCTURE=true|false
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("trading_bot")


# ── Term Structure Point ──────────────────────────────────────────────────────

@dataclass
class TermStructurePoint:
    horizon_hours:  int
    predicted_rate: float   # Vorhergesagte 8h Rate für diesen Horizont
    confidence:     float   # 0.0–1.0


# ── Funding Term Structure Result ─────────────────────────────────────────────

@dataclass
class FundingTermStructureResult:
    current_rate:    float
    predicted_rates: list[TermStructurePoint]
    slope:           float   # (predicted_168h_rate - current) / max(abs(current), 1e-6)
    structure:       str     # "CONTANGO" | "BACKWARDATION" | "FLAT"
    mean_future_rate: float  # Durchschnitt der vorhergesagten Raten
    reason:          str


# ── Funding Term Structure ────────────────────────────────────────────────────

class FundingTermStructure:
    """
    Modelliert die Laufzeitstruktur von Perpetual-Funding-Rates.

    Methode:
      - Speichert Historik der 8h-Funding-Raten
      - EWMA-geglättet als Long-Run-Mittelwert
      - Mean-Reversion-Extrapolation: Rate zieht zur EWMA hin
      - Steigung der Laufzeitstruktur zeigt ob Markt weiter in Richtung bleibt

    Contango:     Zukünftige Rates höher (oder positiver) → Longs zahlen weiter
    Backwardation: Zukünftige Rates niedriger → Market erwartet Rate-Normalisierung
    """
    HORIZONS_HOURS  = [8, 24, 72, 168]   # 8h, 1d, 3d, 1w
    HISTORY_WINDOW  = 90
    EWMA_ALPHA      = 0.05    # Langsam lernende Baseline (Long-Run-Mean)
    MR_SPEED        = 0.15    # Mean-Reversion-Geschwindigkeit pro Horizont-Schritt
    CONTANGO_SLOPE  = 0.10    # Steigung > 10% = Contango
    BACKWARDATION_SLOPE = -0.10

    def __init__(self):
        self._history: deque[float] = deque(maxlen=self.HISTORY_WINDOW)
        self._ewma:   float  = 0.0001   # Neutral-Start: 0.01% per 8h

    def update(self, rate_8h: float) -> None:
        self._history.append(rate_8h)
        self._ewma = self.EWMA_ALPHA * rate_8h + (1 - self.EWMA_ALPHA) * self._ewma

    def compute(self, current_rate: float) -> FundingTermStructureResult:
        try:
            long_run_mean = self._ewma

            # Mean-Reversion-Prognose: Rate konvergiert zur EWMA
            predicted = []
            rate_t    = current_rate
            for h in self.HORIZONS_HOURS:
                steps_in_h = h / 8   # Wie viele 8h-Perioden = h Stunden
                # Vereinfachte MR: rate_t nach k Schritten
                rate_t = long_run_mean + (rate_t - long_run_mean) * np.exp(
                    -self.MR_SPEED * steps_in_h
                )
                # Konfidenz sinkt mit Horizont
                confidence = max(0.1, 1.0 - (h / 168) * 0.7)
                predicted.append(TermStructurePoint(h, round(float(rate_t), 6), round(confidence, 2)))

            # Steigung: letzter Punkt vs aktueller Wert
            rate_1w = predicted[-1].predicted_rate
            slope   = (rate_1w - current_rate) / max(abs(current_rate), 1e-6)

            if slope > self.CONTANGO_SLOPE:
                structure = "CONTANGO"
            elif slope < self.BACKWARDATION_SLOPE:
                structure = "BACKWARDATION"
            else:
                structure = "FLAT"

            mean_fut = float(np.mean([p.predicted_rate for p in predicted]))

            reason = (
                f"Aktuell {current_rate:.4%} → 1W {rate_1w:.4%} | "
                f"Steigung {slope:+.1%} | {structure} | "
                f"LR-Mean {long_run_mean:.4%}"
            )
            return FundingTermStructureResult(
                current_rate      = round(current_rate, 6),
                predicted_rates   = predicted,
                slope             = round(slope, 4),
                structure         = structure,
                mean_future_rate  = round(mean_fut, 6),
                reason            = reason,
            )
        except Exception as e:
            log.debug(f"FundingTermStructure Fehler: {e}")
            return FundingTermStructureResult(
                current_rate=current_rate, predicted_rates=[],
                slope=0.0, structure="FLAT", mean_future_rate=0.0,
                reason=f"Fehler: {e}",
            )


# ── Funding Carry Optimizer ───────────────────────────────────────────────────

@dataclass
class CarryOpportunityResult:
    carry_rate_daily:  float   # Geschätzte tägliche Funding-Einnahme
    estimated_cost:    float   # Slippage + Spread-Kosten pro Tag
    net_carry:         float   # carry - cost
    carry_ratio:       float   # carry / cost (> 1 = positiv)
    is_positive:       bool
    signal:            str     # "CAPTURE" | "AVOID" | "NEUTRAL"
    direction:         str     # "LONG" (kassiert bei pos. Rate) oder "SHORT"
    reason:            str


class FundingCarryOptimizer:
    """
    Bewertet ob ein Funding-Capture-Trade wirtschaftlich sinnvoll ist.

    Konzept: Bei positiver (negativer) Funding Rate zahlen Longs (Shorts).
    Wenn Rate hoch genug → Gegenposition eingehen und Funding kassieren.

    Kriterien:
      - Annualisierte Carry > Transaktionskosten
      - Term Structure stützt (Contango für Short, Backwardation für Long)
    """
    PERIODS_PER_DAY = 3         # 3 × 8h pro Tag
    CARRY_THRESHOLD = 0.0002    # Mindest-Nettocarry pro Tag (0.02%)
    DEFAULT_SPREAD_BPS = 2.0    # 2 bps Standard-Spread
    SLIPPAGE_PER_ROUND = 0.0001 # 1 bps Slippage hin + zurück

    def evaluate(
        self,
        term_structure: FundingTermStructureResult,
        spread_bps: float = DEFAULT_SPREAD_BPS,
    ) -> CarryOpportunityResult:
        try:
            rate        = term_structure.current_rate
            mean_future = term_structure.mean_future_rate

            # Carry je Tag (3 × 8h Perioden)
            carry_daily = abs(rate) * self.PERIODS_PER_DAY

            # Kosten: Slippage + halber Spread × 2 (Einstieg + Ausstieg)
            spread_cost  = (spread_bps / 10_000) * 2
            total_cost   = spread_cost + self.SLIPPAGE_PER_ROUND * 2
            # Amortisierung über 3 Tage (realer Horizont)
            daily_cost   = total_cost / 3.0

            net_carry    = carry_daily - daily_cost
            carry_ratio  = carry_daily / max(daily_cost, 1e-10)
            is_positive  = net_carry > self.CARRY_THRESHOLD

            # Richtung: Bei positiver Rate → SHORT (kassiert Funding)
            if rate > 0:
                direction = "SHORT"
            else:
                direction = "LONG"

            # Signal
            if is_positive and abs(mean_future) >= abs(rate) * 0.5:
                signal = "CAPTURE"
            elif is_positive:
                signal = "NEUTRAL"   # Carry positiv aber Rate dreht bald
            else:
                signal = "AVOID"

            reason = (
                f"Rate {rate:.4%}/8h → Carry {carry_daily:.4%}/d | "
                f"Kosten {daily_cost:.4%}/d | Netto {net_carry:+.4%} | "
                f"{direction} {signal}"
            )
            return CarryOpportunityResult(
                carry_rate_daily = round(carry_daily, 6),
                estimated_cost   = round(daily_cost, 6),
                net_carry        = round(net_carry, 6),
                carry_ratio      = round(carry_ratio, 3),
                is_positive      = is_positive,
                signal           = signal,
                direction        = direction,
                reason           = reason,
            )
        except Exception as e:
            log.debug(f"FundingCarryOptimizer Fehler: {e}")
            return CarryOpportunityResult(0.0, 0.0, 0.0, 0.0, False, "AVOID", "NEUTRAL", f"Fehler: {e}")


# ── Combined Signal Result ────────────────────────────────────────────────────

@dataclass
class FundingTermStructureSignalResult:
    term_structure:  FundingTermStructureResult
    carry:           CarryOpportunityResult
    combined_signal: str     # "BULLISH_CARRY" | "BEARISH_CARRY" | "NEUTRAL"
    reason:          str


# ── Funding Term Structure Signals (Wrapper) ──────────────────────────────────

class FundingTermStructureSignals:
    """Wrapper — kombiniert Term Structure und Carry Optimizer."""

    def __init__(self):
        self.term_structure = FundingTermStructure()
        self.carry_opt      = FundingCarryOptimizer()

    def update(self, rate_8h: float) -> None:
        self.term_structure.update(rate_8h)

    def analyze(
        self,
        current_rate: float,
        spread_bps:   float = 2.0,
    ) -> FundingTermStructureSignalResult:
        ts = self.term_structure.compute(current_rate)
        co = self.carry_opt.evaluate(ts, spread_bps)

        # Kombiniertes Signal
        if co.is_positive and ts.structure == "CONTANGO" and co.direction == "SHORT":
            combined = "BEARISH_CARRY"   # Short-Bias + kassiert positive Funding
        elif co.is_positive and ts.structure == "BACKWARDATION" and co.direction == "LONG":
            combined = "BULLISH_CARRY"   # Long-Bias + kassiert negative Funding
        else:
            combined = "NEUTRAL"

        reason = f"{ts.structure} | Carry {co.signal} | {combined}"
        return FundingTermStructureSignalResult(
            term_structure  = ts,
            carry           = co,
            combined_signal = combined,
            reason          = reason,
        )


_funding_ts: FundingTermStructureSignals | None = None


def get_funding_term_structure() -> FundingTermStructureSignals:
    global _funding_ts
    if _funding_ts is None:
        _funding_ts = FundingTermStructureSignals()
    return _funding_ts
