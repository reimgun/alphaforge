# Konfiguration

[🇬🇧 English](../en/CONFIG.md)

---

Alle Einstellungen werden in der `.env` Datei gesetzt.  
Die vollständige Liste mit Standardwerten ist in `config/settings.py`.

## Wichtigste Einstellungen

```env
# Handelsmodus: paper (virtuell) oder live (echtes Geld)
TRADING_MODE=paper

# Startkapital in USDT
INITIAL_CAPITAL=1000

# KI-Modus (siehe unten)
AI_MODE=ml

# Binance API (nur für live nötig)
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Anthropic API (nur für AI_MODE=claude oder combined)
ANTHROPIC_API_KEY=

# Telegram Benachrichtigungen (optional)
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Dashboard API-Key (optional — schützt POST-Endpunkte)
DASHBOARD_API_KEY=

# Leverage: 1 = Spot (Standard), 2–3 = Futures (max. 3x)
LEVERAGE=1
```

---

## KI-Modi

| Modus | Beschreibung | Empfohlen |
|-------|-------------|-----------|
| `rules` | Klassische MA-Crossover Strategie | Debugging / Schnelltest |
| `ml` | XGBoost + LSTM Ensemble | Standard — kein API-Key nötig |
| `claude` | Nur Claude AI | Wenn kein ML-Modell vorhanden |
| `combined` | ML/LSTM + Claude müssen übereinstimmen | Höchste Präzision |
| `rl` | Reinforcement Learning Agent | Experimentell |

---

## Risk Management

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `RISK_PER_TRADE` | `0.02` | 2% des Kapitals pro Trade riskieren |
| `MAX_DAILY_LOSS_PCT` | `0.06` | Circuit Breaker bei 6% Tagesverlust |
| `MAX_DRAWDOWN_PCT` | `0.20` | Permanenter Stopp bei 20% Gesamtverlust |
| `USE_ATR_SIZING` | `True` | Volatilitäts-basierter Stop-Loss |
| `USE_TRAILING_STOP` | `True` | Stop-Loss zieht automatisch nach |
| `ATR_MULTIPLIER` | `2.0` | Stop-Abstand in ATR-Einheiten |
| `TRAILING_STOP_PCT` | `0.015` | Trailing Stop 1.5% unter Hochpunkt |

### Risk Personality Mode

```env
RISK_MODE=balanced      # Standard (2%/Trade, 20% Max-DD)
RISK_MODE=conservative  # Kleines Risiko (1%/Trade, 10% Max-DD)
RISK_MODE=aggressive    # Höheres Risiko (3%/Trade, 30% Max-DD)
```

Wechselbar zur Laufzeit per Telegram `/set_mode` oder Dashboard — kein Neustart nötig.

### Leverage (nur Futures)

```env
LEVERAGE=1    # Spot — kein Hebel (Standard)
LEVERAGE=2    # 2x Hebel
LEVERAGE=3    # 3x Hebel — Maximum (intern begrenzt)
```

---

## Strategie-Parameter

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `SYMBOL` | `BTC/USDT` | Handelspaar |
| `TIMEFRAME` | `1h` | Entry-Timeframe |
| `TREND_TIMEFRAME` | `4h` | Übergeordneter Trend-Filter |
| `ML_MIN_CONFIDENCE` | `0.60` | Minimale ML-Konfidenz für Trade |

---

## ML-Parameter

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `ML_TRAIN_DAYS` | `730` | Trainingsdaten in Tagen (2 Jahre) |
| `ML_LOOKAHEAD` | `6` | Lookahead für Label-Generierung (6 Stunden) |
| `ML_MIN_F1_LIVE` | `0.38` | Minimaler F1-Score im Live-Betrieb |
| `ML_RETRAIN_AFTER_TRADES` | `50` | Auto-Retraining nach N Live-Trades |
| `ML_RETRAIN_INTERVAL_DAYS` | `7` | Zeitbasiertes Retraining wenn F1 < Schwelle |

---

## Auto Paper→Live Transition

Der Bot wechselt automatisch zu Live wenn alle Schwellenwerte überschritten sind.

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `MIN_PAPER_TRADES` | `20` | Mindest-Anzahl Paper-Trades |
| `MIN_SHARPE` | `0.8` | Mindest-Sharpe Ratio |
| `MIN_WIN_RATE_PCT` | `48.0` | Mindest-Win-Rate % |
| `MAX_ALLOWED_DRAWDOWN` | `15.0` | Maximaler Drawdown % |
| `MIN_MODEL_F1` | `0.38` | Mindest-F1-Score des Modells |

**Historische Daten importieren:**
```bash
make import-history          # 365 Tage Backtest-Daten importieren
make import-history DAYS=90  # Nur 90 Tage
make import-history-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## Feature Flags

Alle Features können per `.env` ein- oder ausgeschaltet werden. **Standard: alle aktiv.**

```env
# Ressourcenschonender Betrieb (z.B. für schwache Hardware):
FEATURE_PDF_REPORTS=false
FEATURE_OPPORTUNITY_RADAR=false
FEATURE_REGIME_FORECASTER=false
FEATURE_LSTM=false              # Wichtig für QNAP (kein AVX2)

# Forex Bot: Einzel-Flag für alle rechenintensiven Features auf einmal:
FOREX_LEAN_MODE=true            # Deaktiviert LSTM, Monte Carlo, Portfolio Optimizer, Entry Timer

# Alle verfügbaren Flags:
FEATURE_ONLINE_LEARNING=true
FEATURE_EXPLAINABILITY=true
FEATURE_PORTFOLIO_OPTIMIZER=true
FEATURE_TAIL_RISK=true
FEATURE_MICROSTRUCTURE=true
FEATURE_DERIVATIVES_SIGNALS=true
FEATURE_CROSS_MARKET=true
FEATURE_REGIME_FORECASTER=true
FEATURE_GROWTH_OPTIMIZER=true
FEATURE_GLOBAL_EXPOSURE=true
FEATURE_STRATEGY_TRACKER=true
FEATURE_SCANNER=true
```

Status prüfen:
```bash
python -c "from config import features; print(features.summary())"
```

---

## Log-Level

```env
LOG_LEVEL=INFO     # Normaler Betrieb
LOG_LEVEL=DEBUG    # Alle Details (für Fehlersuche)
LOG_LEVEL=WARNING  # Nur Warnungen und Fehler
```

Das Log-Level kann auch zur Laufzeit im Web-Dashboard (Sidebar) geändert werden.

---

## Verschlüsselte Konfiguration (Server)

```bash
# Einmalig verschlüsseln (erstellt .env.enc + .env.key)
python -m config.crypto_config --encrypt

# Status prüfen
python -m config.crypto_config --check
```

Die verschlüsselte `.env.enc` kann ins Repository — `.env.key` **niemals**.
