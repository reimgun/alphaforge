# Docker Deployment

[🇩🇪 Deutsch](../de/DOCKER.md)

---

For stable, continuous operation — runs 24/7 in the background.  
Restarts automatically after crashes or server reboots.

## Prerequisites

- [Docker Desktop](https://docker.com/products/docker-desktop) installed  
- `.env` file configured (see [Configuration](CONFIG.md) or [Installation Guide](INSTALL.md))

---

## Start (one command)

```bash
# Build and start bot
make docker-run

# Check status
docker ps

# View live logs
make docker-logs

# Stop
make docker-stop
```

---

## What Docker does

- Bot runs in the background — even when the terminal is closed
- Automatically restarts after crashes (`restart: unless-stopped`)
- Automatically starts after server reboot
- Trades, logs and ML model are preserved through volumes

---

## File volumes

| Local path | Container path | Contents |
|---|---|---|
| `./data_store/` | `/app/data_store/` | SQLite database, bot state |
| `./logs/` | `/app/logs/` | Log files |
| `./ai/` | `/app/ai/` | Trained ML model |

---

## Train AI model in container

```bash
docker compose run --rm bot python -m ai.trainer
```

---

## Web Dashboard with Docker

```bash
# Start all services (bot + API + dashboard)
docker compose up -d

# Open dashboard in browser:
# http://localhost:8501   — Web Dashboard
# http://localhost:8000   — REST API
# http://localhost:8000/docs — API documentation
```

---

## Server deployment (Linux VPS)

```bash
# 1. Connect to server via SSH
ssh root@YOUR-SERVER-IP

# 2. Install Docker (one-time)
curl -fsSL https://get.docker.com | sh

# 3. Clone repository
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot

# 4. Create configuration
cp .env.example .env
nano .env

# 5. Start
docker compose up -d
```

---

## Monitor logs

```bash
docker compose logs -f bot        # Bot logs live
docker compose logs -f api        # Dashboard API logs
docker compose logs -f            # All containers
make docker-logs                  # Shortcut
```

---

## Apply updates

```bash
git pull
docker compose up -d --build
```

---

## Resource usage

| Component | CPU (idle) | RAM |
|---|---|---|
| Bot | < 5% | ~300–500 MB |
| Dashboard API | < 2% | ~100 MB |
| Dashboard UI | < 2% | ~200 MB |
| **Total** | **< 10%** | **~600–800 MB** |

Network: minimal — API calls every 1–4 hours.

---

## QNAP NAS

For operation on a QNAP NAS there is a dedicated optimized configuration.  
→ **[QNAP.md](QNAP.md)** — Complete guide
