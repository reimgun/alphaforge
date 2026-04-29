"""
Black Swan & Tail-Risk Detection — Gaps 14–16.

  Gap 14 — BlackSwanDetector:      Erkennt extreme Marktbewegungen (EVT/Z-Score)
  Gap 15 — LiquidityCrashDetector: Volume-Kollaps + Spread-Spike
  Gap 16 — DynamicLeverageEngine:  Regime-adaptives Leverage-Limit

Alle drei werden vor jedem Trade geprüft.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")

# Timeframe → Candle-Dauer in Minuten
_TF_MINUTES: dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}

def _candle_minutes() -> int:
    try:
        from crypto_bot.config.settings import TIMEFRAME
        return _TF_MINUTES.get(TIMEFRAME, 60)
    except Exception:
        return 60


@dataclass
class TailRiskAssessment:
    is_black_swan:    bool
    is_liquidity_crash: bool
    recommended_leverage: float   # 0.0 = kein Trade, 1.0 = normal
    risk_score:       float       # 0.0–1.0
    reason:           str


class BlackSwanDetector:
    """
    Erkennt extreme Marktbewegungen via Z-Score-Analyse.

    Schwellenwert: Return > 4σ der letzten LOOKBACK Perioden.
    Zusätzlich: Gap-Erkennung (Overnight-Gaps > GAP_THRESHOLD).
    """
    LOOKBACK        = 100     # Perioden für σ-Berechnung
    ZSCORE_THRESH   = 4.0     # σ-Schwelle für Black Swan
    GAP_THRESHOLD   = 0.05    # 5% Gap zwischen Closes

    def detect(self, df: pd.DataFrame) -> tuple[bool, str]:
        """
        Returns:
            (is_black_swan, reason)
        """
        try:
            closes   = df["close"].tail(self.LOOKBACK + 1)
            returns  = closes.pct_change().dropna()

            if len(returns) < 20:
                return False, "Zu wenig Daten"

            mean  = float(returns.mean())
            std   = float(returns.std())
            last  = float(returns.iloc[-1])

            if std < 1e-10:
                return False, "Null-Volatilität"

            z = abs((last - mean) / std)
            if z >= self.ZSCORE_THRESH:
                return True, f"Extreme Bewegung: Z-Score={z:.1f}σ (Return={last:.1%})"

            # Gap-Detection
            prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else 0
            curr_open  = float(df["open"].iloc[-1])
            if prev_close > 0:
                gap = abs(curr_open - prev_close) / prev_close
                if gap >= self.GAP_THRESHOLD:
                    return True, f"Price Gap erkannt: {gap:.1%}"

            return False, f"Normal (Z={z:.1f}σ)"
        except Exception as e:
            log.debug(f"BlackSwanDetector Fehler: {e}")
            return False, "Check fehlgeschlagen"


class LiquidityCrashDetector:
    """
    Erkennt Liquiditätskrisen via:
      - Volume-Kollaps: aktuelles Volume < VOLUME_COLLAPSE_PCT × Durchschnitt
      - Spread-Spike: HL-Range > SPREAD_SPIKE_FACTOR × Durchschnitt
    """
    VOLUME_COLLAPSE_PCT  = 0.20   # < 20% des Durchschnitts = Kollaps
    SPREAD_SPIKE_FACTOR  = 4.0    # > 4× Durchschnitt = Krise

    @property
    def LOOKBACK(self) -> int:  # type: ignore[override]
        """48h Coverage unabhängig vom Timeframe (15m→192, 1h→48, 4h→12)."""
        return max(20, int(48 * 60 / _candle_minutes()))

    @property
    def MIN_CANDLE_AGE_SECONDS(self) -> int:  # type: ignore[override]
        """Candle-Dauer + 5 Min Puffer für partielle Candles."""
        return (_candle_minutes() + 5) * 60

    def _get_completed_candles(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Gibt nur vollständig abgeschlossene Kerzen zurück.
        Eine Kerze gilt als abgeschlossen wenn ihr Timestamp > MIN_CANDLE_AGE_SECONDS alt ist.
        Das verhindert dass partiell gecachte oder laufende Kerzen als Referenz dienen.
        """
        import pandas as _pd
        now = _pd.Timestamp.now(tz="UTC")
        min_age = _pd.Timedelta(seconds=self.MIN_CANDLE_AGE_SECONDS)

        if df.index.tz is None:
            # Kein TZ → historische Daten, alle Kerzen abgeschlossen
            return df

        completed = df[(now - df.index) >= min_age]
        return completed

    def detect(self, df: pd.DataFrame) -> tuple[bool, str]:
        """
        Returns:
            (is_liquidity_crash, reason)
        """
        try:
            completed = self._get_completed_candles(df)

            if len(completed) < self.LOOKBACK + 1:
                return False, "Zu wenig abgeschlossene Kerzen"

            # Letzte vollständig abgeschlossene Kerze vs Durchschnitt der davor
            lookback = completed.tail(self.LOOKBACK + 1)
            curr_candle = lookback.iloc[-1]      # jüngste abgeschlossene Kerze
            history     = lookback.iloc[:-1]     # historische Kerzen für Durchschnitt

            curr_vol = float(curr_candle["volume"])

            # Time-of-day aware: Vergleich mit gleicher Stunde der letzten 7 Tage
            # verhindert False-Positives durch normale intraday-Volumenschwankungen
            candles_per_day = max(1, int(24 * 60 / _candle_minutes()))
            same_hour_refs = []
            for days_back in range(1, 8):
                idx = len(completed) - 1 - days_back * candles_per_day
                if idx >= 0:
                    same_hour_refs.append(float(completed.iloc[idx]["volume"]))

            if len(same_hour_refs) >= 3:
                avg_vol = float(np.median(same_hour_refs))
            else:
                avg_vol = float(history["volume"].mean())

            if avg_vol > 0 and curr_vol < self.VOLUME_COLLAPSE_PCT * avg_vol:
                return True, f"Volume-Kollaps: {curr_vol/avg_vol:.0%} des Durchschnitts"

            # Spread-Spike (HL-Range als Proxy)
            hl_range    = (history["high"] - history["low"]) / history["close"]
            curr_range  = float((curr_candle["high"] - curr_candle["low"]) / curr_candle["close"])
            avg_range   = float(hl_range.mean())

            if avg_range > 0 and curr_range > self.SPREAD_SPIKE_FACTOR * avg_range:
                return True, (
                    f"Spread-Spike: {curr_range:.2%} vs Ø {avg_range:.2%} "
                    f"({curr_range/avg_range:.1f}×)"
                )

            return False, "Liquidität normal"
        except Exception as e:
            log.debug(f"LiquidityCrashDetector Fehler: {e}")
            return False, "Check fehlgeschlagen"


class DynamicLeverageEngine:
    """
    Berechnet das empfohlene Leverage-Limit basierend auf:
      - Markt-Regime (Vol-Forecast)
      - Black Swan / Liquidity Events
      - Konfigurierten MAX_LEVERAGE

    Rückgabe: Leverage-Multiplikator 0.0–1.0
      0.0  = kein Trade (Notfall)
      0.25 = 25% des normalen Leverage
      1.0  = volles Leverage
    """

    def get_leverage_factor(
        self,
        vol_regime:       str,
        is_black_swan:    bool,
        is_liquidity_crash: bool,
    ) -> float:
        """
        Args:
            vol_regime:         "LOW" | "NORMAL" | "HIGH" | "EXTREME"
            is_black_swan:      Black Swan erkannt
            is_liquidity_crash: Liquiditätskrise erkannt

        Returns:
            Leverage-Faktor 0.0–1.0
        """
        if is_black_swan or is_liquidity_crash:
            return 0.0   # Kein Trade bei Notfall

        regime_factors = {
            "LOW":     1.0,
            "NORMAL":  1.0,
            "HIGH":    0.5,
            "EXTREME": 0.25,
        }
        return regime_factors.get(vol_regime, 1.0)


class TailRiskManager:
    """Fasst alle Tail-Risk-Komponenten zusammen."""

    def __init__(self):
        self.black_swan = BlackSwanDetector()
        self.liquidity  = LiquidityCrashDetector()
        self.leverage   = DynamicLeverageEngine()

    def assess(self, df: pd.DataFrame, vol_regime: str = "NORMAL") -> TailRiskAssessment:
        """
        Vollständige Tail-Risk-Bewertung für einen Trade.

        Returns:
            TailRiskAssessment mit allen Flags und empfohlenem Leverage
        """
        bs_flag, bs_reason  = self.black_swan.detect(df)
        lc_flag, lc_reason  = self.liquidity.detect(df)

        lev_factor = self.leverage.get_leverage_factor(vol_regime, bs_flag, lc_flag)

        # Risk-Score: 0.0 = kein Risiko, 1.0 = maximales Risiko
        risk_score = 0.0
        reasons    = []

        if bs_flag:
            risk_score += 0.6
            reasons.append(f"BlackSwan: {bs_reason}")
        if lc_flag:
            risk_score += 0.4
            reasons.append(f"Liquidität: {lc_reason}")

        vol_risk = {"LOW": 0.0, "NORMAL": 0.1, "HIGH": 0.3, "EXTREME": 0.5}
        risk_score += vol_risk.get(vol_regime, 0.1)
        risk_score  = min(1.0, risk_score)

        reason = " | ".join(reasons) if reasons else f"Normal (Vol: {vol_regime})"

        if bs_flag or lc_flag:
            log.warning(f"Tail-Risk erkannt: {reason}")

        return TailRiskAssessment(
            is_black_swan     = bs_flag,
            is_liquidity_crash= lc_flag,
            recommended_leverage = lev_factor,
            risk_score        = round(risk_score, 3),
            reason            = reason,
        )


_tail_risk_manager: TailRiskManager | None = None


def get_tail_risk_manager() -> TailRiskManager:
    global _tail_risk_manager
    if _tail_risk_manager is None:
        _tail_risk_manager = TailRiskManager()
    return _tail_risk_manager
