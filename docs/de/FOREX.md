# Forex Bot — Schritt-für-Schritt Anleitung

[🇬🇧 English](../en/FOREX.md)

---

> **Für Anfänger:** Diese Anleitung erklärt jeden Schritt vom leeren Laptop bis zum laufenden Bot.  
> Kein Vorwissen über Forex oder Trading nötig.

---

## Inhaltsverzeichnis

1. [Was der Bot macht](#1-was-der-bot-macht)
2. [Was bedeuten H1, H4, M5 usw.?](#2-was-bedeuten-h1-h4-m5-usw)
3. [OANDA Account anlegen](#3-oanda-account-anlegen)
4. [Telegram Bot anlegen](#4-telegram-bot-anlegen)
5. [Bot installieren](#5-bot-installieren)
6. [Bot starten](#6-bot-starten)
7. [Was passiert jetzt? — Der Zyklus erklärt](#7-was-passiert-jetzt--der-zyklus-erklärt)
8. [ML-Modell trainieren](#8-ml-modell-trainieren)
9. [Backtest durchführen](#9-backtest-durchführen)
10. [Die drei Phasen: Paper → Practice → Live](#10-die-drei-phasen-paper--practice--live)
11. [Telegram-Befehle](#11-telegram-befehle)
12. [Risk-Modi: conservative / balanced / aggressive](#12-risk-modi)
13. [Alle Features im Überblick](#13-alle-features-im-überblick)
14. [QNAP Deployment](#14-qnap-deployment)
15. [Konfigurationsreferenz](#15-konfigurationsreferenz)
16. [Häufige Fragen](#16-häufige-fragen)

---

## 1. Was der Bot macht

Der Forex-Bot handelt **Währungspaare** (z.B. EUR/USD) vollautomatisch — 24/5, ohne dass du etwas tun musst.

**Was er konkret tut:**
- Liest stündlich Kursdaten von OANDA (kostenloser Practice Account)
- Berechnet technische Indikatoren (EMA, MACD, RSI)
- Entscheidet: Kaufen / Verkaufen / Nichts tun
- Prüft 10 Sicherheitsfilter bevor ein Trade eröffnet wird
- Setzt automatisch Stop-Loss und Take-Profit
- Zieht den Stop-Loss nach (Trailing Stop)
- Schickt dir Nachrichten via Telegram

**Was er NICHT tut:**
- Garantiert keine Gewinne — Trading birgt immer Risiken
- Startet ohne deinen Practice Account nicht

---

## 2. Was bedeuten H1, H4, M5 usw.?

In Trading-Charts gibt es Kerzen (Candles) — jede Kerze zeigt die Preisbewegung eines bestimmten Zeitraums.  
Die Kürzel sagen dir, wie lang dieser Zeitraum ist:

| Kürzel | Bedeutung | Eine Kerze zeigt |
|--------|-----------|-----------------|
| **M1** | 1 Minute | 1 Min. Preisbewegung |
| **M5** | 5 Minuten | 5 Min. Preisbewegung |
| **M15** | 15 Minuten | 15 Min. Preisbewegung |
| **M30** | 30 Minuten | 30 Min. Preisbewegung |
| **H1** | 1 Stunde | 1 Std. Preisbewegung |
| **H4** | 4 Stunden | 4 Std. Preisbewegung |
| **D1** | 1 Tag (Daily) | 1 Tag Preisbewegung |
| **W1** | 1 Woche (Weekly) | 1 Woche Preisbewegung |
| **MN** | 1 Monat | 1 Monat Preisbewegung |

**Wie dieser Bot die Timeframes nutzt:**

```
H1  → Haupt-Timeframe
      Der Bot wacht jede Stunde auf, analysiert H1-Kerzen und
      entscheidet: kaufen / verkaufen / nichts tun.

H4  → Trend-Bestätigung (Multi-Timeframe, MTF)
      Bevor ein H1-Signal ausgelöst wird: stimmt der 4h-Trend überein?
      H1 sagt BUY, aber H4-Trend zeigt DOWN → Signal wird geschwächt.

D1  → Übergeordneter Trend
      Die große Richtung des Markts. Der Bot handelt nicht gegen
      den D1-Trend wenn das MTF-Feature aktiv ist.
```

**Faustregeln:**
- **Kleinerer Timeframe** (M1, M5) = mehr Signale, mehr Rauschen, mehr Serverleistung nötig
- **Größerer Timeframe** (H4, D1) = weniger Signale, sauberere Trends, weniger Fehlsignale
- **H1** ist ideal für einen 24/7-Bot auf dem QNAP — genug Signale, nicht überwältigend

---

## 3. Broker wählen

Der Bot unterstützt vier Broker — wähle den, der für dich am besten passt.  
Setze `FOREX_BROKER` in deiner `.env`-Datei entsprechend.

| Broker | `FOREX_BROKER=` | Gratis Demo | Hinweis |
|--------|----------------|-------------|---------|
| **OANDA** | `oanda` | ✅ | Standard — REST API, gut für Einsteiger |
| **Capital.com** | `capital` | ✅ | CFD, keine Kommission, einfache Einrichtung |
| **IG Group** | `ig` | ✅ | CFD, reguliert in DE/AT/CH |
| **Interactive Brokers** | `ibkr` | ✅ | Professionell — erfordert IB Gateway Desktop-App |

---

### OANDA einrichten

OANDA ist der Standard-Broker. Komplett kostenlos, kein echtes Geld für Practice nötig.

#### Schritt 1 — Registrieren

1. Gehe auf [oanda.com](https://www.oanda.com)
2. Klicke oben rechts **"Try Demo"** oder **"Jetzt starten"**
3. Fülle das Formular aus (Name, E-Mail, Passwort)
4. E-Mail bestätigen

#### Schritt 2 — API-Key erstellen

Nach dem Login:

1. Klicke oben rechts auf deinen **Namen** → **"Mein Konto"**
2. Links im Menü: **"API-Zugang"** (oder "API Access")
3. Klicke **"API-Schlüssel generieren"**
4. Kopiere den Key — du siehst ihn nur einmal! Speichere ihn sofort.

> Tipp: Speichere den Key in einer Textdatei bis du ihn in die `.env` eingetragen hast.

#### Schritt 3 — Account-ID herausfinden

1. Oben rechts: **Name** → **"Mein Konto"**
2. **"Zusammenfassung"** → **"Kontodaten"**
3. Notiere die **Account-Nummer** — Format: `101-001-12345678-001`

---

### Capital.com einrichten

1. Account anlegen auf capital.com → **"Demo-Konto eröffnen"** — kostenlos
2. **Mein Profil** → **API-Schlüssel generieren**
3. In `.env`:

```env
FOREX_BROKER=capital
CAPITAL_API_KEY=dein-key
CAPITAL_EMAIL=deine@email.com
CAPITAL_PASSWORD=dein-passwort
CAPITAL_ENV=demo    # demo | live
```

---

### IG Group einrichten

1. Account anlegen auf ig.com → **"Demo-Konto"** — kostenlos
2. **Mein Konto** → **API-Schlüssel**
3. In `.env`:

```env
FOREX_BROKER=ig
IG_API_KEY=dein-key
IG_USERNAME=dein-benutzername
IG_PASSWORD=dein-passwort
IG_ENV=demo    # demo | live
```

---

### Interactive Brokers (IBKR) einrichten

IBKR erfordert die **IB Gateway** Desktop-App auf demselben Rechner.

1. IB Gateway herunterladen: [ibkr.com/trader-workstation](https://www.ibkr.com/trader-workstation)
2. API aktivieren: Edit → Global Configuration → API → Settings → "Enable ActiveX and Socket Clients"
3. Python-Bibliothek installieren: `pip install ib_insync`
4. In `.env`:

```env
FOREX_BROKER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7497    # 7497=TWS Paper, 7496=TWS Live, 4002=GW Paper, 4001=GW Live
IBKR_CLIENT_ID=1
IBKR_ACCOUNT=     # leer = erster Account
```

> **Hinweis:** IB Gateway muss laufen bevor der Bot startet.

---

## 4. Telegram Bot anlegen

Du brauchst einen **eigenen** Telegram-Bot (getrennt vom Krypto-Bot falls vorhanden).

### Schritt 1 — Bot erstellen

1. Öffne Telegram und suche **@BotFather**
2. Tippe `/newbot`
3. BotFather fragt nach einem Namen → z.B. `Mein Forex Bot`
4. BotFather fragt nach einem Username → z.B. `mein_forex_bot` (muss auf `_bot` enden)
5. Du erhältst einen **Token** — sieht aus wie: `1234567890:ABCdefGHIjklMNOpqrSTUvwxyz`
6. Kopiere den Token

### Schritt 2 — Chat-ID herausfinden

1. Suche deinen neuen Bot in Telegram und starte ihn mit `/start`
2. Öffne im Browser: `https://api.telegram.org/bot<DEIN-TOKEN>/getUpdates`
   (ersetze `<DEIN-TOKEN>` mit dem Token aus Schritt 1)
3. Du siehst JSON-Text — suche nach `"chat":{"id":` → die Zahl danach ist deine Chat-ID
4. Notiere die Chat-ID (z.B. `123456789`)

---

## 5. Bot installieren

### Schritt 1 — Projekt klonen / Verzeichnis öffnen

```bash
cd trading_bot    # falls du das Projekt schon hast
```

### Schritt 2 — Python-Abhängigkeiten installieren

```bash
pip install -r forex_bot/requirements.txt
```

Das installiert: pandas, numpy, requests, fastapi, xgboost, arch (GARCH) und mehr.

> Auf dem QNAP passiert das automatisch beim `make qnap-deploy`.

### Schritt 3 — .env Datei anlegen

```bash
cp forex_bot/.env.example forex_bot/.env
```

Öffne `forex_bot/.env` in einem Texteditor und fülle diese Werte aus:

```env
# ── Broker-Auswahl ──────────────────────────────────────────────────────────
FOREX_BROKER=oanda                     # oanda | capital | ig | ibkr

# ── OANDA ──────────────────────────────────────────────────────────────────
OANDA_API_KEY=dein-api-key-aus-schritt-2
OANDA_ACCOUNT_ID=101-001-12345678-001
OANDA_ENV=practice                     # IMMER mit practice anfangen!

# ── Trading ────────────────────────────────────────────────────────────────
FOREX_TRADING_MODE=paper               # paper = kein echtes Geld, nur Simulation
FOREX_INITIAL_CAPITAL=10000            # Startkapital für die Simulation

# ── Telegram ───────────────────────────────────────────────────────────────
FOREX_TELEGRAM_TOKEN=dein-token-aus-schritt-3
FOREX_TELEGRAM_CHAT_ID=deine-chat-id

# ── Alles andere kann so bleiben ───────────────────────────────────────────
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY
FOREX_TIMEFRAME=H1
FOREX_RISK_PER_TRADE=0.01
FOREX_MAX_DRAWDOWN=0.15
FOREX_MAX_OPEN_TRADES=3
```

> **Wichtig:** `FOREX_TRADING_MODE=paper` bedeutet: Der Bot berechnet alles, handelt aber nicht wirklich. Ideal zum Testen.

---

## 6. Bot starten

```bash
python -m forex_bot.bot
```

Du siehst im Terminal:

```
============================================================
Forex Bot startet — Modus: PAPER
Risk Mode: BALANCED
Instruments: EUR_USD, GBP_USD, USD_JPY
OANDA: practice
============================================================
[INFO] No ML model found — running rule-based only
[INFO] Dashboard API auf Port 8001
[INFO] Forex Telegram Bot gestartet
[INFO] ── Zyklus 2025-01-01 10:00 UTC — mode=balanced ──
[INFO] EUR_USD: kein Signal — skip
[INFO] GBP_USD: kein Signal — skip
[INFO] USD_JPY: kein Signal — skip
```

Das ist **normal**! Der Bot prüft stündlich. Meistens gibt es kein Signal.  
Wenn ein Trade eröffnet wird, bekommst du eine Telegram-Nachricht.

### Dashboard öffnen

```bash
# In einem zweiten Terminal:
streamlit run dashboard/app.py
```

Öffne im Browser: **http://localhost:8501**  
Klicke oben auf **💱 Forex** um den Forex-Bot zu sehen.

---

## 7. Was passiert jetzt? — Der Zyklus erklärt

**Jede Stunde** läuft der Bot durch diese Checks — von oben nach unten:

```
STUNDE 1: Mitternacht? → Daily-Tracking zurücksetzen
          Trailing Stops der offenen Trades nachziehen

STOP-CHECKS (wenn einer zutrifft → Stunde überspringen):
  ⬜ Tagesverlust-Limit erreicht? (z.B. -2% heute)
  ⬜ Zu viele Verluste in Folge? (z.B. 3 hintereinander)
  ⬜ Außerhalb der Trading-Session? (7–20 Uhr UTC)
  ⬜ Großes Makro-Event in den nächsten Stunden?
     → FOMC (Fed Zinsentscheid): 24h Sperrung
     → EZB: 12h Sperrung
     → US-Jobdaten (NFP): 4h Sperrung
  ⬜ High-Impact News in ±30 Minuten?
  ⬜ Circuit Breaker (Gesamtverlust > 15%)?
  ⬜ Schon 3 Trades offen?

PRO WÄHRUNGSPAAR (EUR_USD, GBP_USD, USD_JPY):
  ⬜ Spread zu hoch? (Broker nimmt gerade zu viel)
  ⬜ Spread-Schock? (plötzlich 2.5× normal)
  ⬜ Markt-Regime: SIDEWAYS oder HIGH_VOLATILITY? → skip
  ⬜ Signal: BUY / SELL / HOLD?  → kein Signal → skip
  ⬜ Gegen Makro-Kontext? (z.B. Risk-OFF, USD-Short)
  ⬜ Volatilität zu hoch? (GARCH-Modell)
  ⬜ Trend-Persistenz → Konfidenz anpassen
  ⬜ ML-Modell widerspricht? → Konfidenz reduzieren
  ⬜ Konfidenz unter Mindestwert (65%)?
  ⬜ H4 + D1 bestätigen den Trade?
  ⬜ Zu viele korrelierte Positionen?
  ⬜ Zu viele USD-Positionen in eine Richtung?
  ⬜ Swap-Kosten (Overnight) zu hoch?
  ⬜ Black Swan erkannt? (>3σ Kursbewegung, Flash Crash, 2+ Paare betroffen)
  ⬜ Regime-Wechsel droht? (>60% Übergangswahrscheinlichkeit → Warnung)

  ✅ ALLE CHECKS BESTANDEN → Trade vorbereiten
     M15 Entry Timer: wartet auf Pullback zum EMA20 (M15)
       → refinierter Einstieg typisch 1–5 Pips besser
     Signalstärke: IV-Modifier × CB-Sentiment × Portfolio-Gewicht
     Position Sizing: 1% × Drawdown × Portfolio-Gewicht × IV-Faktor × CB-Faktor
     Stop-Loss: ATR × Regime-Multiplikator (1.5–3.0×)
     Take-Profit: RR-Ratio × Regime (1.5:1 bis 2.5:1)
  ✅ TRADE OFFEN — aktive Überwachung:
     Trailing TP: Aktiviert wenn ADX>35 + Gewinn>50% der TP-Distanz
       → SL auf Breakeven; TP zieht nach mit ATR×1.5
     Regime-Wechsel-Warnung: schließt Position wenn Wechsel >75% wahrscheinlich
```

**Das klingt nach viel — ist es auch.** Deshalb gibt es an einem normalen Tag meistens nur 0–2 Trades. Das ist gewollt.

---

## 8. ML-Modell trainieren

Das ML-Modell ist **optional** — der Bot handelt auch ohne es, nur etwas weniger präzise.

### Wann trainieren?

- **Vor dem ersten echten Einsatz** empfohlen
- Braucht: laufende OANDA-Verbindung + ~2–5 Minuten Zeit

### Wie trainieren?

```bash
python -m forex_bot.ai.trainer
```

Mit mehr Daten (empfohlen):

```bash
python -m forex_bot.ai.trainer --instrument EUR_USD --candles 5000
```

Du siehst:

```
Fetching 5000 H1 candles for EUR_USD...
Fetched: H1=4998 H4=1248 D1=312 candles
Feature matrix shape: (4798, 18)

  Fold 1: val F1=0.3821
  Fold 2: val F1=0.4012
  Fold 3: val F1=0.3956
  Fold 4: val F1=0.4103
  Fold 5: val F1=0.3889
Mean CV F1: 0.3956

              precision  recall  f1-score  support
HOLD               0.73    0.82      0.77     3810
BUY                0.41    0.35      0.38      512
SELL               0.39    0.33      0.36      476

Model saved: forex_bot/ai/model.joblib
```

### Was bedeuten diese Zahlen?

| Wert | Was es bedeutet | Gut wenn |
|------|-----------------|----------|
| **F1-Score** | Wie gut das Modell BUY/SELL erkennt | > 0.35 |
| **Precision** | Wenn das Modell sagt BUY: wie oft stimmt es? | > 0.40 |
| **Recall** | Wie viele echte BUY-Signale erkennt es? | > 0.30 |

> Ein F1 von 0.35–0.45 ist bei Forex **realistisch und gut**. Forex ist schwer vorherzusagen.  
> Das Modell muss nicht perfekt sein — es verbessert nur die Konfidenz-Einschätzung.

### Was passiert mit dem Modell?

Nach dem Training:
- Modell wird in `forex_bot/ai/model.joblib` gespeichert
- Bot lädt es beim nächsten Start automatisch
- Nach jeweils **50 abgeschlossenen Trades** trainiert der Bot es automatisch neu (Background-Thread)

### LSTM-Modell trainieren (tieferes Lernen, optional)

Das LSTM-Modell lernt Muster in Zeitreihen — oft besser als XGBoost bei Trending-Märkten.
Benötigt PyTorch (`pip install torch`):

```bash
python -m forex_bot.ai.lstm_trainer --epochs 15 --instruments EUR_USD GBP_USD USD_JPY
```

Das Training läuft auf den letzten ~2.000 H1-Kerzen pro Paar und dauert ca. 5–10 Minuten.
Das Modell wird in `forex_bot/ai/lstm_model.pth` gespeichert und automatisch im Bot genutzt.

> Auf dem QNAP **nicht** ausführen (kein AVX2). Auf dem PC trainieren und per SCP übertragen.

### RL-Agent trainieren (experimentell)

Der Reinforcement-Learning-Agent lernt aus abgeschlossenen Trades, welche Aktionen in welchen
Marktbedingungen am besten funktionieren. Benötigt mindestens 20 abgeschlossene Trades in der DB:

```bash
python -m forex_bot.ai.rl_trainer --episodes 200 --n-trades 500
```

Die Q-Tabelle wird in `forex_bot/ai/rl_qtable.json` gespeichert.
Aktivierung: `FOREX_AI_MODE=rl` in `forex_bot/.env`.

### Training für mehrere Paare?

Starte das Training einmal pro Pair das du handeln möchtest — bei `--instruments` können mehrere angegeben werden. Das XGBoost-Modell trainiert auf allen Pairs gemeinsam; das LSTM-Modell separat pro Pair.

---

## 9. Backtest durchführen

Ein Backtest simuliert den Bot auf historischen Daten — **bevor** du echtes Geld riskierst.

### Einzelnes Paar testen:

```bash
python -m forex_bot.backtest.backtester --instrument EUR_USD --candles 2000 --mode balanced
```

Ausgabe:

```
──────────────────────────────────────────────────
  FOREX BACKTEST REPORT
──────────────────────────────────────────────────
  Instrument:    EUR_USD
  Risk Mode:     balanced
  Candles used:  1998
  Spread:        0.8 pips
──────────────────────────────────────────────────
  Trades:        47
  Win Rate:      55.3%
  Total Pips:    +183.4
  Sharpe Ratio:  0.82
  Max Drawdown:  8.4%
  Profit Factor: 1.43

  Month      Trades      Pips   WinRate
  ──────── ─────── ───────── ─────────
  2024-06        8    +42.1      62.5%
  2024-07       11    +67.3      63.6%
  2024-08        9    +28.8      44.4%
  ...
```

### Alle Paare gleichzeitig (Robustness Test):

```bash
python -m forex_bot.backtest.backtester --multi --candles 2000
```

Ausgabe:

```
  MULTI-PAIR BACKTEST REPORT
  Pairs tested:    3
  Profitable pairs:3
  Robustness:      100%     ← alle 3 Paare profitabel
  Avg Win Rate:    53.7%
  Avg Sharpe:      0.74

  Pair         Trades      WR%       Pips   Sharpe
  ──────────── ─────── ──────── ──────── ────────
  EUR_USD           47    55.3%   +183.4     0.82
  GBP_USD           39    51.3%   +122.7     0.68
  USD_JPY           52    54.2%   +198.1     0.71
```

> Der Bericht wird auch als JSON gespeichert: `forex_bot/reports/backtest_YYYYMMDD_HHMMSS.json`

### Was bedeuten die Werte?

| Kennzahl | Bedeutung | Mindest-Ziel |
|----------|-----------|-------------|
| **Win Rate** | Prozent der gewinnenden Trades | > 45% |
| **Total Pips** | Summe aller Pip-Gewinne/-Verluste | > 0 |
| **Sharpe Ratio** | Risikobereinigte Rendite | > 0.5 |
| **Max Drawdown** | Größter Rückgang vom Höchststand | < 15% |
| **Profit Factor** | Brutto-Gewinn / Brutto-Verlust | > 1.2 |
| **Robustness** | % der Paare die profitabel sind | > 67% |

---

## 10. Die drei Phasen: Paper → Practice → Live

Der Bot schützt dich mit einem **3-Phasen-System**. Du kannst nicht direkt zum echten Geld springen.

```
Phase 1: PAPER TRADING
  ├─ FOREX_TRADING_MODE=paper
  ├─ Bot simuliert Trades, kein echtes Geld
  ├─ Ziel: Kriterien erfüllen (siehe unten)
  └─ Dauer: typisch 2–4 Wochen

Phase 2: OANDA PRACTICE
  ├─ FOREX_TRADING_MODE=paper + OANDA_ENV=practice
  ├─ Echte Marktpreise von OANDA, aber Fake-Geld
  ├─ Beobachte ob Ergebnisse mit Paper übereinstimmen
  └─ Dauer: weitere 2–4 Wochen empfohlen

Phase 3: OANDA LIVE
  ├─ FOREX_TRADING_MODE=live + OANDA_ENV=live
  ├─ Echtes Geld — NUR wenn /approve_live ✅ gibt
  └─ Mit kleinem Kapital anfangen (z.B. 1.000 USD)
```

### Wann bin ich bereit für Phase 3?

Der Bot prüft das automatisch. Tippe in Telegram `/progress`:

```
📊 Phase Progress

✅ Trades:       23/20 (min. 20 benötigt)
✅ Win-Rate:     52.3% (min. 45%)
✅ Sharpe Ratio: 0.67 (min. 0.5)
✅ Max Drawdown: 8.2% (max. 15%)
✅ ML F1-Score:  0.38 (min. 0.35)

✅ ALLE KRITERIEN ERFÜLLT
Bereit für OANDA Live. /approve_live zur Bestätigung.
```

Wenn nicht alle erfüllt sind:

```
❌ Trades:  12/20 (noch 8 nötig)
❌ Sharpe:  0.23 (min. 0.5)
✅ Win-Rate: 55.0%
...

Noch nicht bereit. Weiter im Paper-Modus.
```

### Pre-Live Check (automatischer Go/No-Go)

Bevor du zu Live wechselst, prüft dieses Script **alle Kriterien automatisch**:

```bash
python forex_bot/scripts/pre_live_check.py
```

Ausgabe:

```
══════════════════════════════════════════════════
   Forex Bot — Pre-Live Deployment Check
══════════════════════════════════════════════════

  Check                               Ergebnis             Status
  ─────────────────────────────────── ──────────────────── ──────
  ✓ Paper Trades vorhanden            34 (min 30)          [PASS]
  ✓ Sharpe Ratio (annualisiert)       0.634 (min 0.50)     [PASS]
  ✓ Win Rate                          51.5% (min 40%)      [PASS]
  ✓ Max Drawdown                      6.1% (max 8%)        [PASS]
  ✓ ML-Modell F1                      0.4112 (min 0.40)    [PASS]
  ✓ Profitfaktor                      1.247 (min 1.10)     [PASS]
  ✓ Emergency Exit inaktiv            inaktiv              [PASS]
  ✓ Regime-Robustheit (WR >= 30%)     OK (TREND_UP: 58%)   [PASS]
  ✓ Macro-Event Resilienz             4 Events WR=75%      [PASS]

  ✓ READY — Bot kann für Live-Trading aktiviert werden
```

Mit strengeren Kriterien (`--strict`) oder eigenem Mindest-Trade-Count:

```bash
python forex_bot/scripts/pre_live_check.py --strict --min-trades 50
python forex_bot/scripts/pre_live_check.py --json    # CI/CD-kompatible Ausgabe
```

### Live-Freigabe erteilen

```
/approve_live
```

Wenn alle Kriterien erfüllt sind:

```
✅ Live-Trading freigegeben!
Alle 5 Kriterien erfüllt.
Setze FOREX_TRADING_MODE=live in der .env
und starte den Bot neu.
```

Dann in `forex_bot/.env`:

```env
FOREX_TRADING_MODE=live
OANDA_ENV=live
```

Bot neu starten:

```bash
python -m forex_bot.bot
```

> **Wichtig:** Der Bot wechselt **niemals automatisch** zu Live. Das machst nur du.

---

## 11. Telegram-Befehle

| Befehl | Was er macht |
|--------|-------------|
| `/status` | Aktuelles Kapital, offene Trades, Tages-PnL, Risk Mode |
| `/trades` | Letzte 5 abgeschlossene Trades |
| `/news` | Heutige High-Impact News-Events |
| `/performance` | Win-Rate, Total Pips, PnL aller Trades |
| `/regime` | Aktuelles Markt-Regime pro Paar (Trend / Sideways / Volatil) |
| `/macro` | Makro-Kontext: USD-Index, VIX, Leitzinsen, Carry-Signale |
| `/correlations` | Korrelations-Check der offenen Positionen |
| `/set_mode balanced` | Risk-Modus auf balanced setzen |
| `/set_mode conservative` | Vorsichtiger Modus (halbe Positionsgröße) |
| `/set_mode aggressive` | Aggressiver Modus (doppelte Positionsgröße) |
| `/progress` | Fortschritt der Phase-Kriterien |
| `/approve_live` | Live-Freigabe bestätigen (wenn Kriterien erfüllt) |
| `/pause` | Trading pausieren |
| `/resume` | Trading fortsetzen |
| `/help` | Alle Befehle anzeigen |

---

## 12. Risk-Modi

Du kannst den Risk-Modus jederzeit wechseln — per Telegram oder in der `.env`.

| | 🛡️ Conservative | ⚖️ Balanced | ⚡ Aggressive |
|--|--|--|--|
| **Risiko/Trade** | 0.5% | 1.0% | 2.0% |
| **Max. offene Trades** | 1 | 3 | 5 |
| **Min. Konfidenz** | 80% | 65% | 50% |
| **News-Pause** | 60 Min. | 30 Min. | 15 Min. |
| **Spread-Limit** | 1.5 Pips | 3.0 Pips | 5.0 Pips |
| **Tagesverlust-Limit** | 1% | 2% | 4% |
| **Session-Beschränkung** | Nur London/NY Overlap | Nein | Nein |
| **MTF-Bestätigung** | H4 + D1 | H4 | Nein |

> **Empfehlung für Anfänger:** Mit `conservative` anfangen. Nach 50+ profitablen Trades auf `balanced` wechseln.

### Auto-Mode (Feature 2)

Der Bot kann den Modus **automatisch anpassen**:

- VIX > 25 oder ATR > 0.12% oder 3+ High-Impact Events → wechselt auf `conservative`
- VIX < 15 und ruhiger Markt → kann auf `aggressive` wechseln
- Sobald du `/set_mode` verwendest → Auto-Mode deaktiviert bis Mitternacht

---

## 13. Alle Features im Überblick

### Kernstrategie & Einstieg

| # | Feature | Was es tut |
|---|---------|-----------|
| 1 | **Makro-Signale** | DXY, VIX, Leitzinsen → Risk-ON/OFF Erkennung, Carry-Filter |
| 2 | **Auto-Mode** | Passt Risk-Modus automatisch an die Marktlage an |
| 3 | **Drawdown Recovery** | Bei -5% DD → halbe Positionsgröße; bei -10% → Viertel |
| 4 | **Swap-Filter** | Blockiert Trades bei hohen Overnight-Kosten |
| 5 | **GARCH Volatilität** | Vorhersage extremer Volatilität → blockiert Trade |
| 6 | **Multi-Pair Backtest** | Testet alle Paare gleichzeitig → Robustness Score |
| 7 | **Makro-Event Lockdown** | FOMC 24h / EZB 12h / NFP+CPI 4h Sperrung vor Events |
| 8 | **Spread-Shock** | Blockiert wenn Spread plötzlich 2.5× Normal |
| 9 | **USD-Konzentration** | Max. 60% der Trades in eine USD-Richtung |
| 10 | **Trend-Persistenz** | ADX + Candle-Zähler → Konfidenz ±25% |

### Präzisions-Einstieg & Trade-Management

| # | Feature | Was es tut |
|---|---------|-----------|
| 11 | **M15 Entry Timer** | Wartet auf Pullback zum EMA20 auf M15 → typisch 1–5 Pips besserer Einstieg |
| 12 | **Trailing Take-Profit** | ADX>35 + 50% Gewinn → TP zieht mit ATR×1.5 nach, SL auf Breakeven |
| 13 | **Regime-Wechsel-Warnung** | >60% Übergangswahrscheinlichkeit → Warnung; >75% → automatisches Schließen |

### Institutionelle Signalfilter

| # | Feature | Was es tut |
|---|---------|-----------|
| 14 | **Options IV Proxy** | ETF-basierte Volatilität (FXE/FXB/FXY): hohe IV → 0.85× Position, niedrige IV → 1.10× |
| 15 | **Zentralbank-Sentiment** | Fed/EZB/BOE/BOJ RSS → Hawkish/Dovish Score → ±8% Konfidenz-Modifier |
| 16 | **Makro-Paar-Selektion** | Risk-OFF: USD_JPY/USD_CHF bevorzugt; Risk-ON: AUD_USD/GBP_USD aktiviert |
| 17 | **Markowitz Portfolio-Optimizer** | Sharpe-maximierende Gewichtung pro Währungspaar — bessere Diversifikation |

### Risikoabsicherung

| # | Feature | Was es tut |
|---|---------|-----------|
| 18 | **Black Swan Detector** | >3σ Bewegung, Flash Crash (>2% in 1 Kerze) oder 2+ Paare betroffen → 1h Pause |
| 19 | **Stress Tester** | 5 Szenarien: Spread×5, Flash Crash -3%, Gap ±2%, Trending DD, Black Thursday |
| 20 | **Regime-Robustheit** | Prüft Win-Rate pro Markt-Regime — unter 30% → Pre-Live Check schlägt an |

### KI & Adaptives Lernen

| # | Feature | Was es tut |
|---|---------|-----------|
| 21 | **LSTM Neural Network** | Sequenz-basiertes Lernen auf 24h-Zeitreihen — ergänzt XGBoost |
| 22 | **RL-Agent** | Q-Learning auf historischen Trades — lernt welche Aktionen in welchem Regime funktionieren |
| 23 | **Automatisches Retraining** | Nach 50 Trades oder bei F1-Degradation → Modell wird automatisch im Hintergrund neu trainiert |
| 24 | **Dynamische Parameter** | ATR-Multiplikator und RR-Ratio passen sich automatisch dem Regime an |
| 25 | **Konfidenz-Monitor** | Gatekeeper: stoppt Live-Trading wenn F1/Sharpe/Win-Rate unter Schwelle fallen |

### Infrastruktur

| # | Feature | Was es tut |
|---|---------|-----------|
| 26 | **VPS Failover** | NAS nicht erreichbar? → Bot startet automatisch per SSH auf konfiguriertem VPS |
| 27 | **LEAN_MODE** | QNAP/NAS-optimierter Betrieb — deaktiviert rechenintensive Features (LSTM, Monte Carlo, etc.) |
| 28 | **Regime Bus** | Krypto- und Forex-Bot teilen Regime-Information — verhindert gegensätzliche Positionen |

---

## 14. QNAP Deployment

Wenn du den Bot auf einem QNAP NAS (oder einem anderen Server) laufen lassen willst:

### Einmalig einrichten

```bash
# .env auf den QNAP übertragen
scp forex_bot/.env admin@YOUR_QNAP_IP:/share/CACHEDEV1_DATA/trading_bot/forex_bot/.env

# Deployment (baut Docker-Image und startet beide Bots)
make qnap-deploy QNAP=admin@YOUR_QNAP_IP
```

Nach dem Deploy läuft der Forex-Bot permanent im Hintergrund — auch wenn dein Laptop aus ist.

### Updates einspielen

```bash
make qnap-update QNAP=admin@YOUR_QNAP_IP
```

### Logs ansehen

```bash
make qnap-forex-logs QNAP=admin@YOUR_QNAP_IP
```

### LEAN_MODE — Ressourcenschonender Betrieb

Auf schwacher Hardware (QNAP, NAS, Raspberry Pi) aktiviere den LEAN_MODE:

```env
FOREX_LEAN_MODE=true
```

Was LEAN_MODE deaktiviert:
- LSTM-Modell (kein PyTorch/AVX2 nötig)
- Monte-Carlo-Simulation
- Markowitz Portfolio-Optimizer
- M15 Entry Timer (ein OANDA-API-Call weniger pro Zyklus)
- Stress Tester

Was weiterhin funktioniert: XGBoost, Regime-Erkennung, alle Risikofilter, Telegram, Dashboard.

### VPS Failover (automatisches Backup)

Wenn der QNAP nicht mehr erreichbar ist, startet der Bot automatisch auf einem VPS:

```env
FAILOVER_VPS_HOST=123.45.67.89
FAILOVER_VPS_USER=root
FAILOVER_VPS_KEY=~/.ssh/id_rsa
FAILOVER_VPS_CMD=cd /opt/trading_bot && docker compose up -d forex-bot
FAILOVER_MAX_FAILS=3      # 3 aufeinanderfolgende Fehlversuche → Failover
FAILOVER_COOLDOWN=30      # 30 Minuten Cooldown zwischen Failovers
```

Failover-Daemon starten (auf dem VPS als Cronjob empfohlen):

```bash
# Einmalig auf dem VPS:
*/1 * * * * python /opt/trading_bot/forex_bot/scripts/failover.py --once >> /var/log/failover.log 2>&1

# Oder als Daemon:
python -m forex_bot.scripts.failover
```

Du bekommst eine Telegram-Nachricht wenn der Failover ausgelöst wird.

### Ressourcen (QNAP Celeron J1900)

| Container | RAM | CPU | LEAN_MODE |
|-----------|-----|-----|-----------|
| forex-bot | ~256 MB | gering (schläft 59/60 Min.) | ~180 MB |
| forex-dashboard | ~128 MB | gering | ~128 MB |

> Der Forex-Bot und der Krypto-Bot zusammen brauchen ca. 2.9 GB RAM — das passt auf ein QNAP mit 4 GB.  
> Mit `FOREX_LEAN_MODE=true` sinkt der RAM-Bedarf des Forex-Bots auf ~180 MB.

---

## 15. Konfigurationsreferenz

Alle Einstellungen in `forex_bot/.env`:

```env
# ── Broker-Auswahl ─────────────────────────────────────────────────────────
FOREX_BROKER=oanda                    # oanda | capital | ig | ibkr

# ── OANDA Broker ───────────────────────────────────────────────────────────
OANDA_API_KEY=dein-api-key
OANDA_ACCOUNT_ID=101-001-12345678-001
OANDA_ENV=practice                    # practice | live

# ── Trading-Modus ──────────────────────────────────────────────────────────
FOREX_TRADING_MODE=paper              # paper | live
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY
FOREX_TIMEFRAME=H1
FOREX_INITIAL_CAPITAL=10000           # Startkapital (Paper-Modus)

# ── Risiko ─────────────────────────────────────────────────────────────────
FOREX_RISK_PER_TRADE=0.01             # 1% pro Trade
FOREX_MAX_DRAWDOWN=0.15               # 15% → Circuit Breaker
FOREX_MAX_OPEN_TRADES=3
FOREX_ATR_MULTIPLIER=1.5              # Stop-Loss Abstand in ATR
FOREX_RR_RATIO=2.0                    # Reward:Risk Verhältnis
FOREX_RISK_MODE=balanced              # conservative | balanced | aggressive

# ── Session-Filter (UTC) ───────────────────────────────────────────────────
FOREX_SESSION_FILTER=true
FOREX_SESSION_START_H=7               # 7 Uhr = London Open
FOREX_SESSION_END_H=20                # 20 Uhr = NY Close

# ── Wirtschaftskalender ────────────────────────────────────────────────────
FOREX_NEWS_PAUSE_MIN=30               # Pause ±30 Min. vor/nach High-Impact
FOREX_NEWS_CURRENCIES=USD,EUR,GBP,JPY,CHF,CAD,AUD,NZD

# ── Strategie ──────────────────────────────────────────────────────────────
FOREX_EMA_FAST=20
FOREX_EMA_SLOW=50
FOREX_EMA_TREND=200
FOREX_RSI_PERIOD=14
FOREX_MIN_CONFIDENCE=0.65             # Mindest-Konfidenz für Trade

# ── Telegram ───────────────────────────────────────────────────────────────
FOREX_TELEGRAM_TOKEN=dein-bot-token
FOREX_TELEGRAM_CHAT_ID=deine-chat-id

# ── Dashboard API ──────────────────────────────────────────────────────────
FOREX_API_PORT=8001

# ── ML Auto-Retrain ────────────────────────────────────────────────────────
FOREX_RETRAIN_AFTER_TRADES=50         # Nach 50 Trades → automatisch neu trainieren

# ── LEAN_MODE (für QNAP / schwache Hardware) ───────────────────────────────
FOREX_LEAN_MODE=false                 # true = deaktiviert LSTM, Monte Carlo, Portfolio Optimizer

# ── VPS Failover (optional) ────────────────────────────────────────────────
# FAILOVER_VPS_HOST=123.45.67.89
# FAILOVER_VPS_USER=root
# FAILOVER_VPS_KEY=~/.ssh/id_rsa
# FAILOVER_VPS_CMD=cd /opt/trading_bot && docker compose up -d forex-bot
# FAILOVER_MAX_FAILS=3
# FAILOVER_COOLDOWN=30

# ── FRED API (optional) ────────────────────────────────────────────────────
# Kostenloser Key auf fred.stlouisfed.org → bessere Fed-Funds-Rate Daten
# FRED_API_KEY=dein-fred-key
```

---

## 16. Häufige Fragen

**F: Der Bot macht keine Trades. Ist etwas kaputt?**  
A: Wahrscheinlich nicht. An vielen Stunden gibt es kein Signal das alle Filter besteht. Check im Terminal ob Meldungen wie `kein Signal — skip` oder `Außerhalb der Trading-Session` erscheinen. Das ist normales Verhalten.

**F: "No ML model found" — was tun?**  
A: Nichts. Der Bot läuft regelbasiert. Wenn du das Modell möchtest: `python -m forex_bot.ai.trainer` ausführen.

**F: Wie lange bis der erste Trade kommt?**  
A: Typisch 0–3 Trades pro Tag, je nach Marktlage. An volatilen Tagen oder vor großen Events oft gar keiner.

**F: Was ist ein Pip?**  
A: Die kleinste Kurseinheit. Bei EUR/USD: 0.0001. Ein Gewinn von "+20 Pips" bei EUR/USD = 0.0020 Kursbewegung zu deinen Gunsten.

**F: Was passiert bei einem Stromausfall / Neustart?**  
A: Offene Trades sind in der SQLite-Datenbank gespeichert und werden beim Neustart wiederhergestellt. Offene OANDA-Positionen bleiben bestehen.

**F: Kann ich mehrere Paare hinzufügen?**  
A: Ja, in `.env`:  
```env
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD
```

**F: Wie setze ich den Risk-Modus zurück auf Auto?**  
A: `/set_mode` sperrt den Auto-Mode bis Mitternacht. Danach ist er wieder aktiv. Oder Bot neu starten.

**F: Kann ich Paper-Modus und OANDA Practice gleichzeitig nutzen?**  
A: `FOREX_TRADING_MODE=paper` mit `OANDA_ENV=practice` ist genau das — der Bot liest Preise von OANDA Practice, simuliert aber Trades lokal. So weißt du ob die Signale auf echten Preisen funktionieren.

**F: Was kostet OANDA?**  
A: Der Practice Account ist kostenlos. Beim Live Account verdient OANDA am Spread (Differenz zwischen Kauf- und Verkaufspreis) — keine fixen Gebühren.

---

*Letzte Aktualisierung: 2026-04-13*  
*[🇬🇧 English Version](../en/FOREX.md)*
