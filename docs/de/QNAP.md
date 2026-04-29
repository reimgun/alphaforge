# QNAP NAS — Dauerbetrieb auf dem Heimserver

[🇬🇧 English](../en/QNAP.md)

---

Der Trading Bot läuft stabil auf einem QNAP TS-451 (Celeron J1900, 8 GB RAM).
Vorteile: 24/7 an, ~20 Watt Stromverbrauch, keine Cloud-Kosten, Daten bleiben lokal.

---

## Voraussetzungen

| Was | Wo installieren |
|-----|----------------|
| **Container Station** | QNAP App Center → Container Station installieren |
| **SSH aktivieren** | QNAP Control Panel → Netzwerkdienste → Telnet/SSH → SSH aktivieren |
| **Git** (optional) | Nicht nötig — deploy-qnap.sh erledigt alles |

---

## Wie es funktioniert

```
Windows WSL/Ubuntu (Training)    QNAP TS-451 (Dauerbetrieb)
─────────────────────────────    ────────────────────────────
make train               →       ai/model.joblib (kopiert)
deploy-qnap.sh           →       Docker Container läuft
                                 Bot-Loop alle 1h
                                 Dashboard Port 8000 (LAN only)
                                 Telegram Alerts + Befehle
```

**Wichtig:** ML-Training läuft unter Windows in WSL/Ubuntu (Celeron J1900 ist zu langsam).

---

## Ersteinrichtung

### Schritt 1 — WSL (Ubuntu) unter Windows einrichten

```powershell
wsl --install
# Startet Ubuntu automatisch, einmal Neustart nötig
```

In Ubuntu:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git make rsync openssh-client python3 python3-pip python3-venv
python3 --version
```

> **Wichtig — Projektpfad:** Das Repository immer im WSL-Dateisystem anlegen:
> ```
> Richtig:   ~/projects/trading_bot     (WSL-Dateisystem, schnell)
> Falsch:    /mnt/c/Users/.../trading_bot  (Windows-Laufwerk, 10× langsamer)
> ```

### Schritt 2 — Bot in WSL einrichten und Modell trainieren

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/reimgun/alphaforge.git
cd trading_bot
bash install.sh
make train
```

### Schritt 3 — SSH-Key auf QNAP hinterlegen (einmalig)

```bash
ssh-keygen -t ed25519 -C "trading-bot-deploy"
ssh-copy-id admin@YOUR_QNAP_IP
```

> QNAP-IP: QNAP Control Panel → Netzwerk → Netzwerkschnittstellen

### Schritt 4 — Deployen

```bash
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Das Skript macht automatisch:
1. Prüft ob `ai/model.joblib` vorhanden ist
2. Überträgt Code + Modell via rsync auf den QNAP
3. Baut den Docker-Container auf dem QNAP
4. Startet Bot + Dashboard als Hintergrund-Dienste
5. Zeigt die Live-Logs zur Bestätigung

---

## Tägliche Nutzung

```bash
make qnap-logs QNAP=admin@YOUR_QNAP_IP    # Live-Logs
make qnap-stop QNAP=admin@YOUR_QNAP_IP    # Bot stoppen
make qnap-deploy QNAP=admin@YOUR_QNAP_IP  # Neu deployen

# Direkt per SSH
ssh admin@YOUR_QNAP_IP
docker ps
docker logs -f trading-bot
```

---

## Code aktualisieren ohne Docker-Rebuild

### qnap-pull — nur Code aktualisieren

```bash
make qnap-pull QNAP=admin@YOUR_QNAP_IP
```

### qnap-pip — einzelnes Paket nachinstallieren

```bash
make qnap-pip QNAP=admin@YOUR_QNAP_IP PKG=streamlit-autorefresh
```

### qnap-update — alles in einem Schritt (empfohlen)

```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

---

## Historische Daten deployen

```bash
make import-history-qnap QNAP=admin@YOUR_QNAP_IP         # 365 Tage
make import-history-qnap QNAP=admin@YOUR_QNAP_IP DAYS=90  # 90 Tage
make import-history-clear-qnap QNAP=admin@YOUR_QNAP_IP   # Löschen + neu
```

---

## Web-Dashboard im lokalen Netzwerk

```
http://YOUR_QNAP_IP:8501       Web-Dashboard (Crypto + Forex Toggle)
http://YOUR_QNAP_IP:8000       Crypto REST API
http://YOUR_QNAP_IP:8000/docs  Crypto API-Dokumentation
http://YOUR_QNAP_IP:8001       Forex REST API
http://YOUR_QNAP_IP:8001/docs  Forex API-Dokumentation
```

---

## Forex Bot auf dem QNAP aktivieren

Der Forex Bot startet automatisch wenn `forex_bot/.env` auf dem QNAP vorhanden ist:

```bash
# Einmalig: .env mit OANDA-Keys auf QNAP übertragen
scp forex_bot/.env admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/forex_bot/.env

# Deployment — startet automatisch beide Bots
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Ohne `forex_bot/.env` werden die Forex-Container übersprungen — der Krypto-Bot läuft wie gewohnt.

Ressourcen beider Bots zusammen:

| Container | RAM | CPU |
|---|---|---|
| trading-bot (Crypto) | 1.500 MB | 2.0 |
| trading-dashboard (Crypto API) | 512 MB | 1.0 |
| trading-streamlit (Dashboard) | 512 MB | 1.0 |
| forex-bot | 256 MB | 0.5 |
| forex-dashboard (Forex API) | 128 MB | 0.5 |
| **Gesamt** | **~2.9 GB** | |

Logs:

```bash
make qnap-logs QNAP=admin@YOUR_QNAP_IP        # Krypto-Logs
make qnap-forex-logs QNAP=admin@YOUR_QNAP_IP  # Forex-Logs
```

---

## Sicherheit im Heimnetz

| Bedrohung | Schutz |
|-----------|--------|
| Zugriff aus dem Internet | FRITZ!Box: **keine** Portweiterleitung für 8000/8001/8501 |
| Fremde im selben WLAN | QNAP-Firewall: nur eigenes Subnetz zulassen |
| Unbefugte Steuerung | API-Key in `.env` setzen |

### QNAP Firewall einrichten

QNAP Control Panel → Sicherheit → Firewall:

1. TCP | `192.168.178.0/24` | Port 8000 | **Zulassen**
2. TCP | `0.0.0.0/0` | Port 8000 | **Ablehnen**
3. TCP | `192.168.178.0/24` | Port 8001 | **Zulassen**
4. TCP | `0.0.0.0/0` | Port 8001 | **Ablehnen**
5. TCP | `192.168.178.0/24` | Port 8501 | **Zulassen**
6. TCP | `0.0.0.0/0` | Port 8501 | **Ablehnen**

### API-Key setzen

```bash
ssh admin@YOUR_QNAP_IP
openssl rand -hex 16
nano /share/CACHEDEV1_DATA/trading_bot/.env
# DASHBOARD_API_KEY=generierter_key
```

---

## Ressourcen auf dem TS-451

### Nur Krypto-Bot

| Komponente | Verbrauch |
|---|---|
| CPU | ~5–15% Ruhe, kurze Spitzen beim Signalgenerieren |
| RAM | ~400–600 MB Bot, ~200 MB Dashboard |
| Festplatte | ~500 MB Code + Modell, DB ~1 MB/Woche |
| Netzwerk | <1 MB/Stunde |

### Krypto + Forex zusammen

| Komponente | Verbrauch |
|---|---|
| CPU | kaum mehr — Forex-Bot schläft 59 von 60 Minuten |
| RAM | +~400 MB (beide Forex-Container) |
| Festplatte | +~1 MB/Woche für Forex-DB |
| Netzwerk | +<0.5 MB/Stunde (OANDA API) |

---

## Limitierungen

### Was geht, was nicht

| Feature | Status | Hinweis |
|---|---|---|
| Paper / Testnet / Live Trading | ✅ | |
| XGBoost Inferenz | ✅ | Millisekunden |
| ML-Training | ⚠️ sehr langsam | 30–60 Min — auf PC machen |
| Auto-Retraining | ❌ deaktivieren | `ML_RETRAIN_AFTER_TRADES=999999` |
| LSTM / PyTorch | ❌ kein AVX2 | Absturz — via `FOREX_LEAN_MODE=true` deaktivieren |
| Online Learning, Anomalie, Regime | ✅ | |
| Regime Forecaster, Black Swan Detector | ✅ | Leichtgewichtig |
| Portfolio Optimizer (Markowitz) | ⚠️ | Mit `FOREX_LEAN_MODE=true` deaktivieren |
| M15 Entry Timer | ⚠️ | Mit `FOREX_LEAN_MODE=true` deaktivieren (spart API-Call) |
| Stress Tester | ⚠️ | Mit `FOREX_LEAN_MODE=true` deaktivieren |
| VPS Failover Daemon | ✅ | Auf VPS als Cronjob empfohlen |
| Claude / Groq / OpenAI | ✅ | Extern |
| Ollama (lokales LLM) | ❌ | Braucht GPU |
| Streamlit Dashboard | ⚠️ | ~20–30s Start |

### Empfohlene `.env` Einstellungen für QNAP

```env
AUTO_TRAIN=false
ML_RETRAIN_AFTER_TRADES=999999
FEATURE_LSTM=false
AI_PROVIDER=groq

# Forex Bot auf QNAP: LEAN_MODE aktivieren
FOREX_LEAN_MODE=true            # Deaktiviert LSTM, Monte Carlo, Portfolio Optimizer
```

`FOREX_LEAN_MODE=true` reduziert den RAM-Bedarf des Forex-Bots von ~256 MB auf ~180 MB und vermeidet
alle Operationen die AVX2-Prozessor-Erweiterungen oder viel RAM benötigen.

---

## Modell aktualisieren

```bash
make train                    # In WSL: neu trainieren
scp ai/model.joblib admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/ai/model.joblib
ssh admin@YOUR_QNAP_IP "docker restart trading-bot"
```

---

## Fehlersuche

**`make` oder `rsync` nicht gefunden**
```bash
sudo apt install -y make rsync openssh-client
```

**`ssh-copy-id` schlägt fehl**
```bash
cat ~/.ssh/id_ed25519.pub | ssh admin@YOUR_QNAP_IP \
  "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

**`qnap-deploy` schlägt fehl — Docker Hub nicht erreichbar**
```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

**Container startet nicht**
```bash
docker logs trading-bot --tail 50
```
- `.env` fehlt → `scp .env admin@YOUR_QNAP_IP:/share/.../trading_bot/.env`
- `model.joblib` fehlt → `scp ai/model.joblib ...`

**RAM-Engpass**
```yaml
# docker-compose.qnap.yml
limits:
  memory: 1000M
```

---

## Firmware-Updates

**Daten und Container bleiben vollständig erhalten.**

| Was | Warum sicher |
|---|---|
| `data_store/trades.db` | NAS-Volume — Firmware fasst das nie an |
| `ai/model.joblib` | Gleiches Volume |
| `.env`, Logs | Gleiches Volume |

Ablauf: Bot stoppt → Neustart (~5–15 Min) → Bot startet automatisch.

**Voraussetzung:** Container Station muss auf Auto-Start stehen.  
QNAP Control Panel → Autostart → Container Station → aktivieren

**Empfehlung:**
```bash
# Telegram: /pause     (Bot vor Update pausieren)
# Firmware-Update durchführen
# Telegram: /resume    (danach fortsetzen)
```

---

## QNAP vs. Cloud-Hoster — Ehrlicher Vergleich

### Kurze Antwort

Für diesen Bot auf H1-Timeframe: **der QNAP reicht vollständig.**  
Mehr Hardware bringt keinen messbaren Mehrgewinn — solange du stündliche Signale tradest.

---

### Was wäre auf einem Hoster besser?

| | QNAP TS-451 (Celeron J1900) | Hetzner CX22 (4 €/Monat) |
|--|--|--|
| **Uptime** | ~99.5% (Heiminternet) | ~99.99% (Rechenzentrum) |
| **Latenz zu OANDA** | 20–150 ms | 5–30 ms (EU-Server) |
| **ML-Training** | ~8 Min. für 5.000 Candles | ~45 Sek. |
| **RAM** | 256 MB reserviert | 4 GB verfügbar |
| **Strom** | ~10 €/Monat extra | inklusive |
| **Kosten** | Einmalig (QNAP schon vorhanden) | 4 €/Monat |
| **Wartung** | Firmware-Updates, Reboots | Keine |
| **H1 Trading-Ergebnis** | **identisch** | **identisch** |

---

### Kann man auf einem Hoster mehr Gewinn machen?

Bei H1-Timeframe: **Nein — nicht messbar.**

Der Gewinn kommt aus der Strategie, nicht aus der Ausführungsgeschwindigkeit.  
Ob die Order 5 ms oder 150 ms nach dem Signal bei OANDA ankommt, macht bei einem Trade der Stunden läuft buchstäblich keinen Unterschied.

**Wann Latenz tatsächlich zählt:**

```
H1  (aktuell)   QNAP reicht vollständig — kein Unterschied
M15             QNAP reicht noch (Timing unkritisch)
M5              Hoster sinnvoll (zuverlässigeres Timing)
M1 / Scalping   Hoster notwendig, idealerweise nahe NY4/LD4
Tick / HFT      Dedizierter Server direkt im Rechenzentrum
```

---

### Was wirklich Einfluss auf den Gewinn hat

1. **Mehr Währungspaare** — statt 3 auf 7–9 erweitern → mehr Signals ohne Hardwarewechsel
2. **Kleinerer Timeframe** — M15/M30 statt H1 → 3–4× mehr Signale pro Tag (Backtest zuerst!)
3. **Mehr Kapital** — bei 1% Risiko/Trade macht die Kontogröße den Unterschied, nicht der Server
4. **Häufigeres ML-Retraining** — auf einem Hoster dauert es 45 Sek. statt 8 Min., deshalb kann `FOREX_RETRAIN_AFTER_TRADES=20` gesetzt werden statt 50

---

### Einziger echter QNAP-Nachteil im Live-Modus

Wenn dein Heiminternet für 1–2 Stunden ausfällt:

- Stop-Loss und Take-Profit sind **server-seitig bei OANDA** — werden auch ohne den Bot ausgelöst ✅
- Der **Trailing Stop** wird während des Ausfalls **nicht nachgezogen** — du lässt potenziellen Gewinn liegen ⚠️
- Neue Signale werden verpasst — aber kein erzwungener Einstieg in einen schlechten Trade

**Fazit:** Kein Totalverlust-Risiko, aber verpasste Optimierungen.

---

### Was auf dem QNAP nicht funktioniert (hardwareseitig)

| Feature | Status | Grund |
|---------|--------|-------|
| LSTM / PyTorch | ❌ | Kein AVX2 auf Celeron J1900 → Absturz |
| Lokales LLM (Ollama) | ❌ | Braucht GPU |
| GARCH via `arch`-Library | ⚠️ | Fallback auf Rolling-Std — funktioniert, nur weniger präzise |
| XGBoost Inferenz | ✅ | Millisekunden |
| XGBoost Training | ⚠️ sehr langsam | Auf PC trainieren, Modell übertragen |
| Alle anderen Bot-Features | ✅ | Keine Einschränkungen |

---

### Was der Bot tut wenn Features nicht verfügbar sind

Der Bot ist so gebaut, dass **kein Feature-Ausfall den Bot stoppt oder Geld verliert**:

| Situation | Was passiert | Sicherheit |
|-----------|-------------|------------|
| `arch` nicht installiert | GARCH → Rolling-Std Fallback | ✅ Bot läuft |
| ML-Modell fehlt | Rule-based only, kein ML-Overlay | ✅ Bot läuft |
| Yahoo Finance blockiert | Hardcoded Fallback-Zinsen | ✅ Bot läuft |
| Kalender-API offline | Fail-Safe: bekannte Risikofenster werden blockiert (NFP, FOMC, CPI) | ✅ Bot pausiert sicher |
| OANDA kurz offline | Instrument überspringen, nächste Stunde Retry | ✅ Kein Fehltrade |
| Trailing Stop Fehler | Log-Warnung, nächste Stunde neu | ⚠️ SL nicht nachgezogen |

---

### Empfehlung

```
Jetzt (Paper/Practice):
  → QNAP — kostet nichts extra, funktioniert für H1 perfekt

Live mit kleinem Kapital (<5.000 €):
  → QNAP weiter nutzen — Stop-Loss ist OANDA-seitig geschützt

Live mit größerem Kapital oder M15-Timeframe:
  → Hetzner CX22 für 4 €/Monat lohnt sich
     Gleicher Code, gleiche .env, nichts anpassen
     python -m forex_bot.bot läuft identisch

Niemals nötig:
  → AWS / GCP / Azure — überteuert für diesen Use Case
  → Dedizierter Server — nur für M1/Scalping relevant
```

### Umzug auf einen Hoster (wenn gewünscht)

```bash
# Hetzner CX22 aufsetzen (Debian 12)
apt install docker.io docker-compose git python3-pip

# Gleicher Ablauf wie QNAP-Deploy
git clone https://github.com/dein-repo/trading_bot.git
cd trading_bot
cp forex_bot/.env.example forex_bot/.env
# .env ausfüllen
python -m forex_bot.bot

# Oder mit Docker (Dockerfile.qnap funktioniert auch auf Hetzner):
docker build -f Dockerfile.qnap -t trading-bot:hetzner .
docker run -d --env-file forex_bot/.env trading-bot:hetzner python -m forex_bot.bot
```

---

## Kompletter Reset

```bash
ssh admin@YOUR_QNAP_IP "
  docker-compose -f /share/CACHEDEV1_DATA/trading_bot/docker-compose.qnap.yml down
  docker rmi trading-bot:qnap
  rm -rf /share/CACHEDEV1_DATA/trading_bot
"
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

> Datenbank vorher sichern:  
> `scp admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/data_store/trades.db ./backup/`
