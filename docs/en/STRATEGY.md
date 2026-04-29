# Strategy — How the Bot Decides

[🇩🇪 Deutsch](../de/STRATEGY.md)

---

## Decision pipeline

Every decision passes through multiple filters in sequence:

```
Step 1: Detect market regime        (Bull / Bear / Sideways / High-Vol)
     ↓
Step 2: Determine volatility regime (Low / Normal / High / Extreme)
     ↓
Step 3: Advanced intelligence       (Microstructure, Derivatives, Cross-Market)
     ↓
Step 4: Anomaly detection           (Block market outliers)
     ↓
Step 5: Select strategy             (AI selects automatically by regime)
     ↓
Step 6: Check 4h trend              (Main trend filter)
     ↓
Step 7: AI signal + position sizing + execute trade
```

---

## Step 1 — Market regime

| Regime | When | Response |
|--------|------|----------|
| **BULL_TREND** | Price above MA50, ADX > 22 | Full position size |
| **BEAR_TREND** | Price below MA50, ADX > 22 | **No trade** — capital protection |
| **SIDEWAYS** | ADX < 22, narrow channel | 60% position size |
| **HIGH_VOLATILITY** | ATR > 80th percentile | 50% position size |

---

## Step 2 — Volatility regime

| Vol regime | Annualized vol | Position factor |
|------------|----------------|----------------|
| **LOW** | < 30% | 1.0× |
| **NORMAL** | 30–80% | 0.85× |
| **HIGH** | 80–120% | 0.60× |
| **EXTREME** | > 120% | 0.30× |

Final factor: `regime_factor × vol_factor` (e.g. BULL × NORMAL = 1.0 × 0.85 = 0.85)

---

## Step 3 — Advanced intelligence

### Market microstructure
- **CVD** (Cumulative Volume Delta) — Buy vs. sell volume
- **Orderbook imbalance** — Bid-Heavy / Ask-Heavy from price position in HL range
- **Liquidity walls** — High volume bars as support/resistance
- **Spoofing proxy** — Suspicious wick-to-body ratios

### Derivatives intelligence
- **Funding rate** extreme → market overlevered → contrarian bias
- **Liquidation clusters** → magnetic price targets near liquidation levels
- **Spot-perp basis** → contango / backwardation sentiment

### Cross-market signals
- **Fear & Greed Index** — < 20 = Extreme Fear (potential contrarian BUY)
- **BTC dominance** — > 55% = Risk-Off, < 35% = Altcoin Season
- **Stablecoin flow** — High USDT/USDC volume = buying power in market

### Regime forecaster
- **Markov transition matrix**: learns empirically which regime transitions are common (TREND_UP → SIDEWAYS etc.)
- High breakout probability → `TREND_FOLLOWING` bias
- High mean reversion probability → `MEAN_REVERSION` bias
- Regime persistence < 30% → `WAIT`
- **Trend persistence**: geometric distribution estimates remaining trend duration (Forex default: ~20 hours)
- **Regime change warning**: transition probability > 60% → warning; > 75% → close open position

---

## Step 4 — Anomaly detection

- **Z-score**: Returns or volume outside ±3.5 standard deviations
- **Isolation Forest**: Multivariate outliers

If anomaly score ≥ 0.5 → automatically **HOLD** (no trade).

---

## Step 5 — Strategy selection

| Regime | Strategy | Logic |
|--------|----------|-------|
| **BULL_TREND** | Momentum + Breakout + Liquidity | All three agree → +15% confidence boost |
| **BEAR_TREND** | — | No trade |
| **SIDEWAYS** | Mean Reversion | Bollinger Bands extremes |
| **HIGH_VOLATILITY** | Scalping → Volatility Expansion → Breakout | Cascade: first signal wins |

### The 7 strategies

| Strategy | Signal | Best regime |
|----------|--------|------------|
| **Momentum** | Golden Cross MA20/MA50 + RSI filter | BULL_TREND |
| **Breakout** | Donchian channel + volume confirmation | BULL_TREND / HIGH_VOL |
| **Mean Reversion** | Bollinger Band touch + RSI extremes | SIDEWAYS |
| **Scalping** | EMA5/EMA13 crossover + volume spike | HIGH_VOL |
| **Volatility Expansion** | Keltner Channel breakout + ATR expansion | HIGH_VOL |
| **Liquidity Signals** | Volume spike (>2×) + tight spread | BULL_TREND |
| **Reinforcement Learning** | Q-learning agent | All (experimental) |

---

## Step 6 — 4h trend filter

```
4h BULLISH + BUY signal    → Trade allowed ✓
4h BEARISH + BUY signal    → Blocked → HOLD
4h NEUTRAL                 → No trade (too uncertain)
```

---

## Step 7 — AI signal (ensemble)

### XGBoost ML model
- Trained on 730 days of BTC data
- 50+ technical indicators as features
- Outputs BUY/SELL/HOLD with confidence %
- Below 60% confidence → automatically HOLD

### LSTM neural network
- Sequence-based model (last 24 hours as input)
- Ensemble: XGBoost 60% + LSTM 40%
- Falls back to MLP if PyTorch not installed

### Claude AI (optional, AI_MODE=combined)
- Analyzes market data as structured text
- In `combined` mode: only trade if ML **and** Claude agree

### Dynamic parameters (regime-adaptive)

ATR multiplier and RR ratio automatically adapt to the regime:

| Regime | ATR multiplier (SL) | RR ratio (TP) |
|--------|---------------------|--------------|
| TREND_UP / TREND_DOWN | 2.0× | 2.5:1 |
| SIDEWAYS | 1.5× | 1.5:1 |
| HIGH_VOLATILITY | 3.0× | 2.0:1 |

Session bonus: London/NY overlap +0.2×; Asian session -0.2×.
Drawdown correction: at >10% DD the ATR multiplier increases (wider stop).

### Position sizing

```
Risk   = Capital × 2% × regime_factor × vol_factor × IV_factor × CB_factor × portfolio_weight
Amount = Risk ÷ stop_distance (ATR × regime_multiplier)
```

**Example** with $1,000 capital, BULL_TREND (1.0), Vol NORMAL (0.85), ATR $1,200:
- Risk: 1,000 × 2% × 0.85 = **$17**
- Amount: 17 ÷ 2,400 = **0.0071 BTC**

---

## Model governance

Three continuous monitors protect against model degradation:

### Prediction entropy
Measures Shannon entropy of ML probability outputs.
- Entropy > 80% → model is uncertain → position size reduced to 0.25×
- Entropy < 50% → normal

### Feature importance drift
Compares current top-5 features vs. historical (Jaccard similarity).
- Jaccard < 40% → concept drift detected → retraining recommended

### Calibration drift (ECE)
Expected Calibration Error: how well do confidence scores match actual hit rate?
- ECE rise > 6% above baseline → additional 20% position reduction

---

## Online learning

After every closed trade the system updates itself:

1. **SGDClassifier** (partial_fit) — incremental update without full retraining
2. **Platt scaling** — calibrates ML probabilities to match real hit rates
3. **Bayesian signal updater** — Beta-Binomial prior per signal source; learns which sources are more reliable

---

## Strategy lifecycle

Every strategy automatically moves through lifecycle phases:

```
ACTIVE → COOLING (win rate 10 points below average)
       → DORMANT (after further deterioration)
       → REVIVAL  (when market regime matches again)
```

The **Adaptive Rotation Scheduler** activates only the historically best strategies per regime.
Dormant strategies are monitored and reactivated when their regime affinity is restored.

---

## Trade explainability

For every trade the bot generates a natural-language explanation (in log + dashboard):

```
📊 EUR_USD BUY @ 1.08542 | Confidence 72%
Regime: TREND_UP (for 14h) | Session: London
Signals: EMA crossover ↑ | MACD positive ↑ | RSI 52 (neutral)
ML: XGBoost BUY 68% | LSTM BUY 74% | Ensemble 72%
Entry: M15 pullback @ EMA20 (3.2 pips better)
SL: 1.08310 (-21.2 pips / 1.0% risk) | TP: 1.08912 (+37.0 pips) | RR 1.75:1
Modified: IV normal (1.0×) | CB hawkish +2% | portfolio weight 28%
```

---

## Risk management

### Circuit breaker
Automatically stops the bot at the daily loss limit. Resets daily.

### Max drawdown stop
Permanently stops the bot at the drawdown limit. Manual review required.

### Trailing stop
- Stop = highest price × (1 - 1.5%)
- Profits are automatically locked in as price rises

### Drawdown recovery

| Drawdown | Position factor |
|----------|----------------|
| < 7% | 1.0× (normal) |
| 7–10% | 0.75× |
| 10–15% | 0.50× |
| ≥ 15% | 0.25× |

### Risk mode profiles

| Mode | Risk/trade | Max drawdown | Circuit breaker |
|------|-----------|--------------|----------------|
| 🛡️ conservative | 1% | 10% | 3% |
| ⚖️ balanced | 2% | 20% | 6% |
| 🔥 aggressive | 3% | 30% | 9% |

---

## Understanding performance metrics

| Metric | Good | Acceptable |
|--------|------|------------|
| **Sharpe Ratio** | > 1.5 | > 1.0 |
| **Profit Factor** | > 1.5 | > 1.2 |
| **Win Rate** | > 55% | > 45% |
| **Max Drawdown** | < 10% | < 20% |

**Important:** Always compare with Buy & Hold (`make backtest`).

---

## Phases: Paper → Testnet → Live

The bot moves through three phases. It **never switches automatically** — every step requires your explicit confirmation.

```
Paper  ──(criteria met + /approve_live)──► Testnet
Testnet──(criteria met + /approve_live)──► Live
```

### Transition criteria (apply to both steps)

| Criterion | Target |
|---|---|
| Trades collected | ≥ 20 |
| Sharpe ratio | ≥ 0.8 |
| Win rate | ≥ 48% |
| Max drawdown | ≤ 15% |
| ML model F1 score | ≥ 0.38 |

All five criteria must be met at the same time.

### Flow

1. **Paper phase:** Bot trades with virtual capital. Check progress at any time with `/progress` in Telegram.
2. **Readiness notification:** Once all criteria are met, the bot sends a Telegram message.
3. **Manual confirmation:** You reply with `/approve_live` (or click the button in the web dashboard).
4. **Testnet phase:** Bot trades on Binance Testnet with real API calls but no real money. The same criteria are measured again.
5. **Live activation:** After a second confirmation (`/approve_live`), the bot switches to real capital.

### Tracking progress

```
/progress        # Current status of all criteria + ETA until next phase
```

The web dashboard shows all criteria with their percentage and an estimated number of days until the next step.

---

## Custom Strategies — Pluggable IStrategy Interface

You can plug in your own trading strategy without touching the bot core.

### Quick start

```bash
# 1. Create strategy file
cp strategies/README.md strategies/my_strategy.py

# 2. Activate strategy
echo "STRATEGY=MyTrendStrategy" >> .env
echo "FEATURE_CUSTOM_STRATEGY=true" >> .env

# 3. Restart bot
make crypto-restart
```

### Required methods

```python
from crypto_bot.strategy.interface import IStrategy
import pandas as pd

class MyTrendStrategy(IStrategy):
    timeframe   = "1h"
    min_bars    = 50
    description = "My trend-following system"

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema20"] = df["close"].ewm(span=20).mean()
        df["ema50"] = df["close"].ewm(span=50).mean()
        return df

    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["buy"] = (df["ema20"] > df["ema50"]).astype(int)
        return df

    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["sell"] = (df["ema20"] < df["ema50"]).astype(int)
        return df
```

### Optional callbacks

| Method | Description | Default |
|--------|-------------|---------|
| `custom_stoploss()` | Custom stop-loss price | ATR-based |
| `confirm_trade_entry()` | Validate trade before execution | `True` |
| `confirm_trade_exit()` | Block an exit signal | `True` |
| `on_trade_opened()` | Callback after buy | – |
| `on_trade_closed()` | Callback after sell | – |
| `custom_stake_amount()` | Position size in USDT | ATR sizing |
| `adjust_trade_position()` | DCA / Scale-out | – |
| `informative_pairs()` | Additional data pairs | `[]` |

### Built-in strategies

| Name | Description | Timeframe |
|------|-------------|-----------|
| `MACrossStrategy` | EMA crossover + RSI filter | 1h |
| `RSIBBStrategy` | RSI overbought/oversold + Bollinger Bands | 1h |

### Hyperopt with custom loss function

```bash
# Find parameters optimised for Calmar ratio (return/drawdown)
HYPEROPT_LOSS=calmar python -m crypto_bot.optimization.hyperopt --trials 100

# Available loss functions:
# sharpe, sortino, calmar, profit_drawdown, only_profit, multi_metric
```
