# FAQ — Frequently Asked Questions

[🇩🇪 Deutsch](../de/FAQ.md)

---

## Installation

**`python: command not found`**  
Try `python3` instead of `python`. On some systems:
```bash
python3 -m ai.trainer
```

**`make: command not found` (Windows)**  
Install Make for Windows: [gnuwin32.sourceforge.net](https://gnuwin32.sourceforge.net/packages/make.htm)  
Or run commands directly:
```
.venv\Scripts\python bot.py
.venv\Scripts\python -m ai.trainer
```

**Package installation fails**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**XGBoost: `libxgboost.dylib could not be loaded` (macOS)**
```bash
brew install libomp
```

**`torch` installation too large**  
CPU-only version is smaller (~200 MB vs ~1 GB):
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

---

## Bot makes no trades

This is usually normal behavior. Possible reasons:

| Cause | Solution |
|-------|----------|
| **Regime BEAR_TREND** | Bot protects capital — no long trades allowed |
| **4h trend NEUTRAL** | Sideways market — bot waits for clear direction |
| **ML confidence too low** | Normal in uncertain markets |
| **ML + Claude disagree** | In `combined` mode, only trades when both agree |
| **Circuit breaker active** | 6% daily loss reached — resets tomorrow |
| **Volume collapse** | Too little trading volume → liquidity issue |
| **Tail-risk detected** | Market anomaly → bot waits |

```bash
# See reasons for HOLDs
make logs
# or
make diagnose
```

---

## Model problems

**"No trained model found"**
```bash
make train
```

**Training fails**
```bash
# Check internet connection (downloads data from Binance)
make train
```

**ML model too old / poor performance**
```bash
make train
```

**LSTM not available**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```
The bot also works without LSTM — XGBoost always runs.

---

## Web Dashboard

**Dashboard shows "API not reachable"**
```bash
# Start API backend first:
make dashboard-api   # Terminal 1
make dashboard       # Terminal 2
```

**Dashboard not updating**  
Click the "🔄 Manual refresh" button or adjust the refresh interval in the sidebar.

**Port 8000 or 8501 already in use**
```bash
.venv/bin/uvicorn dashboard.api:app --port 8001
.venv/bin/streamlit run dashboard/app.py --server.port 8502
```

---

## Telegram not working

1. Check token and chat ID in `.env`
2. Send your bot a message once (required the first time)
3. Run `make check`

---

## Binance API errors

**"Rate Limit"** — The bot has automatic retry, this is temporary.

**"Invalid API Key"** — Check API key in `.env`, no spaces.

**"IP not whitelisted"** — Add your IP in Binance API settings or disable IP restriction.

---

## Paper Trading vs. Live

**Do I need API keys for Paper Trading?**  
No. Paper Trading works without any API keys.

**When does the bot automatically switch to Live?**  
When all 5 criteria are met (≥20 trades, win rate ≥48%, Sharpe ≥0.8, drawdown ≤15%, F1 ≥0.38). You receive a Telegram message and must confirm with `/approve_live`.

**Paper Trading results are better than live — why?**  
Paper Trading: exact prices, no slippage. Live Trading: slippage, fees, partial fills.  
The backtest already accounts for slippage (0.1%) and fees (0.1%).

---

## Performance questions

**What return can I expect?**  
That depends on the market and cannot be predicted.  
Run `make backtest` + `make monte-carlo` to see historical results.

**Bot is losing money — what to do?**
1. `make logs` — analyze trades
2. `make backtest` — test strategy on current data
3. Increase `ML_MIN_CONFIDENCE` in `.env` (fewer but safer trades)
4. Set `TRADING_MODE=paper` in `.env` — back to simulation
5. `/switch_safe_mode` in Telegram — halve position size

**Can the bot lose everything?**  
No — the circuit breaker (6% daily loss) and max drawdown stop (20%) prevent this. The bot stops automatically.
