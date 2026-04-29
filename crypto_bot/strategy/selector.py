"""
Strategy Selector — AI wählt automatisch die beste Strategie je nach Marktregime.

Regime → Strategie:
  BULL_TREND      → Momentum (Golden Cross) + Breakout-Bestätigung
  BEAR_TREND      → HOLD (kein Long)
  SIDEWAYS        → Mean Reversion (Bollinger Bands)
  HIGH_VOLATILITY → Scalping (schnell) + Volatility Expansion (explosiv)
"""
from dataclasses import dataclass
from enum import Enum
import pandas as pd

from crypto_bot.strategy.momentum import generate_signal, Signal, TradeSignal
from crypto_bot.strategy.breakout import generate_breakout_signal, BreakoutSignal
from crypto_bot.strategy.mean_reversion import generate_mean_reversion_signal, MeanReversionSignal
from crypto_bot.strategy.scalping import generate_scalping_signal
from crypto_bot.strategy.volatility_expansion import generate_volatility_expansion_signal
from crypto_bot.strategy.liquidity_signals import generate_liquidity_signal
from crypto_bot.strategy.regime_detector import MarketRegime


class StrategyName(Enum):
    MOMENTUM             = "momentum"
    BREAKOUT             = "breakout"
    MEAN_REVERSION       = "mean_reversion"
    SCALPING             = "scalping"
    VOLATILITY_EXPANSION = "volatility_expansion"
    LIQUIDITY            = "liquidity"
    NONE                 = "none"


@dataclass
class SelectedSignal:
    signal: Signal
    price: float
    reason: str
    strategy: StrategyName
    confidence_boost: float = 0.0   # Bonus wenn Strategie gut zum Regime passt


def select_and_generate(df: pd.DataFrame, regime: MarketRegime) -> SelectedSignal:
    """
    Wählt die zum aktuellen Regime passende Strategie und liefert ihr Signal.
    """
    r = regime.regime

    if r == "BEAR_TREND":
        return SelectedSignal(Signal.HOLD, float(df["close"].iloc[-1]),
                              "BEAR_TREND — kein Long", StrategyName.NONE)

    if r == "SIDEWAYS":
        sig = generate_mean_reversion_signal(df)
        return SelectedSignal(sig.signal, sig.price, sig.reason,
                              StrategyName.MEAN_REVERSION, confidence_boost=0.05)

    if r == "HIGH_VOLATILITY":
        # Scalping-Signal prüfen
        scal = generate_scalping_signal(df)
        if scal.signal != Signal.HOLD:
            return SelectedSignal(scal.signal, scal.price, scal.reason,
                                  StrategyName.SCALPING, confidence_boost=0.05)

        # Volatility Expansion als Alternative
        vol_exp = generate_volatility_expansion_signal(df)
        if vol_exp.signal != Signal.HOLD:
            return SelectedSignal(vol_exp.signal, vol_exp.price, vol_exp.reason,
                                  StrategyName.VOLATILITY_EXPANSION, confidence_boost=0.08)

        # Fallback: Breakout in High-Vol — aber kleinere Position (über regime_factor)
        sig = generate_breakout_signal(df, vol_threshold=1.5)
        return SelectedSignal(sig.signal, sig.price, sig.reason,
                              StrategyName.BREAKOUT, confidence_boost=0.0)

    # BULL_TREND: Momentum primär, Breakout + Liquidity als Bestätigung
    mom = generate_signal(df)
    brk = generate_breakout_signal(df)
    liq = generate_liquidity_signal(df)

    # Alle drei einig → höchste Konfidenz
    if (mom.signal == brk.signal == liq.signal
            and mom.signal != Signal.HOLD):
        return SelectedSignal(
            mom.signal, mom.price,
            f"Momentum+Breakout+Liquidity einig: {mom.reason}",
            StrategyName.MOMENTUM, confidence_boost=0.15,
        )

    # Momentum + Breakout einig
    if mom.signal == brk.signal and mom.signal != Signal.HOLD:
        return SelectedSignal(mom.signal, mom.price,
                              f"Momentum+Breakout einig: {mom.reason}",
                              StrategyName.MOMENTUM, confidence_boost=0.10)

    # Liquidity-Signal allein (starkes Volumen-Ereignis)
    if liq.signal != Signal.HOLD:
        return SelectedSignal(liq.signal, liq.price, liq.reason,
                              StrategyName.LIQUIDITY, confidence_boost=0.05)

    # Nur Momentum-Signal
    return SelectedSignal(mom.signal, mom.price, mom.reason,
                          StrategyName.MOMENTUM)


def get_strategy_for_regime(regime_name: str) -> StrategyName:
    """Gibt die primäre Strategie für ein gegebenes Regime zurück."""
    mapping = {
        "BULL_TREND":       StrategyName.MOMENTUM,
        "BEAR_TREND":       StrategyName.NONE,
        "SIDEWAYS":         StrategyName.MEAN_REVERSION,
        "HIGH_VOLATILITY":  StrategyName.SCALPING,
    }
    return mapping.get(regime_name, StrategyName.MOMENTUM)
