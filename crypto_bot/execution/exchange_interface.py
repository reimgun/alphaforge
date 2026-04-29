"""
Multi-Exchange Abstraction Interface — Gap 19.

Einheitliche Schnittstelle für Binance, Bybit, OKX und Kraken.
Alle Adapter nutzen CCXT unter der Haube.

Verwendung:
    from crypto_bot.execution.exchange_interface import create_exchange
    exchange = create_exchange("binance")
    ticker = exchange.fetch_ticker("BTC/USDT")
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("trading_bot")


@dataclass
class OrderResult:
    id:       str
    symbol:   str
    side:     str    # "buy" | "sell"
    price:    float
    amount:   float
    filled:   float
    status:   str    # "open" | "closed" | "canceled"
    fee_cost: float
    exchange: str


class ExchangeAdapter(ABC):
    """Abstrakte Basisklasse für alle Exchange-Adapter."""

    name: str = "unknown"

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict:
        """Aktueller Preis + Bid/Ask für ein Symbol."""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        """OHLCV-Daten als Liste von [timestamp, open, high, low, close, volume]."""

    @abstractmethod
    def fetch_balance(self) -> dict:
        """Kontostand: {currency: {free: float, total: float}}."""

    @abstractmethod
    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> OrderResult:
        """Limit-Order erstellen."""

    @abstractmethod
    def create_market_order(self, symbol: str, side: str, amount: float) -> OrderResult:
        """Market-Order erstellen."""

    @abstractmethod
    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        """Order-Status abfragen."""

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Order stornieren."""

    def fetch_tickers(self) -> dict:
        """Alle Ticker (für Pair Selector). Override wenn unterstützt."""
        return {}

    def is_available(self) -> bool:
        """Prüft ob Exchange erreichbar ist."""
        try:
            self.fetch_ticker("BTC/USDT")
            return True
        except Exception:
            return False


def _parse_order(raw: dict, exchange_name: str) -> OrderResult:
    """Konvertiert CCXT-Order in OrderResult."""
    return OrderResult(
        id       = str(raw.get("id", "")),
        symbol   = str(raw.get("symbol", "")),
        side     = str(raw.get("side", "")),
        price    = float(raw.get("price") or raw.get("average") or 0),
        amount   = float(raw.get("amount", 0)),
        filled   = float(raw.get("filled", 0)),
        status   = str(raw.get("status", "")),
        fee_cost = float((raw.get("fee") or {}).get("cost", 0)),
        exchange = exchange_name,
    )


class BinanceAdapter(ExchangeAdapter):
    """Binance Exchange Adapter (produktiv eingesetzt)."""

    name = "binance"

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        import ccxt
        self._ex = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "spot"},
        })
        if testnet:
            self._ex.set_sandbox_mode(True)   # → testnet.binance.vision

    def fetch_ticker(self, symbol: str) -> dict:
        return self._ex.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        return self._ex.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self) -> dict:
        return self._ex.fetch_balance()

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> OrderResult:
        raw = self._ex.create_limit_order(symbol, side, amount, price)
        return _parse_order(raw, self.name)

    def create_market_order(self, symbol: str, side: str, amount: float) -> OrderResult:
        raw = self._ex.create_market_order(symbol, side, amount)
        return _parse_order(raw, self.name)

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        raw = self._ex.fetch_order(order_id, symbol)
        return _parse_order(raw, self.name)

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        result = self._ex.cancel_order(order_id, symbol)
        return result.get("status") in ("canceled", "cancelled")

    def fetch_tickers(self) -> dict:
        return self._ex.fetch_tickers()


class BybitAdapter(ExchangeAdapter):
    """Bybit Exchange Adapter (vollständig via CCXT)."""

    name = "bybit"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        import ccxt
        self._ex = ccxt.bybit({"apiKey": api_key, "secret": api_secret})

    def fetch_ticker(self, symbol: str) -> dict:
        return self._ex.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        return self._ex.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self) -> dict:
        return self._ex.fetch_balance()

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> OrderResult:
        raw = self._ex.create_limit_order(symbol, side, amount, price)
        return _parse_order(raw, self.name)

    def create_market_order(self, symbol: str, side: str, amount: float) -> OrderResult:
        raw = self._ex.create_market_order(symbol, side, amount)
        return _parse_order(raw, self.name)

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        raw = self._ex.fetch_order(order_id, symbol)
        return _parse_order(raw, self.name)

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        result = self._ex.cancel_order(order_id, symbol)
        return result.get("status") in ("canceled", "cancelled")

    def fetch_tickers(self) -> dict:
        return self._ex.fetch_tickers()


class OKXAdapter(ExchangeAdapter):
    """OKX Exchange Adapter (vollständig via CCXT)."""

    name = "okx"

    def __init__(self, api_key: str = "", api_secret: str = "", passphrase: str = ""):
        import ccxt
        self._ex = ccxt.okx({
            "apiKey": api_key, "secret": api_secret,
            "password": passphrase,
        })

    def fetch_ticker(self, symbol: str) -> dict:
        return self._ex.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        return self._ex.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self) -> dict:
        return self._ex.fetch_balance()

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> OrderResult:
        raw = self._ex.create_limit_order(symbol, side, amount, price)
        return _parse_order(raw, self.name)

    def create_market_order(self, symbol: str, side: str, amount: float) -> OrderResult:
        raw = self._ex.create_market_order(symbol, side, amount)
        return _parse_order(raw, self.name)

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        raw = self._ex.fetch_order(order_id, symbol)
        return _parse_order(raw, self.name)

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        result = self._ex.cancel_order(order_id, symbol)
        return result.get("status") in ("canceled", "cancelled")


class KrakenAdapter(ExchangeAdapter):
    """Kraken Exchange Adapter (vollständig via CCXT)."""

    name = "kraken"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        import ccxt
        self._ex = ccxt.kraken({"apiKey": api_key, "secret": api_secret})

    def fetch_ticker(self, symbol: str) -> dict:
        return self._ex.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list:
        return self._ex.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_balance(self) -> dict:
        return self._ex.fetch_balance()

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> OrderResult:
        raw = self._ex.create_limit_order(symbol, side, amount, price)
        return _parse_order(raw, self.name)

    def create_market_order(self, symbol: str, side: str, amount: float) -> OrderResult:
        raw = self._ex.create_market_order(symbol, side, amount)
        return _parse_order(raw, self.name)

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        raw = self._ex.fetch_order(order_id, symbol)
        return _parse_order(raw, self.name)

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        result = self._ex.cancel_order(order_id, symbol)
        return result.get("status") in ("canceled", "cancelled")


def create_exchange(
    name:       str = "binance",
    api_key:    str = "",
    api_secret: str = "",
    **kwargs,
) -> ExchangeAdapter:
    """
    Factory-Funktion — erstellt den passenden Exchange-Adapter.

    Args:
        name:       "binance" | "bybit" | "okx" | "kraken"
        api_key:    API-Key
        api_secret: API-Secret
        **kwargs:   Exchange-spezifische Parameter (z.B. passphrase für OKX)

    Returns:
        ExchangeAdapter-Instanz für den gewählten Exchange
    """
    adapters = {
        "binance": BinanceAdapter,
        "bybit":   BybitAdapter,
        "okx":     OKXAdapter,
        "kraken":  KrakenAdapter,
    }
    cls = adapters.get(name.lower())
    if cls is None:
        raise ValueError(f"Unbekannter Exchange: {name}. Gültig: {list(adapters.keys())}")

    log.info(f"Exchange-Adapter erstellt: {name}")
    if name == "okx":
        return cls(api_key, api_secret, kwargs.get("passphrase", ""))
    return cls(api_key, api_secret)


SUPPORTED_EXCHANGES = ["binance", "bybit", "okx", "kraken"]
