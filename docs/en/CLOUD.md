# Cloud & VPS Deployment

[🇩🇪 Deutsch](../de/CLOUD.md)

> The Trading Bot runs entirely in Docker — any Linux server with 1 GB RAM and Docker is sufficient.  
> The included `docker-compose.cloud.yml` automatically sets up HTTPS (Let's Encrypt) via Traefik.

---

## Which Provider Is Right for Me?

| Provider | Recommended Plan | Price/month | Best for |
|---|---|---|---|
| [Hetzner Cloud](https://hetzner.com/cloud) | CX22 (2 vCPU, 4 GB) | ~€5 | Europe, cheapest option |
| [DigitalOcean](https://digitalocean.com) | Basic Droplet (1 vCPU, 2 GB) | ~$12 | Americas, simplest interface |
| [AWS EC2](https://aws.amazon.com/ec2) | t3.small (2 vCPU, 2 GB) | ~$15 | AWS ecosystem, Free Tier available |
| [Azure VM](https://azure.microsoft.com/products/virtual-machines) | B1ms (1 vCPU, 2 GB) | ~$15 | Azure ecosystem, Free Tier available |
| [Contabo](https://contabo.com) | VPS S (4 vCPU, 8 GB) | ~€5 | Very cheap, good for beginners |

**Recommendation for beginners:** Hetzner Cloud CX22 — cheap EU provider, German data center, easy 1-click setup.

---

## Preparation (All Providers)

### What You Need

1. **Domain** (optional, but recommended for HTTPS): e.g. `mybot.com`  
   → Cheap domains at [Namecheap](https://namecheap.com) or [Porkbun](https://porkbun.com)
2. **SSH key** on your PC (if not already present):
   ```bash
   ssh-keygen -t ed25519 -C "trading-bot"
   ```
3. Your **public SSH key** (`~/.ssh/id_ed25519.pub`) — enter it when creating the server

### Prepare the Project on Your PC

```bash
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
bash install.sh      # Setup wizard — creates .env + trains model
```

---

## Hetzner Cloud (Recommended)

### Step 1 — Create Server

1. Sign in at [hetzner.com/cloud](https://hetzner.com/cloud) → **"New Project"**
2. Click **"Add Server"**
3. Settings:
   - **Location:** Nuremberg or Falkenstein (DE)
   - **Image:** Ubuntu 22.04
   - **Type:** CX22 (2 vCPU, 4 GB RAM) — enough for Crypto + Forex
   - **SSH Key:** Upload/paste your public key
   - **Name:** `trading-bot`
4. Click **"Create & Buy Now"** — ready in ~30 seconds
5. Note down the IP address (e.g. `49.12.34.56`)

### Step 2 — Configure Domain (Optional)

Add an A record in your DNS provider:
```
mybot.com     →  49.12.34.56
```

*(Without a domain the bot still works — you access the dashboard via IP)*

### Step 3 — Set Up Server

```bash
# Connect to server
ssh root@49.12.34.56

# Install Docker (one command)
curl -fsSL https://get.docker.com | sh

# Optional: run as non-root user
useradd -m -s /bin/bash botuser
usermod -aG docker botuser
mkdir -p /home/botuser/.ssh
cp ~/.ssh/authorized_keys /home/botuser/.ssh/
chown -R botuser:botuser /home/botuser/.ssh
```

### Step 4 — Deploy Bot

From your **local PC**:

```bash
# Transfer code to server
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='data_store/*.db' --exclude='logs/*' \
    . root@49.12.34.56:/opt/trading_bot/

# Copy .env files
scp .env root@49.12.34.56:/opt/trading_bot/.env
scp forex_bot/.env root@49.12.34.56:/opt/trading_bot/forex_bot/.env
```

On the **server**:

```bash
ssh root@49.12.34.56
cd /opt/trading_bot

# Set domain and email in .env
echo "DOMAIN=mybot.com" >> .env
echo "ACME_EMAIL=your@email.com" >> .env

# Start bot (with HTTPS)
docker compose -f docker-compose.cloud.yml up -d

# Check status
docker compose -f docker-compose.cloud.yml ps
```

**Dashboard is now available at:**
- `https://mybot.com` — Streamlit Dashboard (HTTPS, automatic certificate)
- `https://mybot.com/api` — REST API
- `https://mybot.com/forex` — Forex API

---

## DigitalOcean

### Step 1 — Create Droplet

1. [digitalocean.com](https://digitalocean.com) → **"Create" → "Droplets"**
2. Settings:
   - **Image:** Ubuntu 22.04 LTS
   - **Plan:** Basic — Regular → 2 GB / 1 CPU → ~$12/month
   - **Datacenter:** Frankfurt (for EU users) or New York
   - **Authentication:** SSH Key (recommended)
3. Click **"Create Droplet"**

### Step 2 — Connect & Install Docker

```bash
ssh root@YOUR-DROPLET-IP
curl -fsSL https://get.docker.com | sh
```

### Step 3 — Deploy (Same as Hetzner)

```bash
# From local PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . root@YOUR-DROPLET-IP:/opt/trading_bot/
scp .env root@YOUR-DROPLET-IP:/opt/trading_bot/.env

# On the server:
ssh root@YOUR-DROPLET-IP
cd /opt/trading_bot
echo "DOMAIN=mybot.com" >> .env
echo "ACME_EMAIL=your@email.com" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

---

## AWS EC2

> AWS has a **Free Tier**: t2.micro (1 vCPU, 1 GB) is free for 12 months.  
> For production use we recommend t3.small (2 vCPU, 2 GB).

### Step 1 — Launch EC2 Instance

1. [AWS Console](https://console.aws.amazon.com) → **EC2** → **"Launch Instance"**
2. Settings:
   - **Name:** `trading-bot`
   - **AMI:** Ubuntu Server 22.04 LTS (HVM)
   - **Instance type:** t3.small (or t2.micro for Free Tier)
   - **Key pair:** Create new or choose existing → download `.pem` file
   - **Network settings:** Check "Allow SSH traffic from" → "Anywhere"
3. Click **"Launch Instance"**

### Step 2 — Open Ports (Security Group)

In EC2 Console → **Security Groups** → your group → **"Inbound Rules" → "Edit"**:

| Type | Protocol | Port | Source |
|---|---|---|---|
| SSH | TCP | 22 | Anywhere (or your IP) |
| HTTP | TCP | 80 | Anywhere |
| HTTPS | TCP | 443 | Anywhere |

### Step 3 — Connect & Install

```bash
# Set permissions on .pem file (Mac/Linux)
chmod 400 trading-bot.pem

# SSH connection
ssh -i trading-bot.pem ubuntu@EC2-PUBLIC-IP

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker
```

### Step 4 — Deploy

```bash
# From local PC (replace EC2-PUBLIC-IP and path to .pem):
rsync -az -e "ssh -i trading-bot.pem" \
    --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . ubuntu@EC2-PUBLIC-IP:/home/ubuntu/trading_bot/
scp -i trading-bot.pem .env ubuntu@EC2-PUBLIC-IP:/home/ubuntu/trading_bot/.env

# On EC2 instance:
ssh -i trading-bot.pem ubuntu@EC2-PUBLIC-IP
cd ~/trading_bot
echo "DOMAIN=mybot.com" >> .env
echo "ACME_EMAIL=your@email.com" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

### Elastic IP (Optional — Fixed IP Address)

The EC2 IP changes on every restart. For a static IP:  
**EC2 → Elastic IPs → "Allocate Elastic IP" → "Associate"** → select your instance.

---

## Azure VM

> Azure has **750 hours/month Free Tier** for B1s VMs (first 12 months).

### Step 1 — Create VM

1. [portal.azure.com](https://portal.azure.com) → **"Virtual Machines" → "Create"**
2. Settings:
   - **Resource group:** Create new, e.g. `trading-bot-rg`
   - **VM name:** `trading-bot`
   - **Region:** West Europe (or nearest)
   - **Image:** Ubuntu Server 22.04 LTS
   - **Size:** B1ms (1 vCPU, 2 GB) or B2s (2 vCPU, 4 GB)
   - **Authentication:** SSH public key → paste your key
3. **"Networking"** tab:
   - Enable Public IP
4. **"Review + create" → "Create"**

### Step 2 — Open Ports (NSG)

**Networking → "Add inbound port rule"** for:
- Port 22 (SSH)
- Port 80 (HTTP)
- Port 443 (HTTPS)

### Step 3 — Connect & Install

```bash
# Get IP from Azure portal
ssh azureuser@AZURE-VM-IP

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker azureuser
newgrp docker
```

### Step 4 — Deploy

```bash
# From local PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . azureuser@AZURE-VM-IP:/home/azureuser/trading_bot/
scp .env azureuser@AZURE-VM-IP:/home/azureuser/trading_bot/.env

# On Azure VM:
ssh azureuser@AZURE-VM-IP
cd ~/trading_bot
echo "DOMAIN=mybot.com" >> .env
echo "ACME_EMAIL=your@email.com" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

---

## After Deployment

### HTTPS Without a Domain

Without a domain the bot runs on port 80 without HTTPS. Skip the Traefik labels and start directly:

```bash
# Without HTTPS / without domain
docker compose -f docker-compose.cloud.yml up -d traefik trading-dashboard trading-streamlit
```

Dashboard available at: `http://YOUR-SERVER-IP:8501`

### Monitor the Bot

```bash
# All container status
docker compose -f docker-compose.cloud.yml ps

# Live logs (Crypto Bot)
docker compose -f docker-compose.cloud.yml logs -f trading-bot

# Live logs (Forex Bot)
docker compose -f docker-compose.cloud.yml logs -f forex-bot

# Resource usage
docker stats
```

### Apply Updates

```bash
# From local PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . user@SERVER-IP:/opt/trading_bot/

# On the server:
ssh user@SERVER-IP
cd /opt/trading_bot
docker compose -f docker-compose.cloud.yml up -d --build
```

### Enable PostgreSQL (Optional)

For higher load or to retain database data across container rebuilds:

```bash
# In .env:
DB_BACKEND=postgres
POSTGRES_USER=trading
POSTGRES_PASSWORD=secure_password

# Start with Postgres:
docker compose -f docker-compose.cloud.yml --profile postgres up -d
```

---

## Security (Production)

### Firewall with UFW

```bash
ufw allow ssh
ufw allow http
ufw allow https
ufw enable
```

### Automatic Security Updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

### Backups

```bash
# Daily database backup (add to crontab -e):
0 3 * * * cp /opt/trading_bot/data_store/trading.db /opt/backups/trading_$(date +\%Y\%m\%d).db
```

---

## Raspberry Pi (ARM)

> For low-cost 24/7 home operation (Raspberry Pi 4/5 with ARM64).

```bash
# On your local PC:
make arm-build                           # Build ARM64 image
make arm-deploy ARM_PI=pi@192.168.1.100  # Deploy image + code to Pi
```

The bot then runs in the background, accessible via SSH and browser.

---

## Cost Overview

| Setup | Cost/month | Runs 24/7 | HTTPS |
|---|---|---|---|
| Own PC (Mac/Linux/Windows) | €0 (electricity) | Only when PC is on | No |
| Raspberry Pi | ~€2 electricity | Yes | With domain possible |
| QNAP NAS | ~€3 electricity | Yes | With domain possible |
| Hetzner CX22 | ~€5 | Yes | Yes (automatic) |
| DigitalOcean Droplet | ~$12 | Yes | Yes (automatic) |
| AWS EC2 t3.small | ~$15 | Yes | Yes (automatic) |
| Azure B1ms | ~$15 | Yes | Yes (automatic) |

---

## Advanced Cloud Configuration

### Discord + Webhook Alerting

For teams or multi-user setups, Discord is the recommended alerting channel:

```bash
# Create a Discord Webhook:
# Server → Settings → Integrations → Webhooks → Create Webhook → Copy URL

# Add to .env:
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
FEATURE_DISCORD_RPC=true
```

All trade events (buy/sell, drawdown, daily summary) are sent to Discord in addition to Telegram.

For Grafana/PagerDuty/n8n — Generic HTTP Webhook:

```bash
WEBHOOK_URL=https://your-monitoring.com/bot-events
WEBHOOK_SECRET=your-bearer-token   # optional
FEATURE_WEBHOOK_RPC=true
```

Test: **Dashboard → Strategy → "Send test message to all channels"**

---

### Custom Trading Strategy

Deploy your own strategy without modifying the bot core:

```bash
# Upload strategy file to server:
scp my_strategy.py user@server:/opt/trading_bot/strategies/

# In .env:
STRATEGY=MyTrendStrategy
FEATURE_CUSTOM_STRATEGY=true

# Restart:
docker restart trading-bot
```

---

### LightGBM for CPU-optimised Deployments

On servers without GPU, LightGBM is faster than XGBoost and uses less RAM:

```bash
# In .env:
ML_MODEL_TYPE=lightgbm
FEATURE_LIGHTGBM=true

# Install LightGBM (in Docker container):
docker exec trading-bot pip install lightgbm>=4.3.0

# Or add to Dockerfile:
RUN pip install lightgbm>=4.3.0

# Retrain model:
make crypto-train
```

---

### Hyperopt Loss Function on the Server

```bash
# Optimise locally:
HYPEROPT_LOSS=calmar python -m crypto_bot.optimization.hyperopt --trials 100

# Deploy results:
make crypto-deploy-fast
```
