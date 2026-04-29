# Installationsanleitung

[🇬🇧 English](../en/INSTALL.md)

---

## Was ist Paper-Trading?

> Bevor du echtes Geld einsetzt, empfehlen wir dringend den **Paper-Modus**.  
> Der Bot handelt dabei mit **virtuellem Geld** — kein echtes Kapital wird riskiert.  
> Du siehst genau wie er entscheidet, wie hoch die Gewinne und Verluste wären.  
> Erst wenn du mit der Performance zufrieden bist, aktivierst du echtes Trading.

---

## Welche Installation passt zu dir?

```
Frage 1: Hast du ein QNAP NAS?
  JA  →  QNAP NAS Anleitung: docs/de/QNAP.md
  NEIN ↓

Frage 2: Möchtest du in der Cloud hosten (AWS / Azure / Hetzner)?
  JA  →  Cloud Anleitung: docs/de/CLOUD.md
  NEIN ↓

Frage 3: Hast du einen Raspberry Pi?
  JA  →  Raspberry Pi (weiter unten auf dieser Seite)
  NEIN ↓

Frage 4: Welches Betriebssystem?
  Mac / Linux  →  Mac/Linux (weiter unten)
  Windows      →  Windows (weiter unten)
```

---

## 💻 Mac / Linux

> **Zeitaufwand: ca. 10 Minuten**  
> Du brauchst: einen Mac oder Linux-PC, eine Internetverbindung

### Schritt 1 — Python installieren

Prüfe zuerst ob Python bereits installiert ist. Öffne das **Terminal** (Mac: Spotlight → "Terminal") und tippe:

```bash
python3 --version
```

Wenn eine Versionsnummer erscheint (z.B. `Python 3.12.0`) — **weiter zu Schritt 2**.

Wenn du eine Fehlermeldung bekommst:

**Mac:**
```bash
# Homebrew installieren (falls noch nicht vorhanden)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python installieren
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git make
```

---

### Schritt 2 — Projekt herunterladen

```bash
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
```

> **Kein Git?** Auf GitHub oben rechts auf **"Code" → "Download ZIP"** klicken, entpacken, Terminal in den Ordner navigieren.

---

### Schritt 3 — Installation starten (One-Click)

```bash
bash install.sh
```

Das Skript führt dich durch alle Fragen:

```
? Handelsmodus: paper (virtuell, empfohlen) oder live?   → paper
? Startkapital in USDT (virtuell):                       → 1000
? KI-Modus:                                              → ml (empfohlen)
? Telegram-Alerts einrichten?                            → n (erstmal nein)
? KI-Modell jetzt trainieren? (~3-5 Min)                 → j
? Bot jetzt starten?                                     → j
```

**Das war's. Der Bot läuft.**

---

### Schritt 4 — Bot überwachen (optional)

Live-Logs im Terminal anzeigen:
```bash
make logs
```

Web-Dashboard öffnen (zweites Terminal-Fenster):
```bash
make dashboard-api   # Terminal 2 — Backend
make dashboard       # Terminal 3 — Oberfläche
```
Dann im Browser: **http://localhost:8501**

---

### Bot neu starten (nach PC-Neustart)

```bash
cd trading_bot
source .venv/bin/activate
make start
```

---

## 🪟 Windows

> **Zeitaufwand: ca. 15 Minuten**  
> Du brauchst: einen Windows-PC (Win 10 oder neuer), eine Internetverbindung

### Schritt 1 — Python installieren

1. Öffne den **Microsoft Store**
2. Suche nach **"Python 3.12"**
3. Klicke auf **Installieren**

**Oder:** Lade Python direkt herunter: [python.org/downloads](https://python.org/downloads)  
→ Den **ersten Download-Button** klicken → Installieren  
→ **Wichtig:** Beim Installieren den Haken bei **"Add Python to PATH"** setzen!

Prüfen ob Python funktioniert — öffne die **Eingabeaufforderung** (Windows-Taste → "cmd" eingeben):
```
python --version
```
Es sollte `Python 3.x.x` erscheinen.

---

### Schritt 2 — Projekt herunterladen

**Option A — Mit Git (empfohlen):**

Git herunterladen: [git-scm.com/download/win](https://git-scm.com/download/win) → Installieren  
Dann in der Eingabeaufforderung:
```
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
```

**Option B — Als ZIP:**
1. Auf GitHub oben rechts auf **"Code"** klicken → **"Download ZIP"**
2. ZIP entpacken (Rechtsklick → "Alle extrahieren")
3. Den entpackten Ordner öffnen

---

### Schritt 3 — Installation starten

**Option A — Doppelklick (einfachste Methode):**

1. Öffne den Projektordner im Windows Explorer
2. **Doppelklick auf `install.bat`**

Ein schwarzes Fenster öffnet sich und führt dich durch alle Fragen.

> Falls Windows eine Sicherheitswarnung zeigt: **"Weitere Informationen" → "Trotzdem ausführen"** klicken.

**Option B — PowerShell (kein WSL2 nötig, empfohlen für neuere Windows-Versionen):**

1. Rechtsklick auf `install.ps1` → **"Mit PowerShell ausführen"**  
   (Oder: PowerShell öffnen, in den Projektordner navigieren, `.\install.ps1` eingeben)

```
? Exchange wählen:                                       → binance (oder anderer)
? Handelsmodus: paper (virtuell, empfohlen) oder live?   → paper
? Startkapital in USDT (virtuell):                       → 1000
? Risikoprofil:                                          → balanced
? Telegram-Alerts einrichten?                            → n (erstmal nein)
? KI-Modell jetzt trainieren? (~3-5 Min)                 → j
? Bot jetzt starten?                                     → j
```

**Das war's. Der Bot läuft.**

---

### Schritt 4 — Bot überwachen (optional)

In der Eingabeaufforderung:
```
make logs
```

Web-Dashboard (zwei separate Eingabeaufforderungsfenster öffnen):
```
# Fenster 1:
make dashboard-api

# Fenster 2:
make dashboard
```
Dann im Browser: **http://localhost:8501**

---

### Bot neu starten (nach PC-Neustart)

Eingabeaufforderung öffnen, in den Projektordner navigieren:
```
cd C:\Pfad\zu\trading_bot
.venv\Scripts\activate
make start
```

---

## 📦 QNAP NAS (24/7-Betrieb)

> **Für wen ist das?** Wer den Bot dauerhaft laufen lassen möchte, ohne den eigenen PC ständig eingeschaltet zu lassen. Ein QNAP NAS verbraucht nur ~20 Watt, läuft aber rund um die Uhr.  
>  
> **Zeitaufwand: ca. 30–45 Minuten (Ersteinrichtung)**  
> **Danach: Updates in 1 Minute mit einem Befehl**

### Voraussetzungen

| Was | Wo einrichten |
|---|---|
| QNAP NAS mit Container Station | QNAP App Center → "Container Station" installieren |
| SSH aktiviert | QNAP Control Panel → Netzwerkdienste → SSH aktivieren |
| Dein PC: Mac, Linux oder Windows mit WSL | Für das Deployment (einmalige Einrichtung) |

---

### Windows-Nutzer: WSL einrichten (einmalig, ~5 Min)

WSL = Windows Subsystem for Linux — eine Linux-Umgebung direkt in Windows.  
Das brauchst du nur einmalig einzurichten:

1. **PowerShell als Administrator öffnen** (Windows-Taste → "PowerShell" → Rechtsklick → "Als Administrator ausführen")
2. Folgenden Befehl eingeben:
```powershell
wsl --install
```
3. PC neu starten wenn aufgefordert
4. Nach dem Neustart öffnet sich Ubuntu automatisch — einen Benutzernamen und Passwort vergeben
5. In Ubuntu ausführen:
```bash
sudo apt update && sudo apt install -y git make rsync openssh-client python3 python3-pip python3-venv
```

> **Wichtig:** Führe alle folgenden Befehle im **Ubuntu-Fenster** aus, nicht in PowerShell.

---

### Schritt 1 — Projekt auf deinem PC einrichten

Öffne das Terminal (Mac/Linux) oder das Ubuntu WSL-Fenster (Windows):

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot

# Ersteinrichtung (.env Datei mit Einstellungen erstellen)
bash install.sh
```

Beim `install.sh` für QNAP:
- Handelsmodus: `paper` (beginne mit Paper Trading)
- KI-Modell **jetzt trainieren**: JA (dauert 3–5 Min, läuft auf deinem PC, nicht auf dem QNAP)
- Bot starten: **NEIN** (er startet später auf dem QNAP)

---

### Schritt 2 — SSH-Schlüssel auf QNAP hinterlegen (einmalig)

Damit du dich später ohne Passwort verbinden kannst:

```bash
# SSH-Schlüssel generieren (nur wenn noch keiner vorhanden)
ssh-keygen -t ed25519 -C "trading-bot"
# Fragen mit Enter bestätigen (kein Passwort nötig)

# Schlüssel auf QNAP übertragen (einmalig Passwort eingeben)
ssh-copy-id admin@YOUR_QNAP_IP
```

> Deine QNAP-IP findest du unter:  
> **QNAP Control Panel → Netzwerk → Netzwerkschnittstellen**

---

### Schritt 3 — Bot auf QNAP deployen (One-Click)

```bash
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Ersetze `YOUR_QNAP_IP` mit der IP-Adresse deines QNAP.

Das Skript macht automatisch:
1. Prüft ob das KI-Modell vorhanden ist
2. Überträgt Code + Modell auf den QNAP
3. Baut den Docker-Container auf dem QNAP
4. Startet Bot + Dashboard als Hintergrund-Dienste
5. Zeigt die Live-Logs zur Bestätigung

**Bot läuft jetzt auf dem QNAP — auch wenn du den PC ausschaltest.**

---

### Dashboard im Browser aufrufen

```
http://YOUR_QNAP_IP:8501    Web-Dashboard
http://YOUR_QNAP_IP:8000    REST API
```

*(Nur aus dem eigenen Heimnetzwerk erreichbar — von außen nicht sichtbar)*

---

### Tägliche Nutzung

```bash
# Logs live verfolgen
make qnap-logs QNAP=admin@YOUR_QNAP_IP

# Bot stoppen
make qnap-stop QNAP=admin@YOUR_QNAP_IP

# Code-Update einspielen (nach Änderungen)
make qnap-update QNAP=admin@YOUR_QNAP_IP

# Diagnose — Status, Performance, letzte Signale
make diagnose-qnap QNAP=admin@YOUR_QNAP_IP
```

---

### KI-Modell auf QNAP aktualisieren

Das ML-Training läuft immer auf deinem PC (der QNAP-Prozessor ist zu schwach dafür).  
Nach dem Training überträgst du das neue Modell mit einem Befehl:

```bash
# Auf deinem PC: neu trainieren + auf QNAP übertragen
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## ☁️ Server / VPS (Gehosteter Betrieb)

> **Für wen ist das?** Wer keinen eigenen 24/7-Server hat, aber den Bot dauerhaft laufen lassen möchte. Ein VPS kostet ~5–15 €/Monat bei Anbietern wie Hetzner, DigitalOcean, Netcup oder Contabo.  
>  
> **Anforderungen: 1 CPU, 1 GB RAM, 10 GB Speicher, Ubuntu 22.04**  
> **Zeitaufwand: ca. 20 Minuten**

---

### Schritt 1 — Server mieten

Empfohlene Anbieter (günstig, zuverlässig):

| Anbieter | Kleinster Plan | Preis/Monat |
|---|---|---|
| [Hetzner Cloud](https://hetzner.com/cloud) | CX11 (1 CPU, 2 GB RAM) | ~4 € |
| [Contabo](https://contabo.com) | VPS S (4 CPU, 8 GB RAM) | ~5 € |
| [Netcup](https://netcup.de) | VPS 500 G11s | ~4 € |
| [DigitalOcean](https://digitalocean.com) | Droplet Basic | ~6 $ |

Beim Erstellen: **Ubuntu 22.04 LTS** als Betriebssystem wählen.

---

### Schritt 2 — Per SSH verbinden

Nach der Server-Erstellung erhältst du eine IP-Adresse und Root-Passwort.

**Mac/Linux:**
```bash
ssh root@DEINE-SERVER-IP
```

**Windows:** PuTTY herunterladen ([putty.org](https://putty.org)), IP eingeben, verbinden.

---

### Schritt 3 — Docker installieren (einmalig)

```bash
# System aktualisieren
apt update && apt upgrade -y

# Docker installieren (offizielles Skript)
curl -fsSL https://get.docker.com | sh

# Testen
docker --version
```

---

### Schritt 4 — Bot einrichten

```bash
# Git installieren
apt install -y git

# Projekt herunterladen
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot

# Konfigurationsdatei erstellen
cp .env.example .env
nano .env
```

In der `.env` Datei mindestens diese Werte setzen:

```env
TRADING_MODE=paper        # Mit virtuellem Geld beginnen
INITIAL_CAPITAL=1000      # Virtuelles Startkapital

# Optional: Telegram-Benachrichtigungen
# TELEGRAM_TOKEN=dein_token
# TELEGRAM_CHAT_ID=deine_chat_id
```

Datei speichern: `Strg+O`, dann `Enter`, dann `Strg+X`

---

### Schritt 5 — Bot starten (One-Click mit Docker)

```bash
docker compose up -d
```

Das ist alles. Docker lädt alle nötigen Pakete, baut den Container und startet Bot + Dashboard.

**Bot läuft jetzt dauerhaft im Hintergrund.**

---

### Schritt 6 — Dashboard erreichbar machen (optional)

```
http://DEINE-SERVER-IP:8501
```

> **Sicherheitshinweis:** Setze einen API-Key in der `.env` Datei:  
> `DASHBOARD_API_KEY=ein_langes_zufälliges_passwort`

---

### Tägliche Nutzung auf dem Server

```bash
docker compose logs -f bot   # Logs live
docker compose ps            # Status
docker compose down          # Stoppen
docker compose up -d         # Starten
git pull && docker compose up -d --build  # Aktualisieren
```

---

## 🥧 Raspberry Pi (ARM)

> **Für wen ist das?** Wer den Bot dauerhaft zu Hause für ~5–10 € Stromkosten im Monat laufen lassen möchte.  
> **Voraussetzung:** Raspberry Pi 4 oder 5 mit 64-Bit OS (Raspberry Pi OS Lite 64-bit empfohlen)  
> **Zeitaufwand: ca. 20 Minuten**

### Schritt 1 — Raspberry Pi vorbereiten

Docker auf dem Pi installieren (einmalig):

```bash
# Per SSH mit Pi verbinden
ssh pi@raspberrypi.local

# Docker installieren
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker pi
```

### Schritt 2 — Image bauen + deployen (von deinem PC)

```bash
# Auf deinem lokalen PC (benötigt Docker mit buildx):
make arm-build                          # ARM64 Image bauen (~5-10 Min)
make arm-deploy                         # Image + Code auf Pi übertragen + starten
# → Default: pi@raspberrypi.local

# Mit eigener IP:
make arm-deploy ARM_PI=pi@192.168.1.100
```

Das Script macht automatisch:
1. Überträgt Code per rsync
2. Überträgt Docker Image per `docker save | docker load`
3. Startet den Container auf dem Pi

### Dashboard aufrufen

```
http://raspberrypi.local:8000    Crypto API
```

> Der Pi hat keinen AVX2-Chip — LSTM ist automatisch deaktiviert (`FEATURE_LSTM=false`).  
> Das XGBoost-ML-Modell läuft problemlos.

---

## 🔑 API-Keys einrichten (nur für Live-Trading)

> **Für Paper-Trading brauchst du keine API-Keys!**

Der Setup-Assistent führt dich durch die Einrichtung. Hier die wichtigsten Exchanges:

**Binance:**
1. Auf [binance.com](https://binance.com) anmelden → Profilbild → **"API Management"** → **"API erstellen"**
2. **Berechtigungen:** ✅ Spot Trading — ❌ Auszahlungen **NIEMALS** aktivieren
3. IP-Beschränkung eintragen
4. In `.env` eintragen: `BINANCE_API_KEY=...` / `BINANCE_API_SECRET=...`

**Alpaca (Aktien + Crypto, Paper-Trading gratis):**
1. Auf [alpaca.markets](https://alpaca.markets) anmelden → **"Paper Trading"**
2. API Keys im Dashboard generieren
3. In `.env` eintragen: `ALPACA_API_KEY_PAPER=...` / `ALPACA_API_SECRET_PAPER=...`

**Weitere Exchanges:** Der Setup-Assistent zeigt dir den Link zur API-Key-Seite für jeden unterstützten Exchange.

---

## 🆘 Häufige Probleme

**"python: command not found"**  
→ Python neu installieren, **"Add to PATH"** aktivieren.

**"make: command not found" (Windows)**  
→ `python install.py` statt `make start` verwenden.

**"Permission denied" beim SSH auf QNAP**
```bash
cat ~/.ssh/id_ed25519.pub | ssh admin@YOUR_QNAP_IP \
  "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

**Bot macht keine Trades**  
→ Normal in Bärenmärkten. Prüfe: `make diagnose` oder `make logs`

**"Docker Hub not reachable" beim QNAP-Deploy**
```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

**KI-Modell F1-Score zu niedrig**
```bash
make train
# oder für QNAP:
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## ✅ Nächste Schritte

1. **Paper Trading ein paar Wochen laufen lassen**
2. **Dashboard beobachten** — Equity-Kurve, Win-Rate, Sharpe Ratio
3. **Telegram einrichten** — Push-Nachricht bei jedem Trade
4. **Erst nach guter Performance: Live-Trading aktivieren**
