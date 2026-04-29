# Web-Dashboard

[🇬🇧 English](../en/DASHBOARD.md)

---

## Start

```bash
# Terminal 1 — API Backend (Port 8000)
make dashboard-api

# Terminal 2 — Web-Oberfläche (Port 8501)
make dashboard
```

Dann im Browser öffnen: **http://localhost:8501**

Bei QNAP: **http://YOUR_QNAP_IP:8501**

---

## Was das Dashboard zeigt

### Oben: Live-Status

| Anzeige | Bedeutung |
|---------|-----------|
| **Kapital** | Aktueller Kontostand + % Veränderung seit Start |
| **Tages-PnL** | Heutiger Gewinn/Verlust |
| **Markt-Regime** | BULL / BEAR / SIDEWAYS / HIGH_VOL |
| **Volatilität** | LOW / NORMAL / HIGH / EXTREME |
| **AI Konfidenz** | Aktueller Konfidenz-Score + aktive Strategie |

### Mitte: Equity-Kurve

Kapitalverlauf über die gesamte Laufzeit.  
Grün = über Startkapital, Rot = darunter.

### Rechts: Offene Position

Entry-Preis, aktueller Preis, Stop-Loss, Take-Profit und unrealisierter PnL.

### Performance-Metriken

- Gesamt-PnL + Return %
- Win-Rate (Gewinner / Verlierer)
- Sharpe Ratio / Sortino Ratio
- Max Drawdown
- Profit Factor

---

## Phase-Fortschrittsbalken

```
Phase: Paper Trading  ████████████░░░░░░░░  62%
```

| Kriterium | Ziel |
|-----------|------|
| Trades | ≥ 20 abgeschlossen |
| Sharpe Ratio | ≥ 0.8 |
| Win-Rate | ≥ 48% |
| Max Drawdown | ≤ 15% |
| Model F1 | ≥ 0.38 |

---

## Tabs

| Tab | Inhalt |
|-----|--------|
| **Übersicht** | Live-Status, Equity-Kurve, Position, Performance, Phase-Fortschritt |
| **Wöchentlich/Monatlich** | PnL-Balkendiagramme, Rolling 7d/30d Metriken |
| **Trade History** | Letzte 20 Trades als farbkodierte Tabelle |
| **Strategie-Performance** | PnL, Win-Rate und Konfidenz-Multiplikator pro Strategie |
| **AI Explainability** | Letzter HOLD-Grund, Model Drift, Trade Rejection Log, letzte Signale |
| **📜 Logs** | Live Log-Viewer mit Filter und manuell Refresh |

---

## Sidebar-Controls

| Button | Funktion |
|--------|---------|
| **▶ Start Bot** | Bot starten (nur wenn nicht läuft) |
| **⛔ Stop** | Bot stoppen |
| **📄 Paper** | Auf Paper-Modus wechseln |
| **⏸ Pause** | Trading pausieren |
| **▶️ Resume** | Trading fortsetzen |
| **🛡️ Safe Mode** | Positionsgröße auf 50% reduzieren |
| **🔄 Retrain** | Modell-Retraining anfordern |
| **📥 CSV** | Trades als CSV exportieren |
| **📊 JSON** | Performance als JSON exportieren |

**Log-Level** (Sidebar): DEBUG / INFO / WARNING / ERROR — ändert sich sofort.

**Refresh-Intervall** (Sidebar): 10–120 Sekunden (Standard: 30s).

---

## Risk Mode Buttons (Sidebar)

| Button | Risiko/Trade | Max Drawdown |
|--------|-------------|--------------|
| 🛡️ conservative | 1% | 10% |
| ⚖️ balanced | 2% | 20% |
| 🔥 aggressive | 3% | 30% |

Wechsel wird sofort wirksam — kein Neustart nötig.

---

## REST API

Alle Daten sind als API verfügbar unter `http://localhost:8000`:

```
GET  /api/status          Bot-Status, Kapital, Position, Regime
GET  /api/trades          Letzte Trades (limit=50)
GET  /api/performance     KPIs (Sharpe, Win-Rate, Drawdown ...)
GET  /api/equity          Equity-Kurve
GET  /api/signals         Letzte AI-Signale
GET  /api/model           ML-Modell Info
GET  /api/rejections      Letzte abgelehnte Trades
GET  /api/progress        Phase-Fortschritt Paper→Testnet→Live
GET  /api/exposure        Global Exposure Controller Status
GET  /api/logs            Letzte Log-Einträge
GET  /api/export/csv      Trades als CSV
GET  /api/export/json     Performance als JSON

POST /api/control/start
POST /api/control/stop
POST /api/control/pause
POST /api/control/resume
POST /api/control/safe_mode
POST /api/control/retrain
POST /api/control/risk_mode/{mode}
POST /api/control/log_level/{level}
```

Swagger-Dokumentation: **http://localhost:8000/docs**

---

## Sicherheit

Control-Endpunkte können mit einem API-Key gesichert werden:

```env
DASHBOARD_API_KEY=mein-geheimes-passwort
```

GET-Endpunkte (Lesen) sind immer offen.  
**Empfehlung für QNAP/Heimnetz:** Immer einen API-Key setzen.
