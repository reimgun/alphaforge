# Configuration

[🇩🇪 Deutsch](../de/CONFIG.md)

---

All settings are configured in the `.env` file.  
The complete list with default values is in `config/settings.py`.

## Key settings

```env
# Trading mode: paper (virtual) or live (real money)
TRADING_MODE=paper

# Starting capital in USDT
INITIAL_CAPITAL=1000

# AI mode (see below)
AI_MODE=ml

# Binance API (only needed for live trading)
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Anthropic API (only for AI_MODE=claude or combined)
ANTHROPIC_API_KEY=

# Telegram notifications (optional)
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Dashboard API key (optional — protects POST endpoints)
DASHBOARD_API_KEY=

# Leverage: 1 = Spot (default), 2–3 = Futures (max 3x)
LEVERAGE=1
```

---

## AI modes

| Mode | Description | Recommended |
|------|-------------|-------------|
| `rules` | Classic MA crossover strategy | Debugging / quick test |
| `ml` | XGBoost + LSTM ensemble | Default — no API key needed |
| `claude` | Claude AI only | If no ML model available |
| `combined` | ML/LSTM + Claude must agree | Highest precision |
| `rl` | Reinforcement Learning agent | Experimental |

---

## Risk management

| Variable | Default | Description |
|----------|---------|-------------|
| `RISK_PER_TRADE` | `0.02` | Risk 2% of capital per trade |
| `MAX_DAILY_LOSS_PCT` | `0.06` | Circuit breaker at 6% daily loss |
| `MAX_DRAWDOWN_PCT` | `0.20` | Permanent stop at 20% total drawdown |
| `USE_ATR_SIZING` | `True` | Volatility-based stop-loss |
| `USE_TRAILING_STOP` | `True` | Stop-loss trails automatically |
| `ATR_MULTIPLIER` | `2.0` | Stop distance in ATR units |
| `TRAILING_STOP_PCT` | `0.015` | Trailing stop 1.5% below high |

### Risk personality mode

```env
RISK_MODE=balanced      # Default (2%/trade, 20% max drawdown)
RISK_MODE=conservative  # Low risk (1%/trade, 10% max drawdown)
RISK_MODE=aggressive    # Higher risk (3%/trade, 30% max drawdown)
```

Changeable at runtime via Telegram `/set_mode` or dashboard — no restart needed.

### Leverage (futures only)

```env
LEVERAGE=1    # Spot — no leverage (default)
LEVERAGE=2    # 2x leverage
LEVERAGE=3    # 3x leverage — maximum (internally capped)
```

---

## Strategy parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `SYMBOL` | `BTC/USDT` | Trading pair |
| `TIMEFRAME` | `1h` | Entry timeframe |
| `TREND_TIMEFRAME` | `4h` | Higher timeframe trend filter |
| `ML_MIN_CONFIDENCE` | `0.60` | Minimum ML confidence for trade |

---

## ML parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `ML_TRAIN_DAYS` | `730` | Training data in days (2 years) |
| `ML_LOOKAHEAD` | `6` | Lookahead for label generation (6 hours) |
| `ML_MIN_F1_LIVE` | `0.38` | Minimum F1 score in live operation |
| `ML_RETRAIN_AFTER_TRADES` | `50` | Auto-retraining after N live trades |
| `ML_RETRAIN_INTERVAL_DAYS` | `7` | Time-based retraining if F1 < threshold |

---

## Auto Paper→Live transition

The bot automatically switches to live when all thresholds are exceeded.

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_PAPER_TRADES` | `20` | Minimum number of paper trades |
| `MIN_SHARPE` | `0.8` | Minimum Sharpe ratio |
| `MIN_WIN_RATE_PCT` | `48.0` | Minimum win rate % |
| `MAX_ALLOWED_DRAWDOWN` | `15.0` | Maximum drawdown % |
| `MIN_MODEL_F1` | `0.38` | Minimum model F1 score |

**Import historical data:**
```bash
make import-history          # Import 365 days of backtest data
make import-history DAYS=90  # Only 90 days
make import-history-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## Feature flags

All features can be turned on or off via `.env`. **Default: all active.**

```env
# Resource-saving operation (e.g. for weak hardware):
FEATURE_PDF_REPORTS=false
FEATURE_OPPORTUNITY_RADAR=false
FEATURE_REGIME_FORECASTER=false
FEATURE_LSTM=false              # Important for QNAP (no AVX2)

# Forex bot: single flag that disables all compute-intensive features at once:
FOREX_LEAN_MODE=true            # Disables LSTM, Monte Carlo, Portfolio Optimizer, Entry Timer

# All available flags:
FEATURE_ONLINE_LEARNING=true
FEATURE_EXPLAINABILITY=true
FEATURE_PORTFOLIO_OPTIMIZER=true
FEATURE_TAIL_RISK=true
FEATURE_MICROSTRUCTURE=true
FEATURE_DERIVATIVES_SIGNALS=true
FEATURE_CROSS_MARKET=true
FEATURE_REGIME_FORECASTER=true
FEATURE_GROWTH_OPTIMIZER=true
FEATURE_GLOBAL_EXPOSURE=true
FEATURE_STRATEGY_TRACKER=true
FEATURE_SCANNER=true
```

Check status:
```bash
python -c "from config import features; print(features.summary())"
```

---

## Log level

```env
LOG_LEVEL=INFO     # Normal operation
LOG_LEVEL=DEBUG    # All details (for troubleshooting)
LOG_LEVEL=WARNING  # Warnings and errors only
```

The log level can also be changed at runtime in the web dashboard (sidebar).

---

## Encrypted configuration (server)

```bash
# Encrypt once (creates .env.enc + .env.key)
python -m config.crypto_config --encrypt

# Check status
python -m config.crypto_config --check
```

The encrypted `.env.enc` can go into the repository — `.env.key` **never**.
