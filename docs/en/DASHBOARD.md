# Web Dashboard

[🇩🇪 Deutsch](../de/DASHBOARD.md)

---

## Start

```bash
# Terminal 1 — API Backend (Port 8000)
make dashboard-api

# Terminal 2 — Web UI (Port 8501)
make dashboard
```

Then open in browser: **http://localhost:8501**

On QNAP: **http://YOUR_QNAP_IP:8501**

---

## What the dashboard shows

### Top: Live status

| Display | Meaning |
|---------|---------|
| **Capital** | Current account balance + % change since start |
| **Daily PnL** | Today's profit/loss |
| **Market Regime** | BULL / BEAR / SIDEWAYS / HIGH_VOL |
| **Volatility** | LOW / NORMAL / HIGH / EXTREME |
| **AI Confidence** | Current confidence score + active strategy |

### Middle: Equity curve

Capital history over the entire runtime.  
Green = above starting capital, Red = below.

### Right: Open position

Entry price, current price, stop-loss, take-profit and unrealized PnL.

### Performance metrics

- Total PnL + return %
- Win rate (winners / losers)
- Sharpe ratio / Sortino ratio
- Max drawdown
- Profit factor

---

## Phase progress bar

```
Phase: Paper Trading  ████████████░░░░░░░░  62%
```

| Criterion | Target |
|-----------|--------|
| Trades | ≥ 20 completed |
| Sharpe Ratio | ≥ 0.8 |
| Win Rate | ≥ 48% |
| Max Drawdown | ≤ 15% |
| Model F1 | ≥ 0.38 |

---

## Tabs

| Tab | Content |
|-----|---------|
| **Overview** | Live status, equity curve, position, performance, phase progress |
| **Weekly/Monthly** | PnL bar charts, rolling 7d/30d metrics |
| **Trade History** | Last 20 trades as color-coded table |
| **Strategy Performance** | PnL, win rate and confidence multiplier per strategy |
| **AI Explainability** | Last HOLD reason, model drift, trade rejection log, recent signals |
| **📜 Logs** | Live log viewer with filter and manual refresh |

---

## Sidebar controls

| Button | Function |
|--------|---------|
| **▶ Start Bot** | Start bot (only when not running) |
| **⛔ Stop** | Stop bot |
| **📄 Paper** | Switch to paper mode |
| **⏸ Pause** | Pause trading |
| **▶️ Resume** | Resume trading |
| **🛡️ Safe Mode** | Reduce position size to 50% |
| **🔄 Retrain** | Request model retraining |
| **📥 CSV** | Export trades as CSV |
| **📊 JSON** | Export performance as JSON |

**Log level** (sidebar): DEBUG / INFO / WARNING / ERROR — changes immediately.

**Refresh interval** (sidebar): 10–120 seconds (default: 30s).

---

## Risk mode buttons (sidebar)

| Button | Risk/trade | Max drawdown |
|--------|-----------|--------------|
| 🛡️ conservative | 1% | 10% |
| ⚖️ balanced | 2% | 20% |
| 🔥 aggressive | 3% | 30% |

Change takes effect immediately — no restart needed.

---

## REST API

All data is available as API at `http://localhost:8000`:

```
GET  /api/status          Bot status, capital, position, regime
GET  /api/trades          Recent trades (limit=50)
GET  /api/performance     KPIs (Sharpe, win rate, drawdown ...)
GET  /api/equity          Equity curve
GET  /api/signals         Recent AI signals
GET  /api/model           ML model info
GET  /api/rejections      Recent rejected trades
GET  /api/progress        Phase progress Paper→Testnet→Live
GET  /api/exposure        Global Exposure Controller status
GET  /api/logs            Recent log entries
GET  /api/export/csv      Trades as CSV
GET  /api/export/json     Performance as JSON

POST /api/control/start
POST /api/control/stop
POST /api/control/pause
POST /api/control/resume
POST /api/control/safe_mode
POST /api/control/retrain
POST /api/control/risk_mode/{mode}
POST /api/control/log_level/{level}
```

Swagger documentation: **http://localhost:8000/docs**

---

## Security

Control endpoints can be protected with an API key:

```env
DASHBOARD_API_KEY=my-secret-password
```

GET endpoints (read) are always open.  
**Recommendation for QNAP/home network:** Always set an API key.
