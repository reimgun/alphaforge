import os
from pathlib import Path
from dotenv import load_dotenv

# Projekt-Verzeichnisse
CRYPTO_BOT_DIR = Path(__file__).parent.parent        # crypto_bot/
BASE_DIR       = CRYPTO_BOT_DIR.parent               # Projekt-Root

# Verschlüsselte Config laden (falls vorhanden), sonst .env
try:
    from crypto_bot.config.crypto_config import load_secure_env
    if not load_secure_env():
        load_dotenv(BASE_DIR / ".env")
except Exception:
    load_dotenv(BASE_DIR / ".env")

# ── Exchange ──────────────────────────────────────────────────────────────────
EXCHANGE        = os.getenv("EXCHANGE", "binance")   # binance | bybit | okx | kraken
SYMBOL          = os.getenv("SYMBOL", "BTC/USDT").strip()
TIMEFRAME       = os.getenv("TIMEFRAME", "1h").strip()
TREND_TIMEFRAME = os.getenv("TREND_TIMEFRAME", "4h").strip()

# ── Binance API ───────────────────────────────────────────────────────────────
BINANCE_API_KEY_TESTNET    = os.getenv("BINANCE_API_KEY_TESTNET",    "")
BINANCE_API_SECRET_TESTNET = os.getenv("BINANCE_API_SECRET_TESTNET", "")
BINANCE_API_KEY_LIVE       = os.getenv("BINANCE_API_KEY_LIVE",       "")
BINANCE_API_SECRET_LIVE    = os.getenv("BINANCE_API_SECRET_LIVE",    "")
# Legacy-Fallback (alte .env ohne Suffix)
API_KEY    = os.getenv("BINANCE_API_KEY",    BINANCE_API_KEY_TESTNET    or BINANCE_API_KEY_LIVE)
API_SECRET = os.getenv("BINANCE_API_SECRET", BINANCE_API_SECRET_TESTNET or BINANCE_API_SECRET_LIVE)

# ── Bybit API ─────────────────────────────────────────────────────────────────
BYBIT_API_KEY_TESTNET    = os.getenv("BYBIT_API_KEY_TESTNET",    "")
BYBIT_API_SECRET_TESTNET = os.getenv("BYBIT_API_SECRET_TESTNET", "")
BYBIT_API_KEY_LIVE       = os.getenv("BYBIT_API_KEY_LIVE",       "")
BYBIT_API_SECRET_LIVE    = os.getenv("BYBIT_API_SECRET_LIVE",    "")

# ── OKX API ───────────────────────────────────────────────────────────────────
OKX_API_KEY_DEMO    = os.getenv("OKX_API_KEY_DEMO",    "")
OKX_API_SECRET_DEMO = os.getenv("OKX_API_SECRET_DEMO", "")
OKX_PASSPHRASE_DEMO = os.getenv("OKX_PASSPHRASE_DEMO", "")
OKX_API_KEY_LIVE    = os.getenv("OKX_API_KEY_LIVE",    "")
OKX_API_SECRET_LIVE = os.getenv("OKX_API_SECRET_LIVE", "")
OKX_PASSPHRASE_LIVE = os.getenv("OKX_PASSPHRASE_LIVE", "")

# ── Kraken API ────────────────────────────────────────────────────────────────
KRAKEN_API_KEY    = os.getenv("KRAKEN_API_KEY",    "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

# ── Coinbase Advanced API ─────────────────────────────────────────────────────
COINBASE_API_KEY    = os.getenv("COINBASE_API_KEY",    "")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET", "")

# ── Gate.io API ───────────────────────────────────────────────────────────────
GATEIO_API_KEY    = os.getenv("GATEIO_API_KEY",    "")
GATEIO_API_SECRET = os.getenv("GATEIO_API_SECRET", "")

# ── KuCoin API ────────────────────────────────────────────────────────────────
KUCOIN_API_KEY        = os.getenv("KUCOIN_API_KEY",        "")
KUCOIN_API_SECRET     = os.getenv("KUCOIN_API_SECRET",     "")
KUCOIN_API_PASSPHRASE = os.getenv("KUCOIN_API_PASSPHRASE", "")

# ── Bitget API ────────────────────────────────────────────────────────────────
BITGET_API_KEY        = os.getenv("BITGET_API_KEY",        "")
BITGET_API_SECRET     = os.getenv("BITGET_API_SECRET",     "")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE", "")

# ── HTX / Huobi API ───────────────────────────────────────────────────────────
HTX_API_KEY    = os.getenv("HTX_API_KEY",    "")
HTX_API_SECRET = os.getenv("HTX_API_SECRET", "")

# ── MEXC API ──────────────────────────────────────────────────────────────────
MEXC_API_KEY    = os.getenv("MEXC_API_KEY",    "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# ── Modus: "paper" | "testnet" | "live" ──────────────────────────────────────
# paper:   Komplett lokale Simulation — kein Binance-Account nötig
# testnet: Echte Binance-API auf testnet.binance.vision — virtuelles Geld, echte Orders
# live:    Echtes Geld auf Binance (nur nach expliziter Bestätigung)
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# ── Kapital ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "1000").strip())

# ── Strategie ─────────────────────────────────────────────────────────────────
FAST_MA       = 20
SLOW_MA       = 50
RSI_PERIOD    = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30

# ── Risk Management ───────────────────────────────────────────────────────────
RISK_PER_TRADE    = 0.02   # 2% des Kapitals pro Trade riskieren
STOP_LOSS_PCT     = 0.02   # Fallback-SL wenn kein ATR verfügbar
TAKE_PROFIT_PCT   = 0.04   # Fallback-TP
MAX_DAILY_LOSS_PCT = 0.06  # Circuit Breaker: 6% Tagesverlust
MAX_DRAWDOWN_PCT  = 0.20   # Permanenter Stopp bei 20% Gesamtverlust
MAX_OPEN_POSITIONS = 1

# ATR-basiertes Sizing (Tier 2)
USE_ATR_SIZING    = True
ATR_PERIOD        = 14
_ATR_MULTIPLIER_DEFAULT = {"15m": "2.5", "30m": "2.5"}.get(TIMEFRAME, "2.0")
ATR_MULTIPLIER    = float(os.getenv("ATR_MULTIPLIER", _ATR_MULTIPLIER_DEFAULT))

# Trailing Stop (Tier 2)
USE_TRAILING_STOP = True
TRAILING_STOP_PCT = 0.015  # Trailing-Stop 1.5% unterhalb Hochpunkt

# ── Backtest ──────────────────────────────────────────────────────────────────
BACKTEST_DAYS    = 365
SLIPPAGE_PCT     = 0.001   # 0.1% Slippage
TRADING_FEE_PCT  = 0.001   # 0.1% Binance Taker-Fee

# ── AI ────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")

# "rules" | "ml" | "claude" | "combined"
AI_MODE     = os.getenv("AI_MODE", "combined")
# "claude" | "openai" | "gemini" | "groq" | "ollama"
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude")
# Leer = Provider-Standard (z.B. claude-opus-4-6, gpt-4o-mini, llama-3.3-70b-versatile)
AI_MODEL    = os.getenv("AI_MODEL", "")
ML_MODEL_PATH     = CRYPTO_BOT_DIR / "ai" / "model.joblib"
ML_TRAIN_DAYS      = int(os.getenv("ML_TRAIN_DAYS", "730"))
ML_LOOKAHEAD       = int(os.getenv("ML_LOOKAHEAD", "6"))
ML_MIN_CONFIDENCE  = float(os.getenv("ML_MIN_CONFIDENCE", "0.55"))
# Label-Threshold: 1.5% (1h) → 0.8% (15m) für ausgeglichene BUY/SELL/HOLD-Verteilung
ML_LABEL_THRESHOLD = float(os.getenv("ML_LABEL_THRESHOLD", "0.015"))
# Auto-Retraining: Modell neu trainieren wenn F1 unter Schwelle fällt
ML_MIN_F1_LIVE           = 0.38
ML_RETRAIN_AFTER_TRADES  = 50   # Nach 50 Live-Trades Accuracy prüfen
ML_RETRAIN_INTERVAL_DAYS = 7    # Zeitbasiert: wöchentlich prüfen wenn F1 < Schwelle

# ── Short-Selling (Perpetual Futures / Paper-Shorts) ─────────────────────────
# ALLOW_SHORT=true: Bot kann Short-Positionen eingehen (BEAR_TREND + SIDEWAYS Mean Reversion)
# Paper-Modus: simuliert Short lokal
# Live-Modus: erfordert USDT-M Futures API-Keys (separate von Spot-Keys)
ALLOW_SHORT = os.getenv("ALLOW_SHORT", "true").strip().lower() in ("1", "true", "yes")

# ── Leverage (optional, nur Futures) ─────────────────────────────────────────
# LEVERAGE=1 = Spot-Modus (Standard), >1 nur für Futures-Konto
LEVERAGE              = int(os.getenv("LEVERAGE", "1").strip())
MAX_LEVERAGE          = 3      # Sicherheitsgrenze — niemals höher

# ── Risk Personality Modes ────────────────────────────────────────────────────
# conservative: kleines Risiko, enger Drawdown-Stopp
# balanced:     Standard (2% / 20%)
# aggressive:   höheres Risiko, weiterer Drawdown-Stopp
_raw_risk_mode = os.getenv("RISK_MODE", "balanced").strip().lower()
RISK_MODE = _raw_risk_mode if _raw_risk_mode in ("conservative", "balanced", "aggressive") else "balanced"

RISK_MODE_PARAMS = {
    "conservative": {"risk_factor": 0.5,  "drawdown_limit": 0.10, "daily_loss_limit": 0.03},
    "balanced":     {"risk_factor": 1.0,  "drawdown_limit": 0.20, "daily_loss_limit": 0.06},
    "aggressive":   {"risk_factor": 1.5,  "drawdown_limit": 0.30, "daily_loss_limit": 0.09},
}

# ── Trade Cooldown & Protection ───────────────────────────────────────────────
TRADE_COOLDOWN_MINUTES = int(os.getenv("TRADE_COOLDOWN_MINUTES", "60"))  # Pause nach Verlust-Trade
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))   # SL-Guard: Blockade nach N Verlusten

# ── Execution (Tier 3) ────────────────────────────────────────────────────────
USE_LIMIT_ORDERS     = True    # Limit statt Market Orders (weniger Slippage)
LIMIT_ORDER_OFFSET   = 0.001   # 0.1% über/unter Marktpreis für schnelle Füllung
LIMIT_ORDER_TIMEOUT  = 45      # Sekunden bis Fallback auf Market Order

# ── Multi-Asset Scanning & Trading ───────────────────────────────────────────
SCANNER_INTERVAL_HOURS = 24   # Pair-Scanner alle N Stunden ausführen

# Multi-Asset Live Trading (FEATURE_MULTI_PAIR=true)
# MULTI_PAIR_SYMBOLS: kommagetrennte Liste fixer Paare (überschreibt Auto-Selektion)
#   Beispiel: BTC/USDT,ETH/USDT,SOL/USDT
# MULTI_PAIR_COUNT: Anzahl Paare wenn Auto-Selektion aktiv (1–5 empfohlen)
# MULTI_PAIR_MIN_VOLUME: Mindest-Tagesvolumen in USDT für Auto-Selektion
_multi_symbols_raw = os.getenv("MULTI_PAIR_SYMBOLS", "").strip()
MULTI_PAIR_SYMBOLS: list[str] = (
    [s.strip() for s in _multi_symbols_raw.split(",") if s.strip()]
    if _multi_symbols_raw else []
)
MULTI_PAIR_COUNT      = int(os.getenv("MULTI_PAIR_COUNT",      "3"))
MULTI_PAIR_MIN_VOLUME = float(os.getenv("MULTI_PAIR_MIN_VOLUME", "50000000"))  # 50M USDT

# ── Persistenz ────────────────────────────────────────────────────────────────
DB_PATH        = BASE_DIR / "data_store" / "trades.db"
LOG_DIR        = BASE_DIR / "logs"
LOG_LEVEL      = os.getenv("LOG_LEVEL", "INFO").strip().upper()
PDF_REPORT_DIR = BASE_DIR / "reports"

# ── Alerting: Telegram ────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Alerting: Discord + Generic Webhook ──────────────────────────────────────
# FEATURE_DISCORD_RPC=true  →  Discord Webhook aktivieren
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
# FEATURE_WEBHOOK_RPC=true  →  Generic HTTP Webhook aktivieren
WEBHOOK_URL    = os.getenv("WEBHOOK_URL",    "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")   # optional: Bearer-Token

# ── Strategy ──────────────────────────────────────────────────────────────────
# Leer = interne ML+Regime-Logik, gesetzt = IStrategy-Subklasse laden
# STRATEGY=MACrossStrategy | RSIBBStrategy | <CustomKlassenname>
STRATEGY      = os.getenv("STRATEGY",       "")
STRATEGY_PATH = os.getenv("STRATEGY_PATH",  "")  # optionaler Dateipfad

# ── ML Model Type ─────────────────────────────────────────────────────────────
# xgboost (Standard, CPU-optimiert) | lightgbm (schneller auf CPU, weniger RAM)
ML_MODEL_TYPE = os.getenv("ML_MODEL_TYPE", "xgboost").strip().lower()

# ── Hyperopt Loss Function ────────────────────────────────────────────────────
# sharpe | sortino | calmar | profit_drawdown | only_profit | multi_metric
HYPEROPT_LOSS = os.getenv("HYPEROPT_LOSS", "multi_metric").strip().lower()
