"""
Multi-Timeframe Analysis — übergeordneter 4h-Trend als Filter.

Logik:
  BULLISH  → 4h Preis über MA50, MA50 steigt  → nur BUY-Signale zulassen
  BEARISH  → 4h Preis unter MA50, MA50 fällt  → nur SELL-Signale zulassen
  NEUTRAL  → Unklarer Trend                   → HOLD (kein Trade)

Damit werden Fehlsignale gegen den übergeordneten Trend eliminiert.
"""
import pandas as pd
from dataclasses import dataclass
from crypto_bot.data.fetcher import fetch_ohlcv
from crypto_bot.config.settings import SYMBOL, TREND_TIMEFRAME
from crypto_bot.monitoring.logger import log


@dataclass
class TrendContext:
    direction: str     # "BULLISH" | "BEARISH" | "NEUTRAL"
    ma50: float
    ma20: float
    price: float
    slope_5: float     # MA50-Steigung über letzte 5 Candles (positiv = steigend)
    strength: str      # "strong" | "weak"


def get_htf_trend(symbol: str = SYMBOL, timeframe: str = TREND_TIMEFRAME) -> TrendContext:
    """
    Analysiert den übergeordneten Trend auf dem höheren Timeframe.
    Cached nichts — wird einmal pro Bot-Zyklus aufgerufen.
    """
    try:
        df = fetch_ohlcv(symbol, timeframe, days=120)
        close = df["close"]

        ma20  = close.rolling(20).mean()
        ma50  = close.rolling(50).mean()

        current_price = close.iloc[-1]
        current_ma50  = ma50.iloc[-1]
        current_ma20  = ma20.iloc[-1]

        # MA50-Steigung: Verhältnis aktuell vs vor 5 Candles
        slope_5 = (current_ma50 / ma50.iloc[-6] - 1) * 100 if len(ma50) >= 6 else 0.0

        # Trendstärke: Abstand Preis zu MA50
        distance_pct = abs(current_price - current_ma50) / current_ma50 * 100

        price_above_ma50 = current_price > current_ma50
        price_above_ma20 = current_price > current_ma20
        ma20_above_ma50  = current_ma20  > current_ma50

        if price_above_ma50 and slope_5 > 0.05:
            direction = "BULLISH"
            strength  = "strong" if (price_above_ma20 and ma20_above_ma50) else "weak"
        elif not price_above_ma50 and slope_5 < -0.05:
            direction = "BEARISH"
            strength  = "strong" if (not price_above_ma20 and not ma20_above_ma50) else "weak"
        else:
            direction = "NEUTRAL"
            strength  = "weak"

        log.debug(
            f"HTF Trend [{timeframe}]: {direction} ({strength}) | "
            f"Preis={current_price:.0f} | MA50={current_ma50:.0f} | Slope={slope_5:+.3f}%"
        )
        return TrendContext(
            direction=direction,
            ma50=current_ma50,
            ma20=current_ma20,
            price=current_price,
            slope_5=slope_5,
            strength=strength,
        )

    except Exception as e:
        log.warning(f"HTF-Trend-Fehler: {e} — NEUTRAL als Fallback")
        return TrendContext("NEUTRAL", 0, 0, 0, 0, "weak")


def filter_signal_by_trend(signal: str, trend: TrendContext) -> str:
    """
    Filtert ein Signal anhand des übergeordneten Trends.
    BUY-Signale gegen den Trend werden zu HOLD.
    """
    if trend.direction == "BEARISH" and signal == "BUY":
        log.debug(f"Signal BUY gefiltert (4h BEARISH) → HOLD")
        return "HOLD"

    if trend.direction == "BULLISH" and signal == "SELL":
        # Im starken Bullenmarkt: SELL nur wenn wirklich stark
        if trend.strength == "strong":
            log.debug(f"Signal SELL gefiltert (4h BULLISH strong) → HOLD")
            return "HOLD"

    if trend.direction == "NEUTRAL":
        # Im Seitwärtsmarkt: nur sehr sichere Signale durch
        log.debug(f"Signal {signal} in NEUTRAL-Trend → HOLD")
        return "HOLD"

    return signal
