"""
Black Swan Detector — Extreme-Move und Cross-Pair-Kontagion Erkennung.

Erkennt außerordentliche Marktbewegungen:
  1. Einzelnes Pair: >3σ Preisbewegung innerhalb einer Candle
  2. Cross-Pair-Kontagion: ≥2 korrelierte Pairs mit extremen Moves gleichzeitig
  3. Flash-Crash-Proxy: Kursrückgang >2% in einer H1-Candle

Bei Erkennung:
  - Sofortiger Stop aller neuen Positionen
  - Laufende Positions mit engeren Stops absichern
  - Cooldown-Periode (BLACKSWAN_COOLDOWN_SEC)

Usage:
    from forex_bot.risk.black_swan import get_black_swan_detector
    detector = get_black_swan_detector()
    event = detector.check(df, instrument)
    if event.is_black_swan:
        # Keine neuen Trades öffnen
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

# Konfiguration
ZSCORE_THRESHOLD       = 3.0   # σ-Schwelle für Extreme-Move
FLASH_CRASH_THRESHOLD  = 0.02  # 2% Kursrückgang in einer Candle
LOOKBACK_CANDLES       = 50    # Für σ-Berechnung
MIN_CANDLES            = 20    # Mindest-Candles für Berechnung
BLACKSWAN_COOLDOWN_SEC = 3600  # 1 Stunde Cooldown nach Black Swan
CONTAGION_MIN_PAIRS    = 2     # Mindest-Pairs für Kontagion-Signal


@dataclass
class BlackSwanEvent:
    is_black_swan:  bool
    instrument:     str
    event_type:     str    # "extreme_move" | "flash_crash" | "contagion" | "none"
    z_score:        float
    move_pct:       float
    affected_pairs: list[str] = field(default_factory=list)
    cooldown_until: float = 0.0   # Unix timestamp


class BlackSwanDetector:
    """
    Erkennt Black Swan Events über alle beobachteten Pairs.
    Thread-safe durch Lock.
    """

    def __init__(self):
        self._lock         = threading.Lock()
        self._active_event: BlackSwanEvent | None = None
        self._pair_alerts:  dict[str, float] = {}   # instrument → timestamp der letzten Warnung

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        df:         pd.DataFrame,
        instrument: str,
    ) -> BlackSwanEvent:
        """
        Prüft ob aktuelle Candle ein Black Swan Event auslöst.

        Parameters
        ----------
        df:         OHLC DataFrame (mind. MIN_CANDLES Zeilen)
        instrument: Instrument-Name (z.B. "EUR_USD")

        Returns
        -------
        BlackSwanEvent (is_black_swan=False wenn kein Event)
        """
        # Cooldown prüfen
        if self._is_in_cooldown():
            return self._active_event or BlackSwanEvent(
                is_black_swan=False, instrument=instrument,
                event_type="none", z_score=0.0, move_pct=0.0,
            )

        if len(df) < MIN_CANDLES:
            return BlackSwanEvent(
                is_black_swan=False, instrument=instrument,
                event_type="none", z_score=0.0, move_pct=0.0,
            )

        try:
            event = self._analyze(df, instrument)
            if event.is_black_swan:
                self._register_event(event)
            return event
        except Exception as e:
            log.debug(f"BlackSwan check [{instrument}]: {e}")
            return BlackSwanEvent(
                is_black_swan=False, instrument=instrument,
                event_type="none", z_score=0.0, move_pct=0.0,
            )

    def is_active(self) -> bool:
        """True wenn aktives Black Swan Event mit laufendem Cooldown."""
        return self._is_in_cooldown()

    def clear(self) -> None:
        """Manuelles Zurücksetzen (z.B. nach Admin-Bestätigung)."""
        with self._lock:
            self._active_event = None
            self._pair_alerts.clear()
        log.info("BlackSwanDetector: Manuell zurückgesetzt")

    def get_active_event(self) -> BlackSwanEvent | None:
        with self._lock:
            return self._active_event

    # ── Internal ─────────────────────────────────────────────────────────────

    def _analyze(self, df: pd.DataFrame, instrument: str) -> BlackSwanEvent:
        closes = df["close"].astype(float)
        highs  = df["high"].astype(float)
        lows   = df["low"].astype(float)

        # Candle-Returns für σ-Berechnung
        returns = closes.pct_change().dropna()
        if len(returns) < MIN_CANDLES - 1:
            return BlackSwanEvent(
                is_black_swan=False, instrument=instrument,
                event_type="none", z_score=0.0, move_pct=0.0,
            )

        lookback = returns.iloc[-LOOKBACK_CANDLES:]
        mu       = float(lookback.mean())
        sigma    = float(lookback.std())
        last_ret = float(returns.iloc[-1])

        z_score  = (last_ret - mu) / (sigma + 1e-10) if sigma > 1e-10 else 0.0
        move_pct = abs(last_ret)

        # Flash Crash: Candle High-Low Range > FLASH_CRASH_THRESHOLD
        hl_range = float((highs.iloc[-1] - lows.iloc[-1]) / (closes.iloc[-2] if len(closes) > 1 else closes.iloc[-1]))

        # Extreme Move Check
        if abs(z_score) >= ZSCORE_THRESHOLD:
            direction = "Anstieg" if last_ret > 0 else "Einbruch"
            log.warning(
                f"BLACK SWAN: {instrument} — z={z_score:.1f}σ "
                f"{direction} {last_ret:.2%}"
            )

            # Cross-Pair Kontagion prüfen
            with self._lock:
                self._pair_alerts[instrument] = time.time()
                active_alerts = [
                    p for p, t in self._pair_alerts.items()
                    if time.time() - t < 300  # 5 Minuten Fenster
                ]

            if len(active_alerts) >= CONTAGION_MIN_PAIRS:
                return BlackSwanEvent(
                    is_black_swan=True,
                    instrument=instrument,
                    event_type="contagion",
                    z_score=round(z_score, 2),
                    move_pct=round(move_pct, 4),
                    affected_pairs=active_alerts,
                )

            return BlackSwanEvent(
                is_black_swan=True,
                instrument=instrument,
                event_type="extreme_move",
                z_score=round(z_score, 2),
                move_pct=round(move_pct, 4),
            )

        # Flash Crash Check
        if hl_range >= FLASH_CRASH_THRESHOLD:
            log.warning(
                f"BLACK SWAN (Flash Crash): {instrument} — HL-Range {hl_range:.2%}"
            )
            with self._lock:
                self._pair_alerts[instrument] = time.time()

            return BlackSwanEvent(
                is_black_swan=True,
                instrument=instrument,
                event_type="flash_crash",
                z_score=round(z_score, 2),
                move_pct=round(hl_range, 4),
            )

        return BlackSwanEvent(
            is_black_swan=False,
            instrument=instrument,
            event_type="none",
            z_score=round(z_score, 2),
            move_pct=round(move_pct, 4),
        )

    def _is_in_cooldown(self) -> bool:
        with self._lock:
            if self._active_event and self._active_event.cooldown_until > time.time():
                return True
            return False

    def _register_event(self, event: BlackSwanEvent) -> None:
        event.cooldown_until = time.time() + BLACKSWAN_COOLDOWN_SEC
        with self._lock:
            self._active_event = event
        log.warning(
            f"BlackSwan registriert: {event.event_type} [{event.instrument}] "
            f"— Cooldown {BLACKSWAN_COOLDOWN_SEC // 60} Minuten"
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: BlackSwanDetector | None = None
_detector_lock = threading.Lock()


def get_black_swan_detector() -> BlackSwanDetector:
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                _detector = BlackSwanDetector()
    return _detector
