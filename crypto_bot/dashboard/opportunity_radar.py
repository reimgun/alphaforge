"""
AI Opportunity Radar — Per-Pair Opportunity Scoring + Dashboard.

  OpportunityScorer:     Bewertet Trading-Paare nach mehreren Dimensionen
  OpportunityRadar:      Hauptklasse — scannt und rankt alle verfügbaren Paare
  get_opportunity_radar: Singleton-Zugriff

Feature-Flag: FEATURE_OPPORTUNITY_RADAR=true|false
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")


# ── Opportunity Score ─────────────────────────────────────────────────────────

@dataclass
class OpportunityScore:
    symbol:          str
    total_score:     float   # 0–100 (höher = bessere Chance)
    regime_score:    float   # Regime-Alignment (0–100)
    liquidity_score: float   # Liquiditäts-Qualität (0–100)
    momentum_score:  float   # Preis-Momentum (0–100)
    volatility_score: float  # Optimale Volatilität (0–100, nicht zu hoch/niedrig)
    estimated_sharpe: float  # Geschätzter Sharpe-Ratio (annualisiert)
    current_regime:  str
    signal:          str     # "STRONG_BUY" | "BUY" | "NEUTRAL" | "AVOID"
    reason:          str
    timestamp:       float = field(default_factory=time.time)


# ── Opportunity Scorer ────────────────────────────────────────────────────────

class OpportunityScorer:
    """
    Bewertet ein Trading-Paar anhand von:
      1. Regime-Alignment (passt Regime zur Strategie?)
      2. Liquidität (Spread, Volumen)
      3. Momentum (kurzfristiger Preistrend)
      4. Volatilität (optimal: moderat, nicht zu hoch/niedrig)
      5. Geschätzter Sharpe-Ratio aus historischen Returns
    """
    # Optimale annualisierte Volatilität: 30–80%
    VOL_OPT_LOW  = 0.30   # Unter 30% → langweilig
    VOL_OPT_HIGH = 0.80   # Über 80% → zu riskant
    MIN_VOLUME   = 1e6    # Mindest-24h-Volumen in USD

    REGIME_WEIGHTS: dict[str, float] = {
        "BULL_TREND": 1.0,    # Bestes Regime für Long-Strategien
        "SIDEWAYS":   0.7,
        "HIGH_VOL":   0.5,
        "BEAR_TREND": 0.3,    # Schwierigeres Regime
    }

    def score(
        self,
        symbol: str,
        df: pd.DataFrame,
        regime: str = "SIDEWAYS",
        avg_spread_pct: float = 0.001,
        volume_24h_usd: float = 0.0,
    ) -> OpportunityScore:
        try:
            close = df["close"]

            # ── Momentum Score ─────────────────────────────────────────────
            ret_1d  = float((close.iloc[-1] - close.iloc[min(-24, -len(close)+1)]) /
                            close.iloc[min(-24, -len(close)+1)]) if len(close) > 24 else 0.0
            ret_7d  = float((close.iloc[-1] - close.iloc[min(-168, -len(close)+1)]) /
                            close.iloc[min(-168, -len(close)+1)]) if len(close) > 168 else 0.0
            # Momentum: positiv aber nicht überhitzt
            mom_raw = ret_1d * 0.4 + ret_7d * 0.6
            momentum_score = min(100.0, max(0.0, 50 + mom_raw * 200))

            # ── Volatility Score ───────────────────────────────────────────
            daily_rets = close.pct_change().dropna()
            ann_vol    = float(daily_rets.std()) * np.sqrt(365 * 24) if len(daily_rets) > 1 else 0.5

            if ann_vol < self.VOL_OPT_LOW:
                vol_score = ann_vol / self.VOL_OPT_LOW * 60    # Zu niedrig
            elif ann_vol > self.VOL_OPT_HIGH:
                overshoot = (ann_vol - self.VOL_OPT_HIGH) / self.VOL_OPT_HIGH
                vol_score = max(0.0, 100 - overshoot * 80)     # Zu hoch
            else:
                # Optimal: 100 in der Mitte
                opt_mid   = (self.VOL_OPT_LOW + self.VOL_OPT_HIGH) / 2
                distance  = abs(ann_vol - opt_mid) / (opt_mid - self.VOL_OPT_LOW)
                vol_score = 100 * (1 - distance * 0.3)

            # ── Liquidity Score ────────────────────────────────────────────
            spread_score  = max(0.0, 100 * (1 - avg_spread_pct / 0.005))
            volume_score  = min(100.0, volume_24h_usd / self.MIN_VOLUME * 50) \
                            if volume_24h_usd > 0 else 50.0
            liquidity_score = spread_score * 0.5 + volume_score * 0.5

            # ── Regime Score ───────────────────────────────────────────────
            regime_factor = self.REGIME_WEIGHTS.get(regime, 0.5)
            regime_score  = regime_factor * 100

            # ── Estimated Sharpe ───────────────────────────────────────────
            if len(daily_rets) >= 30:
                mean_ret = float(daily_rets.tail(168).mean()) * 24 * 365  # Annualisiert
                std_ret  = float(daily_rets.tail(168).std())  * np.sqrt(24 * 365)
                sharpe   = mean_ret / std_ret if std_ret > 0 else 0.0
            else:
                sharpe = 0.0

            # ── Total Score ────────────────────────────────────────────────
            total = (
                regime_score     * 0.30 +
                liquidity_score  * 0.25 +
                momentum_score   * 0.25 +
                vol_score        * 0.20
            )
            total = min(100.0, max(0.0, total))

            # ── Signal ────────────────────────────────────────────────────
            if total >= 75:
                signal = "STRONG_BUY"
            elif total >= 55:
                signal = "BUY"
            elif total >= 35:
                signal = "NEUTRAL"
            else:
                signal = "AVOID"

            reason = (
                f"Regime {regime} ({regime_score:.0f}/100) | "
                f"Momentum {momentum_score:.0f} | "
                f"Vol {ann_vol:.0%} ({vol_score:.0f}) | "
                f"Sharpe ~{sharpe:.2f}"
            )

            return OpportunityScore(
                symbol           = symbol,
                total_score      = round(total, 1),
                regime_score     = round(regime_score, 1),
                liquidity_score  = round(liquidity_score, 1),
                momentum_score   = round(momentum_score, 1),
                volatility_score = round(vol_score, 1),
                estimated_sharpe = round(sharpe, 3),
                current_regime   = regime,
                signal           = signal,
                reason           = reason,
            )

        except Exception as e:
            log.debug(f"OpportunityScorer Fehler für {symbol}: {e}")
            return OpportunityScore(
                symbol=symbol, total_score=0.0, regime_score=0.0,
                liquidity_score=0.0, momentum_score=0.0, volatility_score=0.0,
                estimated_sharpe=0.0, current_regime=regime,
                signal="AVOID", reason=f"Fehler: {e}",
            )


# ── Opportunity Radar ─────────────────────────────────────────────────────────

@dataclass
class RadarResult:
    top_opportunities: list[OpportunityScore]   # Top-N nach Score
    all_scores:        dict[str, OpportunityScore]
    best_symbol:       str
    scan_time:         float
    n_scanned:         int


class OpportunityRadar:
    """
    Scannt und rankt alle verfügbaren Pairs.
    Verwendet OpportunityScorer für jedes Pair.
    Gecachte Ergebnisse für Dashboard-API.
    """
    CACHE_TTL_S = 300    # Cache 5 Minuten
    TOP_N       = 10

    def __init__(self):
        self.scorer    = OpportunityScorer()
        self._cache:   dict[str, OpportunityScore] = {}
        self._cache_ts: float = 0.0

    def scan(
        self,
        pairs: dict[str, pd.DataFrame],
        regimes: dict[str, str] | None = None,
        spreads: dict[str, float] | None = None,
        volumes: dict[str, float] | None = None,
    ) -> RadarResult:
        """
        Scannt alle Pairs.

        Args:
            pairs:   {symbol: OHLCV DataFrame}
            regimes: {symbol: regime_string} — optional
            spreads: {symbol: spread_pct}    — optional
            volumes: {symbol: volume_24h_usd}— optional
        """
        regimes = regimes or {}
        spreads = spreads or {}
        volumes = volumes or {}
        scores: dict[str, OpportunityScore] = {}

        for symbol, df in pairs.items():
            if df is None or len(df) < 10:
                continue
            sc = self.scorer.score(
                symbol,
                df,
                regime          = regimes.get(symbol, "SIDEWAYS"),
                avg_spread_pct  = spreads.get(symbol, 0.001),
                volume_24h_usd  = volumes.get(symbol, 0.0),
            )
            scores[symbol] = sc

        if not scores:
            return RadarResult([], {}, "", time.time(), 0)

        sorted_scores = sorted(scores.values(), key=lambda s: s.total_score, reverse=True)
        top_n         = sorted_scores[:self.TOP_N]
        best          = top_n[0].symbol if top_n else ""

        self._cache    = scores
        self._cache_ts = time.time()

        return RadarResult(
            top_opportunities = top_n,
            all_scores        = scores,
            best_symbol       = best,
            scan_time         = time.time(),
            n_scanned         = len(scores),
        )

    def get_cached(self) -> dict[str, OpportunityScore]:
        """Gibt gecachte Scores zurück (für Dashboard)."""
        return dict(self._cache)

    def get_top_symbols(self, n: int = 5) -> list[str]:
        """Gibt Top-N Symbole aus Cache zurück."""
        if not self._cache:
            return []
        sorted_cache = sorted(self._cache.values(), key=lambda s: s.total_score, reverse=True)
        return [s.symbol for s in sorted_cache[:n]]

    def score_single(
        self,
        symbol: str,
        df: pd.DataFrame,
        regime: str = "SIDEWAYS",
    ) -> OpportunityScore:
        """Bewertet ein einzelnes Pair (ohne Cache-Update)."""
        return self.scorer.score(symbol, df, regime)


def format_radar_dashboard(result: RadarResult) -> str:
    """Formatiert Radar-Ergebnis für Logging/Display."""
    lines = [f"Opportunity Radar — {result.n_scanned} Pairs gescannt"]
    lines.append(f"Best: {result.best_symbol}")
    lines.append("─" * 50)
    for sc in result.top_opportunities[:5]:
        lines.append(
            f"  {sc.symbol:15s} {sc.total_score:5.1f}/100 "
            f"[{sc.signal:10s}] {sc.current_regime}"
        )
    return "\n".join(lines)


_opportunity_radar: OpportunityRadar | None = None


def get_opportunity_radar() -> OpportunityRadar:
    global _opportunity_radar
    if _opportunity_radar is None:
        _opportunity_radar = OpportunityRadar()
    return _opportunity_radar
