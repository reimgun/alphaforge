"""
Global Market Exposure Controller

Portfolio-Level Decision Layer — entscheidet wie viel Kapital deployed wird.

Outputs:
  exposure_factor  — 0.0 (kein Trading) bis 1.0 (volles Kapital)
  risk_off         — True = kein neues BUY
  mode             — NORMAL / CAUTIOUS / RISK_OFF / EMERGENCY / RECOVERY
  crisis_score     — 0.0–1.0 Krisenwahrscheinlichkeit
  recovery_score   — 0.0–1.0 Erholungswahrscheinlichkeit

Keine binären Schalter — smooth transitions via EMA.

Integration:
    gec = GlobalExposureController()
    state = gec.compute(inputs)
    rm.kelly_factor *= state.exposure_factor   # skaliert Positionsgröße
    if state.risk_off: signal = "HOLD"         # blockiert neue BUYs
"""
import logging
import time
from collections import deque
from dataclasses import dataclass

log = logging.getLogger("trading_bot")

# ── Modi ──────────────────────────────────────────────────────────────────────
MODE_NORMAL    = "NORMAL"       # Normalbetrieb
MODE_CAUTIOUS  = "CAUTIOUS"     # Reduzierte Exposure
MODE_RISK_OFF  = "RISK_OFF"     # Minimale Exposure, kein BUY
MODE_EMERGENCY = "EMERGENCY"    # 0% Exposure, Capital Preservation
MODE_RECOVERY  = "RECOVERY"     # Graduell zurück nach Krise

# ── Basis-Exposure nach Regime ────────────────────────────────────────────────
_REGIME_BASE = {
    "BULL_TREND": 0.85,
    "SIDEWAYS":   0.40,
    "BEAR_TREND": 0.30,
    "UNKNOWN":    0.30,
}

# ── Volatilitäts-Multiplikator ────────────────────────────────────────────────
_VOL_MULT = {
    "LOW_VOL":    1.10,
    "NORMAL":     1.00,
    "HIGH_VOL":   0.55,
    "EXTREME_VOL": 0.20,
}


@dataclass
class ExposureInputs:
    regime:              str   = "UNKNOWN"
    vol_regime:          str   = "NORMAL"
    fear_greed_value:    int   = 50
    ml_confidence:       float = 0.5
    stress_factor:       float = 0.0    # 0=kein Stress, 1=max Stress
    drawdown_pct:        float = 0.0    # 0–100
    microstructure_bias: str   = "NEUTRAL"
    news_sentiment:      float = 0.0    # -1 bis +1
    regime_sim_factor:   float = 1.0
    funding_extreme:     bool  = False


@dataclass
class ExposureState:
    exposure_factor:           float = 1.0
    crisis_score:              float = 0.0
    recovery_score:            float = 0.0
    mode:                      str   = MODE_NORMAL
    risk_off:                  bool  = False
    reason:                    str   = ""
    # Empfohlene Strategie-Gewichtung
    trend_allocation:          float = 0.45
    mean_reversion_allocation: float = 0.20
    volatility_allocation:     float = 0.15
    arbitrage_allocation:      float = 0.20


class GlobalExposureController:
    """
    Aggregiert alle Marktsignale und liefert einen exposure_factor (0–1).

    Wird einmal pro Bot-Zyklus aufgerufen. Smooth transitions via EMA —
    keine abrupten Sprünge in der Positionsgröße.
    """

    def __init__(self, ema_alpha: float = 0.25):
        self._ema_alpha          = ema_alpha
        self._smoothed_exposure  = 1.0
        self._mode               = MODE_NORMAL
        self._manual_risk_off    = False
        self._manual_max_exposure = 1.0
        self._crisis_history     = deque(maxlen=5)
        self._recovery_history   = deque(maxlen=5)
        self._mode_since         = time.time()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_risk_off(self, active: bool):
        """Manuell via Telegram /risk_off_mode."""
        self._manual_risk_off = active
        log.warning(
            f"[Exposure] Manueller Risk-Off {'aktiviert' if active else 'deaktiviert'}"
        )

    def set_max_exposure(self, value: float):
        """Manuell via Telegram /set_max_exposure <0.0–1.0>."""
        self._manual_max_exposure = max(0.0, min(1.0, value))
        log.info(f"[Exposure] Max-Exposure → {self._manual_max_exposure:.0%}")

    def is_risk_off(self) -> bool:
        return self._manual_risk_off or self._mode in (MODE_RISK_OFF, MODE_EMERGENCY)

    def compute(self, inputs: ExposureInputs) -> ExposureState:
        """Berechnet Exposure-Empfehlung. Einmal pro Bot-Zyklus aufrufen."""

        crisis   = self._compute_crisis_score(inputs)
        recovery = self._compute_recovery_score(inputs)

        self._crisis_history.append(crisis)
        self._recovery_history.append(recovery)

        avg_crisis   = sum(self._crisis_history) / len(self._crisis_history)
        avg_recovery = sum(self._recovery_history) / len(self._recovery_history)

        mode, target, reason = self._determine_mode(inputs, avg_crisis, avg_recovery)

        # Smooth transition via EMA
        self._smoothed_exposure = (
            self._ema_alpha * target
            + (1 - self._ema_alpha) * self._smoothed_exposure
        )

        final = min(self._smoothed_exposure, self._manual_max_exposure)
        if self._manual_risk_off:
            final = min(final, 0.10)

        risk_off = self._manual_risk_off or mode in (MODE_RISK_OFF, MODE_EMERGENCY)
        self._mode = mode

        alloc = self._compute_allocation(inputs, mode)

        log.info(
            f"[Exposure] {mode} | factor={final:.0%} | "
            f"crisis={avg_crisis:.2f} recovery={avg_recovery:.2f} | {reason}"
        )

        return ExposureState(
            exposure_factor           = round(final, 4),
            crisis_score              = round(avg_crisis, 3),
            recovery_score            = round(avg_recovery, 3),
            mode                      = mode,
            risk_off                  = risk_off,
            reason                    = reason,
            trend_allocation          = alloc["trend"],
            mean_reversion_allocation = alloc["mean_reversion"],
            volatility_allocation     = alloc["volatility"],
            arbitrage_allocation      = alloc["arbitrage"],
        )

    # ── Crisis Score (0–1) ────────────────────────────────────────────────────

    def _compute_crisis_score(self, inp: ExposureInputs) -> float:
        score = 0.0

        # Fear & Greed: Extreme Fear
        if inp.fear_greed_value < 10:
            score += 0.30
        elif inp.fear_greed_value < 20:
            score += 0.20
        elif inp.fear_greed_value < 30:
            score += 0.10

        # Volatilität
        if inp.vol_regime == "EXTREME_VOL":
            score += 0.30
        elif inp.vol_regime == "HIGH_VOL":
            score += 0.15

        # Stress Test
        if inp.stress_factor > 0.80:
            score += 0.20
        elif inp.stress_factor > 0.60:
            score += 0.10

        # Drawdown
        if inp.drawdown_pct > 15:
            score += 0.25
        elif inp.drawdown_pct > 10:
            score += 0.15
        elif inp.drawdown_pct > 5:
            score += 0.05

        # Niedriges ML-Vertrauen
        if inp.ml_confidence < 0.30:
            score += 0.10
        elif inp.ml_confidence < 0.40:
            score += 0.05

        # Bear Regime
        if inp.regime == "BEAR_TREND":
            score += 0.15

        # Bearishes Sentiment
        if inp.news_sentiment < -0.5:
            score += 0.10
        elif inp.news_sentiment < -0.3:
            score += 0.05

        # Funding Extremes
        if inp.funding_extreme:
            score += 0.10

        # Bearish Microstructure
        if inp.microstructure_bias == "BEARISH":
            score += 0.05

        return min(score, 1.0)

    # ── Recovery Score (0–1) ──────────────────────────────────────────────────

    def _compute_recovery_score(self, inp: ExposureInputs) -> float:
        score = 0.0

        if inp.vol_regime in ("NORMAL", "LOW_VOL"):
            score += 0.25
        if inp.fear_greed_value > 40:
            score += 0.20
        if inp.fear_greed_value > 55:
            score += 0.10
        if inp.stress_factor < 0.30:
            score += 0.20
        if inp.ml_confidence > 0.55:
            score += 0.15
        if inp.regime == "BULL_TREND":
            score += 0.15
        if inp.news_sentiment > 0.2:
            score += 0.10
        if inp.microstructure_bias == "BULLISH":
            score += 0.10
        if inp.drawdown_pct < 3:
            score += 0.10

        return min(score, 1.0)

    # ── Modus + Ziel-Exposure ─────────────────────────────────────────────────

    def _determine_mode(
        self, inp: ExposureInputs, crisis: float, recovery: float
    ) -> tuple[str, float, str]:

        if self._manual_risk_off:
            return MODE_RISK_OFF, 0.10, "Manueller Risk-Off aktiv"

        # Emergency: anhaltende schwere Krise
        if crisis > 0.75:
            return (
                MODE_EMERGENCY, 0.0,
                f"Krisenindex {crisis:.0%} — Emergency Capital Preservation"
            )

        # Recovery nach Risk-Off / Emergency
        if self._mode in (MODE_RISK_OFF, MODE_EMERGENCY) and recovery > 0.60:
            # Graduell von 30% auf 80% je nach Recovery-Stärke
            target = 0.30 + (recovery - 0.60) * 1.25
            return (
                MODE_RECOVERY, min(target, 0.80),
                f"Recovery {recovery:.0%} — graduell zurück"
            )

        # Risk-Off: mittlere bis hohe Krise
        if crisis > 0.50:
            return MODE_RISK_OFF, 0.15, f"Krisenindex {crisis:.0%} — Risk-Off"

        # Cautious: moderate Krise
        if crisis > 0.30:
            base = _REGIME_BASE.get(inp.regime, 0.40) * 0.60
            return MODE_CAUTIOUS, base, f"Krisenindex {crisis:.0%} — reduzierte Exposure"

        # Normal: Regime + Volatilität + Konfidenz
        base     = _REGIME_BASE.get(inp.regime, 0.40)
        vmult    = _VOL_MULT.get(inp.vol_regime, 1.0)
        conf_adj = (inp.ml_confidence - 0.5) * 0.30   # ±0.15
        target   = base * vmult * inp.regime_sim_factor + conf_adj
        target   = max(0.10, min(1.0, target))

        reason = (
            f"Regime={inp.regime} Vol={inp.vol_regime} "
            f"conf={inp.ml_confidence:.0%} → {target:.0%}"
        )
        return MODE_NORMAL, target, reason

    # ── Kapital-Allokation ────────────────────────────────────────────────────

    def _compute_allocation(self, inp: ExposureInputs, mode: str) -> dict:
        if mode in (MODE_EMERGENCY, MODE_RISK_OFF):
            return {"trend": 0.10, "mean_reversion": 0.20,
                    "volatility": 0.00, "arbitrage": 0.70}

        if inp.regime == "BULL_TREND" and inp.vol_regime == "NORMAL":
            return {"trend": 0.60, "mean_reversion": 0.15,
                    "volatility": 0.15, "arbitrage": 0.10}

        if inp.vol_regime in ("HIGH_VOL", "EXTREME_VOL"):
            return {"trend": 0.20, "mean_reversion": 0.20,
                    "volatility": 0.40, "arbitrage": 0.20}

        if inp.regime == "SIDEWAYS":
            return {"trend": 0.20, "mean_reversion": 0.50,
                    "volatility": 0.10, "arbitrage": 0.20}

        if inp.regime == "BEAR_TREND":
            return {"trend": 0.10, "mean_reversion": 0.30,
                    "volatility": 0.20, "arbitrage": 0.40}

        return {"trend": 0.45, "mean_reversion": 0.20,
                "volatility": 0.15, "arbitrage": 0.20}


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: GlobalExposureController | None = None


def get_exposure_controller() -> GlobalExposureController:
    global _instance
    if _instance is None:
        _instance = GlobalExposureController()
    return _instance
