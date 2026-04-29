"""
Broker Factory — wählt den richtigen Client basierend auf FOREX_BROKER.

Unterstützte Broker:
  oanda    — OANDA REST API v3 (Standard, practice + live)
  capital  — Capital.com REST API (CFD, Demo kostenlos)
  ig       — IG Group REST API (CFD, reguliert DE/AT/CH)
  ibkr     — Interactive Brokers via ib_insync (professionell, Desktop nötig)
  alpaca   — Alpaca Markets (Aktien + Crypto + Forex, reine REST API)

Konfiguration in forex_bot/.env:
  FOREX_BROKER=oanda   # oanda | capital | ig | ibkr | alpaca

Alle Clients implementieren dasselbe Interface:
  get_account(), get_balance(), get_candles(), get_price(),
  get_spread_pips(), place_market_order(), place_limit_order(),
  cancel_order(), close_trade(), modify_stop_loss(),
  get_open_trades(), get_closed_trades(),
  pip_value_per_unit(), calculate_units()
"""
from __future__ import annotations

import logging
from forex_bot.config import settings as cfg

log = logging.getLogger("forex_bot")


def create_broker_client(creds: dict | None = None):
    """
    Erstellt den konfigurierten Broker-Client.

    creds (optional): Credential-Override-Dict aus dem Dashboard.
      Felder die übergeben werden überschreiben die .env-Werte.
      Beispiel: {"env": "live", "api_key": "...", "email": "..."}

    Returns:
        OandaClient | CapitalClient | IGClient | IBKRClient
    """
    c = creds or {}
    broker = c.get("broker", cfg.FOREX_BROKER).lower().strip()
    log.info(f"Broker: {broker} ({'dashboard' if creds else '.env'})")

    if broker == "capital":
        env = c.get("env") or cfg.CAPITAL_ENV
        from forex_bot.execution.capital_client import CapitalClient
        return CapitalClient(
            api_key     = c.get("api_key")  or (cfg.CAPITAL_API_KEY_LIVE  if env == "live" else cfg.CAPITAL_API_KEY_DEMO)  or cfg.CAPITAL_API_KEY,
            email       = c.get("email")    or (cfg.CAPITAL_EMAIL_LIVE    if env == "live" else cfg.CAPITAL_EMAIL_DEMO)    or cfg.CAPITAL_EMAIL,
            password    = c.get("password") or (cfg.CAPITAL_PASSWORD_LIVE if env == "live" else cfg.CAPITAL_PASSWORD_DEMO) or cfg.CAPITAL_PASSWORD,
            environment = env,
        )

    if broker == "ig":
        env = c.get("env") or cfg.IG_ENV
        from forex_bot.execution.ig_client import IGClient
        return IGClient(
            api_key     = c.get("api_key")    or (cfg.IG_API_KEY_LIVE  if env == "live" else cfg.IG_API_KEY_DEMO)  or cfg.IG_API_KEY,
            username    = c.get("username")   or (cfg.IG_USERNAME_LIVE if env == "live" else cfg.IG_USERNAME_DEMO) or cfg.IG_USERNAME,
            password    = c.get("password")   or (cfg.IG_PASSWORD_LIVE if env == "live" else cfg.IG_PASSWORD_DEMO) or cfg.IG_PASSWORD,
            environment = env,
            account_id  = c.get("account_id") or cfg.IG_ACCOUNT_ID,
        )

    if broker == "ibkr":
        from forex_bot.execution.ibkr_client import IBKRClient
        return IBKRClient(
            host      = c.get("host")      or cfg.IBKR_HOST,
            port      = int(c.get("port")  or cfg.IBKR_PORT),
            client_id = int(c.get("client_id") or cfg.IBKR_CLIENT_ID),
            account   = c.get("account")   or cfg.IBKR_ACCOUNT,
        )

    if broker == "alpaca":
        env = c.get("env") or cfg.ALPACA_ENV
        from forex_bot.execution.alpaca_client import AlpacaClient
        return AlpacaClient(
            api_key     = c.get("api_key")    or (cfg.ALPACA_API_KEY_LIVE    if env == "live" else cfg.ALPACA_API_KEY_PAPER)    or cfg.ALPACA_API_KEY,
            api_secret  = c.get("api_secret") or (cfg.ALPACA_API_SECRET_LIVE if env == "live" else cfg.ALPACA_API_SECRET_PAPER) or cfg.ALPACA_API_SECRET,
            environment = env,
        )

    if broker == "oanda":
        env = c.get("env") or cfg.OANDA_ENV
        from forex_bot.execution.oanda_client import OandaClient
        return OandaClient(
            c.get("api_key")    or (cfg.OANDA_API_KEY_LIVE    if env == "live" else cfg.OANDA_API_KEY_PRACTICE)    or cfg.OANDA_API_KEY,
            c.get("account_id") or (cfg.OANDA_ACCOUNT_ID_LIVE if env == "live" else cfg.OANDA_ACCOUNT_ID_PRACTICE) or cfg.OANDA_ACCOUNT_ID,
            env,
        )

    raise ValueError(
        f"Unbekannter Broker: '{broker}'. "
        f"Erlaubt: oanda, capital, ig, ibkr, alpaca."
    )
