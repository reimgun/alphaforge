# Docker Deployment

[🇬🇧 English](../en/DOCKER.md)

---

Für stabilen, dauerhaften Betrieb — läuft 24/7 im Hintergrund.  
Startet automatisch neu nach Abstürzen oder Server-Reboots.

## Voraussetzungen

- [Docker Desktop](https://docker.com/products/docker-desktop) installiert  
- `.env` Datei konfiguriert (siehe [Konfiguration](CONFIG.md) oder [Installationsanleitung](INSTALL.md))

---

## Start (ein Befehl)

```bash
# Bot bauen und starten
make docker-run

# Status prüfen
docker ps

# Logs live anzeigen
make docker-logs

# Stoppen
make docker-stop
```

---

## Was Docker macht

- Bot läuft im Hintergrund — auch wenn das Terminal geschlossen wird
- Startet automatisch neu bei Absturz (`restart: unless-stopped`)
- Startet automatisch nach Server-Neustart
- Trades, Logs und ML-Modell bleiben durch Volumes erhalten

---

## Datei-Volumes

| Lokaler Pfad | Container-Pfad | Inhalt |
|---|---|---|
| `./data_store/` | `/app/data_store/` | SQLite Datenbank, Bot-State |
| `./logs/` | `/app/logs/` | Log-Dateien |
| `./ai/` | `/app/ai/` | Trainiertes ML-Modell |

---

## KI-Modell im Container trainieren

```bash
docker compose run --rm bot python -m ai.trainer
```

---

## Web-Dashboard mit Docker

```bash
# Alle Services (Bot + API + Dashboard) starten
docker compose up -d

# Dashboard im Browser aufrufen:
# http://localhost:8501   — Web-Dashboard
# http://localhost:8000   — REST API
# http://localhost:8000/docs — API-Dokumentation
```

---

## Server-Deployment (Linux VPS)

```bash
# 1. Server per SSH verbinden
ssh root@DEINE-SERVER-IP

# 2. Docker installieren (einmalig)
curl -fsSL https://get.docker.com | sh

# 3. Repository klonen
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot

# 4. Konfiguration erstellen
cp .env.example .env
nano .env

# 5. Starten
docker compose up -d
```

---

## Logs überwachen

```bash
docker compose logs -f bot        # Bot-Logs live
docker compose logs -f api        # Dashboard-API-Logs
docker compose logs -f            # Alle Container
make docker-logs                  # Kurzbefehl
```

---

## Update einspielen

```bash
git pull
docker compose up -d --build
```

---

## Ressourcenverbrauch

| Komponente | CPU (Ruhe) | RAM |
|---|---|---|
| Bot | < 5% | ~300–500 MB |
| Dashboard API | < 2% | ~100 MB |
| Dashboard UI | < 2% | ~200 MB |
| **Gesamt** | **< 10%** | **~600–800 MB** |

Netzwerk: minimal — API-Calls alle 1–4 Stunden.

---

## QNAP NAS

Für den Betrieb auf einem QNAP NAS gibt es eine eigene optimierte Konfiguration.  
→ **[QNAP.md](QNAP.md)** — Vollständige Anleitung
