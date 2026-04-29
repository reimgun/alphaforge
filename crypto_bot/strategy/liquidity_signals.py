"""
Liquidity-Driven Signals — handelt auf Basis von Liquiditätsereignissen.

Konzept:
  Große Marktteilnehmer (Institutional Flow) hinterlassen Spuren:
  - Plötzliche Volumen-Spikes bei niedrigem Spread = Accumulation
  - Hoher Amihud-Illiquidity-Score = dünnes Orderbuch = Vorsicht

Signal-Logik:
  BUY  → Volumen-Spike (>2x Ø) + niedriger Spread-Proxy + Preis über EMA20
          = Institutional Buying erkannt → mitreiten
  SELL → Volumen-Spike + Preis unter EMA20 + RSI überkauft
          = Distribution erkannt → aussteigen
  HOLD → Kein klares Liquiditätssignal

Geeignet für: BULL_TREND als Bestätigung starker Bewegungen.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from crypto_bot.strategy.momentum import Signal


@dataclass
class LiquiditySignal:
    signal:         Signal
    price:          float
    reason:         str
    volume_ratio:   float   # Aktuelles Volumen / 20-Perioden-Ø
    spread_proxy:   float   # (High - Low) / Close — niedriger = enger Spread
    illiquidity:    float   # Amihud-Illiquidity-Proxy
    price_vs_ema20: float   # (Close / EMA20 - 1) in %


def add_liquidity_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet alle Liquiditäts-Indikatoren."""
    d = df.copy()

    # Volumen-Ratio: aktuell vs 20-Perioden-Ø
    vol_ma20          = d["volume"].rolling(20).mean()
    d["vol_ratio"]    = d["volume"] / vol_ma20.replace(0, np.nan)

    # Spread-Proxy: (High - Low) / Close — enger Spread = hohe Liquidität
    d["spread_proxy"] = (d["high"] - d["low"]) / d["close"].replace(0, np.nan)

    # Amihud-Illiquidity: |Return| / Volume — klein = liquide
    abs_ret            = d["close"].pct_change().abs()
    d["illiquidity"]   = (abs_ret / d["volume"].replace(0, np.nan)).rolling(5).mean() * 1e6

    # EMA20 für Trend-Kontext
    d["ema20"]         = d["close"].ewm(span=20, adjust=False).mean()
    d["price_vs_ema20"] = (d["close"] / d["ema20"].replace(0, np.nan) - 1) * 100

    # RSI14 für Überkauft/Überverkauft
    delta  = d["close"].diff()
    gain   = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    d["rsi14"] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50)

    # Gleitender Spread-Ø für relativen Vergleich
    d["spread_ma10"]   = d["spread_proxy"].rolling(10).mean()

    return d


def generate_liquidity_signal(
    df: pd.DataFrame,
    vol_spike_threshold:   float = 2.0,    # Volumen muss X-fach über Ø sein
    spread_ratio_threshold: float = 0.8,   # Spread muss unter X * Ø liegen
    rsi_overbought:        float = 70.0,
    rsi_oversold:          float = 30.0,
) -> LiquiditySignal:
    """
    Erzeugt Liquiditäts-getriebenes Handelssignal.

    Args:
        df:                    OHLCV DataFrame (mind. 50 Candles)
        vol_spike_threshold:   Volumen-Multiplikator für "Spike"
        spread_ratio_threshold: Max. erlaubter Spread-Ratio vs Ø
        rsi_overbought:        RSI-Grenze für Überkauft
        rsi_oversold:          RSI-Grenze für Überverkauft
    """
    d = add_liquidity_indicators(df)

    price          = float(d["close"].iloc[-1])
    vol_ratio      = float(d["vol_ratio"].fillna(1.0).iloc[-1])
    spread_proxy   = float(d["spread_proxy"].fillna(0.01).iloc[-1])
    spread_ma      = float(d["spread_ma10"].fillna(spread_proxy).iloc[-1])
    illiquidity    = float(d["illiquidity"].fillna(0).iloc[-1])
    price_vs_ema20 = float(d["price_vs_ema20"].fillna(0).iloc[-1])
    rsi14          = float(d["rsi14"].iloc[-1])

    # Spread relativ zum Ø — kleiner = enger = mehr Liquidität
    spread_ratio = spread_proxy / spread_ma if spread_ma > 0 else 1.0

    has_vol_spike   = vol_ratio >= vol_spike_threshold
    has_tight_spread = spread_ratio <= spread_ratio_threshold
    price_above_ema = price_vs_ema20 > 0
    price_below_ema = price_vs_ema20 < 0

    # ── BUY: Institutional Accumulation ────────────────────────────────────
    # Großer Volumen-Spike + enger Spread + Preis über EMA20 + nicht überkauft
    if has_vol_spike and has_tight_spread and price_above_ema and rsi14 < rsi_overbought:
        return LiquiditySignal(
            signal=Signal.BUY,
            price=price,
            reason=(
                f"Liquidity BUY: Vol={vol_ratio:.1f}x Spike | "
                f"Spread={spread_ratio:.2f}x eng | "
                f"Preis {price_vs_ema20:+.1f}% über EMA20 | "
                f"RSI={rsi14:.0f}"
            ),
            volume_ratio=vol_ratio,
            spread_proxy=spread_proxy,
            illiquidity=illiquidity,
            price_vs_ema20=price_vs_ema20,
        )

    # ── SELL: Distribution / Institutional Exit ─────────────────────────────
    # Volumen-Spike + Preis unter EMA20 (oder RSI überkauft)
    if has_vol_spike and (price_below_ema or rsi14 > rsi_overbought):
        return LiquiditySignal(
            signal=Signal.SELL,
            price=price,
            reason=(
                f"Liquidity SELL: Vol={vol_ratio:.1f}x Spike | "
                f"Preis {price_vs_ema20:+.1f}% vs EMA20 | "
                f"RSI={rsi14:.0f}"
            ),
            volume_ratio=vol_ratio,
            spread_proxy=spread_proxy,
            illiquidity=illiquidity,
            price_vs_ema20=price_vs_ema20,
        )

    # ── HOLD: Kein klares Liquiditätssignal ────────────────────────────────
    return LiquiditySignal(
        signal=Signal.HOLD,
        price=price,
        reason=(
            f"Liquidity HOLD: Vol={vol_ratio:.1f}x "
            f"({'Spike' if has_vol_spike else 'normal'}) | "
            f"Spread={'eng' if has_tight_spread else 'weit'}"
        ),
        volume_ratio=vol_ratio,
        spread_proxy=spread_proxy,
        illiquidity=illiquidity,
        price_vs_ema20=price_vs_ema20,
    )
