"""
WebSocket Streamer — Echtzeit Binance Kline-Stream.

Ersetzt REST-Polling durch echte Live-Daten (< 1s Latenz).
Reconnect-Logik mit exponentiellem Backoff.
Thread-sicher: get_latest_df() gibt immer den aktuellen Buffer zurück.
"""
import asyncio
import json
import threading
import time
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

log = logging.getLogger("trading_bot")

# Binance WebSocket URL
WS_BASE = "wss://stream.binance.com:9443/ws"


class BinanceWSStreamer:
    """
    Streamt Binance Kline-Daten via WebSocket.

    Verwendung:
        streamer = BinanceWSStreamer("BTC/USDT", "1h", buffer_size=500)
        streamer.start()
        df = streamer.get_latest_df()   # pandas DataFrame, thread-sicher
        streamer.stop()
    """

    def __init__(self, symbol: str, timeframe: str, buffer_size: int = 500):
        self._symbol      = symbol.replace("/", "").lower()   # btcusdt
        self._timeframe   = timeframe                         # 1h
        self._buffer_size = buffer_size
        self._buffer: deque = deque(maxlen=buffer_size)
        self._lock        = threading.Lock()
        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._last_message_ts: float = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ws-streamer"
        )
        self._thread.start()
        log.info(f"WebSocket Streamer gestartet: {self._symbol}@kline_{self._timeframe}")

    def stop(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log.info("WebSocket Streamer gestoppt")

    def is_connected(self) -> bool:
        """True wenn in den letzten 90 Sekunden eine Nachricht empfangen wurde."""
        return self._running and (time.time() - self._last_message_ts) < 90

    def get_latest_df(self) -> Optional[pd.DataFrame]:
        """Gibt Thread-sicheren DataFrame der gepufferten Candles zurück."""
        with self._lock:
            if len(self._buffer) < 2:
                return None
            rows = list(self._buffer)

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        return df.sort_index()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_with_retry())
        except RuntimeError:
            pass  # Event loop stopped by shutdown signal — expected
        finally:
            try:
                # Cancel all pending tasks cleanly
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            self._loop.close()

    async def _connect_with_retry(self):
        while self._running:
            try:
                await self._connect()
                self._reconnect_delay = 1.0   # Reset bei Erfolg
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                log.warning(f"WS Disconnect: {e} — Reconnect in {self._reconnect_delay:.0f}s")
                try:
                    await asyncio.sleep(self._reconnect_delay)
                except asyncio.CancelledError:
                    break
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

    async def _connect(self):
        try:
            import websockets
        except ImportError:
            log.error("websockets nicht installiert: pip install websockets")
            self._running = False
            return

        url = f"{WS_BASE}/{self._symbol}@kline_{self._timeframe}"
        log.info(f"WS Verbinde: {url}")

        async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
            log.info("WS Verbunden")
            async for raw in ws:
                if not self._running:
                    break
                self._handle_message(raw)

    def _handle_message(self, raw: str):
        try:
            data  = json.loads(raw)
            kline = data.get("k", {})
            if not kline:
                return

            candle = [
                int(kline["t"]),          # open_time ms
                float(kline["o"]),        # open
                float(kline["h"]),        # high
                float(kline["l"]),        # low
                float(kline["c"]),        # close
                float(kline["v"]),        # volume
            ]

            with self._lock:
                # Update oder append: Candle mit gleichem Timestamp ersetzen
                if self._buffer and self._buffer[-1][0] == candle[0]:
                    self._buffer[-1] = candle
                else:
                    self._buffer.append(candle)

            self._last_message_ts = time.time()

        except (KeyError, ValueError, json.JSONDecodeError) as e:
            log.debug(f"WS Message Parse Error: {e}")
