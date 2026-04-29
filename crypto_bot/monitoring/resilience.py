"""
Self-Healing Infrastructure — API-Latenz, WS-Health, Auto-Failover.

  APILatencyAnomalyDetector:  Erkennt ungewöhnlich hohe Latenzen
  WebSocketHealthMonitor:     Überwacht WS-Verbindungsqualität
  ExchangeOutageDetector:     Erkennt Exchange-Ausfälle
  AutoFailoverManager:        Automatisches Wechseln zu Backup-Exchange

Feature-Flag: FEATURE_RESILIENCE=true|false
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import numpy as np

log = logging.getLogger("trading_bot")


# ── API Latency Anomaly Detector ──────────────────────────────────────────────

class HealthStatus(str, Enum):
    HEALTHY    = "HEALTHY"
    DEGRADED   = "DEGRADED"
    CRITICAL   = "CRITICAL"
    OFFLINE    = "OFFLINE"


@dataclass
class LatencyAnomalyResult:
    exchange:   str
    status:     HealthStatus
    current_ms: float
    baseline_ms: float
    anomaly_factor: float   # Wie viel mal über Baseline
    reason:     str


class APILatencyAnomalyDetector:
    """
    Erkennt API-Latenz-Anomalien via Z-Score oder Faktor-Schwellwert.

    Baseline wird aus ersten N Messungen berechnet.
    Danach wird aktuelle Latenz mit Baseline verglichen.
    """
    BASELINE_SAMPLES    = 20
    DEGRADED_FACTOR     = 3.0    # 3× Baseline = DEGRADED
    CRITICAL_FACTOR     = 10.0   # 10× Baseline = CRITICAL
    OFFLINE_TIMEOUT_S   = 30.0   # Keine Response > 30s = OFFLINE

    def __init__(self):
        self._samples: dict[str, deque[float]] = {}
        self._last_seen: dict[str, float] = {}

    def record(self, exchange: str, latency_ms: float) -> LatencyAnomalyResult:
        now = time.time()
        self._last_seen[exchange] = now

        if exchange not in self._samples:
            self._samples[exchange] = deque(maxlen=100)
        self._samples[exchange].append(latency_ms)

        samples = list(self._samples[exchange])
        if len(samples) < self.BASELINE_SAMPLES:
            return LatencyAnomalyResult(
                exchange, HealthStatus.HEALTHY, latency_ms, latency_ms, 1.0,
                f"Sammle Baseline ({len(samples)}/{self.BASELINE_SAMPLES})",
            )

        baseline = float(np.median(samples[:-1]))   # Median ohne aktuellen Wert
        if baseline <= 0:
            baseline = 1.0

        factor = latency_ms / baseline

        if factor >= self.CRITICAL_FACTOR:
            status = HealthStatus.CRITICAL
            reason = f"Latenz {latency_ms:.0f}ms = {factor:.1f}× Baseline"
        elif factor >= self.DEGRADED_FACTOR:
            status = HealthStatus.DEGRADED
            reason = f"Erhöhte Latenz {latency_ms:.0f}ms = {factor:.1f}× Baseline"
        else:
            status = HealthStatus.HEALTHY
            reason = f"Normale Latenz {latency_ms:.0f}ms (Baseline {baseline:.0f}ms)"

        return LatencyAnomalyResult(
            exchange       = exchange,
            status         = status,
            current_ms     = round(latency_ms, 1),
            baseline_ms    = round(baseline, 1),
            anomaly_factor = round(factor, 2),
            reason         = reason,
        )

    def check_timeout(self, exchange: str) -> LatencyAnomalyResult:
        """Prüft ob Exchange zu lange nicht geantwortet hat."""
        last = self._last_seen.get(exchange, 0)
        elapsed = time.time() - last
        if elapsed > self.OFFLINE_TIMEOUT_S and last > 0:
            return LatencyAnomalyResult(
                exchange, HealthStatus.OFFLINE,
                elapsed * 1000, 0, 0,
                f"Kein Response seit {elapsed:.0f}s",
            )
        return LatencyAnomalyResult(exchange, HealthStatus.HEALTHY, 0, 0, 1.0, "Aktiv")


# ── WebSocket Health Monitor ──────────────────────────────────────────────────

@dataclass
class WSHealthResult:
    exchange:          str
    status:            HealthStatus
    messages_per_min:  float
    reconnect_count:   int
    last_message_age_s: float
    reason:            str


class WebSocketHealthMonitor:
    """
    Überwacht WebSocket-Verbindungsqualität:
      - Message Rate (Nachrichten pro Minute)
      - Reconnect-Häufigkeit
      - Zeit seit letzter Nachricht
    """
    MIN_MSG_RATE        = 1.0     # Mindestens 1 Nachricht/Minute
    MAX_MSG_AGE_S       = 60.0    # Letzte Nachricht > 60s = Problem
    MAX_RECONNECTS_1H   = 5       # > 5 Reconnects/Stunde = DEGRADED

    def __init__(self):
        self._msg_times: dict[str, deque[float]] = {}
        self._reconnects: dict[str, list[float]] = {}

    def record_message(self, exchange: str) -> None:
        now = time.time()
        if exchange not in self._msg_times:
            self._msg_times[exchange] = deque(maxlen=200)
        self._msg_times[exchange].append(now)

    def record_reconnect(self, exchange: str) -> None:
        now = time.time()
        if exchange not in self._reconnects:
            self._reconnects[exchange] = []
        self._reconnects[exchange].append(now)

    def get_health(self, exchange: str) -> WSHealthResult:
        now    = time.time()
        msgs   = list(self._msg_times.get(exchange, []))
        recons = [t for t in self._reconnects.get(exchange, []) if now - t < 3600]

        if not msgs:
            return WSHealthResult(exchange, HealthStatus.OFFLINE, 0.0, len(recons),
                                  999.0, "Keine WS-Nachrichten empfangen")

        last_msg_age = now - msgs[-1]

        # Nachrichten in letzter Minute
        recent = [t for t in msgs if now - t < 60]
        msg_rate = len(recent) / 1.0   # pro Minute

        if last_msg_age > self.MAX_MSG_AGE_S:
            status = HealthStatus.CRITICAL
            reason = f"Letzte Nachricht vor {last_msg_age:.0f}s"
        elif len(recons) > self.MAX_RECONNECTS_1H:
            status = HealthStatus.DEGRADED
            reason = f"{len(recons)} Reconnects in letzter Stunde"
        elif msg_rate < self.MIN_MSG_RATE:
            status = HealthStatus.DEGRADED
            reason = f"Niedrige Message-Rate ({msg_rate:.1f}/min)"
        else:
            status = HealthStatus.HEALTHY
            reason = f"WS gesund ({msg_rate:.0f} msgs/min)"

        return WSHealthResult(
            exchange           = exchange,
            status             = status,
            messages_per_min   = round(msg_rate, 1),
            reconnect_count    = len(recons),
            last_message_age_s = round(last_msg_age, 1),
            reason             = reason,
        )


# ── Exchange Outage Detector ──────────────────────────────────────────────────

@dataclass
class OutageResult:
    exchange:      str
    is_outage:     bool
    consecutive_fails: int
    last_success_ago_s: float
    reason:        str


class ExchangeOutageDetector:
    """
    Erkennt Exchange-Ausfälle durch konsekutive Fehler.
    Nach N konsekutiven Fehlern wird Outage deklariert.
    """
    OUTAGE_THRESHOLD = 3     # 3 konsekutive Fehler = Outage
    RECOVERY_OK      = 2     # 2 konsekutive Erfolge = Wiederhergestellt

    def __init__(self):
        self._consecutive_fails: dict[str, int] = {}
        self._consecutive_ok:    dict[str, int] = {}
        self._last_success:      dict[str, float] = {}
        self._in_outage:         dict[str, bool] = {}

    def record_success(self, exchange: str) -> None:
        self._consecutive_fails[exchange] = 0
        self._consecutive_ok[exchange] = self._consecutive_ok.get(exchange, 0) + 1
        self._last_success[exchange] = time.time()
        if self._consecutive_ok.get(exchange, 0) >= self.RECOVERY_OK:
            if self._in_outage.get(exchange, False):
                log.info(f"Exchange {exchange}: Outage beendet, wiederhergestellt")
            self._in_outage[exchange] = False

    def record_failure(self, exchange: str) -> OutageResult:
        self._consecutive_ok[exchange] = 0
        self._consecutive_fails[exchange] = self._consecutive_fails.get(exchange, 0) + 1
        fails = self._consecutive_fails[exchange]

        if fails >= self.OUTAGE_THRESHOLD:
            if not self._in_outage.get(exchange, False):
                log.warning(f"Exchange {exchange}: OUTAGE erkannt nach {fails} Fehlern")
            self._in_outage[exchange] = True

        last_ok = self._last_success.get(exchange, 0)
        age     = time.time() - last_ok if last_ok > 0 else 999.0

        return OutageResult(
            exchange             = exchange,
            is_outage            = self._in_outage.get(exchange, False),
            consecutive_fails    = fails,
            last_success_ago_s   = round(age, 1),
            reason               = (
                f"Outage: {fails} konsekutive Fehler"
                if self._in_outage.get(exchange, False)
                else f"{fails} Fehler (kein Outage)"
            ),
        )

    def is_in_outage(self, exchange: str) -> bool:
        return self._in_outage.get(exchange, False)


# ── Auto Failover Manager ─────────────────────────────────────────────────────

@dataclass
class FailoverResult:
    primary:        str
    active:         str
    is_failover:    bool
    reason:         str


class AutoFailoverManager:
    """
    Automatisches Wechseln zu Backup-Exchange bei Outage.
    Versucht primären Exchange nach Recovery-Periode wieder zu aktivieren.
    """
    RECOVERY_CHECK_INTERVAL_S = 300   # 5 Minuten

    def __init__(self, primary: str, backups: list[str]):
        self.primary  = primary
        self.backups  = backups
        self._active  = primary
        self._failover_time: float | None = None

    def check_and_update(
        self,
        outage_status: dict[str, OutageResult],
    ) -> FailoverResult:
        primary_ok = not outage_status.get(self.primary, OutageResult(
            self.primary, False, 0, 0, ""
        )).is_outage

        if primary_ok:
            # Primärer Exchange ist OK → zurückwechseln
            if self._active != self.primary:
                log.info(f"Failover: Wechsle zurück zu {self.primary}")
            self._active = self.primary
            self._failover_time = None
            return FailoverResult(self.primary, self.primary, False, "Primary aktiv")

        # Primärer Exchange ist ausgefallen → Backup suchen
        for backup in self.backups:
            if not outage_status.get(backup, OutageResult(backup, False, 0, 0, "")).is_outage:
                if self._active != backup:
                    log.warning(f"Failover: Wechsle von {self.primary} zu {backup}")
                    self._failover_time = time.time()
                self._active = backup
                return FailoverResult(
                    self.primary, backup, True,
                    f"Failover zu {backup} wegen {self.primary} Outage",
                )

        # Alle Exchanges ausgefallen
        return FailoverResult(
            self.primary, self._active, True,
            "Alle Exchanges ausgefallen — kein Failover möglich",
        )

    @property
    def active_exchange(self) -> str:
        return self._active


# ── Resilience Monitor (Wrapper) ──────────────────────────────────────────────

@dataclass
class ResilienceStatus:
    latency:   dict[str, LatencyAnomalyResult]
    ws_health: dict[str, WSHealthResult]
    outages:   dict[str, OutageResult]
    failover:  FailoverResult
    overall:   HealthStatus


class ResilienceMonitor:
    """Wrapper — kombiniert alle Self-Healing Komponenten."""

    def __init__(self, primary_exchange: str = "binance", backup_exchanges: list[str] | None = None):
        self.latency_detector = APILatencyAnomalyDetector()
        self.ws_monitor       = WebSocketHealthMonitor()
        self.outage_detector  = ExchangeOutageDetector()
        self.failover_mgr     = AutoFailoverManager(
            primary_exchange,
            backup_exchanges or ["bybit", "okx"],
        )

    def record_api_call(self, exchange: str, latency_ms: float, success: bool) -> None:
        self.latency_detector.record(exchange, latency_ms)
        if success:
            self.outage_detector.record_success(exchange)
        else:
            self.outage_detector.record_failure(exchange)

    def record_ws_message(self, exchange: str) -> None:
        self.ws_monitor.record_message(exchange)

    def record_ws_reconnect(self, exchange: str) -> None:
        self.ws_monitor.record_reconnect(exchange)

    def get_status(self, exchanges: list[str] | None = None) -> ResilienceStatus:
        active_exchanges = exchanges or [self.failover_mgr.primary] + self.failover_mgr.backups

        lat_results  = {ex: self.latency_detector.check_timeout(ex) for ex in active_exchanges}
        ws_results   = {ex: self.ws_monitor.get_health(ex) for ex in active_exchanges}
        out_results  = {ex: OutageResult(ex, self.outage_detector.is_in_outage(ex),
                                         self.outage_detector._consecutive_fails.get(ex, 0),
                                         0, "") for ex in active_exchanges}
        failover     = self.failover_mgr.check_and_update(out_results)

        # Overall-Status
        all_statuses = [r.status for r in lat_results.values()] + \
                       [r.status for r in ws_results.values()]
        if any(s == HealthStatus.OFFLINE for s in all_statuses):
            overall = HealthStatus.CRITICAL
        elif any(s == HealthStatus.CRITICAL for s in all_statuses):
            overall = HealthStatus.CRITICAL
        elif any(s == HealthStatus.DEGRADED for s in all_statuses):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return ResilienceStatus(lat_results, ws_results, out_results, failover, overall)

    @property
    def active_exchange(self) -> str:
        return self.failover_mgr.active_exchange


_resilience: ResilienceMonitor | None = None


def get_resilience(primary: str = "binance") -> ResilienceMonitor:
    global _resilience
    if _resilience is None:
        _resilience = ResilienceMonitor(primary)
    return _resilience
