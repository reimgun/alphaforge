# Telegram — Setup & Commands

[🇩🇪 Deutsch](../de/TELEGRAM.md)

---

Receive push notifications for every trade and control the bot via chat.

## Setup (5 minutes)

### Step 1 — Create a Telegram bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Enter a name (e.g. `My Trading Bot`)
4. Enter a username (must end in `_bot`, e.g. `my_trading_bot`)
5. Copy the **token** — it looks like: `123456789:ABC-DEFGhijklmno`

### Step 2 — Find your Chat ID

1. Search for `@userinfobot` in Telegram and open it
2. Send `/start`
3. Copy the **ID** — a number like: `987654321`

### Step 3 — Add to `.env`

```env
TELEGRAM_TOKEN=123456789:ABC-DEFGhijklmno
TELEGRAM_CHAT_ID=987654321
```

### Step 4 — Activate the bot

Send your new bot **any message once** in Telegram.  
After that, all commands appear automatically as a menu when you type `/`.

---

## Automatic notifications

| Event | Message contains |
|-------|-----------------|
| Bot started | Mode, capital |
| Trade opened | Price, quantity, stop-loss, take-profit, reason |
| Trade closed | Price, PnL, account balance |
| Training complete | Val-F1, samples, duration |
| Auto-retraining complete | New F1 score |
| Strategy switched | Old → new strategy + regime |
| Circuit breaker triggered | Daily loss limit reached |
| Max drawdown reached | Bot stopped — manual review needed |
| Live trading ready | All criteria met — waiting for confirmation |
| Error occurred | Error message |
| Daily report (00:00 UTC) | Daily PnL, number of trades |

---

## All commands

### Status & Monitoring

| Command | Function |
|---------|---------|
| `/start` | Start bot · resume from pause · show status |
| `/stop` | Stop bot (waits for end of current cycle) |
| `/status` | Capital, open position, daily PnL |
| `/trades` | Last 5 closed trades |
| `/performance` | Sharpe, Sortino, win rate, profit factor, drawdown |
| `/open_positions` | Current position with entry / stop-loss / take-profit |
| `/model` | ML model info (F1 score, training date, age) |
| `/rejections` | Last rejected trades with reasons |
| `/progress` | Progress bar Paper → Testnet → Live |
| `/help` | Show all commands |

### Trading control

| Command | Function |
|---------|---------|
| `/pause` | Pause trading (bot runs, but doesn't trade) |
| `/resume` | Resume trading |
| `/emergency_shutdown` | Stop immediately |
| `/approve_live` | Confirm live trading after notification |
| `/retrain_models` | Retrain model immediately |
| `/switch_safe_mode` | Safe mode on/off — position size to 50% |
| `/set_mode conservative` | Conservative: 1% risk/trade, 10% max drawdown |
| `/set_mode balanced` | Default: 2% risk/trade, 20% max drawdown |
| `/set_mode aggressive` | Aggressive: 3% risk/trade, 30% max drawdown |

### Exposure controller

| Command | Function |
|---------|---------|
| `/exposure_status` | Current risk mode + exposure in % |
| `/risk_off_mode` | Switch to RISK_OFF immediately (max. 15% exposure) |
| `/resume_trading` | Return from RISK_OFF / EMERGENCY to NORMAL |
| `/set_max_exposure 50` | Set maximum exposure to 50% |

---

## /progress in detail

```
📊 Learning Progress: Paper → Testnet → Live

Phase: Paper Trading
Overall: ████████████░░░░░░░░  62%

Criteria:
✅ Win-Rate:   51.2% / 48.0%   (100%)
✅ Drawdown:   8.3% / ≤15.0%   (100%)
✅ Model F1:   0.41 / 0.38     (100%)
🔄 Trades:     15 / 20         ( 75%)
🔄 Sharpe:     0.65 / 0.80     ( 81%)

💡 62% reached — Testnet switch possible at 60%
```

---

## Troubleshooting

**Not receiving messages**
- Did you send your bot a message? (required the first time)
- Token and chat ID correctly entered in `.env`?
- Run `make check`

**Bot not responding to commands**
- Is `bot.py` still running? → `make logs`
- Telegram token in `.env` correct?

**Commands not appearing as menu**
- Restart the bot — commands will appear when you next type `/`
