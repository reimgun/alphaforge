"""
Execution Venue Intelligence — Fee-aware Exchange-Routing.

  FeeTable:            Gebührenstruktur pro Exchange
  LatencyMonitor:      Misst und trackt API-Latenz pro Exchange
  VenueScorer:         Bewertet Exchanges nach Fee + Latenz + Spread
  VenueOptimizer:      Wrapper — wählt bestes Venue für Order

Feature-Flag: FEATURE_VENUE_OPTIMIZER=true|false
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("trading_bot")


# ── Fee Table ─────────────────────────────────────────────────────────────────

@dataclass
class FeeStructure:
    exchange:       str
    maker_fee:      float   # Maker-Gebühr (negativ = Rebate, z.B. -0.0001)
    taker_fee:      float   # Taker-Gebühr (z.B. 0.001 = 0.1%)
    withdrawal_fee: float   # Abhebe-Gebühr in USD
    has_futures:    bool    # Unterstützt Futures/Perpetuals

    @property
    def net_maker(self) -> float:
        """Netto-Kosten bei Maker-Order (negativ = Gewinn)."""
        return self.maker_fee

    @property
    def net_taker(self) -> float:
        return self.taker_fee


# Standardmäßige Fee-Tabelle (Stand 2024, kann per .env überschrieben werden)
DEFAULT_FEE_TABLE: dict[str, FeeStructure] = {
    "binance": FeeStructure("binance", maker_fee=0.0001, taker_fee=0.0004, withdrawal_fee=0.5, has_futures=True),
    "bybit":   FeeStructure("bybit",   maker_fee=0.0001, taker_fee=0.0006, withdrawal_fee=0.5, has_futures=True),
    "okx":     FeeStructure("okx",     maker_fee=0.0000, taker_fee=0.0005, withdrawal_fee=0.5, has_futures=True),
    "kraken":  FeeStructure("kraken",  maker_fee=0.0002, taker_fee=0.0026, withdrawal_fee=1.0, has_futures=True),
    "kucoin":  FeeStructure("kucoin",  maker_fee=0.0002, taker_fee=0.0006, withdrawal_fee=0.5, has_futures=False),
}


# ── Latency Monitor ───────────────────────────────────────────────────────────

@dataclass
class LatencyStats:
    exchange:    str
    avg_ms:      float    # Durchschnittliche Latenz (ms)
    p95_ms:      float    # 95. Perzentil
    last_ms:     float    # Letzte gemessene Latenz
    n_samples:   int


class LatencyMonitor:
    """
    Misst und trackt API-Response-Zeiten pro Exchange.
    Verwendet ringförmigen Puffer für gleitende Statistiken.
    """
    WINDOW = 20   # Letzten N Messungen

    def __init__(self):
        self._latencies: dict[str, deque[float]] = {}

    def record(self, exchange: str, latency_ms: float) -> None:
        if exchange not in self._latencies:
            self._latencies[exchange] = deque(maxlen=self.WINDOW)
        self._latencies[exchange].append(latency_ms)

    def measure_and_record(self, exchange: str, fn) -> float:
        """Führt fn() aus und misst Latenz. Gibt Latenz in ms zurück."""
        start = time.monotonic()
        try:
            fn()
        except Exception:
            pass
        elapsed_ms = (time.monotonic() - start) * 1000
        self.record(exchange, elapsed_ms)
        return elapsed_ms

    def get_stats(self, exchange: str) -> LatencyStats:
        data = list(self._latencies.get(exchange, []))
        if not data:
            return LatencyStats(exchange, 999.0, 999.0, 999.0, 0)

        arr = np.array(data)
        return LatencyStats(
            exchange  = exchange,
            avg_ms    = round(float(np.mean(arr)), 1),
            p95_ms    = round(float(np.percentile(arr, 95)), 1),
            last_ms   = round(data[-1], 1),
            n_samples = len(data),
        )

    def get_all_stats(self) -> dict[str, LatencyStats]:
        return {ex: self.get_stats(ex) for ex in self._latencies}


# ── Venue Scorer ──────────────────────────────────────────────────────────────

@dataclass
class VenueScore:
    exchange:    str
    total_score: float   # Gesamtpunktzahl (höher = besser)
    fee_score:   float   # Gebühren-Teilscore
    latency_score: float # Latenz-Teilscore
    spread_score:  float # Spread-Teilscore
    effective_cost: float # Gesamtkosten in % pro Trade
    reason:      str


class VenueScorer:
    """
    Bewertet Exchanges anhand von:
      - Gebühren (Maker vs Taker, abhängig von Order-Typ)
      - Latenz (niedrigere Latenz = besser für Timing)
      - Spread (falls verfügbar)

    Score 0–100 (höher = bevorzugtes Venue).
    """
    MAX_LATENCY_MS  = 500.0    # Über 500ms = sehr schlecht
    MAX_FEE_PCT     = 0.003    # 0.3% = sehr teuer

    def score(
        self,
        exchange:    str,
        fee_struct:  FeeStructure,
        latency:     LatencyStats,
        spread_pct:  float = 0.001,
        is_maker:    bool  = True,
    ) -> VenueScore:
        fee = fee_struct.net_maker if is_maker else fee_struct.net_taker
        effective_cost = fee + spread_pct / 2   # Halber Spread + Gebühr

        # Fee-Score: 0.1% oder besser → 100 Punkte, 0.3% → 0 Punkte
        fee_score = max(0.0, 100 * (1 - effective_cost / self.MAX_FEE_PCT))

        # Latenz-Score: < 50ms → 100, > 500ms → 0
        lat_score = max(0.0, 100 * (1 - latency.avg_ms / self.MAX_LATENCY_MS))

        # Spread-Score (niedrig besser): 0.05% → 100, 0.3% → 0
        spread_score = max(0.0, 100 * (1 - spread_pct / 0.003))

        total = fee_score * 0.5 + lat_score * 0.3 + spread_score * 0.2

        reason = (
            f"{exchange}: Kosten {effective_cost:.3%} | "
            f"Latenz {latency.avg_ms:.0f}ms | "
            f"Spread {spread_pct:.3%}"
        )

        return VenueScore(
            exchange       = exchange,
            total_score    = round(total, 1),
            fee_score      = round(fee_score, 1),
            latency_score  = round(lat_score, 1),
            spread_score   = round(spread_score, 1),
            effective_cost = round(effective_cost, 5),
            reason         = reason,
        )


# ── Venue Optimizer (Wrapper) ─────────────────────────────────────────────────

@dataclass
class VenueRecommendation:
    best_venue:   str
    all_scores:   list[VenueScore]
    reason:       str
    savings_bps:  float   # Einsparung vs schlechtestes Venue (Basispunkte)


class VenueOptimizer:
    """Wrapper — wählt bestes Execution Venue für gegebene Order."""

    def __init__(self, fee_table: dict[str, FeeStructure] | None = None):
        self.fee_table       = fee_table or DEFAULT_FEE_TABLE
        self.latency_monitor = LatencyMonitor()
        self.scorer          = VenueScorer()

    def record_latency(self, exchange: str, latency_ms: float) -> None:
        self.latency_monitor.record(exchange, latency_ms)

    def recommend(
        self,
        available_exchanges: list[str] | None = None,
        is_maker: bool = True,
        symbol: str = "BTC/USDT",
        spread_estimates: dict[str, float] | None = None,
    ) -> VenueRecommendation:
        exchanges = available_exchanges or list(self.fee_table.keys())
        spread_est = spread_estimates or {}

        scores: list[VenueScore] = []
        for ex in exchanges:
            if ex not in self.fee_table:
                continue
            fee   = self.fee_table[ex]
            lat   = self.latency_monitor.get_stats(ex)
            spread= spread_est.get(ex, 0.001)   # Default 0.1% Spread
            sc    = self.scorer.score(ex, fee, lat, spread, is_maker)
            scores.append(sc)

        if not scores:
            return VenueRecommendation("binance", [], "Keine Venues verfügbar", 0.0)

        scores.sort(key=lambda s: s.total_score, reverse=True)
        best = scores[0]
        worst= scores[-1]

        savings = max(0.0, worst.effective_cost - best.effective_cost) * 10_000  # in bps

        return VenueRecommendation(
            best_venue  = best.exchange,
            all_scores  = scores,
            reason      = f"Bestes Venue: {best.exchange} (Score {best.total_score:.0f}/100)",
            savings_bps = round(savings, 2),
        )

    def get_maker_rebate_info(self, exchange: str) -> str:
        fee = self.fee_table.get(exchange)
        if fee is None:
            return f"{exchange}: Unbekannte Fee-Struktur"
        if fee.maker_fee < 0:
            return f"{exchange}: Maker-Rebate {abs(fee.maker_fee):.4%} → Limit-Orders bevorzugen"
        return f"{exchange}: Maker {fee.maker_fee:.4%} / Taker {fee.taker_fee:.4%}"


_venue_optimizer: VenueOptimizer | None = None


def get_venue_optimizer() -> VenueOptimizer:
    global _venue_optimizer
    if _venue_optimizer is None:
        _venue_optimizer = VenueOptimizer()
    return _venue_optimizer
