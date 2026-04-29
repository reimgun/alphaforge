"""
Fear & Greed Index — Crypto Fear & Greed via alternative.me API.

Der Index misst die allgemeine Marktstimmung (0=Extreme Fear, 100=Extreme Greed).
Quelle: https://api.alternative.me/fng/ (kostenlos, kein API-Key nötig)

Einfluss auf den Bot:
  Extreme Fear  (<25): Position ×0.5 — Panik-Markt, kein Catching-Knife
  Fear          (25–44): Position ×0.75
  Neutral       (45–55): Position ×1.0  (kein Einfluss)
  Greed         (56–74): Position ×0.85 — Markt überhitzt
  Extreme Greed (≥75): Position ×0.5, kein neuer BUY — klassischer Top-Indikator
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass

import requests

log = logging.getLogger("trading_bot")

_CACHE_TTL = 3600   # 1 Stunde
_API_URL   = "https://api.alternative.me/fng/?limit=1"


@dataclass
class FearGreedResult:
    value:           int     # 0–100
    label:           str     # "Extreme Fear" … "Extreme Greed"
    position_factor: float   # Multiplikator für Positionsgröße
    block_buy:       bool    # True bei Extreme Greed → kein neuer BUY


class FearGreedIndex:
    """Fetcht den Crypto Fear & Greed Index mit stündlichem Cache."""

    def __init__(self) -> None:
        self._cached:    FearGreedResult | None = None
        self._cached_at: float = 0.0

    def fetch(self) -> FearGreedResult:
        """Gibt den aktuellen Fear & Greed Wert zurück (gecacht, 1h TTL)."""
        if self._cached and (time.time() - self._cached_at) < _CACHE_TTL:
            return self._cached

        try:
            resp = requests.get(_API_URL, timeout=8)
            resp.raise_for_status()
            data   = resp.json()["data"][0]
            value  = int(data["value"])
            label  = data["value_classification"]
            result = _build_result(value, label)
            log.info(f"Fear & Greed Index: {value} ({label}) → PositionFaktor×{result.position_factor}")
        except Exception as e:
            log.warning(f"Fear & Greed Fetch-Fehler: {e} — Fallback: Neutral")
            result = FearGreedResult(value=50, label="Neutral", position_factor=1.0, block_buy=False)

        self._cached    = result
        self._cached_at = time.time()
        return result


def _build_result(value: int, label: str) -> FearGreedResult:
    # Kontra-zyklische Kalibrierung:
    # Extreme Fear (<25) = Kaufgelegenheit → BOOST (nicht reduzieren)
    # Extreme Greed (>75) = möglicher Top → Block
    if value < 25:
        factor, block = 1.25, False   # Extreme Fear: Kontra-zyklisch kaufen
    elif value < 45:
        factor, block = 1.0, False    # Fear: normal traden
    elif value < 56:
        factor, block = 1.0, False    # Neutral
    elif value < 75:
        factor, block = 0.85, False   # Greed: leicht vorsichtig
    else:
        factor, block = 0.5, True     # Extreme Greed: möglicher Top
    return FearGreedResult(value=value, label=label, position_factor=factor, block_buy=block)


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: FearGreedIndex | None = None

def get_fear_greed() -> FearGreedIndex:
    global _instance
    if _instance is None:
        _instance = FearGreedIndex()
    return _instance
