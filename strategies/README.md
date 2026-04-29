# Custom Strategies

Eigene Trading-Strategien in diesem Verzeichnis ablegen.

## Anforderungen

1. Python-Datei erstellen (z.B. `my_strategy.py`)
2. Klasse von `IStrategy` ableiten
3. 3 Pflicht-Methoden implementieren

## Beispiel

```python
from crypto_bot.strategy.interface import IStrategy
import pandas as pd

class MyTrendStrategy(IStrategy):
    timeframe   = "1h"
    description = "Meine eigene Trend-Strategie"
    author      = "Max Mustermann"

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema20"] = df["close"].ewm(span=20).mean()
        df["ema50"] = df["close"].ewm(span=50).mean()
        return df

    def populate_entry_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["buy"] = (df["ema20"] > df["ema50"]).astype(int)
        return df

    def populate_exit_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        df["sell"] = (df["ema20"] < df["ema50"]).astype(int)
        return df
```

## Aktivierung

```env
STRATEGY=MyTrendStrategy
FEATURE_CUSTOM_STRATEGY=true
```

Oder im Dashboard unter **Strategie → Strategie wählen**.

## Verfügbare Callbacks (optional)

| Methode | Beschreibung |
|---------|-------------|
| `custom_stoploss()` | Eigener Stop-Loss statt ATR |
| `confirm_trade_entry()` | Trade vor Ausführung validieren |
| `confirm_trade_exit()` | Exit blockieren (z.B. bei starkem Momentum) |
| `on_trade_opened()` | Callback nach Kauf |
| `on_trade_closed()` | Callback nach Verkauf (PnL verfügbar) |
| `custom_stake_amount()` | Eigene Positions-Größe |
| `adjust_trade_position()` | DCA / Scale-Out während offener Position |
| `informative_pairs()` | Zusätzliche Paare für Indikatoren |

Vollständige Dokumentation: `docs/de/STRATEGY.md`
