# Installation Guide

[🇩🇪 Deutsch](../de/INSTALL.md)

---

## What is Paper Trading?

> Before using real money, we strongly recommend **Paper Mode**.  
> The bot trades with **virtual money** — no real capital at risk.  
> You can see exactly how it decides, and what the gains and losses would have been.  
> Only switch to real trading when you're happy with the performance.

---

## Which installation fits you?

```
Question 1: Do you have a QNAP NAS?
  YES  →  QNAP guide: docs/en/QNAP.md
  NO   ↓

Question 2: Do you want to host in the cloud (AWS / Azure / Hetzner)?
  YES  →  Cloud guide: docs/en/CLOUD.md
  NO   ↓

Question 3: Do you have a Raspberry Pi?
  YES  →  Raspberry Pi (further down this page)
  NO   ↓

Question 4: What operating system?
  Mac / Linux  →  Mac/Linux (further down)
  Windows      →  Windows (further down)
```

---

## 💻 Mac / Linux

> **Time needed: ~10 minutes**  
> You need: a Mac or Linux PC, an internet connection

### Step 1 — Install Python

Check if Python is already installed. Open a **Terminal** (Mac: Spotlight → "Terminal"):

```bash
python3 --version
```

If a version number appears (e.g. `Python 3.12.0`) — **go to Step 2**.

If you get an error:

**Mac:**
```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git make
```

---

### Step 2 — Download the project

```bash
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
```

> **No Git?** On GitHub, click **"Code" → "Download ZIP"** in the top right, unzip it, and navigate to the folder in Terminal.

---

### Step 3 — Start installation (One-Click)

```bash
bash install.sh
```

The script guides you through all questions:

```
? Trading mode: paper (virtual, recommended) or live?    → paper
? Starting capital in USDT (virtual):                    → 1000
? AI mode:                                               → ml (recommended)
? Set up Telegram alerts?                                → n (skip for now)
? Train AI model now? (~3-5 min)                         → y
? Start bot now?                                         → y
```

**That's it. The bot is running.**

---

### Step 4 — Monitor the bot (optional)

Live logs in the terminal:
```bash
make logs
```

Open the web dashboard (second terminal window):
```bash
make dashboard-api   # Terminal 2 — Backend
make dashboard       # Terminal 3 — UI
```
Then in your browser: **http://localhost:8501**

---

### Restart bot (after rebooting your PC)

```bash
cd trading_bot
source .venv/bin/activate
make start
```

---

## 🪟 Windows

> **Time needed: ~15 minutes**  
> You need: a Windows PC (Win 10 or newer), an internet connection

### Step 1 — Install Python

1. Open the **Microsoft Store**
2. Search for **"Python 3.12"**
3. Click **Install**

**Or:** Download Python directly: [python.org/downloads](https://python.org/downloads)  
→ Click the **first download button** → Install  
→ **Important:** Check the box **"Add Python to PATH"** during installation!

Check that Python works — open **Command Prompt** (Windows key → type "cmd"):
```
python --version
```
You should see `Python 3.x.x`.

---

### Step 2 — Download the project

**Option A — With Git (recommended):**

Download Git: [git-scm.com/download/win](https://git-scm.com/download/win) → Install  
Then in the Command Prompt:
```
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
```

**Option B — As ZIP:**
1. On GitHub, click **"Code"** → **"Download ZIP"** in the top right
2. Unzip the file (right-click → "Extract All")
3. Open the extracted folder

---

### Step 3 — Start installation

**Option A — Double-click (easiest):**

1. Open the project folder in Windows Explorer
2. **Double-click `install.bat`**

> If Windows shows a security warning: click **"More info" → "Run anyway"**.

**Option B — PowerShell (native, no WSL2 needed — recommended for Windows 10/11):**

1. Right-click `install.ps1` → **"Run with PowerShell"**  
   (Or: open PowerShell, navigate to the project folder, run `.\install.ps1`)

```
? Choose exchange:                                       → binance (or another)
? Trading mode: paper (virtual, recommended) or live?    → paper
? Starting capital in USDT (virtual):                    → 1000
? Risk profile:                                          → balanced
? Set up Telegram alerts?                                → n (skip for now)
? Train AI model now? (~3-5 min)                         → y
? Start bot now?                                         → y
```

**That's it. The bot is running.**

---

### Step 4 — Monitor the bot (optional)

In the Command Prompt:
```
make logs
```

Web dashboard (open two separate Command Prompt windows):
```
# Window 1:
make dashboard-api

# Window 2:
make dashboard
```
Then in your browser: **http://localhost:8501**

---

### Restart bot (after rebooting your PC)

Open Command Prompt, navigate to the project folder:
```
cd C:\path\to\trading_bot
.venv\Scripts\activate
make start
```

---

## 📦 QNAP NAS (24/7 Operation)

> **Who is this for?** Anyone who wants to run the bot 24/7 without keeping their own PC on all the time. A QNAP NAS uses only ~20 watts but runs around the clock.  
>  
> **Time needed: ~30–45 minutes (first-time setup)**  
> **After that: updates in 1 minute with a single command**

### Prerequisites

| What | Where to set up |
|---|---|
| QNAP NAS with Container Station | QNAP App Center → Install "Container Station" |
| SSH enabled | QNAP Control Panel → Network Services → Enable SSH |
| Your PC: Mac, Linux, or Windows with WSL | For deployment (one-time setup) |

---

### Windows users: Set up WSL (one-time, ~5 min)

WSL = Windows Subsystem for Linux — a Linux environment directly inside Windows.  
You only need to set this up once:

1. **Open PowerShell as Administrator** (Windows key → "PowerShell" → right-click → "Run as administrator")
2. Enter this command:
```powershell
wsl --install
```
3. Restart your PC when prompted
4. After restart, Ubuntu opens automatically — set a username and password
5. In Ubuntu, run:
```bash
sudo apt update && sudo apt install -y git make rsync openssh-client python3 python3-pip python3-venv
```

> **Important:** Run all following commands in the **Ubuntu window**, not in PowerShell.

---

### Step 1 — Set up project on your PC

Open Terminal (Mac/Linux) or the Ubuntu WSL window (Windows):

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot

# Initial setup (creates .env config file)
bash install.sh
```

When running `install.sh` for QNAP:
- Trading mode: `paper` (start with paper trading)
- Train AI model **now**: YES (takes 3–5 min, but runs on your PC, not on the QNAP)
- Start bot: **NO** (it will start on the QNAP later)

---

### Step 2 — Add SSH key to QNAP (one-time)

So you can connect without a password in the future:

```bash
# Generate SSH key (only if you don't have one yet)
ssh-keygen -t ed25519 -C "trading-bot"
# Press Enter for all questions (no passphrase needed)

# Copy key to QNAP (enter password once)
ssh-copy-id admin@YOUR_QNAP_IP
```

> Find your QNAP's IP address at:  
> **QNAP Control Panel → Network → Network Interfaces**

---

### Step 3 — Deploy bot to QNAP (One-Click)

```bash
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Replace `YOUR_QNAP_IP` with your QNAP's IP address.

The script automatically:
1. Checks if the AI model exists
2. Transfers code + model to the QNAP
3. Builds the Docker container on the QNAP
4. Starts bot + dashboard as background services
5. Shows live logs to confirm everything is running

**The bot is now running on the QNAP — even when you turn off your PC.**

---

### Open the dashboard in your browser

```
http://YOUR_QNAP_IP:8501    Web Dashboard
http://YOUR_QNAP_IP:8000    REST API
```

*(Only accessible from your home network — not visible from the internet)*

---

### Daily usage

```bash
make qnap-logs QNAP=admin@YOUR_QNAP_IP     # Follow live logs
make qnap-stop QNAP=admin@YOUR_QNAP_IP     # Stop bot
make qnap-update QNAP=admin@YOUR_QNAP_IP   # Apply code update
make diagnose-qnap QNAP=admin@YOUR_QNAP_IP # Diagnose
```

---

### Update the AI model on QNAP

ML training always runs on your PC (the QNAP's processor is too slow for it).  
After training, transfer the new model with one command:

```bash
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## ☁️ Server / VPS (Hosted Operation)

> **Who is this for?** Anyone without a 24/7 home server who wants the bot to run continuously. A VPS costs ~5–15 €/month from providers like Hetzner, DigitalOcean, Netcup, or Contabo.  
>  
> **Requirements: 1 CPU, 1 GB RAM, 10 GB storage, Ubuntu 22.04**  
> **Time needed: ~20 minutes**

---

### Step 1 — Rent a server

Recommended providers (affordable, reliable):

| Provider | Smallest plan | Price/month |
|---|---|---|
| [Hetzner Cloud](https://hetzner.com/cloud) | CX11 (1 CPU, 2 GB RAM) | ~€4 |
| [Contabo](https://contabo.com) | VPS S (4 CPU, 8 GB RAM) | ~€5 |
| [Netcup](https://netcup.de) | VPS 500 G11s | ~€4 |
| [DigitalOcean](https://digitalocean.com) | Basic Droplet | ~$6 |

When creating: choose **Ubuntu 22.04 LTS** as the operating system.

---

### Step 2 — Connect via SSH

**Mac/Linux:**
```bash
ssh root@YOUR-SERVER-IP
```

**Windows:** Download PuTTY ([putty.org](https://putty.org)), enter the IP, connect.

---

### Step 3 — Install Docker (one-time)

```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
docker --version
```

---

### Step 4 — Set up the bot

```bash
apt install -y git
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
cp .env.example .env
nano .env
```

Set at least:
```env
TRADING_MODE=paper
INITIAL_CAPITAL=1000
```

Save: `Ctrl+O`, `Enter`, `Ctrl+X`

---

### Step 5 — Start the bot (One-Click with Docker)

```bash
docker compose up -d
```

**The bot is now running permanently in the background.**

---

### Step 6 — Access the dashboard (optional)

```
http://YOUR-SERVER-IP:8501
```

> **Security note:** Set `DASHBOARD_API_KEY=a_long_random_password` in `.env`

---

### Daily usage on the server

```bash
docker compose logs -f bot            # Live logs
docker compose ps                     # Status
docker compose down                   # Stop
docker compose up -d                  # Start
git pull && docker compose up -d --build  # Update
```

---

## 🥧 Raspberry Pi (ARM)

> **Who is this for?** Anyone who wants to run the bot 24/7 at home for ~€2–5 electricity/month.  
> **Requirements:** Raspberry Pi 4 or 5 with 64-bit OS (Raspberry Pi OS Lite 64-bit recommended)  
> **Time needed: ~20 minutes**

### Step 1 — Prepare the Raspberry Pi

Install Docker on the Pi (once):

```bash
# Connect to Pi via SSH
ssh pi@raspberrypi.local

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker pi
```

### Step 2 — Build and deploy (from your local PC)

```bash
make arm-build                           # Build ARM64 image (~5-10 min)
make arm-deploy                          # Transfer image + code to Pi + start
# Default: pi@raspberrypi.local

# With custom IP:
make arm-deploy ARM_PI=pi@192.168.1.100
```

Dashboard available at: `http://raspberrypi.local:8000`

> The Pi has no AVX2 chip — LSTM is automatically disabled. XGBoost runs fine.

---

## 🔑 API Keys Setup (Live Trading Only)

> **You don't need API keys for Paper Trading!**

The setup wizard guides you through configuration. Most common options:

**Binance:**
1. Log in to [binance.com](https://binance.com) → Profile → **"API Management"** → **"Create API"**
2. **Permissions:** ✅ Spot Trading — ❌ Withdrawals **NEVER**
3. Add IP restriction
4. Add to `.env`: `BINANCE_API_KEY=...` / `BINANCE_API_SECRET=...`

**Alpaca (Stocks + Crypto, paper trading free):**
1. Sign up at [alpaca.markets](https://alpaca.markets) → **"Paper Trading"**
2. Generate API keys in the dashboard
3. Add to `.env`: `ALPACA_API_KEY_PAPER=...` / `ALPACA_API_SECRET_PAPER=...`

**Other exchanges:** The setup wizard shows you the API key link for each supported exchange.

---

## 🆘 Common Problems

**"python: command not found"**  
→ Reinstall Python and make sure **"Add to PATH"** is checked.

**"make: command not found" (Windows)**  
→ Use `python install.py` instead of `make start`.

**"Permission denied" when SSH-ing to QNAP**
```bash
cat ~/.ssh/id_ed25519.pub | ssh admin@YOUR_QNAP_IP \
  "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

**Bot runs but makes no trades**  
→ Normal in bear markets. Check: `make diagnose` or `make logs`

**"Docker Hub not reachable" during QNAP deploy**
```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

**AI model F1 score too low**
```bash
make train
# or for QNAP:
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## ✅ Next steps after installation

1. **Let Paper Trading run for a few weeks**
2. **Watch the dashboard** — equity curve, win rate, Sharpe ratio
3. **Set up Telegram** — push notification for every trade
4. **Only switch to Live Trading after good performance**
