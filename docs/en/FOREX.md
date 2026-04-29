# Forex Bot — Step-by-Step Guide

[🇩🇪 Deutsch](../de/FOREX.md)

---

> **For beginners:** This guide walks you through every step from an empty laptop to a running bot.  
> No prior knowledge of Forex or trading required.

---

## Table of Contents

1. [What the bot does](#1-what-the-bot-does)
2. [What do H1, H4, M5 etc. mean?](#2-what-do-h1-h4-m5-etc-mean)
3. [Create an OANDA account](#3-create-an-oanda-account)
4. [Create a Telegram bot](#4-create-a-telegram-bot)
5. [Install the bot](#5-install-the-bot)
6. [Start the bot](#6-start-the-bot)
7. [What happens now? — The cycle explained](#7-what-happens-now--the-cycle-explained)
8. [Train the ML model](#8-train-the-ml-model)
9. [Run a backtest](#9-run-a-backtest)
10. [The three phases: Paper → Practice → Live](#10-the-three-phases-paper--practice--live)
11. [Telegram commands](#11-telegram-commands)
12. [Risk modes: conservative / balanced / aggressive](#12-risk-modes)
13. [All features at a glance](#13-all-features-at-a-glance)
14. [QNAP deployment](#14-qnap-deployment)
15. [Configuration reference](#15-configuration-reference)
16. [Frequently asked questions](#16-frequently-asked-questions)

---

## 1. What the bot does

The Forex bot trades **currency pairs** (e.g. EUR/USD) fully automatically — 24/5, without any manual input.

**What it specifically does:**
- Reads hourly price data from OANDA (free practice account)
- Calculates technical indicators (EMA, MACD, RSI)
- Decides: Buy / Sell / Do nothing
- Checks 10 safety filters before opening any trade
- Automatically sets stop-loss and take-profit
- Trails the stop-loss as price moves in your favour
- Sends you messages via Telegram

**What it does NOT do:**
- It does not guarantee profits — trading always carries risk
- It cannot run without your practice account

---

## 2. What do H1, H4, M5 etc. mean?

In trading charts, prices are displayed as candles — each candle shows the price movement over a specific time period.  
The abbreviations tell you how long that period is:

| Code | Meaning | One candle shows |
|------|---------|-----------------|
| **M1** | 1 Minute | 1 min price movement |
| **M5** | 5 Minutes | 5 min price movement |
| **M15** | 15 Minutes | 15 min price movement |
| **M30** | 30 Minutes | 30 min price movement |
| **H1** | 1 Hour | 1 hour price movement |
| **H4** | 4 Hours | 4 hour price movement |
| **D1** | 1 Day (Daily) | 1 day price movement |
| **W1** | 1 Week (Weekly) | 1 week price movement |
| **MN** | 1 Month | 1 month price movement |

**How this bot uses timeframes:**

```
H1  → Primary timeframe
      The bot wakes up every hour, analyses H1 candles and
      decides: buy / sell / do nothing.

H4  → Trend confirmation (Multi-Timeframe, MTF)
      Before an H1 signal fires: does the 4h trend agree?
      H1 says BUY, but H4 trend is DOWN → signal is weakened.

D1  → Macro trend
      The big market direction. The bot won't trade against
      the D1 trend when the MTF feature is enabled.
```

**Rules of thumb:**
- **Smaller timeframe** (M1, M5) = more signals, more noise, more server power needed
- **Larger timeframe** (H4, D1) = fewer signals, cleaner trends, fewer false signals
- **H1** is ideal for a 24/7 bot on QNAP — enough signals, not overwhelming

---

## 3. Choose a broker

The bot supports four brokers — pick whichever works for you.  
Set `FOREX_BROKER` in your `.env` file accordingly.

| Broker | `FOREX_BROKER=` | Free Demo | Notes |
|--------|----------------|-----------|-------|
| **OANDA** | `oanda` | ✅ | Default — REST API, good for beginners |
| **Capital.com** | `capital` | ✅ | CFD, no commission, simple setup |
| **IG Group** | `ig` | ✅ | CFD, regulated DE/AT/CH |
| **Interactive Brokers** | `ibkr` | ✅ | Most professional — requires IB Gateway desktop app |

---

### OANDA setup

OANDA is the default broker. Completely free, no real money needed for practice.

#### Step 1 — Register

1. Go to [oanda.com](https://www.oanda.com)
2. Click **"Try Demo"** or **"Get started"** in the top right
3. Fill in the form (name, email, password)
4. Confirm your email

#### Step 2 — Create an API key

After logging in:

1. Click your **name** in the top right → **"My Account"**
2. In the left menu: **"API Access"**
3. Click **"Generate API Key"**
4. Copy the key — you only see it once! Save it immediately.

#### Step 3 — Find your account ID

1. Top right: **Name** → **"My Account"**
2. **"Summary"** → **"Account Details"**
3. Note your **Account Number** — format: `101-001-12345678-001`

---

### Capital.com setup

1. Register at capital.com → **"Open Demo Account"** — free
2. Go to **My Profile** → **Generate API Key**
3. In `.env`:

```env
FOREX_BROKER=capital
CAPITAL_API_KEY=your-key
CAPITAL_EMAIL=your@email.com
CAPITAL_PASSWORD=your-password
CAPITAL_ENV=demo    # demo | live
```

---

### IG Group setup

1. Register at ig.com → **"Demo Account"** — free
2. Go to **My Account** → **API Key**
3. In `.env`:

```env
FOREX_BROKER=ig
IG_API_KEY=your-key
IG_USERNAME=your-username
IG_PASSWORD=your-password
IG_ENV=demo    # demo | live
```

---

### Interactive Brokers (IBKR) setup

IBKR requires the **IB Gateway** desktop app running on the same machine.

1. Download IB Gateway: [ibkr.com/trader-workstation](https://www.ibkr.com/trader-workstation)
2. Enable API: Edit → Global Configuration → API → Settings → "Enable ActiveX and Socket Clients"
3. Install the Python library: `pip install ib_insync`
4. In `.env`:

```env
FOREX_BROKER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7497    # 7497=TWS Paper, 7496=TWS Live, 4002=GW Paper, 4001=GW Live
IBKR_CLIENT_ID=1
IBKR_ACCOUNT=     # leave empty = first account found
```

> **Note:** IBKR requires IB Gateway to be running before the bot starts.

---

## 4. Create a Telegram bot

You need your **own** Telegram bot (separate from the crypto bot if you have one).

### Step 1 — Create the bot

1. Open Telegram and search for **@BotFather**
2. Type `/newbot`
3. BotFather asks for a name → e.g. `My Forex Bot`
4. BotFather asks for a username → e.g. `my_forex_bot` (must end in `_bot`)
5. You receive a **token** — looks like: `1234567890:ABCdefGHIjklMNOpqrSTUvwxyz`
6. Copy the token

### Step 2 — Find your chat ID

1. Search for your new bot in Telegram and start it with `/start`
2. Open in your browser: `https://api.telegram.org/bot<YOUR-TOKEN>/getUpdates`
   (replace `<YOUR-TOKEN>` with the token from step 1)
3. You'll see JSON text — search for `"chat":{"id":` → the number after that is your chat ID
4. Note the chat ID (e.g. `123456789`)

---

## 5. Install the bot

### Step 1 — Open the project directory

```bash
cd trading_bot    # if you already have the project
```

### Step 2 — Install Python dependencies

```bash
pip install -r forex_bot/requirements.txt
```

This installs: pandas, numpy, requests, fastapi, xgboost, arch (GARCH) and more.

> On the QNAP this happens automatically during `make qnap-deploy`.

### Step 3 — Create the .env file

```bash
cp forex_bot/.env.example forex_bot/.env
```

Open `forex_bot/.env` in a text editor and fill in these values:

```env
# ── Broker choice ───────────────────────────────────────────────────────────
FOREX_BROKER=oanda                     # oanda | capital | ig | ibkr

# ── OANDA ──────────────────────────────────────────────────────────────────
OANDA_API_KEY=your-api-key-from-step-2
OANDA_ACCOUNT_ID=101-001-12345678-001
OANDA_ENV=practice                     # ALWAYS start with practice!

# ── Trading ────────────────────────────────────────────────────────────────
FOREX_TRADING_MODE=paper               # paper = no real money, simulation only
FOREX_INITIAL_CAPITAL=10000            # starting capital for simulation

# ── Telegram ───────────────────────────────────────────────────────────────
FOREX_TELEGRAM_TOKEN=your-token-from-step-3
FOREX_TELEGRAM_CHAT_ID=your-chat-id

# ── Everything else can stay as-is ─────────────────────────────────────────
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY
FOREX_TIMEFRAME=H1
FOREX_RISK_PER_TRADE=0.01
FOREX_MAX_DRAWDOWN=0.15
FOREX_MAX_OPEN_TRADES=3
```

> **Important:** `FOREX_TRADING_MODE=paper` means: the bot calculates everything but does not actually trade. Perfect for testing.

---

## 6. Start the bot

```bash
python -m forex_bot.bot
```

You'll see in the terminal:

```
============================================================
Forex Bot starting — Mode: PAPER
Risk Mode: BALANCED
Instruments: EUR_USD, GBP_USD, USD_JPY
OANDA: practice
============================================================
[INFO] No ML model found — running rule-based only
[INFO] Dashboard API running on port 8001
[INFO] Forex Telegram Bot started
[INFO] ── Cycle 2025-01-01 10:00 UTC — mode=balanced ──
[INFO] EUR_USD: no signal — skip
[INFO] GBP_USD: no signal — skip
[INFO] USD_JPY: no signal — skip
```

This is **normal**! The bot checks every hour. Most of the time there's no signal.  
When a trade opens, you'll get a Telegram message.

### Open the dashboard

```bash
# In a second terminal:
streamlit run dashboard/app.py
```

Open in your browser: **http://localhost:8501**  
Click **💱 Forex** at the top to view the Forex bot.

---

## 7. What happens now? — The cycle explained

**Every hour** the bot runs through these checks — top to bottom:

```
HOUR 1: Midnight? → Reset daily tracking
         Trail stop-losses on open trades

STOP CHECKS (if any trigger → skip this hour):
  ⬜ Daily loss limit reached? (e.g. -2% today)
  ⬜ Too many consecutive losses? (e.g. 3 in a row)
  ⬜ Outside trading session? (7:00–20:00 UTC)
  ⬜ Major macro event coming up?
     → FOMC (Fed rate decision): 24h blackout
     → ECB: 12h blackout
     → US jobs report (NFP): 4h blackout
  ⬜ High-impact news within ±30 minutes?
  ⬜ Circuit breaker (total loss > 15%)?
  ⬜ Already 3 open trades?

PER CURRENCY PAIR (EUR_USD, GBP_USD, USD_JPY):
  ⬜ Spread too wide? (broker charging too much)
  ⬜ Spread shock? (suddenly 2.5× normal)
  ⬜ Market regime: SIDEWAYS or HIGH_VOLATILITY? → skip
  ⬜ Signal: BUY / SELL / HOLD?  → no signal → skip
  ⬜ Against macro context? (e.g. Risk-OFF, USD short)
  ⬜ Volatility too high? (GARCH forecast)
  ⬜ Trend persistence → adjust confidence
  ⬜ ML model disagrees? → reduce confidence
  ⬜ Confidence below minimum (65%)?
  ⬜ H4 + D1 confirm the trade?
  ⬜ Too many correlated positions?
  ⬜ Too many USD positions in one direction?
  ⬜ Overnight swap cost too high?
  ⬜ Black Swan detected? (>3σ move, flash crash, 2+ pairs affected)
  ⬜ Regime change imminent? (>60% transition probability → warning)

  ✅ ALL CHECKS PASSED → prepare trade
     M15 Entry Timer: waits for pullback to EMA20 on M15
       → refined entry typically 1–5 pips better
     Signal strength: IV modifier × CB sentiment × portfolio weight
     Position sizing: 1% × drawdown × portfolio weight × IV factor × CB factor
     Stop-loss: ATR × regime multiplier (1.5–3.0×)
     Take-profit: RR ratio × regime (1.5:1 to 2.5:1)
  ✅ TRADE OPEN — active monitoring:
     Trailing TP: activated when ADX>35 + profit>50% of TP distance
       → SL moves to breakeven; TP trails with ATR×1.5
     Regime change warning: closes position if change >75% likely
```

**That sounds like a lot — and it is.** That's why on a typical day there are usually only 0–2 trades. This is intentional.

---

## 8. Train the ML model

The ML model is **optional** — the bot trades without it, just slightly less precisely.

### When to train?

- **Before your first real deployment** is recommended
- Requires: active OANDA connection + ~2–5 minutes

### How to train?

```bash
python -m forex_bot.ai.trainer
```

With more data (recommended):

```bash
python -m forex_bot.ai.trainer --instrument EUR_USD --candles 5000
```

You'll see:

```
Fetching 5000 H1 candles for EUR_USD...
Fetched: H1=4998 H4=1248 D1=312 candles
Feature matrix shape: (4798, 18)

  Fold 1: val F1=0.3821
  Fold 2: val F1=0.4012
  Fold 3: val F1=0.3956
  Fold 4: val F1=0.4103
  Fold 5: val F1=0.3889
Mean CV F1: 0.3956

              precision  recall  f1-score  support
HOLD               0.73    0.82      0.77     3810
BUY                0.41    0.35      0.38      512
SELL               0.39    0.33      0.36      476

Model saved: forex_bot/ai/model.joblib
```

### What do these numbers mean?

| Value | What it means | Good if |
|-------|---------------|---------|
| **F1-Score** | How well the model identifies BUY/SELL | > 0.35 |
| **Precision** | When the model says BUY: how often is it right? | > 0.40 |
| **Recall** | How many real BUY signals does it catch? | > 0.30 |

> An F1 of 0.35–0.45 is **realistic and good** for Forex. Forex is inherently hard to predict.  
> The model doesn't need to be perfect — it just refines the confidence estimation.

### What happens to the model?

After training:
- Model is saved to `forex_bot/ai/model.joblib`
- The bot loads it automatically on the next start
- After every **50 closed trades**, the bot retrains it automatically (background thread)

### Train the LSTM model (deeper learning, optional)

The LSTM model learns patterns in time series — often better than XGBoost in trending markets.
Requires PyTorch (`pip install torch`):

```bash
python -m forex_bot.ai.lstm_trainer --epochs 15 --instruments EUR_USD GBP_USD USD_JPY
```

Training runs on the last ~2,000 H1 candles per pair and takes about 5–10 minutes.
The model is saved to `forex_bot/ai/lstm_model.pth` and used automatically by the bot.

> Do **not** run on QNAP (no AVX2). Train on a PC and transfer via SCP.

### Train the RL agent (experimental)

The Reinforcement Learning agent learns from closed trades which actions work best in which
market conditions. Requires at least 20 closed trades in the database:

```bash
python -m forex_bot.ai.rl_trainer --episodes 200 --n-trades 500
```

The Q-table is saved to `forex_bot/ai/rl_qtable.json`.
Activation: set `FOREX_AI_MODE=rl` in `forex_bot/.env`.

### Training for multiple pairs?

Run training once per pair you want to trade — pass multiple instruments with `--instruments`.
The XGBoost model trains on all pairs jointly; the LSTM model trains per pair separately.

---

## 9. Run a backtest

A backtest simulates the bot on historical data — **before** you risk any real money.

### Single pair:

```bash
python -m forex_bot.backtest.backtester --instrument EUR_USD --candles 2000 --mode balanced
```

Output:

```
──────────────────────────────────────────────────
  FOREX BACKTEST REPORT
──────────────────────────────────────────────────
  Instrument:    EUR_USD
  Risk Mode:     balanced
  Candles used:  1998
  Spread:        0.8 pips
──────────────────────────────────────────────────
  Trades:        47
  Win Rate:      55.3%
  Total Pips:    +183.4
  Sharpe Ratio:  0.82
  Max Drawdown:  8.4%
  Profit Factor: 1.43

  Month      Trades      Pips   WinRate
  ──────── ─────── ───────── ─────────
  2024-06        8    +42.1      62.5%
  2024-07       11    +67.3      63.6%
  2024-08        9    +28.8      44.4%
  ...
```

### All pairs at once (robustness test):

```bash
python -m forex_bot.backtest.backtester --multi --candles 2000
```

Output:

```
  MULTI-PAIR BACKTEST REPORT
  Pairs tested:    3
  Profitable pairs:3
  Robustness:      100%     ← all 3 pairs profitable
  Avg Win Rate:    53.7%
  Avg Sharpe:      0.74

  Pair         Trades      WR%       Pips   Sharpe
  ──────────── ─────── ──────── ──────── ────────
  EUR_USD           47    55.3%   +183.4     0.82
  GBP_USD           39    51.3%   +122.7     0.68
  USD_JPY           52    54.2%   +198.1     0.71
```

> The report is also saved as JSON: `forex_bot/reports/backtest_YYYYMMDD_HHMMSS.json`

### What the numbers mean:

| Metric | Meaning | Target |
|--------|---------|--------|
| **Win Rate** | Percentage of winning trades | > 45% |
| **Total Pips** | Sum of all pip gains/losses | > 0 |
| **Sharpe Ratio** | Risk-adjusted return | > 0.5 |
| **Max Drawdown** | Largest drop from peak | < 15% |
| **Profit Factor** | Gross profit / gross loss | > 1.2 |
| **Robustness** | % of pairs that are profitable | > 67% |

---

## 10. The three phases: Paper → Practice → Live

The bot protects you with a **3-phase system**. You cannot jump straight to real money.

```
Phase 1: PAPER TRADING
  ├─ FOREX_TRADING_MODE=paper
  ├─ Bot simulates trades, no real money
  ├─ Goal: meet the criteria below
  └─ Duration: typically 2–4 weeks

Phase 2: OANDA PRACTICE
  ├─ FOREX_TRADING_MODE=paper + OANDA_ENV=practice
  ├─ Real OANDA market prices, but fake money
  ├─ Check that results match paper trading
  └─ Duration: another 2–4 weeks recommended

Phase 3: OANDA LIVE
  ├─ FOREX_TRADING_MODE=live + OANDA_ENV=live
  ├─ Real money — ONLY after /approve_live gives ✅
  └─ Start with a small amount (e.g. $1,000)
```

### When am I ready for phase 3?

The bot checks this automatically. Type `/progress` in Telegram:

```
📊 Phase Progress

✅ Trades:       23/20 (min. 20 required)
✅ Win Rate:     52.3% (min. 45%)
✅ Sharpe Ratio: 0.67 (min. 0.5)
✅ Max Drawdown: 8.2% (max. 15%)
✅ ML F1 Score:  0.38 (min. 0.35)

✅ ALL CRITERIA MET
Ready for OANDA Live. /approve_live to confirm.
```

If not all are met:

```
❌ Trades:  12/20 (8 more needed)
❌ Sharpe:  0.23 (min. 0.5)
✅ Win Rate: 55.0%
...

Not ready yet. Continue in paper mode.
```

### Pre-live check (automated go/no-go)

Before switching to live, this script checks **all criteria automatically**:

```bash
python forex_bot/scripts/pre_live_check.py
```

Output:

```
══════════════════════════════════════════════════
   Forex Bot — Pre-Live Deployment Check
══════════════════════════════════════════════════

  Check                               Result               Status
  ─────────────────────────────────── ──────────────────── ──────
  ✓ Paper trades present              34 (min 30)          [PASS]
  ✓ Sharpe ratio (annualised)         0.634 (min 0.50)     [PASS]
  ✓ Win rate                          51.5% (min 40%)      [PASS]
  ✓ Max drawdown                      6.1% (max 8%)        [PASS]
  ✓ ML model F1                       0.4112 (min 0.40)    [PASS]
  ✓ Profit factor                     1.247 (min 1.10)     [PASS]
  ✓ Emergency exit inactive           inactive             [PASS]
  ✓ Regime robustness (WR >= 30%)     OK (TREND_UP: 58%)   [PASS]
  ✓ Macro-event resilience            4 events WR=75%      [PASS]

  ✓ READY — Bot can be activated for live trading
```

With stricter criteria (`--strict`) or a custom minimum trade count:

```bash
python forex_bot/scripts/pre_live_check.py --strict --min-trades 50
python forex_bot/scripts/pre_live_check.py --json    # CI/CD-compatible output
```

### Grant live approval

```
/approve_live
```

When all criteria are met:

```
✅ Live trading approved!
All 5 criteria met.
Set FOREX_TRADING_MODE=live in .env
and restart the bot.
```

Then in `forex_bot/.env`:

```env
FOREX_TRADING_MODE=live
OANDA_ENV=live
```

Restart the bot:

```bash
python -m forex_bot.bot
```

> **Important:** The bot **never switches to live automatically**. Only you do that.

---

## 11. Telegram commands

| Command | What it does |
|---------|-------------|
| `/status` | Current capital, open trades, daily PnL, risk mode |
| `/trades` | Last 5 closed trades |
| `/news` | Today's high-impact news events |
| `/performance` | Win rate, total pips, PnL of all trades |
| `/regime` | Current market regime per pair (Trend / Sideways / Volatile) |
| `/macro` | Macro context: USD index, VIX, interest rates, carry signals |
| `/correlations` | Correlation check of open positions |
| `/set_mode balanced` | Set risk mode to balanced |
| `/set_mode conservative` | Cautious mode (half position size) |
| `/set_mode aggressive` | Aggressive mode (double position size) |
| `/progress` | Progress towards phase transition criteria |
| `/approve_live` | Grant live trading approval (if criteria are met) |
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/help` | Show all commands |

---

## 12. Risk modes

You can switch the risk mode at any time — via Telegram or in `.env`.

| | 🛡️ Conservative | ⚖️ Balanced | ⚡ Aggressive |
|--|--|--|--|
| **Risk/trade** | 0.5% | 1.0% | 2.0% |
| **Max open trades** | 1 | 3 | 5 |
| **Min confidence** | 80% | 65% | 50% |
| **News pause** | 60 min | 30 min | 15 min |
| **Spread limit** | 1.5 pips | 3.0 pips | 5.0 pips |
| **Daily loss limit** | 1% | 2% | 4% |
| **Session restriction** | London/NY overlap only | No | No |
| **MTF confirmation** | H4 + D1 | H4 only | No |

> **Recommendation for beginners:** Start with `conservative`. After 50+ profitable trades switch to `balanced`.

### Auto-mode (Feature 2)

The bot can **automatically adjust** the mode:

- VIX > 25 or ATR > 0.12% or 3+ high-impact events → switches to `conservative`
- VIX < 15 and calm market → may switch to `aggressive`
- As soon as you use `/set_mode` → auto-mode is disabled until midnight

---

## 13. All features at a glance

### Core strategy & entry

| # | Feature | What it does |
|---|---------|-------------|
| 1 | **Macro signals** | DXY, VIX, interest rates → Risk-ON/OFF detection, carry filter |
| 2 | **Auto-mode** | Automatically adjusts risk mode to market conditions |
| 3 | **Drawdown recovery** | At -5% DD → half position size; at -10% → quarter |
| 4 | **Swap filter** | Blocks trades with high overnight holding costs |
| 5 | **GARCH volatility** | Forecasts extreme volatility → blocks trade |
| 6 | **Multi-pair backtest** | Tests all pairs simultaneously → robustness score |
| 7 | **Macro event lockdown** | FOMC 24h / ECB 12h / NFP+CPI 4h blackout before events |
| 8 | **Spread shock** | Blocks when spread suddenly spikes to 2.5× normal |
| 9 | **USD concentration** | Max 60% of trades in one USD direction |
| 10 | **Trend persistence** | ADX + candle counter → confidence ±25% |

### Precision entry & trade management

| # | Feature | What it does |
|---|---------|-------------|
| 11 | **M15 Entry Timer** | Waits for M15 pullback to EMA20 → typically 1–5 pips better entry |
| 12 | **Trailing Take-Profit** | ADX>35 + 50% profit → TP trails with ATR×1.5, SL moves to breakeven |
| 13 | **Regime change warning** | >60% transition probability → warning; >75% → automatic close |

### Institutional signal filters

| # | Feature | What it does |
|---|---------|-------------|
| 14 | **Options IV proxy** | ETF-based volatility (FXE/FXB/FXY): high IV → 0.85× position, low IV → 1.10× |
| 15 | **Central bank sentiment** | Fed/ECB/BOE/BOJ RSS → hawkish/dovish score → ±8% confidence modifier |
| 16 | **Macro pair selector** | Risk-OFF: prefers USD_JPY/USD_CHF; Risk-ON: activates AUD_USD/GBP_USD |
| 17 | **Markowitz portfolio optimizer** | Sharpe-maximising weighting per currency pair — better diversification |

### Risk protection

| # | Feature | What it does |
|---|---------|-------------|
| 18 | **Black Swan detector** | >3σ move, flash crash (>2% in 1 candle) or 2+ pairs affected → 1h pause |
| 19 | **Stress tester** | 5 scenarios: spread×5, flash crash -3%, gap ±2%, trending DD, Black Thursday |
| 20 | **Regime robustness** | Checks win rate per market regime — below 30% → pre-live check fails |

### AI & adaptive learning

| # | Feature | What it does |
|---|---------|-------------|
| 21 | **LSTM neural network** | Sequence-based learning on 24h time series — complements XGBoost |
| 22 | **RL agent** | Q-learning on historical trades — learns which actions work in which regime |
| 23 | **Automatic retraining** | After 50 trades or F1 degradation → model retrains automatically in the background |
| 24 | **Dynamic parameters** | ATR multiplier and RR ratio automatically adapt to the regime |
| 25 | **Confidence monitor** | Gatekeeper: stops live trading if F1/Sharpe/win rate fall below thresholds |

### Infrastructure

| # | Feature | What it does |
|---|---------|-------------|
| 26 | **VPS failover** | QNAP unreachable? → Bot automatically starts via SSH on configured VPS |
| 27 | **LEAN_MODE** | QNAP/NAS-optimised operation — disables compute-intensive features (LSTM, Monte Carlo, etc.) |
| 28 | **Regime bus** | Crypto and Forex bots share regime information — prevents conflicting positions |

---

## 14. QNAP deployment

If you want to run the bot on a QNAP NAS (or another server):

### Initial setup

```bash
# Transfer .env to QNAP
scp forex_bot/.env admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/forex_bot/.env

# Deploy (builds Docker image and starts both bots)
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

After deployment the Forex bot runs permanently in the background — even when your laptop is off.

### Apply updates

```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

### View logs

```bash
make qnap-forex-logs QNAP=admin@YOUR_QNAP_IP
```

### LEAN_MODE — resource-efficient operation

On low-power hardware (QNAP, NAS, Raspberry Pi) activate LEAN_MODE:

```env
FOREX_LEAN_MODE=true
```

What LEAN_MODE disables:
- LSTM model (no PyTorch/AVX2 required)
- Monte Carlo simulation
- Markowitz portfolio optimizer
- M15 Entry Timer (one fewer OANDA API call per cycle)
- Stress tester

What continues to work: XGBoost, regime detection, all risk filters, Telegram, dashboard.

### VPS Failover (automatic backup)

If the QNAP becomes unreachable, the bot automatically starts on a VPS:

```env
FAILOVER_VPS_HOST=123.45.67.89
FAILOVER_VPS_USER=root
FAILOVER_VPS_KEY=~/.ssh/id_rsa
FAILOVER_VPS_CMD=cd /opt/trading_bot && docker compose up -d forex-bot
FAILOVER_MAX_FAILS=3      # 3 consecutive failures → trigger failover
FAILOVER_COOLDOWN=30      # 30 minutes cooldown between failovers
```

Start the failover daemon (recommended as a cron job on the VPS):

```bash
# On the VPS — run once per minute via cron:
*/1 * * * * python /opt/trading_bot/forex_bot/scripts/failover.py --once >> /var/log/failover.log 2>&1

# Or as a daemon:
python -m forex_bot.scripts.failover
```

You receive a Telegram notification when failover is triggered.

### Resource usage (QNAP Celeron J1900)

| Container | RAM | CPU | LEAN_MODE |
|-----------|-----|-----|-----------|
| forex-bot | ~256 MB | low (sleeps 59/60 min.) | ~180 MB |
| forex-dashboard | ~128 MB | low | ~128 MB |

> The Forex bot and crypto bot together use about 2.9 GB RAM — this fits on a QNAP with 4 GB.  
> With `FOREX_LEAN_MODE=true` the Forex bot RAM drops to ~180 MB.

---

## 15. Configuration reference

All settings in `forex_bot/.env`:

```env
# ── Broker choice ──────────────────────────────────────────────────────────
FOREX_BROKER=oanda                    # oanda | capital | ig | ibkr

# ── OANDA broker ───────────────────────────────────────────────────────────
OANDA_API_KEY=your-api-key
OANDA_ACCOUNT_ID=101-001-12345678-001
OANDA_ENV=practice                    # practice | live

# ── Trading mode ───────────────────────────────────────────────────────────
FOREX_TRADING_MODE=paper              # paper | live
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY
FOREX_TIMEFRAME=H1
FOREX_INITIAL_CAPITAL=10000           # starting capital (paper mode)

# ── Risk ───────────────────────────────────────────────────────────────────
FOREX_RISK_PER_TRADE=0.01             # 1% per trade
FOREX_MAX_DRAWDOWN=0.15               # 15% → circuit breaker
FOREX_MAX_OPEN_TRADES=3
FOREX_ATR_MULTIPLIER=1.5              # stop-loss distance in ATR
FOREX_RR_RATIO=2.0                    # reward:risk ratio
FOREX_RISK_MODE=balanced              # conservative | balanced | aggressive

# ── Session filter (UTC) ───────────────────────────────────────────────────
FOREX_SESSION_FILTER=true
FOREX_SESSION_START_H=7               # 7:00 = London open
FOREX_SESSION_END_H=20                # 20:00 = NY close

# ── Economic calendar ──────────────────────────────────────────────────────
FOREX_NEWS_PAUSE_MIN=30               # pause ±30 min around high-impact events
FOREX_NEWS_CURRENCIES=USD,EUR,GBP,JPY,CHF,CAD,AUD,NZD

# ── Strategy ───────────────────────────────────────────────────────────────
FOREX_EMA_FAST=20
FOREX_EMA_SLOW=50
FOREX_EMA_TREND=200
FOREX_RSI_PERIOD=14
FOREX_MIN_CONFIDENCE=0.65             # minimum confidence to enter a trade

# ── Telegram ───────────────────────────────────────────────────────────────
FOREX_TELEGRAM_TOKEN=your-bot-token
FOREX_TELEGRAM_CHAT_ID=your-chat-id

# ── Dashboard API ──────────────────────────────────────────────────────────
FOREX_API_PORT=8001

# ── ML auto-retrain ────────────────────────────────────────────────────────
FOREX_RETRAIN_AFTER_TRADES=50         # retrain after every 50 closed trades

# ── LEAN_MODE (for QNAP / low-power hardware) ──────────────────────────────
FOREX_LEAN_MODE=false                 # true = disables LSTM, Monte Carlo, Portfolio Optimizer

# ── VPS failover (optional) ────────────────────────────────────────────────
# FAILOVER_VPS_HOST=123.45.67.89
# FAILOVER_VPS_USER=root
# FAILOVER_VPS_KEY=~/.ssh/id_rsa
# FAILOVER_VPS_CMD=cd /opt/trading_bot && docker compose up -d forex-bot
# FAILOVER_MAX_FAILS=3
# FAILOVER_COOLDOWN=30

# ── FRED API (optional) ────────────────────────────────────────────────────
# Free key at fred.stlouisfed.org → better Fed funds rate data
# FRED_API_KEY=your-fred-key
```

---

## 16. Frequently asked questions

**Q: The bot isn't making any trades. Is something broken?**  
A: Probably not. Many hours pass without a signal that clears all filters. Check the terminal for messages like `no signal — skip` or `outside trading session`. This is normal behaviour.

**Q: "No ML model found" — what should I do?**  
A: Nothing urgent. The bot runs rule-based. If you want the model: run `python -m forex_bot.ai.trainer`.

**Q: How long until the first trade?**  
A: Typically 0–3 trades per day depending on market conditions. On volatile days or before major events often none.

**Q: What is a pip?**  
A: The smallest price unit. For EUR/USD: 0.0001. A gain of "+20 pips" on EUR/USD means a 0.0020 price move in your favour.

**Q: What happens on a power cut / restart?**  
A: Open trades are stored in the SQLite database and restored on restart. Open OANDA positions remain in place.

**Q: Can I add more pairs?**  
A: Yes, in `.env`:  
```env
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD
```

**Q: How do I reset the risk mode back to auto?**  
A: `/set_mode` disables auto-mode until midnight. After that it re-enables. Or restart the bot.

**Q: Can I use paper mode and OANDA practice at the same time?**  
A: `FOREX_TRADING_MODE=paper` with `OANDA_ENV=practice` is exactly that — the bot reads real prices from OANDA practice but simulates trades locally. This tells you whether signals work on real prices.

**Q: What does OANDA cost?**  
A: The practice account is free. On the live account OANDA earns through the spread (difference between buy and sell price) — no fixed commissions.

---

*Last updated: 2026-04-13*  
*[🇩🇪 Deutsche Version](../de/FOREX.md)*
