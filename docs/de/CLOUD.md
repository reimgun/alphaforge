# Cloud & VPS Deployment

[🇬🇧 English](../en/CLOUD.md)

> Der Trading Bot läuft vollständig in Docker — jeder Linux-Server mit 1 GB RAM und Docker reicht aus.  
> Das enthaltene `docker-compose.cloud.yml` richtet automatisch HTTPS (Let's Encrypt) über Traefik ein.

---

## Welcher Anbieter passt zu mir?

| Anbieter | Empfohlener Plan | Preis/Monat | Gut für |
|---|---|---|---|
| [Hetzner Cloud](https://hetzner.com/cloud) | CX22 (2 vCPU, 4 GB) | ~5 € | Europa, günstigste Option |
| [DigitalOcean](https://digitalocean.com) | Basic Droplet (1 vCPU, 2 GB) | ~12 $ | Amerika, einfachstes Interface |
| [AWS EC2](https://aws.amazon.com/ec2) | t3.small (2 vCPU, 2 GB) | ~15 $ | AWS-Ökosystem, Free-Tier verfügbar |
| [Azure VM](https://azure.microsoft.com/de-de/products/virtual-machines) | B1ms (1 vCPU, 2 GB) | ~15 $ | Azure-Ökosystem, Free-Tier verfügbar |
| [Contabo](https://contabo.com) | VPS S (4 vCPU, 8 GB) | ~5 € | Sehr günstig, gut für Anfänger |

**Empfehlung für Einsteiger:** Hetzner Cloud CX22 — günstiger EU-Anbieter, deutsches Rechenzentrum, 1-Klick-Einrichtung.

---

## Vorbereitung (alle Anbieter)

### Was du brauchst

1. **Domain** (optional, aber empfohlen für HTTPS): z.B. `meinbot.de`  
   → Günstige Domains bei [Namecheap](https://namecheap.com) oder [Hetzner Domains](https://hetzner.com/domainregistration)
2. **SSH-Key** auf deinem PC (falls noch nicht vorhanden):
   ```bash
   ssh-keygen -t ed25519 -C "trading-bot"
   ```
3. Dein **öffentlicher SSH-Key** (`~/.ssh/id_ed25519.pub`) — wird beim Server-Erstellen hinterlegt

### Projekt auf deinem PC vorbereiten

```bash
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
bash install.sh      # Setup-Assistent lokal — erstellt .env + trainiert Modell
```

---

## Hetzner Cloud (empfohlen)

### Schritt 1 — Server erstellen

1. Auf [hetzner.com/cloud](https://hetzner.com/cloud) anmelden → **"Neues Projekt"**
2. **"Server erstellen"** klicken
3. Einstellungen:
   - **Standort:** Nürnberg oder Falkenstein (DE)
   - **Image:** Ubuntu 22.04
   - **Typ:** CX22 (2 vCPU, 4 GB RAM) — reicht für Crypto + Forex
   - **SSH-Key:** Deinen öffentlichen Key hochladen/einfügen
   - **Name:** `trading-bot`
4. **"Server erstellen"** — fertig in ~30 Sekunden
5. IP-Adresse notieren (z.B. `49.12.34.56`)

### Schritt 2 — Domain konfigurieren (optional)

In deinem DNS-Provider einen A-Record anlegen:
```
meinbot.de     →  49.12.34.56
```

*(Ohne Domain läuft der Bot auch — du erreichst das Dashboard dann per IP)*

### Schritt 3 — Server einrichten

```bash
# Mit Server verbinden
ssh root@49.12.34.56

# Docker installieren (ein Befehl)
curl -fsSL https://get.docker.com | sh

# Nicht als root deployen (optional aber empfohlen)
useradd -m -s /bin/bash botuser
usermod -aG docker botuser
mkdir -p /home/botuser/.ssh
cp ~/.ssh/authorized_keys /home/botuser/.ssh/
chown -R botuser:botuser /home/botuser/.ssh
```

### Schritt 4 — Bot deployen

Von deinem **lokalen PC**:

```bash
# Code auf den Server übertragen
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='data_store/*.db' --exclude='logs/*' \
    . root@49.12.34.56:/opt/trading_bot/

# .env auf den Server kopieren
scp .env root@49.12.34.56:/opt/trading_bot/.env
scp forex_bot/.env root@49.12.34.56:/opt/trading_bot/forex_bot/.env
```

Auf dem **Server**:

```bash
ssh root@49.12.34.56
cd /opt/trading_bot

# Domain und E-Mail in .env eintragen
echo "DOMAIN=meinbot.de" >> .env
echo "ACME_EMAIL=deine@email.de" >> .env

# Bot starten (mit HTTPS)
docker compose -f docker-compose.cloud.yml up -d

# Status prüfen
docker compose -f docker-compose.cloud.yml ps
```

**Das Dashboard ist jetzt erreichbar unter:**
- `https://meinbot.de` — Streamlit Dashboard (HTTPS, automatisches Zertifikat)
- `https://meinbot.de/api` — REST API
- `https://meinbot.de/forex` — Forex API

---

## DigitalOcean

### Schritt 1 — Droplet erstellen

1. [digitalocean.com](https://digitalocean.com) → **"Create" → "Droplets"**
2. Einstellungen:
   - **Image:** Ubuntu 22.04 LTS
   - **Plan:** Basic — Regular → 2 GB / 1 CPU → ~$12/month
   - **Datacenter:** Frankfurt (für EU-Nutzer)
   - **Authentication:** SSH Key (empfohlen)
3. **"Create Droplet"** klicken

### Schritt 2 — SSH verbinden & Docker installieren

```bash
ssh root@DEINE-DROPLET-IP
curl -fsSL https://get.docker.com | sh
```

### Schritt 3 — Deployen (wie Hetzner)

```bash
# Von lokalem PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . root@DEINE-DROPLET-IP:/opt/trading_bot/
scp .env root@DEINE-DROPLET-IP:/opt/trading_bot/.env

# Auf dem Server:
ssh root@DEINE-DROPLET-IP
cd /opt/trading_bot
echo "DOMAIN=meinbot.de" >> .env
echo "ACME_EMAIL=deine@email.de" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

---

## AWS EC2

> AWS hat ein **Free Tier**: t2.micro (1 vCPU, 1 GB) ist 12 Monate kostenlos.  
> Für den Produktivbetrieb empfehlen wir t3.small (2 vCPU, 2 GB).

### Schritt 1 — EC2 Instance erstellen

1. [AWS Console](https://console.aws.amazon.com) → **EC2** → **"Launch Instance"**
2. Einstellungen:
   - **Name:** `trading-bot`
   - **AMI:** Ubuntu Server 22.04 LTS (HVM)
   - **Instance type:** t3.small (oder t2.micro für Free Tier)
   - **Key pair:** Neues Key Pair erstellen oder vorhandenes wählen → `.pem` herunterladen
   - **Network settings:** Haken bei "Allow SSH traffic from" → "Anywhere"
3. **"Launch Instance"** klicken

### Schritt 2 — Security Group: Ports freigeben

In der EC2-Console → **Security Groups** → deine Gruppe → **"Inbound Rules" → "Edit"**:

| Type | Protocol | Port | Source |
|---|---|---|---|
| SSH | TCP | 22 | Anywhere (oder deine IP) |
| HTTP | TCP | 80 | Anywhere |
| HTTPS | TCP | 443 | Anywhere |

### Schritt 3 — Verbinden & installieren

```bash
# .pem-Datei Rechte setzen (Mac/Linux)
chmod 400 trading-bot.pem

# SSH-Verbindung
ssh -i trading-bot.pem ubuntu@EC2-PUBLIC-IP

# Docker installieren
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker
```

### Schritt 4 — Deployen

```bash
# Von lokalem PC (ersetze EC2-PUBLIC-IP und Pfad zur .pem):
rsync -az -e "ssh -i trading-bot.pem" \
    --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . ubuntu@EC2-PUBLIC-IP:/home/ubuntu/trading_bot/
scp -i trading-bot.pem .env ubuntu@EC2-PUBLIC-IP:/home/ubuntu/trading_bot/.env

# Auf der EC2-Instance:
ssh -i trading-bot.pem ubuntu@EC2-PUBLIC-IP
cd ~/trading_bot
echo "DOMAIN=meinbot.de" >> .env
echo "ACME_EMAIL=deine@email.de" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

### Elastic IP (optional — für feste IP-Adresse)

Die EC2-IP ändert sich bei jedem Neustart. Um eine feste IP zu bekommen:  
**EC2 → Elastic IPs → "Allocate Elastic IP" → "Associate"** → Instance auswählen.

---

## Azure VM

> Azure hat **750 Stunden/Monat Free Tier** für B1s VMs (erste 12 Monate).

### Schritt 1 — VM erstellen

1. [portal.azure.com](https://portal.azure.com) → **"Virtual Machines" → "Create"**
2. Einstellungen:
   - **Resource group:** Neue Gruppe erstellen, z.B. `trading-bot-rg`
   - **VM name:** `trading-bot`
   - **Region:** Germany West Central (oder nächstgelegene)
   - **Image:** Ubuntu Server 22.04 LTS
   - **Size:** B1ms (1 vCPU, 2 GB) oder B2s (2 vCPU, 4 GB)
   - **Authentication:** SSH public key → deinen Key einfügen
3. **"Networking"** Tab:
   - Public IP aktivieren
4. **"Review + create" → "Create"**

### Schritt 2 — Ports freigeben (NSG)

**Networking → "Add inbound port rule"** für:
- Port 22 (SSH)
- Port 80 (HTTP)
- Port 443 (HTTPS)

### Schritt 3 — Verbinden & installieren

```bash
# IP-Adresse in der Azure-Console ablesen
ssh azureuser@AZURE-VM-IP

# Docker installieren
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker azureuser
newgrp docker
```

### Schritt 4 — Deployen

```bash
# Von lokalem PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . azureuser@AZURE-VM-IP:/home/azureuser/trading_bot/
scp .env azureuser@AZURE-VM-IP:/home/azureuser/trading_bot/.env

# Auf der Azure VM:
ssh azureuser@AZURE-VM-IP
cd ~/trading_bot
echo "DOMAIN=meinbot.de" >> .env
echo "ACME_EMAIL=deine@email.de" >> .env
docker compose -f docker-compose.cloud.yml up -d
```

---

## Nach dem Deployment

### HTTPS ohne eigene Domain

Ohne Domain läuft der Bot auf Port 80 ohne HTTPS. Entferne die Traefik-Labels in `docker-compose.cloud.yml` und starte direkt:

```bash
# Ohne HTTPS / ohne Domain
docker compose -f docker-compose.cloud.yml up -d traefik trading-dashboard trading-streamlit
```

Dashboard erreichbar unter: `http://DEINE-SERVER-IP:8501`

### Bot überwachen

```bash
# Alle Container-Status
docker compose -f docker-compose.cloud.yml ps

# Live-Logs (Crypto Bot)
docker compose -f docker-compose.cloud.yml logs -f trading-bot

# Live-Logs (Forex Bot)
docker compose -f docker-compose.cloud.yml logs -f forex-bot

# Ressourcenverbrauch
docker stats
```

### Updates einspielen

```bash
# Von lokalem PC:
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    . user@SERVER-IP:/opt/trading_bot/

# Auf dem Server:
ssh user@SERVER-IP
cd /opt/trading_bot
docker compose -f docker-compose.cloud.yml up -d --build
```

### PostgreSQL aktivieren (optional)

Für höhere Last oder wenn du die Datenbankdaten behalten möchtest:

```bash
# In .env:
DB_BACKEND=postgres
POSTGRES_USER=trading
POSTGRES_PASSWORD=sicheres_passwort

# Starten mit Postgres:
docker compose -f docker-compose.cloud.yml --profile postgres up -d
```

---

## Sicherheit (Produktivbetrieb)

### Firewall mit UFW einrichten

```bash
ufw allow ssh
ufw allow http
ufw allow https
ufw enable
```

### Automatische Updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

### Backups

```bash
# Datenbankdatei täglich sichern (crontab -e):
0 3 * * * cp /opt/trading_bot/data_store/trading.db /opt/backups/trading_$(date +\%Y\%m\%d).db
```

---

## Raspberry Pi (ARM)

> Für einen preisgünstigen 24/7-Betrieb zu Hause (Raspberry Pi 4/5 mit ARM64).

```bash
# Auf deinem lokalen PC:
make arm-build                          # ARM64 Image bauen
make arm-deploy ARM_PI=pi@192.168.1.100 # Image + Code auf Pi deployen
```

Vollständige Anleitung: Der Bot läuft dann im Hintergrund, erreichbar per SSH und Browser.

---

## Kosten-Übersicht

| Setup | Kosten/Monat | Läuft 24/7 | HTTPS |
|---|---|---|---|
| Eigener PC (Mac/Linux/Windows) | 0 € (Strom) | Nur wenn PC an | Nein |
| Raspberry Pi | ~2 € Strom | Ja | Mit Domain möglich |
| QNAP NAS | ~3 € Strom | Ja | Mit Domain möglich |
| Hetzner CX22 | ~5 € | Ja | Ja (automatisch) |
| DigitalOcean Droplet | ~12 $ | Ja | Ja (automatisch) |
| AWS EC2 t3.small | ~15 $ | Ja | Ja (automatisch) |
| Azure B1ms | ~15 $ | Ja | Ja (automatisch) |

---

## Erweiterte Cloud-Konfiguration

### Discord + Webhook Alerting

Für Teams oder Multi-User-Setups empfiehlt sich Discord als Alerting-Kanal:

```bash
# Discord Webhook erstellen:
# Server → Einstellungen → Integrationen → Webhooks → Webhook erstellen → URL kopieren

# In .env eintragen:
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
FEATURE_DISCORD_RPC=true
```

Alle Trade-Events (Kauf/Verkauf, Drawdown, Daily Summary) werden dann zusätzlich zu Discord gesendet.

Für Grafana/PagerDuty/n8n: Generic HTTP Webhook:

```bash
WEBHOOK_URL=https://your-monitoring.com/bot-events
WEBHOOK_SECRET=your-bearer-token   # optional
FEATURE_WEBHOOK_RPC=true
```

Test: **Dashboard → Strategie → "Test-Nachricht an alle Kanäle senden"**

---

### Custom Trading-Strategie

Eigene Strategien ohne Code-Änderungen:

```bash
# Strategie-Datei auf dem Server ablegen:
scp my_strategy.py user@server:/opt/trading_bot/strategies/

# In .env:
STRATEGY=MyTrendStrategy
FEATURE_CUSTOM_STRATEGY=true

# Restart:
docker restart trading-bot
```

---

### LightGBM für CPU-optimierte Deployments

Auf Servern ohne GPU empfiehlt sich LightGBM (schneller als XGBoost, weniger RAM):

```bash
# In .env:
ML_MODEL_TYPE=lightgbm
FEATURE_LIGHTGBM=true

# LightGBM installieren (in Docker-Container):
docker exec trading-bot pip install lightgbm>=4.3.0

# Oder in Dockerfile hinzufügen:
RUN pip install lightgbm>=4.3.0

# Modell neu trainieren:
make crypto-train
```

---

### Hyperopt-Loss auf dem Server

```bash
# Lokal optimieren:
HYPEROPT_LOSS=calmar python -m crypto_bot.optimization.hyperopt --trials 100

# Ergebnis in .env übertragen:
make crypto-deploy-fast
```
