"""
Forex Bot — Konfiguration.
Alle Werte werden aus forex_bot/.env geladen.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Broker-Auswahl ────────────────────────────────────────────────────────────
FOREX_BROKER     = os.getenv("FOREX_BROKER", "oanda")   # oanda | capital | ig | ibkr

# ── OANDA API ─────────────────────────────────────────────────────────────────
OANDA_API_KEY_PRACTICE    = os.getenv("OANDA_API_KEY_PRACTICE", "")
OANDA_ACCOUNT_ID_PRACTICE = os.getenv("OANDA_ACCOUNT_ID_PRACTICE", "")
OANDA_API_KEY_LIVE        = os.getenv("OANDA_API_KEY_LIVE", "")
OANDA_ACCOUNT_ID_LIVE     = os.getenv("OANDA_ACCOUNT_ID_LIVE", "")
# Legacy-Fallback (alte .env ohne Suffix)
OANDA_API_KEY    = os.getenv("OANDA_API_KEY",    OANDA_API_KEY_PRACTICE    or OANDA_API_KEY_LIVE)
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", OANDA_ACCOUNT_ID_PRACTICE or OANDA_ACCOUNT_ID_LIVE)
OANDA_ENV        = os.getenv("OANDA_ENV", "practice")   # "practice" | "live"

# ── Capital.com API ───────────────────────────────────────────────────────────
CAPITAL_API_KEY_DEMO  = os.getenv("CAPITAL_API_KEY_DEMO", "")
CAPITAL_EMAIL_DEMO    = os.getenv("CAPITAL_EMAIL_DEMO", "")
CAPITAL_PASSWORD_DEMO = os.getenv("CAPITAL_PASSWORD_DEMO", "")
CAPITAL_API_KEY_LIVE  = os.getenv("CAPITAL_API_KEY_LIVE", "")
CAPITAL_EMAIL_LIVE    = os.getenv("CAPITAL_EMAIL_LIVE", "")
CAPITAL_PASSWORD_LIVE = os.getenv("CAPITAL_PASSWORD_LIVE", "")
# Legacy-Fallback
CAPITAL_API_KEY  = os.getenv("CAPITAL_API_KEY",  CAPITAL_API_KEY_DEMO  or CAPITAL_API_KEY_LIVE)
CAPITAL_EMAIL    = os.getenv("CAPITAL_EMAIL",    CAPITAL_EMAIL_DEMO    or CAPITAL_EMAIL_LIVE)
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD", CAPITAL_PASSWORD_DEMO or CAPITAL_PASSWORD_LIVE)
CAPITAL_ENV      = os.getenv("CAPITAL_ENV", "demo")     # "demo" | "live"

# ── IG Group API ──────────────────────────────────────────────────────────────
IG_API_KEY_DEMO  = os.getenv("IG_API_KEY_DEMO", "")
IG_USERNAME_DEMO = os.getenv("IG_USERNAME_DEMO", "")
IG_PASSWORD_DEMO = os.getenv("IG_PASSWORD_DEMO", "")
IG_API_KEY_LIVE  = os.getenv("IG_API_KEY_LIVE", "")
IG_USERNAME_LIVE = os.getenv("IG_USERNAME_LIVE", "")
IG_PASSWORD_LIVE = os.getenv("IG_PASSWORD_LIVE", "")
# Legacy-Fallback
IG_API_KEY    = os.getenv("IG_API_KEY",  IG_API_KEY_DEMO  or IG_API_KEY_LIVE)
IG_USERNAME   = os.getenv("IG_USERNAME", IG_USERNAME_DEMO or IG_USERNAME_LIVE)
IG_PASSWORD   = os.getenv("IG_PASSWORD", IG_PASSWORD_DEMO or IG_PASSWORD_LIVE)
IG_ENV        = os.getenv("IG_ENV", "demo")              # "demo" | "live"
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID", "")          # optional

# ── Interactive Brokers (IBKR) ────────────────────────────────────────────────
IBKR_HOST      = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT      = int(os.getenv("IBKR_PORT", "7497"))    # 7497=TWS Paper, 7496=TWS Live
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_ACCOUNT   = os.getenv("IBKR_ACCOUNT", "")          # leer = erster Account

# ── Alpaca Markets (Aktien + Crypto + Forex) ──────────────────────────────────
ALPACA_ENV             = os.getenv("ALPACA_ENV", "paper")           # paper | live
ALPACA_API_KEY         = os.getenv("ALPACA_API_KEY", "")            # Legacy-Fallback
ALPACA_API_SECRET      = os.getenv("ALPACA_API_SECRET", "")
ALPACA_API_KEY_PAPER   = os.getenv("ALPACA_API_KEY_PAPER",   ALPACA_API_KEY)
ALPACA_API_SECRET_PAPER= os.getenv("ALPACA_API_SECRET_PAPER", ALPACA_API_SECRET)
ALPACA_API_KEY_LIVE    = os.getenv("ALPACA_API_KEY_LIVE",    "")
ALPACA_API_SECRET_LIVE = os.getenv("ALPACA_API_SECRET_LIVE", "")

# ── Trading ───────────────────────────────────────────────────────────────────
INSTRUMENTS      = os.getenv("FOREX_INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,EUR_JPY,GBP_JPY,EUR_GBP").split(",")
TIMEFRAME        = os.getenv("FOREX_TIMEFRAME", "H1")
INITIAL_CAPITAL  = float(os.getenv("FOREX_INITIAL_CAPITAL", "10000"))
TRADING_MODE     = os.getenv("FOREX_TRADING_MODE", "paper")   # paper | live

# ── Risiko ────────────────────────────────────────────────────────────────────
RISK_PER_TRADE   = float(os.getenv("FOREX_RISK_PER_TRADE", "0.01"))   # 1% pro Trade
MAX_DRAWDOWN     = float(os.getenv("FOREX_MAX_DRAWDOWN",   "0.15"))   # 15% Circuit Breaker
MAX_OPEN_TRADES  = int(os.getenv("FOREX_MAX_OPEN_TRADES",  "3"))
ATR_MULTIPLIER   = float(os.getenv("FOREX_ATR_MULTIPLIER", "1.5"))    # SL-Abstand
RR_RATIO         = float(os.getenv("FOREX_RR_RATIO",       "2.0"))    # Reward:Risk

# ── Strategie ─────────────────────────────────────────────────────────────────
EMA_FAST         = int(os.getenv("FOREX_EMA_FAST",   "20"))
EMA_SLOW         = int(os.getenv("FOREX_EMA_SLOW",   "50"))
EMA_TREND        = int(os.getenv("FOREX_EMA_TREND",  "200"))
RSI_PERIOD       = int(os.getenv("FOREX_RSI_PERIOD", "14"))
MIN_CONFIDENCE   = float(os.getenv("FOREX_MIN_CONFIDENCE", "0.65"))

# ── Session-Filter ────────────────────────────────────────────────────────────
# Nur während London + NY Overlap traden (15:00–17:00 CEST = 13:00–15:00 UTC)
SESSION_FILTER   = os.getenv("FOREX_SESSION_FILTER", "true").lower() == "true"
SESSION_START_H  = int(os.getenv("FOREX_SESSION_START_H", "7"))    # UTC
SESSION_END_H    = int(os.getenv("FOREX_SESSION_END_H",   "20"))   # UTC

# ── Wirtschaftskalender ───────────────────────────────────────────────────────
NEWS_PAUSE_MIN   = int(os.getenv("FOREX_NEWS_PAUSE_MIN", "30"))    # ±Minuten um High-Impact
NEWS_CURRENCIES  = os.getenv("FOREX_NEWS_CURRENCIES", "USD,EUR,GBP,JPY,CHF,CAD,AUD,NZD").split(",")

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("FOREX_TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID  = os.getenv("FOREX_TELEGRAM_CHAT_ID", "")
# FOREX_TELEGRAM_POLLING=true nur wenn eigener dedizierter Forex-Bot-Token
# gesetzt ist (nicht denselben Token wie Crypto-Bot verwenden — Polling-Konflikt).
TELEGRAM_POLLING  = os.getenv("FOREX_TELEGRAM_POLLING", "false").lower() == "true"

# ── Dashboard API ─────────────────────────────────────────────────────────────
API_PORT         = int(os.getenv("FOREX_API_PORT", "8001"))

# ── Risk Mode ─────────────────────────────────────────────────────────────────
RISK_MODE              = os.getenv("FOREX_RISK_MODE", "balanced")   # conservative | balanced | aggressive
RETRAIN_AFTER_TRADES   = int(os.getenv("FOREX_RETRAIN_AFTER_TRADES", "50"))

# ── Externe Daten (optional) ──────────────────────────────────────────────────
FRED_API_KEY           = os.getenv("FRED_API_KEY", "")            # fred.stlouisfed.org (kostenlos)
GROQ_API_KEY           = os.getenv("GROQ_API_KEY", "")            # console.groq.com (kostenlos)

# ── Session Quality ────────────────────────────────────────────────────────────
SESSION_QUALITY_FILTER = os.getenv("FOREX_SESSION_QUALITY", "true").lower() == "true"

# ── Strategy Selector ─────────────────────────────────────────────────────────
MULTI_STRATEGY         = os.getenv("FOREX_MULTI_STRATEGY", "true").lower() == "true"

# ── Shared Exposure (Crypto + Forex) ─────────────────────────────────────────
SHARED_EXPOSURE_PATH   = os.getenv("SHARED_EXPOSURE_PATH",
                                    "/tmp/trading_shared_exposure.json")

# ── Lean Mode — minimaler Ressourcenverbrauch (QNAP/NAS) ─────────────────────
# True: Deaktiviert LSTM, Monte Carlo, Portfolio Optimizer, Stress Tester
#       Ideal für schwache Hardware (≤4 GB RAM)
LEAN_MODE = os.getenv("FOREX_LEAN_MODE", "false").lower() == "true"
