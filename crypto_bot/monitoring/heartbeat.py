"""
Dead Man's Switch — Heartbeat-Monitoring.

Der Bot schreibt alle N Minuten einen Timestamp in data_store/heartbeat.json.
Ein externer Watchdog-Thread prüft ob der Timestamp frisch ist.
Falls nicht → Telegram-Alert + Logging.

Schützt vor:
  - Bot hängt in Endlosschleife ohne Trading
  - Exception-Loop der keine Trades produziert
  - Container-Freeze ohne Docker-Exit

Verwendung:
  heartbeat = Heartbeat()
  heartbeat.start()
  # Im Bot-Loop:
  heartbeat.ping()
  # Beim Shutdown:
  heartbeat.stop()
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from crypto_bot.monitoring.logger import log, log_event
from crypto_bot.monitoring import alerts

_HEARTBEAT_FILE = Path(__file__).parent.parent / "data_store" / "heartbeat.json"
_DEFAULT_MAX_SILENCE_MINUTES = 90   # Alert wenn Bot N Minuten kein Ping sendet (60min Cycle + 30min Buffer)
_CHECK_INTERVAL_SECONDS = 60        # Watchdog-Check alle 60s


class Heartbeat:
    """
    Schreibt regelmäßig einen Heartbeat-Timestamp.
    Watchdog-Thread prüft ob Bot noch lebt.
    """

    def __init__(self, max_silence_minutes: int = _DEFAULT_MAX_SILENCE_MINUTES):
        self.max_silence_minutes = max_silence_minutes
        self._running            = False
        self._watchdog_thread: threading.Thread | None = None
        self._last_ping: datetime | None = None
        self._alert_sent         = False  # Verhindert Spam-Alerts

    def ping(self) -> None:
        """Muss aus dem Bot-Loop aufgerufen werden (einmal pro Iteration)."""
        self._last_ping = datetime.now(timezone.utc)
        self._alert_sent = False  # Reset nach Recovery
        try:
            _HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _HEARTBEAT_FILE.write_text(json.dumps({
                "timestamp":   self._last_ping.isoformat(),
                "pid":         __import__("os").getpid(),
                "status":      "alive",
            }))
        except Exception as e:
            log.debug(f"Heartbeat schreiben fehlgeschlagen: {e}")

    def start(self) -> None:
        """Startet den Watchdog-Thread."""
        self._running = True
        self.ping()  # Initialer Ping
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="heartbeat-watchdog",
        )
        self._watchdog_thread.start()
        log.info(f"Heartbeat Watchdog gestartet (max Stille: {self.max_silence_minutes} min)")

    def stop(self) -> None:
        """Stoppt den Watchdog und schreibt letzten Status."""
        self._running = False
        try:
            _HEARTBEAT_FILE.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status":    "stopped",
            }))
        except Exception:
            pass
        log.info("Heartbeat Watchdog gestoppt")

    def get_status(self) -> dict:
        """Gibt aktuellen Heartbeat-Status zurück (für Dashboard API)."""
        if self._last_ping is None:
            return {"alive": False, "last_ping": None, "silence_minutes": None}
        now     = datetime.now(timezone.utc)
        silence = (now - self._last_ping).total_seconds() / 60
        return {
            "alive":            silence < self.max_silence_minutes,
            "last_ping":        self._last_ping.isoformat(),
            "silence_minutes":  round(silence, 1),
            "max_silence_min":  self.max_silence_minutes,
        }

    def _watchdog_loop(self) -> None:
        while self._running:
            time.sleep(_CHECK_INTERVAL_SECONDS)
            if not self._running:
                break
            if self._last_ping is None:
                continue

            now     = datetime.now(timezone.utc)
            silence = (now - self._last_ping).total_seconds() / 60

            if silence >= self.max_silence_minutes and not self._alert_sent:
                msg = (
                    f"⚠️ Dead Man's Switch: Bot hat seit {silence:.0f} Minuten "
                    f"keinen Heartbeat gesendet!\n"
                    f"Letzter Ping: {self._last_ping.isoformat()}\n"
                    f"Möglicherweise eingefroren — bitte prüfen!"
                )
                log.critical(f"DEAD MAN'S SWITCH: {silence:.0f} min Stille!")
                log_event(f"Dead Man's Switch: {silence:.0f} min Stille", "heartbeat", "critical")
                alerts.alert_error(msg)
                self._alert_sent = True


# Singleton — wird in bot.py verwendet
_heartbeat_instance: Heartbeat | None = None


def get_heartbeat(max_silence_minutes: int = _DEFAULT_MAX_SILENCE_MINUTES) -> Heartbeat:
    global _heartbeat_instance
    if _heartbeat_instance is None:
        _heartbeat_instance = Heartbeat(max_silence_minutes)
    return _heartbeat_instance
