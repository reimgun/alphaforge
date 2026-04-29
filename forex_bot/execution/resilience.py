"""
OANDA API Resilience Layer — Latenzerkennung, Retry-Logik, Auto-Recovery.

  APILatencyTracker:         Verfolgt Response-Zeiten, erkennt Latenz-Spikes
  OandaCircuitBreaker:       Verhindert Stampede bei API-Ausfällen
  ResilientOandaWrapper:     Wrapper mit Retry + Exponential Backoff
  OandaResilienceMonitor:    Gesamt-Wrapper für bot.py

Aktivierung: Wrapping von OandaClient-Calls in run_cycle().

Usage:
    from forex_bot.execution.resilience import OandaResilienceMonitor
    resilience = OandaResilienceMonitor()

    # In run_cycle:
    resilience.record_call(response_time_ms, success=True)
    if resilience.is_circuit_open():
        log.warning("OANDA API Circuit Breaker offen — Zyklus übersprungen")
        return
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Any

log = logging.getLogger("forex_bot")


# ── API Latency Tracker ───────────────────────────────────────────────────────

@dataclass
class LatencyStatus:
    avg_ms:       float
    p95_ms:       float
    spike_detected: bool
    reason:       str


class APILatencyTracker:
    """
    Verfolgt OANDA API Response-Zeiten und erkennt Latenz-Spikes.
    Spike = aktuelle Latenz > 3× der P50-Baseline.
    """
    WINDOW                = 50     # Letzte N Anfragen
    SPIKE_MULTIPLIER      = 3.0    # > 3× Median = Spike
    SPIKE_ABS_THRESHOLD   = 5000   # > 5000ms immer ein Spike
    P95_HIGH_THRESHOLD    = 3000   # P95 > 3s = "degradiert"

    def __init__(self):
        self._latencies: deque[float] = deque(maxlen=self.WINDOW)

    def record(self, response_time_ms: float) -> None:
        self._latencies.append(response_time_ms)

    def get_status(self) -> LatencyStatus:
        if not self._latencies:
            return LatencyStatus(0.0, 0.0, False, "Keine Messungen")

        data    = sorted(self._latencies)
        avg_ms  = sum(data) / len(data)
        p50     = data[len(data) // 2]
        p95_idx = min(len(data) - 1, int(len(data) * 0.95))
        p95_ms  = data[p95_idx]

        latest  = data[-1] if data else 0.0
        spike   = (latest > p50 * self.SPIKE_MULTIPLIER) or (latest > self.SPIKE_ABS_THRESHOLD)
        degraded = p95_ms > self.P95_HIGH_THRESHOLD

        reason = (
            f"Ø {avg_ms:.0f}ms | P95 {p95_ms:.0f}ms | Last {self._latencies[-1]:.0f}ms"
            + (" | SPIKE" if spike else "")
            + (" | DEGRADIERT" if degraded else "")
        )
        return LatencyStatus(
            avg_ms        = round(avg_ms, 1),
            p95_ms        = round(p95_ms, 1),
            spike_detected = spike or degraded,
            reason        = reason,
        )


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class OandaCircuitBreaker:
    """
    Circuit Breaker für OANDA API.

    Zustände:
      CLOSED   → Normal (Requests werden durchgelassen)
      OPEN     → Fehler-Limit erreicht (alle Requests blockiert)
      HALF_OPEN → Testphase nach OPEN (1 Request erlaubt)

    Öffnet nach N aufeinanderfolgenden Fehlern.
    Schließt automatisch nach RESET_TIMEOUT Sekunden.
    """
    FAILURE_THRESHOLD = 5     # Fehler bis Circuit öffnet
    RESET_TIMEOUT     = 120   # Sekunden bis Retry nach OPEN
    HALF_OPEN_TIMEOUT = 30    # Sekunden in HALF_OPEN

    def __init__(self):
        self._state:           str   = "CLOSED"
        self._failure_count:   int   = 0
        self._last_failure_ts: float = 0.0
        self._open_since:      float = 0.0

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state in ("OPEN", "HALF_OPEN"):
            self._state = "CLOSED"
            log.info("Circuit Breaker: CLOSED (Erfolg nach Failure)")

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_ts = time.time()
        if self._failure_count >= self.FAILURE_THRESHOLD and self._state == "CLOSED":
            self._state      = "OPEN"
            self._open_since = time.time()
            log.error(
                f"Circuit Breaker OFFEN — {self._failure_count} Fehler in Folge. "
                f"Retry in {self.RESET_TIMEOUT}s"
            )

    def is_open(self) -> bool:
        now = time.time()
        if self._state == "OPEN":
            if now - self._open_since >= self.RESET_TIMEOUT:
                self._state = "HALF_OPEN"
                log.info("Circuit Breaker: HALF_OPEN — Teste einen Request")
                return False   # Einen Request durch
            return True
        if self._state == "HALF_OPEN":
            return False  # Bereits im Test-Modus
        return False

    @property
    def state(self) -> str:
        return self._state


# ── Retry mit Exponential Backoff ─────────────────────────────────────────────

def with_retry(
    func:       Callable,
    max_retries: int  = 3,
    base_delay:  float = 1.0,   # Sekunden
    max_delay:   float = 30.0,
    exceptions:  tuple = (Exception,),
) -> Any:
    """
    Führt func mit Exponential Backoff aus.
    Wirft nach max_retries Versuchen die letzte Exception.
    """
    delay = base_delay
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exc = e
            if attempt == max_retries:
                break
            actual_delay = min(delay * (2 ** attempt), max_delay)
            log.warning(
                f"Retry {attempt + 1}/{max_retries}: {e} — "
                f"Warte {actual_delay:.1f}s"
            )
            time.sleep(actual_delay)

    raise last_exc


# ── Stale Data Detector ───────────────────────────────────────────────────────

class StaleDataDetector:
    """
    Erkennt veraltete Preisdaten (kein Update seit > threshold Sekunden).
    Wichtig bei OANDA-Verbindungsabbrüchen — Preise frieren ein.
    """
    STALE_THRESHOLD = 300   # 5 Minuten ohne Update = stale

    def __init__(self):
        self._last_prices: dict[str, tuple[float, float]] = {}  # instrument → (price, ts)

    def update(self, instrument: str, price: float) -> None:
        self._last_prices[instrument] = (price, time.time())

    def is_stale(self, instrument: str) -> bool:
        if instrument not in self._last_prices:
            return False
        price, ts = self._last_prices[instrument]
        return time.time() - ts > self.STALE_THRESHOLD

    def get_stale_instruments(self) -> list[str]:
        return [instr for instr in self._last_prices if self.is_stale(instr)]


# ── Resilience Monitor (Wrapper) ──────────────────────────────────────────────

class OandaResilienceMonitor:
    """
    Zentraler Resilience-Manager für bot.py.

    Nutzung:
        resilience = OandaResilienceMonitor()

        # Am Beginn jedes Zyklus:
        if resilience.is_circuit_open():
            log.warning("API Circuit Breaker — Zyklus übersprungen")
            return

        # Nach jedem API-Call:
        resilience.record_call(response_ms, success=True)

        # Preis-Update tracken:
        resilience.update_price(instrument, price)
    """

    def __init__(self):
        self.latency        = APILatencyTracker()
        self.circuit_breaker = OandaCircuitBreaker()
        self.stale_detector = StaleDataDetector()
        self._total_calls   = 0
        self._total_errors  = 0

    def record_call(self, response_ms: float, success: bool = True) -> None:
        self._total_calls += 1
        self.latency.record(response_ms)
        if success:
            self.circuit_breaker.record_success()
        else:
            self._total_errors += 1
            self.circuit_breaker.record_failure()

    def is_circuit_open(self) -> bool:
        return self.circuit_breaker.is_open()

    def update_price(self, instrument: str, price: float) -> None:
        self.stale_detector.update(instrument, price)

    def get_status(self) -> dict:
        lat    = self.latency.get_status()
        stale  = self.stale_detector.get_stale_instruments()
        return {
            "circuit_state":   self.circuit_breaker.state,
            "avg_latency_ms":  lat.avg_ms,
            "p95_latency_ms":  lat.p95_ms,
            "latency_spike":   lat.spike_detected,
            "stale_instruments": stale,
            "total_calls":     self._total_calls,
            "total_errors":    self._total_errors,
            "error_rate":      round(self._total_errors / max(1, self._total_calls), 3),
        }

    def log_status(self) -> None:
        s = self.get_status()
        if s["total_calls"] % 10 == 0:   # Alle 10 Calls loggen
            log.debug(
                f"API Resilience: Circuit={s['circuit_state']} "
                f"Ø{s['avg_latency_ms']:.0f}ms P95={s['p95_latency_ms']:.0f}ms "
                f"Errors={s['error_rate']:.1%}"
            )
        if s["stale_instruments"]:
            log.warning(f"Veraltete Preisdaten: {s['stale_instruments']}")
        if s["latency_spike"]:
            log.warning(f"API Latenz-Spike: {self.latency.get_status().reason}")
