# AI Trading Bot

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?logo=github)](https://github.com/sponsors/reimgun)
[![Ko-fi](https://img.shields.io/badge/Buy%20me%20a%20coffee-Ko--fi-FF5E5B?logo=ko-fi)](https://ko-fi.com/reimgun)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**🇩🇪 [Deutsch](#-deutsch)** &nbsp;|&nbsp; **🇬🇧 [English](#-english)**

---

## 🇩🇪 Deutsch

Vollautonomer KI-Trading-Bot für **Crypto, Forex und Aktien**.  
Unterstützt 10+ Crypto-Exchanges (Binance, Bybit, OKX, Kraken, Coinbase...) sowie Forex-Broker (IG, OANDA, Alpaca, IBKR).

> **Kein Exchange-Account nötig zum Starten.** Der Bot beginnt im **Paper-Modus** — er handelt mit virtuellem Geld und zeigt dir was er getan hätte. Erst wenn du willst (und die Performance überzeugt), wechselst du zu echtem Geld.

---

### Wo soll der Bot laufen?

| Ich möchte... | Passende Installation |
|---|---|
| 💻 Den Bot **auf meinem Mac** ausprobieren | [→ Mac](docs/de/INSTALL.md#-mac--linux) |
| 🐧 Den Bot **auf meinem Linux-PC** ausprobieren | [→ Linux](docs/de/INSTALL.md#-mac--linux) |
| 🪟 Den Bot **auf meinem Windows-PC** ausprobieren | [→ Windows](docs/de/INSTALL.md#-windows) |
| 🥧 Den Bot **auf einem Raspberry Pi** betreiben | [→ Raspberry Pi](docs/de/INSTALL.md#-raspberry-pi-arm) |
| 📦 Den Bot **24/7 auf meinem QNAP NAS** laufen lassen | [→ QNAP NAS](docs/de/QNAP.md) |
| ☁️ Den Bot **günstig in der Cloud** betreiben (Hetzner/DO) | [→ Cloud/VPS](docs/de/CLOUD.md) |
| 🟠 Den Bot **auf AWS EC2** betreiben | [→ AWS](docs/de/CLOUD.md#aws-ec2) |
| 🔵 Den Bot **auf Azure** betreiben | [→ Azure](docs/de/CLOUD.md#azure-vm) |

---

### Schnellstart (Mac/Linux — ein Befehl)

```bash
bash install.sh
```

Der Setup-Assistent fragt Exchange, Startkapital, Risikoprofil und optionale Telegram-Alerts — dann startet der Bot automatisch.

### Schnellstart (Windows)

**Option A — Doppelklick (empfohlen):**  
Doppelklick auf **`install.bat`** im Projektordner.

**Option B — PowerShell (nativ, kein WSL2 nötig):**
```powershell
.\install.ps1
```

### Schnellstart (Docker / VPS / Cloud)

```bash
# .env anlegen + Bot starten (inkl. HTTPS via Traefik)
cp .env.example .env && nano .env   # DOMAIN + Credentials setzen
docker compose -f docker-compose.cloud.yml up -d
```

---

### Was der Bot macht

```
Jede Stunde (konfigurierbar):
  1. Marktdaten laden (Crypto: CCXT / Forex: Broker-API)
  2. 50+ Indikatoren + On-Chain-Daten berechnen
  3. KI-Modell analysiert Marktregime (Bull/Bear/Seitwärts/Hoch-Volatilität)
  4. ML-Konfidenz + News-Sentiment + Fear & Greed kombinieren
  5. Signal: KAUFEN / VERKAUFEN / WARTEN
  6. Bei Kauf: Stop-Loss + Take-Profit automatisch setzen (Bracket Order)
  7. Position überwachen, Trailing Stop nachziehen
  8. Telegram-Benachrichtigung bei jedem Trade
```

---

### Features

| Bereich | Was ist enthalten |
|---|---|
| **Exchanges** | 10 Crypto-Exchanges via CCXT · Binance, Bybit, OKX, Kraken, Coinbase, Gate.io, KuCoin, Bitget, HTX, MEXC |
| **Broker** | IG, OANDA, Alpaca (Aktien + Crypto), IBKR, Capital.com |
| **KI & ML** | XGBoost + LightGBM · LSTM · RL Agent · Anomalie-Erkennung · On-Chain-Daten · Groq LLM News-Sentiment |
| **Marktanalyse** | 4 Regime · Multi-Timeframe · 50+ Indikatoren · Fear & Greed · Walk-Forward Backtest (Crypto + Forex) |
| **Risiko** | ATR-Sizing · Trailing Stop · Bracket Orders (OCO) · Circuit Breaker · Black Swan Guard · Korrelations-Guard |
| **Strategie** | Pluggable IStrategy Interface · 2 eingebaute Strategien · Custom Strategies · Funding Rate Arbitrage |
| **Execution** | TWAP für Orders $10k+ · Slippage-Tracking · Venue Optimizer (Fee-aware Routing) |
| **Multi-Bot** | Signal Bus (File + Redis) · Multi-Bot Pub/Sub zwischen Crypto- und Forex-Bot |
| **Dashboard** | Streamlit Web-UI · Standard/Pro-Modus · Feature-Toggles · Strategy-Selector · Marketplace |
| **Alerts** | Telegram · Discord · HTTP Webhook (Grafana/PagerDuty/n8n) · 12 Steuerungsbefehle |
| **Setup** | Hardware-Benchmark + Auto-Config · Setup-Wizard · `make upgrade` (Backup + DB-Migration) |
| **Deployment** | Docker · QNAP NAS · Raspberry Pi ARM · Cloud (Hetzner/DO/AWS/Azure) mit HTTPS |
| **Steuer** | FIFO Trade-Journal · DE-Format (Elster) · AT-Format · CSV-Export (`make tax-export`) |
| **Zuverlässigkeit** | Dead Man's Switch · Heartbeat · Rate-Limit-Monitoring · Live State Reconciliation |

---

### Setup-Assistent

Beim ersten Start führt dich der Assistent durch alles:

```
Schritt 1: Exchange oder Broker wählen   [Binance / Bybit / OKX / Alpaca / OANDA ...]
Schritt 2: API-Key eingeben              [mit Link zur Anleitung für jeden Exchange]
Schritt 3: Handelsmodus                  [Paper (empfohlen) oder Live]
Schritt 4: Startkapital                  [virtuell oder echt]
Schritt 5: Risikoprofil                  [Konservativ / Balanced / Aggressiv]
Schritt 6: Telegram-Alerts einrichten    [optional]
→ Hardware-Benchmark läuft automatisch   [passt Feature-Flags ans System an]
→ KI-Modell wird trainiert               [~3-5 Minuten]
→ Bot startet + erste Telegram-Nachricht
```

---

### Web-Dashboard aufrufen

```bash
make crypto-api       # Terminal 1 — API Backend (Port 8000)
make crypto-dashboard # Terminal 2 — Streamlit UI (Port 8501)
```

Dann im Browser: **http://localhost:8501**

Dashboard-Tabs: Übersicht · Trades · **Strategie** · Logs · Features · Marketplace · System · Hilfe  
Pro-Modus zusätzlich: Performance · Strategie-Performance · Risk & Market · AI Explainability

---

### Alle Befehle

```bash
make help                   # Alle Befehle mit Beschreibung
make crypto-start           # Crypto Bot lokal starten
make crypto-train           # ML-Modell trainieren
make crypto-backtest        # AI-Pipeline Backtest
make crypto-deploy QNAP=admin@YOUR_QNAP_IP   # Auf QNAP deployen
make forex-start            # Forex Bot lokal starten
make forex-deploy QNAP=admin@YOUR_QNAP_IP   # Forex auf QNAP deployen
make arm-build              # Raspberry Pi ARM64 Image bauen
make arm-deploy             # Auf Raspberry Pi deployen
```

---

### 🇩🇪 Dokumentation

| Dokument | Inhalt |
|---|---|
| [📖 Installationsanleitung](docs/de/INSTALL.md) | Schritt-für-Schritt für alle Plattformen |
| [☁️ Cloud & VPS Deployment](docs/de/CLOUD.md) | AWS, Azure, Hetzner, DigitalOcean |
| [⚙️ Konfiguration](docs/de/CONFIG.md) | Alle Einstellungen erklärt |
| [📊 Dashboard](docs/de/DASHBOARD.md) | Web-Dashboard Anleitung |
| [📱 Telegram](docs/de/TELEGRAM.md) | Push-Nachrichten & Befehle |
| [🐳 Docker](docs/de/DOCKER.md) | Produktivbetrieb mit Docker |
| [📦 QNAP NAS](docs/de/QNAP.md) | Dauerbetrieb auf QNAP TS-451 |
| [🧠 Strategie](docs/de/STRATEGY.md) | Wie der Bot Entscheidungen trifft |
| [💱 Forex Bot](docs/de/FOREX.md) | Forex Bot — OANDA, Alpaca, Wirtschaftskalender |
| [🔧 Einrichtung](docs/de/SETUP.md) | Erweiterte Einrichtungsoptionen |
| [❓ FAQ](docs/de/FAQ.md) | Häufige Fragen & Probleme |

---
---

## 🇬🇧 English

Fully autonomous AI trading bot for **Crypto, Forex and Equities**.  
Supports 10+ crypto exchanges (Binance, Bybit, OKX, Kraken, Coinbase...) and Forex brokers (IG, OANDA, Alpaca, IBKR).

> **No exchange account needed to start.** The bot begins in **Paper Mode** — it trades with virtual money and shows you what it would have done. You only switch to real money when you're ready (and the performance looks good).

---

### Where Should the Bot Run?

| I want to... | Right installation |
|---|---|
| 💻 Try the bot **on my Mac** | [→ Mac](docs/en/INSTALL.md#-mac--linux) |
| 🐧 Try the bot **on my Linux PC** | [→ Linux](docs/en/INSTALL.md#-mac--linux) |
| 🪟 Try the bot **on my Windows PC** | [→ Windows](docs/en/INSTALL.md#-windows) |
| 🥧 Run the bot **on a Raspberry Pi** | [→ Raspberry Pi](docs/en/INSTALL.md#-raspberry-pi-arm) |
| 📦 Run the bot **24/7 on my QNAP NAS** | [→ QNAP NAS](docs/en/QNAP.md) |
| ☁️ Run the bot **cheaply in the cloud** (Hetzner/DO) | [→ Cloud/VPS](docs/en/CLOUD.md) |
| 🟠 Run the bot **on AWS EC2** | [→ AWS](docs/en/CLOUD.md#aws-ec2) |
| 🔵 Run the bot **on Azure** | [→ Azure](docs/en/CLOUD.md#azure-vm) |

---

### Quick Start (Mac/Linux — one command)

```bash
bash install.sh
```

The setup wizard asks for your exchange, starting capital, risk profile, and optional Telegram alerts — then starts the bot automatically.

### Quick Start (Windows)

**Option A — Double-click (recommended):**  
Double-click **`install.bat`** in the project folder.

**Option B — PowerShell (native, no WSL2 needed):**
```powershell
.\install.ps1
```

### Quick Start (Docker / VPS / Cloud)

```bash
# Create .env + start bot (incl. HTTPS via Traefik)
cp .env.example .env && nano .env   # Set DOMAIN + credentials
docker compose -f docker-compose.cloud.yml up -d
```

---

### How the Bot Works

```
Every hour (configurable):
  1. Load market data (Crypto: CCXT / Forex: Broker API)
  2. Calculate 50+ indicators + on-chain data
  3. AI model analyzes market regime (Bull/Bear/Sideways/High-Volatility)
  4. Combine ML confidence + news sentiment + Fear & Greed
  5. Signal: BUY / SELL / HOLD
  6. On buy: set stop-loss + take-profit automatically (bracket order)
  7. Monitor position, trail stop upward
  8. Telegram notification on every trade
```

---

### Features

| Area | What's included |
|---|---|
| **Exchanges** | 10 Crypto exchanges via CCXT · Binance, Bybit, OKX, Kraken, Coinbase, Gate.io, KuCoin, Bitget, HTX, MEXC |
| **Brokers** | IG, OANDA, Alpaca (stocks + crypto), IBKR, Capital.com |
| **AI & ML** | XGBoost + LightGBM · LSTM · RL Agent · Anomaly detection · On-chain data · Groq LLM news sentiment |
| **Market Analysis** | 4 Regimes · Multi-Timeframe · 50+ Indicators · Fear & Greed · Walk-Forward Backtest (Crypto + Forex) |
| **Risk** | ATR Sizing · Trailing Stop · Bracket Orders (OCO) · Circuit Breaker · Black Swan Guard · Correlation Guard |
| **Strategy** | Pluggable IStrategy interface · 2 built-in strategies · Custom strategies · Funding Rate Arbitrage |
| **Execution** | TWAP for orders $10k+ · Slippage tracking · Venue Optimizer (fee-aware routing) |
| **Multi-Bot** | Signal Bus (File + Redis) · Pub/Sub between Crypto and Forex bot |
| **Dashboard** | Streamlit Web UI · Standard/Pro mode · Feature toggles · Strategy selector · Marketplace |
| **Alerts** | Telegram · Discord · HTTP Webhook (Grafana/PagerDuty/n8n) · 12 control commands |
| **Setup** | Hardware benchmark + auto-config · Setup wizard · `make upgrade` (backup + DB migration) |
| **Deployment** | Docker · QNAP NAS · Raspberry Pi ARM · Cloud (Hetzner/DO/AWS/Azure) with HTTPS |
| **Tax** | FIFO Trade Journal · German format (Elster) · Austrian format · CSV export (`make tax-export`) |
| **Reliability** | Dead Man's Switch · Heartbeat · Rate-limit monitoring · Live State Reconciliation |

---

### Setup Wizard

On first start, the wizard guides you through everything:

```
Step 1: Choose exchange or broker   [Binance / Bybit / OKX / Alpaca / OANDA ...]
Step 2: Enter API key               [with link to guide for each exchange]
Step 3: Trading mode                [Paper (recommended) or Live]
Step 4: Starting capital            [virtual or real]
Step 5: Risk profile                [Conservative / Balanced / Aggressive]
Step 6: Set up Telegram alerts      [optional]
→ Hardware benchmark runs auto      [adjusts feature flags to your hardware]
→ AI model is trained               [~3-5 minutes]
→ Bot starts + first Telegram msg
```

---

### Open the Web Dashboard

```bash
make crypto-api       # Terminal 1 — API backend (port 8000)
make crypto-dashboard # Terminal 2 — Streamlit UI (port 8501)
```

Then in browser: **http://localhost:8501**

Dashboard tabs: Overview · Trades · **Strategy** · Logs · Features · Marketplace · System · Help  
Pro mode adds: Performance · Strategy Performance · Risk & Market · AI Explainability

---

### All Commands

```bash
make help                   # All commands with description
make crypto-start           # Start Crypto bot locally
make crypto-train           # Train ML model
make crypto-backtest        # AI-pipeline backtest
make crypto-deploy QNAP=admin@YOUR_QNAP_IP   # Deploy to QNAP
make forex-start            # Start Forex bot locally
make forex-deploy QNAP=admin@YOUR_QNAP_IP   # Deploy Forex to QNAP
make arm-build              # Build Raspberry Pi ARM64 image
make arm-deploy             # Deploy to Raspberry Pi
```

---

### 🇬🇧 Documentation

| Document | Content |
|---|---|
| [📖 Installation Guide](docs/en/INSTALL.md) | Step-by-step for all platforms |
| [☁️ Cloud & VPS Deployment](docs/en/CLOUD.md) | AWS, Azure, Hetzner, DigitalOcean |
| [⚙️ Configuration](docs/en/CONFIG.md) | All settings explained |
| [📊 Dashboard](docs/en/DASHBOARD.md) | Web dashboard guide |
| [📱 Telegram](docs/en/TELEGRAM.md) | Push notifications & commands |
| [🐳 Docker](docs/en/DOCKER.md) | Production deployment with Docker |
| [📦 QNAP NAS](docs/en/QNAP.md) | 24/7 operation on QNAP TS-451 |
| [🧠 Strategy](docs/en/STRATEGY.md) | How the bot makes decisions |
| [💱 Forex Bot](docs/en/FOREX.md) | Forex bot — OANDA, Alpaca, economic calendar |
| [🔧 Setup](docs/en/SETUP.md) | Advanced setup options |
| [❓ FAQ](docs/en/FAQ.md) | Common questions & troubleshooting |
