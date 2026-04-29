"""
Exchange Factory — wählt den richtigen Adapter basierend auf EXCHANGE.

Unterstützte Exchanges:
  binance  — Binance Spot (testnet.binance.vision / live)
  bybit    — Bybit Spot (testnet / live)
  okx      — OKX (paper / live)
  kraken   — Kraken (live only)

Konfiguration in .env:
  EXCHANGE=binance   # binance | bybit | okx | kraken

Alle Adapter implementieren dasselbe ExchangeAdapter-Interface:
  fetch_ticker(), fetch_ohlcv(), fetch_balance(),
  create_limit_order(), create_market_order(),
  fetch_order(), cancel_order()
"""
from __future__ import annotations

import logging
from crypto_bot.config import settings as cfg

log = logging.getLogger("trading_bot")


def create_exchange_client(creds: dict | None = None):
    """
    Erstellt den konfigurierten Exchange-Adapter.

    creds (optional): Credential-Override-Dict aus dem Dashboard.
      Felder die übergeben werden überschreiben die .env-Werte.
      Beispiel: {"exchange": "binance", "env": "testnet", "api_key": "...", "api_secret": "..."}

    Returns:
        BinanceAdapter | BybitAdapter | OKXAdapter | KrakenAdapter
    """
    from crypto_bot.execution.exchange_interface import (
        BinanceAdapter, BybitAdapter, OKXAdapter, KrakenAdapter,
    )

    c      = creds or {}
    name   = c.get("exchange", cfg.EXCHANGE).lower().strip()
    log.info(f"Exchange: {name} ({'dashboard' if creds else '.env'})")

    if name == "binance":
        env     = c.get("env") or ("testnet" if cfg.TRADING_MODE == "testnet" else "live")
        testnet = (env == "testnet")
        return BinanceAdapter(
            api_key    = c.get("api_key")    or (cfg.BINANCE_API_KEY_TESTNET    if testnet else cfg.BINANCE_API_KEY_LIVE)    or cfg.API_KEY,
            api_secret = c.get("api_secret") or (cfg.BINANCE_API_SECRET_TESTNET if testnet else cfg.BINANCE_API_SECRET_LIVE) or cfg.API_SECRET,
            testnet    = testnet,
        )

    if name == "bybit":
        env     = c.get("env") or "live"
        testnet = (env == "testnet")
        return BybitAdapter(
            api_key    = c.get("api_key")    or (cfg.BYBIT_API_KEY_TESTNET    if testnet else cfg.BYBIT_API_KEY_LIVE),
            api_secret = c.get("api_secret") or (cfg.BYBIT_API_SECRET_TESTNET if testnet else cfg.BYBIT_API_SECRET_LIVE),
        )

    if name == "okx":
        env  = c.get("env") or "live"
        demo = (env == "demo")
        return OKXAdapter(
            api_key    = c.get("api_key")    or (cfg.OKX_API_KEY_DEMO    if demo else cfg.OKX_API_KEY_LIVE),
            api_secret = c.get("api_secret") or (cfg.OKX_API_SECRET_DEMO if demo else cfg.OKX_API_SECRET_LIVE),
            passphrase = c.get("passphrase") or (cfg.OKX_PASSPHRASE_DEMO if demo else cfg.OKX_PASSPHRASE_LIVE),
        )

    if name == "kraken":
        return KrakenAdapter(
            api_key    = c.get("api_key")    or cfg.KRAKEN_API_KEY,
            api_secret = c.get("api_secret") or cfg.KRAKEN_API_SECRET,
        )

    raise ValueError(
        f"Unbekannter Exchange: '{name}'. "
        f"Erlaubt: binance, bybit, okx, kraken."
    )
