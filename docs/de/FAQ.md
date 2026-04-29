# FAQ — Häufige Fragen

[🇬🇧 English](../en/FAQ.md)

---

## Installation

**`python: command not found`**  
Versuche `python3` statt `python`. Auf manchen Systemen:
```bash
python3 -m ai.trainer
```

**`make: command not found` (Windows)**  
Make für Windows installieren: [gnuwin32.sourceforge.net](https://gnuwin32.sourceforge.net/packages/make.htm)  
Oder Befehle direkt ausführen:
```
.venv\Scripts\python bot.py
.venv\Scripts\python -m ai.trainer
```

**Pakete installieren schlägt fehl**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**XGBoost: `libxgboost.dylib could not be loaded` (macOS)**
```bash
brew install libomp
```

**`torch` Installation zu groß**  
CPU-only Version ist kleiner (~200 MB statt ~1 GB):
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

---

## Bot macht keine Trades

Das ist meistens normales Verhalten. Mögliche Gründe:

| Ursache | Lösung |
|---------|--------|
| **Regime BEAR_TREND** | Bot schützt Kapital — kein Long-Trade erlaubt |
| **4h-Trend NEUTRAL** | Seitwärtsmarkt — Bot wartet auf klare Richtung |
| **ML-Konfidenz zu niedrig** | Normales Verhalten bei unsicherem Markt |
| **ML + Claude uneinig** | Im `combined`-Modus nur Trade bei Einigkeit |
| **Circuit Breaker aktiv** | 6% Tagesverlust erreicht — setzt sich morgen zurück |
| **Volume-Kollaps** | Zu wenig Handelsvolumen → Liquiditätsproblem |
| **Tail-Risk erkannt** | Marktanomalie → Bot wartet |

```bash
# Gründe für HOLDs ansehen
make logs
# oder
make diagnose
```

---

## Modell-Probleme

**"Kein trainiertes Modell gefunden"**
```bash
make train
```

**Training schlägt fehl**
```bash
# Internetverbindung prüfen (lädt Daten von Binance)
make train
```

**ML-Modell zu alt / schlechte Performance**
```bash
make train
```

**LSTM nicht verfügbar**
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```
Der Bot funktioniert auch ohne LSTM — XGBoost läuft immer.

---

## Web-Dashboard

**Dashboard zeigt "API nicht erreichbar"**
```bash
# API Backend zuerst starten:
make dashboard-api   # Terminal 1
make dashboard       # Terminal 2
```

**Dashboard aktualisiert sich nicht**  
Button "🔄 Manuell aktualisieren" klicken oder Refresh-Intervall in der Sidebar einstellen.

**Port 8000 oder 8501 schon belegt**
```bash
.venv/bin/uvicorn dashboard.api:app --port 8001
.venv/bin/streamlit run dashboard/app.py --server.port 8502
```

---

## Telegram funktioniert nicht

1. Token und Chat-ID in `.env` prüfen
2. Deinem Bot einmalig eine Nachricht schicken (Pflicht beim ersten Mal)
3. `make check` ausführen

---

## Binance API-Fehler

**"Rate Limit"** — Der Bot hat automatisches Retry, das ist temporär.

**"Invalid API Key"** — API-Key in `.env` prüfen, keine Leerzeichen.

**"IP not whitelisted"** — In Binance API-Einstellungen eigene IP eintragen oder IP-Beschränkung deaktivieren.

---

## Paper Trading vs. Live

**Brauche ich API-Keys für Paper Trading?**  
Nein. Paper Trading funktioniert ohne jegliche API-Keys.

**Wann wechselt der Bot automatisch zu Live?**  
Wenn alle 5 Kriterien erfüllt sind (≥20 Trades, Win-Rate ≥48%, Sharpe ≥0.8, Drawdown ≤15%, F1 ≥0.38). Du bekommst eine Telegram-Nachricht und musst mit `/approve_live` bestätigen.

**Paper Trading Ergebnisse sind besser als Live — warum?**  
Paper Trading: exakte Preise, keine Slippage. Live Trading: Slippage, Gebühren, Partial Fills.  
Im Backtest sind Slippage (0.1%) und Gebühren (0.1%) bereits eingerechnet.

---

## Performance-Fragen

**Welche Rendite kann ich erwarten?**  
Das hängt vom Markt ab und lässt sich nicht vorhersagen.  
Führe `make backtest` + `make monte-carlo` aus um historische Ergebnisse zu sehen.

**Bot verliert Geld — was tun?**
1. `make logs` — Trades analysieren
2. `make backtest` — Strategie auf aktuellen Daten testen
3. `ML_MIN_CONFIDENCE` in `.env` erhöhen (weniger aber sicherere Trades)
4. In `.env` `TRADING_MODE=paper` setzen — zurück zur Simulation
5. `/switch_safe_mode` in Telegram — Positionsgröße halbieren

**Kann der Bot alles verlieren?**  
Nein — der Circuit Breaker (6% Tagesverlust) und Max-Drawdown-Stopp (20%) verhindern das. Der Bot stoppt automatisch.
