# Advanced Setup

[🇩🇪 Deutsch](../de/SETUP.md)

---

> **New here?** The complete step-by-step installation guide for all platforms  
> (Mac, Windows, QNAP, Server) is here:  
> **→ [INSTALL.md](INSTALL.md)**

This page contains advanced setup options and background information.

---

## Setting up Binance API keys (live trading only)

> No API keys needed for paper trading!

1. Log in to [binance.com](https://binance.com)
2. Profile → **API Management** → **Create API**
3. Permissions: only enable **Spot & Margin Trading**
4. **Withdrawals: NEVER enable**
5. IP restriction: enter your IP (recommended)
6. Enter API key + secret in `.env`:

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TRADING_MODE=live
```

---

## Auto-training on first start

When `AI_MODE=ml` or `combined` is set and no model exists yet:

```
Bot started
     ↓
No model found (ai/model.joblib)
     ↓
Load 730 days of data (or from cache)
     ↓
XGBoost + Walk-Forward Validation (~3–5 min)
     ↓
Model saved → Trading starts
```

You don't need to do anything — just wait.

---

## Manual training

```bash
make train
```

Or train + transfer to QNAP:
```bash
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## Enabling live trading

### Option A — Manual

```env
TRADING_MODE=live
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
```

### Option B — Automatic (recommended)

The bot proposes switching to live when all criteria are met.  
You receive a Telegram message and confirm with `/approve_live`.

**Recommendation:** At least 2–3 months of paper trading first. Start with a small amount.

---

## Encrypted API keys (recommended for servers)

```bash
# Encrypt (one-time)
python -m config.crypto_config --encrypt
# Creates .env.enc (safe to share) + .env.key (keep secret!)

# Check status
python -m config.crypto_config --check
```

**Never** push `.env.key` to a repository or GitHub.

---

## Install LSTM model (optional)

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Without PyTorch, the model automatically falls back to an MLP classifier.  
On QNAP: **do not install** — disable LSTM with `FEATURE_LSTM=false`.

---

## System check

```bash
make check
```

Shows status of all components: packages, database, model, API connection.
