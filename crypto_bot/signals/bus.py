"""
Signal Bus — Producer/Consumer für Multi-Bot-Kommunikation.

Bot A publiziert ein Signal → Bot B (oder mehrere) konsumieren es.
Transport: JSON-Datei im shared Volume (kein Redis/Broker nötig).
Für Redis-Transport: SIGNAL_BUS_REDIS_URL setzen.

Producer (Crypto Bot):
    bus = get_bus("crypto_bot")
    bus.publish("BUY", "BTC/USDT", confidence=0.82, price=65000)

Consumer (Forex Bot oder zweiter Crypto-Bot):
    bus = get_bus("forex_bot")
    for signal in bus.consume(timeout=5):
        print(signal)
"""
from __future__ import annotations

import json
import os
import time
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Iterator, Optional

log = logging.getLogger(__name__)

_BUS_DIR = Path(os.getenv("SIGNAL_BUS_DIR", "/tmp/trading_bot_signals"))
_REDIS_URL = os.getenv("SIGNAL_BUS_REDIS_URL", "")
_MAX_AGE_SECONDS = 300   # Signale älter als 5 min werden ignoriert


@dataclass
class Signal:
    source:     str        # z.B. "crypto_bot", "forex_bot"
    action:     str        # "BUY", "SELL", "HOLD", "ALERT"
    symbol:     str
    confidence: float = 0.0
    price:      float = 0.0
    timestamp:  float = 0.0
    data:       dict  = None

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.data is None:
            self.data = {}

    def is_fresh(self) -> bool:
        return (time.time() - self.timestamp) < _MAX_AGE_SECONDS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class FileBus:
    """File-basierter Signal Bus — kein externer Broker nötig."""

    def __init__(self, consumer_id: str):
        self.consumer_id = consumer_id
        _BUS_DIR.mkdir(parents=True, exist_ok=True)
        self._inbox = _BUS_DIR / f"{consumer_id}.signals.jsonl"
        self._outbox = _BUS_DIR / "broadcast.signals.jsonl"

    def publish(
        self,
        action: str,
        symbol: str,
        confidence: float = 0.0,
        price: float = 0.0,
        targets: Optional[list[str]] = None,
        **data,
    ) -> Signal:
        sig = Signal(
            source=self.consumer_id,
            action=action.upper(),
            symbol=symbol,
            confidence=confidence,
            price=price,
            data=data,
        )
        line = json.dumps(sig.to_dict()) + "\n"

        # Broadcast + gezielte Empfänger
        with self._outbox.open("a") as f:
            f.write(line)

        if targets:
            for target in targets:
                inbox = _BUS_DIR / f"{target}.signals.jsonl"
                with inbox.open("a") as f:
                    f.write(line)

        log.debug(f"SignalBus PUBLISH [{self.consumer_id}→]: {action} {symbol} @ {price}")
        return sig

    def consume(self, timeout: float = 0.0, max_signals: int = 100) -> Iterator[Signal]:
        deadline = time.time() + timeout
        yielded  = 0

        def _read_file(path: Path) -> list[Signal]:
            if not path.exists():
                return []
            signals = []
            lines   = path.read_text().splitlines()
            fresh   = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    sig = Signal.from_dict(json.loads(line))
                    if sig.source != self.consumer_id and sig.is_fresh():
                        signals.append(sig)
                        fresh.append(line)
                    elif sig.is_fresh():
                        fresh.append(line)
                except Exception:
                    pass
            path.write_text("\n".join(fresh) + ("\n" if fresh else ""))
            return signals

        while yielded < max_signals:
            for sig in _read_file(self._inbox) + _read_file(self._outbox):
                yield sig
                yielded += 1
                if yielded >= max_signals:
                    return

            if timeout <= 0 or time.time() >= deadline:
                break
            time.sleep(0.5)

    def clear(self) -> None:
        for f in [self._inbox, self._outbox]:
            if f.exists():
                f.unlink()


class RedisBus:
    """Redis-basierter Signal Bus für produktive Multi-Server-Setups."""

    def __init__(self, consumer_id: str, redis_url: str):
        import redis
        self.consumer_id = consumer_id
        self._r = redis.from_url(redis_url, decode_responses=True)
        self._channel = "trading_bot:signals"

    def publish(self, action: str, symbol: str, confidence: float = 0.0,
                price: float = 0.0, **data) -> Signal:
        sig = Signal(source=self.consumer_id, action=action.upper(),
                     symbol=symbol, confidence=confidence, price=price, data=data)
        self._r.publish(self._channel, json.dumps(sig.to_dict()))
        self._r.lpush(f"{self._channel}:history", json.dumps(sig.to_dict()))
        self._r.ltrim(f"{self._channel}:history", 0, 999)
        return sig

    def consume(self, timeout: float = 5.0, max_signals: int = 100) -> Iterator[Signal]:
        pubsub = self._r.pubsub()
        pubsub.subscribe(self._channel)
        deadline = time.time() + timeout
        yielded  = 0
        for msg in pubsub.listen():
            if time.time() > deadline or yielded >= max_signals:
                break
            if msg["type"] != "message":
                continue
            try:
                sig = Signal.from_dict(json.loads(msg["data"]))
                if sig.source != self.consumer_id and sig.is_fresh():
                    yield sig
                    yielded += 1
            except Exception:
                pass
        pubsub.unsubscribe()

    def clear(self) -> None:
        self._r.delete(self._channel, f"{self._channel}:history")


def get_bus(consumer_id: str) -> FileBus | RedisBus:
    if _REDIS_URL:
        try:
            return RedisBus(consumer_id, _REDIS_URL)
        except ImportError:
            log.warning("redis nicht installiert — verwende FileBus")
    return FileBus(consumer_id)
