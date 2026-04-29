# QNAP NAS — Running 24/7 on your home server

[🇩🇪 Deutsch](../de/QNAP.md)

---

The trading bot runs stably on a QNAP TS-451 (Celeron J1900, 8 GB RAM).
Advantages: always on, ~20 watts power consumption, no cloud costs, data stays local.

---

## Prerequisites

| What | Where to install |
|------|-----------------|
| **Container Station** | QNAP App Center → install Container Station |
| **SSH enabled** | QNAP Control Panel → Network Services → Telnet/SSH → enable SSH |
| **Git** (optional) | Not needed — deploy-qnap.sh handles everything |

---

## How it works

```
Windows WSL/Ubuntu (training)    QNAP TS-451 (continuous operation)
─────────────────────────────    ──────────────────────────────────
make train               →       ai/model.joblib (copied over)
deploy-qnap.sh           →       Docker container running
                                 Bot loop every 1h
                                 Dashboard port 8000 (LAN only)
                                 Telegram alerts + commands
```

**Important:** ML training runs on Windows in WSL/Ubuntu (Celeron J1900 is too slow for it).

---

## Initial setup

### Step 1 — Set up WSL (Ubuntu) on Windows

```powershell
wsl --install
# Automatically installs Ubuntu, one restart needed
```

In Ubuntu:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git make rsync openssh-client python3 python3-pip python3-venv
python3 --version
```

> **Important — project path:** Always create the repository in the WSL filesystem:
> ```
> Correct:   ~/projects/trading_bot     (WSL filesystem, fast)
> Wrong:     /mnt/c/Users/.../trading_bot  (Windows drive, 10× slower)
> ```

### Step 2 — Set up bot in WSL and train model

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
bash install.sh
make train
```

### Step 3 — Store SSH key on QNAP (once)

```bash
ssh-keygen -t ed25519 -C "trading-bot-deploy"
ssh-copy-id admin@YOUR_QNAP_IP
```

> Find QNAP IP: QNAP Control Panel → Network → Network Interfaces

### Step 4 — Deploy

```bash
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

The script automatically:
1. Checks if `ai/model.joblib` exists
2. Transfers code + model via rsync to the QNAP
3. Builds the Docker container on the QNAP
4. Starts bot + dashboard as background services
5. Shows live logs to confirm

---

## Daily usage

```bash
make qnap-logs QNAP=admin@YOUR_QNAP_IP    # Live logs
make qnap-stop QNAP=admin@YOUR_QNAP_IP    # Stop bot
make qnap-deploy QNAP=admin@YOUR_QNAP_IP  # Redeploy

# Directly via SSH
ssh admin@YOUR_QNAP_IP
docker ps
docker logs -f trading-bot
```

---

## Update code without Docker rebuild

### qnap-pull — update code only

```bash
make qnap-pull QNAP=admin@YOUR_QNAP_IP
```

### qnap-pip — install a single package

```bash
make qnap-pip QNAP=admin@YOUR_QNAP_IP PKG=streamlit-autorefresh
```

### qnap-update — everything in one step (recommended)

```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

---

## Deploy historical data

```bash
make import-history-qnap QNAP=admin@YOUR_QNAP_IP         # 365 days
make import-history-qnap QNAP=admin@YOUR_QNAP_IP DAYS=90  # 90 days
make import-history-clear-qnap QNAP=admin@YOUR_QNAP_IP   # Clear + reimport
```

---

## Web dashboard on local network

```
http://YOUR_QNAP_IP:8501       Web Dashboard (Crypto + Forex toggle)
http://YOUR_QNAP_IP:8000       Crypto REST API
http://YOUR_QNAP_IP:8000/docs  Crypto API documentation
http://YOUR_QNAP_IP:8001       Forex REST API
http://YOUR_QNAP_IP:8001/docs  Forex API documentation
```

---

## Running the Forex bot on QNAP

The Forex bot starts automatically when `forex_bot/.env` is present on the QNAP:

```bash
# One-time: transfer .env with OANDA keys to QNAP
scp forex_bot/.env admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/forex_bot/.env

# Deploy — automatically starts both bots
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Without `forex_bot/.env` the Forex containers are skipped — the crypto bot runs as usual.

Resources for both bots combined:

| Container | RAM | CPU |
|---|---|---|
| trading-bot (Crypto) | 1,500 MB | 2.0 |
| trading-dashboard (Crypto API) | 512 MB | 1.0 |
| trading-streamlit (Dashboard) | 512 MB | 1.0 |
| forex-bot | 256 MB | 0.5 |
| forex-dashboard (Forex API) | 128 MB | 0.5 |
| **Total** | **~2.9 GB** | |

Logs:

```bash
make qnap-logs QNAP=admin@YOUR_QNAP_IP        # Crypto logs
make qnap-forex-logs QNAP=admin@YOUR_QNAP_IP  # Forex logs
```

---

## Security on home network

| Threat | Protection |
|--------|-----------|
| Access from internet | FRITZ!Box: **no** port forwarding for 8000/8001/8501 |
| Strangers on same WiFi | QNAP firewall: allow only own subnet |
| Unauthorized control | Set API key in `.env` |

### Set up QNAP firewall

QNAP Control Panel → Security → Firewall:

1. TCP | `192.168.178.0/24` | Port 8000 | **Allow**
2. TCP | `0.0.0.0/0` | Port 8000 | **Deny**
3. TCP | `192.168.178.0/24` | Port 8001 | **Allow**
4. TCP | `0.0.0.0/0` | Port 8001 | **Deny**
5. TCP | `192.168.178.0/24` | Port 8501 | **Allow**
6. TCP | `0.0.0.0/0` | Port 8501 | **Deny**

### Set API key

```bash
ssh admin@YOUR_QNAP_IP
openssl rand -hex 16
nano /share/CACHEDEV1_DATA/trading_bot/.env
# DASHBOARD_API_KEY=generated_key
```

---

## Resources on the TS-451

### Crypto bot only

| Component | Usage |
|---|---|
| CPU | ~5–15% idle, brief spikes when generating signals |
| RAM | ~400–600 MB bot, ~200 MB dashboard |
| Storage | ~500 MB code + model, DB ~1 MB/week |
| Network | <1 MB/hour |

### Crypto + Forex combined

| Component | Usage |
|---|---|
| CPU | Barely more — Forex bot sleeps 59 of every 60 minutes |
| RAM | +~400 MB (both Forex containers) |
| Storage | +~1 MB/week for Forex DB |
| Network | +<0.5 MB/hour (OANDA API) |

---

## Limitations

### What works, what doesn't

| Feature | Status | Note |
|---|---|---|
| Paper / Testnet / Live Trading | ✅ | |
| XGBoost inference | ✅ | Milliseconds |
| ML training | ⚠️ very slow | 30–60 min — do on PC |
| Auto-retraining | ❌ disable | `ML_RETRAIN_AFTER_TRADES=999999` |
| LSTM / PyTorch | ❌ no AVX2 | Crash — disable via `FOREX_LEAN_MODE=true` |
| Online learning, anomaly, regime | ✅ | |
| Regime forecaster, Black Swan detector | ✅ | Lightweight |
| Portfolio optimizer (Markowitz) | ⚠️ | Disable via `FOREX_LEAN_MODE=true` |
| M15 Entry Timer | ⚠️ | Disable via `FOREX_LEAN_MODE=true` (saves one API call) |
| Stress tester | ⚠️ | Disable via `FOREX_LEAN_MODE=true` |
| VPS failover daemon | ✅ | Recommended as cron job on VPS |
| Claude / Groq / OpenAI | ✅ | External |
| Ollama (local LLM) | ❌ | Requires GPU |
| Streamlit dashboard | ⚠️ | ~20–30s start |

### Recommended `.env` settings for QNAP

```env
AUTO_TRAIN=false
ML_RETRAIN_AFTER_TRADES=999999
FEATURE_LSTM=false
AI_PROVIDER=groq

# Forex bot on QNAP: enable LEAN_MODE
FOREX_LEAN_MODE=true            # Disables LSTM, Monte Carlo, Portfolio Optimizer
```

`FOREX_LEAN_MODE=true` reduces the Forex bot's RAM usage from ~256 MB to ~180 MB and avoids
all operations that require AVX2 CPU extensions or heavy RAM usage.

---

## Update model

```bash
make train                    # In WSL: retrain
scp ai/model.joblib admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/ai/model.joblib
ssh admin@YOUR_QNAP_IP "docker restart trading-bot"
```

---

## Troubleshooting

**`make` or `rsync` not found**
```bash
sudo apt install -y make rsync openssh-client
```

**`ssh-copy-id` fails**
```bash
cat ~/.ssh/id_ed25519.pub | ssh admin@YOUR_QNAP_IP \
  "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

**`qnap-deploy` fails — Docker Hub unreachable**
```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

**Container does not start**
```bash
docker logs trading-bot --tail 50
```
- `.env` missing → `scp .env admin@YOUR_QNAP_IP:/share/.../trading_bot/.env`
- `model.joblib` missing → `scp ai/model.joblib ...`

**RAM bottleneck**
```yaml
# docker-compose.qnap.yml
limits:
  memory: 1000M
```

---

## Firmware updates

**Data and containers are fully preserved.**

| What | Why it's safe |
|---|---|
| `data_store/trades.db` | NAS volume — firmware never touches it |
| `ai/model.joblib` | Same volume |
| `.env`, logs | Same volume |

Sequence: bot stops → reboot (~5–15 min) → bot starts automatically.

**Prerequisite:** Container Station must be set to auto-start.  
QNAP Control Panel → Autostart → Container Station → enable

**Recommendation:**
```bash
# Telegram: /pause     (pause bot before update)
# Run firmware update
# Telegram: /resume    (resume afterwards)
```

---

## QNAP vs. Cloud hosting — honest comparison

### Short answer

For this bot on the H1 timeframe: **the QNAP is fully sufficient.**  
More hardware brings no measurable extra profit — as long as you're trading hourly signals.

---

### What would be better on a hosted server?

| | QNAP TS-451 (Celeron J1900) | Hetzner CX22 (€4/month) |
|--|--|--|
| **Uptime** | ~99.5% (home internet) | ~99.99% (data centre) |
| **Latency to OANDA** | 20–150 ms | 5–30 ms (EU server) |
| **ML training** | ~8 min for 5,000 candles | ~45 sec |
| **RAM** | 256 MB reserved | 4 GB available |
| **Power** | ~€10/month extra | included |
| **Cost** | One-off (QNAP already owned) | €4/month |
| **Maintenance** | Firmware updates, reboots | None |
| **H1 trading result** | **identical** | **identical** |

---

### Can you make more profit on a hosted server?

At H1 timeframe: **No — not measurably.**

Profit comes from the strategy, not from execution speed.  
Whether the order reaches OANDA 5 ms or 150 ms after the signal makes literally no difference for a trade that runs for hours.

**When latency actually matters:**

```
H1  (current)   QNAP fully sufficient — no difference
M15             QNAP still fine (timing not critical)
M5              Hosted server useful (more reliable timing)
M1 / Scalping   Hosted server necessary, ideally near NY4/LD4
Tick / HFT      Dedicated server directly in the data centre
```

---

### What actually influences profit

1. **More currency pairs** — expand from 3 to 7–9 → more signals, no hardware change needed
2. **Smaller timeframe** — M15/M30 instead of H1 → 3–4× more signals per day (backtest first!)
3. **More capital** — at 1% risk/trade, account size is what makes the difference, not the server
4. **More frequent ML retraining** — on a hosted server training takes 45 sec instead of 8 min, so `FOREX_RETRAIN_AFTER_TRADES=20` becomes practical instead of 50

---

### The only real QNAP disadvantage in live mode

If your home internet drops for 1–2 hours:

- Stop-loss and take-profit are **server-side at OANDA** — triggered even without your bot ✅
- The **trailing stop** won't be moved during the outage — you may leave profit on the table ⚠️
- New signals will be missed — but no forced entry into a bad trade

**Conclusion:** No total-loss risk, but missed optimisations.

---

### What doesn't work on QNAP (hardware limitations)

| Feature | Status | Reason |
|---------|--------|--------|
| LSTM / PyTorch | ❌ | No AVX2 on Celeron J1900 → crash |
| Local LLM (Ollama) | ❌ | Requires GPU |
| GARCH via `arch` library | ⚠️ | Falls back to rolling-std — works, just less precise |
| XGBoost inference | ✅ | Milliseconds |
| XGBoost training | ⚠️ very slow | Train on PC, transfer model |
| All other bot features | ✅ | No limitations |

---

### What the bot does when features are unavailable

The bot is designed so that **no feature failure stops the bot or loses money**:

| Situation | What happens | Safety |
|-----------|-------------|--------|
| `arch` not installed | GARCH → rolling-std fallback | ✅ bot runs |
| ML model missing | Rule-based only, no ML overlay | ✅ bot runs |
| Yahoo Finance blocked | Hardcoded fallback rates | ✅ bot runs |
| Calendar API offline | Fail-safe: known risk windows are blocked (NFP, FOMC, CPI) | ✅ bot pauses safely |
| OANDA briefly offline | Skip instrument, retry next hour | ✅ no bad trade |
| Trailing stop error | Log warning, retry next hour | ⚠️ SL not trailed |

---

### Recommendation

```
Now (Paper/Practice):
  → QNAP — no extra cost, works perfectly for H1

Live with small capital (<€5,000):
  → Keep using QNAP — stop-loss is protected server-side at OANDA

Live with larger capital or M15 timeframe:
  → Hetzner CX22 for €4/month is worth it
     Same code, same .env, nothing to change
     python -m forex_bot.bot runs identically

Never needed:
  → AWS / GCP / Azure — overpriced for this use case
  → Dedicated server — only relevant for M1/scalping
```

### Moving to a hosted server (if desired)

```bash
# Set up Hetzner CX22 (Debian 12)
apt install docker.io docker-compose git python3-pip

# Same flow as QNAP deploy
git clone https://github.com/your-repo/trading_bot.git
cd trading_bot
cp forex_bot/.env.example forex_bot/.env
# fill in .env
python -m forex_bot.bot

# Or with Docker (Dockerfile.qnap also works on Hetzner):
docker build -f Dockerfile.qnap -t trading-bot:hetzner .
docker run -d --env-file forex_bot/.env trading-bot:hetzner python -m forex_bot.bot
```

---

## Complete reset

```bash
ssh admin@YOUR_QNAP_IP "
  docker-compose -f /share/CACHEDEV1_DATA/trading_bot/docker-compose.qnap.yml down
  docker rmi trading-bot:qnap
  rm -rf /share/CACHEDEV1_DATA/trading_bot
"
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

> Back up database first:  
> `scp admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/data_store/trades.db ./backup/`
