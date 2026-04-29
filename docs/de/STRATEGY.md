# Strategie — Wie der Bot entscheidet

[🇬🇧 English](../en/STRATEGY.md)

---

## Entscheidungs-Pipeline

Jede Entscheidung durchläuft mehrere Filter hintereinander:

```
Schritt 1: Markt-Regime erkennen     (Bull / Bear / Sideways / High-Vol)
     ↓
Schritt 2: Volatility-Regime bestimmen  (Low / Normal / High / Extreme)
     ↓
Schritt 3: Advanced Intelligence      (Microstructure, Derivatives, Cross-Market)
     ↓
Schritt 4: Anomalie-Erkennung         (Marktausreißer blocken)
     ↓
Schritt 5: Strategie wählen           (KI wählt automatisch nach Regime)
     ↓
Schritt 6: 4h-Trend prüfen            (Haupttrend-Filter)
     ↓
Schritt 7: KI-Signal + Positionsgröße + Trade ausführen
```

---

## Schritt 1 — Markt-Regime

| Regime | Wann | Reaktion |
|--------|------|----------|
| **BULL_TREND** | Preis über MA50, ADX > 22 | Volle Positionsgröße |
| **BEAR_TREND** | Preis unter MA50, ADX > 22 | **Kein Trade** — Kapitalschutz |
| **SIDEWAYS** | ADX < 22, enger Kanal | 60% Positionsgröße |
| **HIGH_VOLATILITY** | ATR > 80. Perzentil | 50% Positionsgröße |

---

## Schritt 2 — Volatility-Regime

| Vol-Regime | Annualisierte Vol | Positions-Faktor |
|------------|-------------------|-----------------|
| **LOW** | < 30% | 1.0× |
| **NORMAL** | 30–80% | 0.85× |
| **HIGH** | 80–120% | 0.60× |
| **EXTREME** | > 120% | 0.30× |

Endgültiger Faktor: `regime_factor × vol_factor` (z.B. BULL × NORMAL = 1.0 × 0.85 = 0.85)

---

## Schritt 3 — Advanced Intelligence

### Market Microstructure
- **CVD** (Cumulative Volume Delta) — Kauf- vs. Verkaufsvolumen
- **Orderbook-Imbalanz** — Bid-Heavy / Ask-Heavy aus Preis-Position in HL-Range
- **Liquidity Walls** — Hohe Volumensäulen als Support/Resistance
- **Spoofing-Proxy** — Verdächtige Wick-zu-Body Verhältnisse

### Derivatives Intelligence
- **Funding Rate** extremen Wert → Markt overlevered → Contrarian Bias
- **Liquidations-Cluster** → Magnetische Preisziele nahe Liquidationslevel
- **Spot-Perp-Basis** → Contango / Backwardation Stimmung

### Cross-Market Signals
- **Fear & Greed Index** — < 20 = Extreme Fear (potentiell Contrarian BUY)
- **BTC-Dominanz** — > 55% = Risk-Off, < 35% = Altcoin Season
- **Stablecoin-Flow** — Hohe USDT/USDC Handelsvolumen = Kaufkraft im Markt

### Regime Forecaster
- **Markov-Übergangsmatrix**: Lernt empirisch welche Regime-Übergänge häufig sind (TREND_UP → SIDEWAYS etc.)
- Breakout-Wahrscheinlichkeit hoch → `TREND_FOLLOWING` Bias
- Mean-Reversion-Wahrscheinlichkeit hoch → `MEAN_REVERSION` Bias
- Regime-Persistenz < 30% → `WAIT` (abwarten)
- **Trend-Persistenz**: Geometrische Verteilung schätzt verbleibende Trend-Dauer (Forex-Standard: ~20 Stunden)
- **Regime-Wechsel-Warnung**: Wenn Übergangswahrscheinlichkeit > 60% → Warnung; > 75% → offene Position schließen

---

## Schritt 4 — Anomalie-Erkennung

- **Z-Score**: Returns oder Volumen außerhalb ±3.5 Standardabweichungen
- **Isolation Forest**: Multivariate Ausreißer

Bei Anomalie-Score ≥ 0.5 → automatisch **HOLD** (kein Trade).

---

## Schritt 5 — Strategie-Auswahl

| Regime | Strategie | Logik |
|--------|-----------|-------|
| **BULL_TREND** | Momentum + Breakout + Liquidity | Alle drei einig → +15% Konfidenz-Boost |
| **BEAR_TREND** | — | Kein Trade |
| **SIDEWAYS** | Mean Reversion | Bollinger Bands Extrempunkte |
| **HIGH_VOLATILITY** | Scalping → Volatility Expansion → Breakout | Kaskade: erstes Signal gewinnt |

### Die 7 Strategien

| Strategie | Signal | Bestes Regime |
|-----------|--------|--------------|
| **Momentum** | Golden Cross MA20/MA50 + RSI-Filter | BULL_TREND |
| **Breakout** | Donchian-Kanal + Volumen-Bestätigung | BULL_TREND / HIGH_VOL |
| **Mean Reversion** | Bollinger Band Berührung + RSI Extreme | SIDEWAYS |
| **Scalping** | EMA5/EMA13 Crossover + Volumen-Spike | HIGH_VOL |
| **Volatility Expansion** | Keltner Channel Ausbruch + ATR-Expansion | HIGH_VOL |
| **Liquidity-Signals** | Volumen-Spike (>2×) + enger Spread | BULL_TREND |
| **Reinforcement Learning** | Q-Learning Agent | Alle (experimentell) |

---

## Schritt 6 — 4h-Trend-Filter

```
4h BULLISH + BUY-Signal   → Trade erlaubt ✓
4h BEARISH + BUY-Signal   → Geblockt → HOLD
4h NEUTRAL                → Kein Trade (zu unsicher)
```

---

## Schritt 7 — KI-Signal (Ensemble)

### XGBoost ML-Modell
- Trainiert auf 730 Tagen BTC-Daten
- 50+ technische Indikatoren als Features
- Gibt BUY/SELL/HOLD mit Konfidenz-% aus
- Unter 60% Konfidenz → automatisch HOLD

### LSTM Neural Network
- Sequenz-basiertes Modell (letzte 24 Stunden als Input)
- Ensemble: XGBoost 60% + LSTM 40%
- Fallback auf MLP wenn PyTorch nicht installiert

### Claude AI (optional, AI_MODE=combined)
- Analysiert Marktdaten als strukturierten Text
- Im `combined`-Modus: nur Trade wenn ML **und** Claude übereinstimmen

### Dynamische Parameter (Regime-adaptiv)

ATR-Multiplikator und RR-Ratio passen sich automatisch dem Regime an:

| Regime | ATR-Multiplikator (SL) | RR-Ratio (TP) |
|--------|----------------------|--------------|
| TREND_UP / TREND_DOWN | 2.0× | 2.5:1 |
| SIDEWAYS | 1.5× | 1.5:1 |
| HIGH_VOLATILITY | 3.0× | 2.0:1 |

Session-Bonus: London/NY Overlap +0.2×; Asian Session -0.2×.
Drawdown-Korrektur: bei >10% DD wird ATR-Multiplikator erhöht (weiterer Stop).

### Positions-Sizing

```
Risiko = Kapital × 2% × Regime-Faktor × Vol-Faktor × IV-Faktor × CB-Faktor × Portfolio-Gewicht
Menge  = Risiko ÷ Stop-Abstand (ATR × Regime-Multiplikator)
```

**Beispiel** bei 1.000$ Kapital, BULL_TREND (1.0), Vol NORMAL (0.85), ATR 1.200$:
- Risiko: 1.000 × 2% × 0.85 = **17 USDT**
- Menge: 17 ÷ 2.400 = **0.0071 BTC**

---

## Model Governance

Drei laufende Monitore schützen vor Modell-Degradation:

### Vorhersage-Entropie
Misst Shannon-Entropie der ML-Wahrscheinlichkeiten.
- Entropie > 80% → Modell ist unsicher → Positionsgröße auf 0.25× reduziert
- Entropie < 50% → normal

### Feature-Importance-Drift
Vergleicht Top-5-Features aktuell vs. historisch (Jaccard-Ähnlichkeit).
- Jaccard < 40% → Concept Drift erkannt → Retraining empfohlen

### Kalibrierungs-Drift (ECE)
Expected Calibration Error: wie gut stimmen Konfidenz-% mit realer Trefferrate überein?
- ECE-Anstieg > 6% über Baseline → 20% zusätzliche Positions-Reduktion

---

## Online Learning

Nach jedem abgeschlossenen Trade aktualisiert sich das System:

1. **SGDClassifier** (partial_fit) — inkrementelles Update ohne volles Retraining
2. **Platt Scaling** — kalibriert ML-Wahrscheinlichkeiten auf echte Trefferrate
3. **Bayesian Signal Updater** — Beta-Binomial Prior pro Signalquelle; lernt welche Quellen zuverlässiger sind

---

## Strategy Lifecycle

Jede Strategie durchläuft automatisch Lebenszyklus-Phasen:

```
ACTIVE → COOLING (Win-Rate 10 Punkte unter Durchschnitt)
       → DORMANT (nach weiterer Verschlechterung)
       → REVIVAL  (wenn Markt-Regime wieder passt)
```

Der **Adaptive Rotation Scheduler** aktiviert pro Regime nur die historisch besten Strategien.
Dormante Strategien werden überwacht und reaktiviert wenn ihre Regime-Affinität wieder stimmt.

---

## Trade Explainability

Für jeden Trade generiert der Bot eine natürlichsprachliche Erklärung (im Log + Dashboard):

```
📊 EUR_USD BUY @ 1.08542 | Konfidenz 72%
Regime: TREND_UP (seit 14h) | Session: London
Signale: EMA-Crossover ↑ | MACD positiv ↑ | RSI 52 (neutral)
ML: XGBoost BUY 68% | LSTM BUY 74% | Ensemble 72%
Einstieg: M15 Pullback @ EMA20 (3.2 Pips besser)
SL: 1.08310 (-21.2 Pips / 1.0% Risiko) | TP: 1.08912 (+37.0 Pips) | RR 1.75:1
Modifiziert: IV normal (1.0×) | CB hawkish +2% | Portfolio-Gewicht 28%
```

---

## Risk Management

### Circuit Breaker
Stoppt den Bot automatisch bei Tagesverlust-Limit. Setzt sich täglich zurück.

### Max-Drawdown-Stopp
Stoppt den Bot permanent bei Drawdown-Limit. Manuelle Prüfung erforderlich.

### Trailing Stop
- Stop = Höchstpreis × (1 - 1.5%)
- Gewinne werden automatisch gesichert wenn der Preis steigt

### Drawdown Recovery

| Drawdown | Positions-Faktor |
|----------|-----------------|
| < 7% | 1.0× (normal) |
| 7–10% | 0.75× |
| 10–15% | 0.50× |
| ≥ 15% | 0.25× |

### Risk Mode Profile

| Mode | Risiko/Trade | Max Drawdown | Circuit Breaker |
|------|-------------|--------------|-----------------|
| 🛡️ conservative | 1% | 10% | 3% |
| ⚖️ balanced | 2% | 20% | 6% |
| 🔥 aggressive | 3% | 30% | 9% |

---

## Performance-Metriken

| Metrik | Gut | Akzeptabel |
|--------|-----|------------|
| **Sharpe Ratio** | > 1.5 | > 1.0 |
| **Profit Factor** | > 1.5 | > 1.2 |
| **Win-Rate** | > 55% | > 45% |
| **Max Drawdown** | < 10% | < 20% |

**Wichtig:** Immer mit Buy & Hold vergleichen (`make backtest`).

---

## Phasen: Paper → Testnet → Live

Der Bot durchläuft drei Phasen. Er wechselt **niemals automatisch** — jeder Schritt erfordert deine ausdrückliche Bestätigung.

```
Paper  ──(Kriterien erfüllt + /approve_live)──► Testnet
Testnet──(Kriterien erfüllt + /approve_live)──► Live
```

### Übergangs-Kriterien (gelten für beide Schritte)

| Kriterium | Zielwert |
|---|---|
| Trades gesammelt | ≥ 20 |
| Sharpe Ratio | ≥ 0.8 |
| Win-Rate | ≥ 48% |
| Max. Drawdown | ≤ 15% |
| ML-Modell F1-Score | ≥ 0.38 |

Alle fünf Kriterien müssen gleichzeitig erfüllt sein.

### Ablauf

1. **Paper-Phase:** Bot handelt mit virtuellem Kapital. Fortschritt jederzeit mit `/progress` in Telegram abrufbar.
2. **Bereitschaftsmeldung:** Sobald alle Kriterien erfüllt sind, sendet der Bot eine Telegram-Nachricht.
3. **Manuelle Bestätigung:** Du antwortest mit `/approve_live` (oder klickst den Button im Web-Dashboard).
4. **Testnet-Phase:** Bot handelt auf Binance Testnet mit echten API-Aufrufen, aber ohne echtes Geld. Dieselben Kriterien werden erneut gemessen.
5. **Live-Aktivierung:** Nach erneuter Bestätigung (`/approve_live`) wechselt der Bot zu echtem Kapital.

### Fortschritt verfolgen

```
/progress        # Aktueller Stand aller Kriterien + ETA bis nächste Phase
```

Im Web-Dashboard zeigt die Fortschrittsanzeige alle Kriterien mit Prozentwert und geschätzten Tagen bis zum nächsten Schritt.

---

## Custom Strategies — Eigene Strategien (IStrategy Interface)

Eigene Trading-Strategien können ohne Anpassung des Bot-Kerns eingebunden werden.

### Schnellstart

```bash
# 1. Datei erstellen
cp strategies/README.md strategies/my_strategy.py

# 2. Strategie aktivieren
echo "STRATEGY=MyTrendStrategy" >> .env
echo "FEATURE_CUSTOM_STRATEGY=true" >> .env

# 3. Bot neu starten
make crypto-restart
```

### Pflicht-Methoden

```python
from crypto_bot.strategy.interface import IStrategy
import pandas as pd

class MyTrendStrategy(IStrategy):
    timeframe   = "1h"        # Candle-Timeframe
    min_bars    = 50           # Mindest-Candles für Indikatoren
    description = "Mein Trend-Folge-System"

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Technische Indikatoren als neue Spalten hinzufügen."""
        df["ema20"] = df["close"].ewm(span=20).mean()
        df["ema50"] = df["close"].ewm(span=50).mean()
        return df

    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """df['buy'] = 1 wenn Kauf-Signal, 0 sonst."""
        df["buy"] = (df["ema20"] > df["ema50"]).astype(int)
        return df

    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """df['sell'] = 1 wenn Verkauf-Signal, 0 sonst."""
        df["sell"] = (df["ema20"] < df["ema50"]).astype(int)
        return df
```

### Optionale Callbacks

| Methode | Beschreibung | Standard |
|---------|-------------|---------|
| `custom_stoploss()` | Eigener Stop-Loss Preis | ATR-basiert |
| `confirm_trade_entry()` | Trade vor Ausführung validieren | `True` |
| `confirm_trade_exit()` | Exit blockieren | `True` |
| `on_trade_opened()` | Callback nach Kauf | – |
| `on_trade_closed()` | Callback nach Verkauf | – |
| `custom_stake_amount()` | Positions-Größe in USDT | ATR-Sizing |
| `adjust_trade_position()` | DCA / Scale-Out | – |
| `informative_pairs()` | Zusätzliche Daten-Paare | `[]` |

### Eingebaute Strategien

| Name | Beschreibung | Timeframe |
|------|-------------|-----------|
| `MACrossStrategy` | EMA-Crossover + RSI-Filter | 1h |
| `RSIBBStrategy` | RSI-Überkauf/-Überverkauf + Bollinger Bands | 1h |

### Hyperopt mit Custom Loss-Funktion

```bash
# Calmar-optimierte Parameter suchen (Rendite/Drawdown)
HYPEROPT_LOSS=calmar python -m crypto_bot.optimization.hyperopt --trials 100

# Verfügbare Loss-Funktionen:
# sharpe, sortino, calmar, profit_drawdown, only_profit, multi_metric
```
