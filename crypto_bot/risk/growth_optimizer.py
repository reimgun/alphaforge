"""
Capital Growth Optimizer — Round 8.

  RollingKellyOptimizer:  Geglättete Kelly-Fraktion aus rollierendem Fenster
  ProfitLockingLadder:    Progressives Gewinnmitnahme-System
  ConvexExposureScaler:   Konkaves/Konvexes Exposure-Scaling mit Equity-Kurve
  EquityCurveFeedback:    Position-Sizing basierend auf Equity-Kurve

Feature-Flag: FEATURE_GROWTH_OPTIMIZER=true|false
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("trading_bot")


# ── Rolling Kelly Optimizer ───────────────────────────────────────────────────

@dataclass
class KellyResult:
    raw_kelly:     float   # Ungeglätteter Kelly
    smoothed_kelly: float  # Geglättet (EWMA)
    half_kelly:    float   # Half-Kelly (konservativ)
    confidence:    float   # Datenbasis (0–1)
    reason:        str


class RollingKellyOptimizer:
    """
    Berechnet Kelly-Fraktion aus rollierendem Fenster von Trade-Ergebnissen.
    Verwendet EWMA-Glättung für stabilere Schätzung.

    Kelly-Formel: f* = (p * b - q) / b
      p = Gewinnwahrscheinlichkeit
      q = 1 - p
      b = durchschnittliches Gewinn/Verlust-Verhältnis
    """
    WINDOW        = 50     # Rollendes Fenster
    EWMA_ALPHA    = 0.1    # EWMA-Glättungsfaktor
    MAX_KELLY     = 0.25   # Maximale Kelly-Fraktion (Risikobegrenzung)
    MIN_SAMPLES   = 10     # Mindest-Trades für valide Schätzung

    def __init__(self):
        self._returns: deque[float] = deque(maxlen=self.WINDOW)
        self._smoothed_kelly: float = 0.1   # Startwert

    def update(self, trade_return: float) -> None:
        """Fügt Trade-Ergebnis (prozentual, z.B. 0.02 = +2%) hinzu."""
        self._returns.append(trade_return)

    def compute(self) -> KellyResult:
        if len(self._returns) < self.MIN_SAMPLES:
            return KellyResult(
                raw_kelly=0.1, smoothed_kelly=0.1, half_kelly=0.05,
                confidence=len(self._returns) / self.MIN_SAMPLES,
                reason=f"Zu wenig Daten ({len(self._returns)}/{self.MIN_SAMPLES})",
            )

        arr     = np.array(self._returns)
        wins    = arr[arr > 0]
        losses  = arr[arr < 0]

        p = len(wins)  / len(arr)
        q = len(losses)/ len(arr)

        avg_win  = float(np.mean(wins))  if len(wins)  > 0 else 0.01
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.01

        b = avg_win / avg_loss if avg_loss > 0 else 1.0
        raw_kelly = max(0.0, (p * b - q) / b)
        raw_kelly = min(raw_kelly, self.MAX_KELLY)

        # EWMA-Glättung
        self._smoothed_kelly = (
            self.EWMA_ALPHA * raw_kelly +
            (1 - self.EWMA_ALPHA) * self._smoothed_kelly
        )
        smoothed = min(self._smoothed_kelly, self.MAX_KELLY)
        half_k   = smoothed / 2

        confidence = min(1.0, len(self._returns) / self.WINDOW)

        reason = (
            f"Kelly {raw_kelly:.1%} (geglättet {smoothed:.1%}) | "
            f"Win-Rate {p:.0%} | W/L-Ratio {b:.2f} | N={len(self._returns)}"
        )

        return KellyResult(
            raw_kelly      = round(raw_kelly, 4),
            smoothed_kelly = round(smoothed, 4),
            half_kelly     = round(half_k, 4),
            confidence     = round(confidence, 3),
            reason         = reason,
        )


# ── Profit Locking Ladder ─────────────────────────────────────────────────────

@dataclass
class ProfitLockResult:
    locked_profit_pct: float   # Bereits gesicherter Gewinn (% des Peaks)
    suggested_trail:   float   # Empfohlener Trailing-Stop
    ladder_level:      int     # Aktuelle Leiter-Stufe (0=kein Lock)
    reason:            str


class ProfitLockingLadder:
    """
    Progressives Gewinnmitnahme-System — je mehr Gewinn, desto enger der Stop.

    Stufen:
      +2%  → Trailing Stop auf Break-Even
      +5%  → Lock 50% des Gewinns
      +10% → Lock 70% des Gewinns
      +20% → Lock 85% des Gewinns
    """
    LADDER: list[tuple[float, float, float]] = [
        # (min_profit_pct, lock_fraction, trail_pct)
        (0.20, 0.85, 0.03),
        (0.10, 0.70, 0.05),
        (0.05, 0.50, 0.08),
        (0.02, 0.00, 0.10),   # Break-Even
    ]

    def compute(self, entry_price: float, current_price: float) -> ProfitLockResult:
        if entry_price <= 0:
            return ProfitLockResult(0.0, 0.10, 0, "Ungültiger Entry")

        profit_pct = (current_price - entry_price) / entry_price

        for level, (min_prof, lock_frac, trail) in enumerate(self.LADDER, 1):
            if profit_pct >= min_prof:
                locked = profit_pct * lock_frac
                reason = (
                    f"Stufe {level}: +{profit_pct:.1%} Gewinn → "
                    f"Lock {lock_frac:.0%}, Trail {trail:.1%}"
                )
                return ProfitLockResult(
                    locked_profit_pct = round(locked, 4),
                    suggested_trail   = trail,
                    ladder_level      = level,
                    reason            = reason,
                )

        return ProfitLockResult(0.0, 0.10, 0, f"Kein Lock ({profit_pct:.1%} unter Schwelle)")


# ── Convex Exposure Scaler ────────────────────────────────────────────────────

@dataclass
class ExposureResult:
    base_size:     float   # Basis-Positionsgröße (0–1)
    scaled_size:   float   # Skalierte Größe nach Equity-Feedback
    scaling_factor: float  # Skalierungsfaktor
    regime:        str     # "GROWTH" | "PRESERVE" | "RECOVER"
    reason:        str


class ConvexExposureScaler:
    """
    Skaliert Positionsgröße konkav/konvex je nach Equity-Kurve:
      - Positive Momentum der Equity → Exposure erhöhen (konvex)
      - Drawdown der Equity         → Exposure reduzieren (konkav)

    Ziel: Asymmetrisches Wachstum — größer bei Gewinnen, kleiner bei Verlusten.
    """
    GROWTH_MULTIPLIER   = 1.25   # Max Boost bei Equity-ATH
    PRESERVE_MULTIPLIER = 0.75   # Reduktion bei moderatem Drawdown
    RECOVER_MULTIPLIER  = 0.50   # Starke Reduktion bei tiefem Drawdown
    DRAWDOWN_MODERATE   = 0.05   # > 5% Drawdown = Preserve-Mode
    DRAWDOWN_DEEP       = 0.15   # > 15% Drawdown = Recovery-Mode

    def scale(
        self,
        base_size: float,
        equity_peak: float,
        current_equity: float,
    ) -> ExposureResult:
        if equity_peak <= 0:
            return ExposureResult(base_size, base_size, 1.0, "GROWTH", "Kein Peak")

        drawdown = max(0.0, (equity_peak - current_equity) / equity_peak)

        if drawdown >= self.DRAWDOWN_DEEP:
            factor = self.RECOVER_MULTIPLIER
            regime = "RECOVER"
            reason = f"Tiefer Drawdown {drawdown:.1%} → Recovery-Mode"
        elif drawdown >= self.DRAWDOWN_MODERATE:
            # Lineare Interpolation zwischen PRESERVE und RECOVER
            t = (drawdown - self.DRAWDOWN_MODERATE) / (self.DRAWDOWN_DEEP - self.DRAWDOWN_MODERATE)
            factor = self.PRESERVE_MULTIPLIER + t * (self.RECOVER_MULTIPLIER - self.PRESERVE_MULTIPLIER)
            regime = "PRESERVE"
            reason = f"Moderater Drawdown {drawdown:.1%} → Preserve-Mode"
        elif drawdown < 0.01:
            # Near ATH → Boost
            factor = self.GROWTH_MULTIPLIER
            regime = "GROWTH"
            reason = "Nahe ATH → Growth-Mode"
        else:
            factor = 1.0
            regime = "GROWTH"
            reason = f"Normaler Bereich ({drawdown:.1%} DD)"

        scaled = min(1.0, base_size * factor)

        return ExposureResult(
            base_size      = round(base_size, 4),
            scaled_size    = round(scaled, 4),
            scaling_factor = round(factor, 3),
            regime         = regime,
            reason         = reason,
        )


# ── Equity Curve Feedback ─────────────────────────────────────────────────────

@dataclass
class EquityFeedbackResult:
    recommended_size: float   # Empfohlene Positionsgröße (0–1)
    equity_momentum:  float   # Kurzzeitige Equity-Momentum (-1 bis +1)
    above_ma:         bool    # Equity über MA → Risk-On
    reason:           str


class EquityCurveFeedback:
    """
    Position-Sizing basierend auf Equity-Kurve:
      - Equity über 20-Perioden-MA → volle Größe
      - Equity unter MA → halbe Größe
      - Stark fallende Equity-Kurve → minimale Größe

    Klassisches "Equity Curve Trading" Konzept.
    """
    MA_PERIOD    = 20
    FULL_SIZE    = 1.0
    REDUCED_SIZE = 0.5
    MIN_SIZE     = 0.25

    def __init__(self):
        self._equity_history: deque[float] = deque(maxlen=self.MA_PERIOD + 5)

    def update(self, equity: float) -> None:
        self._equity_history.append(equity)

    def compute(self, base_size: float) -> EquityFeedbackResult:
        if len(self._equity_history) < self.MA_PERIOD:
            return EquityFeedbackResult(
                recommended_size = base_size,
                equity_momentum  = 0.0,
                above_ma         = True,
                reason           = "Nicht genug Equity-Historie",
            )

        history  = list(self._equity_history)
        current  = history[-1]
        ma       = float(np.mean(history[-self.MA_PERIOD:]))

        # Kurzes Momentum (letzte 5 vs letzte 20)
        short_ma = float(np.mean(history[-5:])) if len(history) >= 5 else current
        momentum = (short_ma - ma) / ma if ma > 0 else 0.0

        above_ma = current >= ma

        if above_ma and momentum > 0:
            size   = base_size * self.FULL_SIZE
            reason = f"Equity über MA ({current:.0f} > {ma:.0f}), positives Momentum"
        elif above_ma:
            size   = base_size * self.REDUCED_SIZE * 1.5   # Leicht reduziert
            reason = f"Equity über MA aber negatives Momentum"
        elif momentum > -0.02:
            size   = base_size * self.REDUCED_SIZE
            reason = f"Equity unter MA ({current:.0f} < {ma:.0f})"
        else:
            size   = base_size * self.MIN_SIZE
            reason = f"Equity stark unter MA, stark fallend"

        return EquityFeedbackResult(
            recommended_size = round(min(1.0, max(self.MIN_SIZE, size)), 4),
            equity_momentum  = round(momentum, 4),
            above_ma         = above_ma,
            reason           = reason,
        )


# ── Growth Optimizer (Wrapper) ────────────────────────────────────────────────

@dataclass
class GrowthOptimizerResult:
    kelly:    KellyResult
    profit_lock: ProfitLockResult
    exposure: ExposureResult
    equity_feedback: EquityFeedbackResult
    final_size: float   # Finale empfohlene Positionsgröße (0–1)


class GrowthOptimizer:
    """Wrapper — kombiniert alle Capital Growth Optimizer Komponenten."""

    def __init__(self):
        self.kelly        = RollingKellyOptimizer()
        self.profit_lock  = ProfitLockingLadder()
        self.exposure     = ConvexExposureScaler()
        self.equity_fb    = EquityCurveFeedback()

    def update_trade(self, trade_return: float) -> None:
        self.kelly.update(trade_return)

    def update_equity(self, equity: float) -> None:
        self.equity_fb.update(equity)

    def compute(
        self,
        base_size:      float,
        equity_peak:    float,
        current_equity: float,
        entry_price:    float = 0.0,
        current_price:  float = 0.0,
    ) -> GrowthOptimizerResult:
        kelly_r  = self.kelly.compute()
        # Kelly als Basis-Größe verwenden wenn verfügbar
        kelly_base = kelly_r.half_kelly if kelly_r.confidence > 0.5 else base_size

        expo_r   = self.exposure.scale(kelly_base, equity_peak, current_equity)
        eq_fb_r  = self.equity_fb.compute(expo_r.scaled_size)
        lock_r   = self.profit_lock.compute(entry_price, current_price)

        # Finale Größe — Equity-Feedback hat letztes Wort
        final = eq_fb_r.recommended_size

        return GrowthOptimizerResult(
            kelly          = kelly_r,
            profit_lock    = lock_r,
            exposure       = expo_r,
            equity_feedback= eq_fb_r,
            final_size     = round(final, 4),
        )


_growth_optimizer: GrowthOptimizer | None = None


def get_growth_optimizer() -> GrowthOptimizer:
    global _growth_optimizer
    if _growth_optimizer is None:
        _growth_optimizer = GrowthOptimizer()
    return _growth_optimizer
