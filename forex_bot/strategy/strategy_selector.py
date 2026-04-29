"""
Strategy Selector — Regime- und Session-basierte Strategie-Auswahl.

Wählt automatisch die optimale Strategie basierend auf:
  1. Markt-Regime (TREND / SIDEWAYS / HIGH_VOLATILITY)
  2. Trading-Session (London / NY / Asia / Overlap)

Verfügbare Strategien:
  ema_crossover   — EMA20/50/200 Crossover (Trend-Following, Standard)
  breakout        — 20-Perioden Kanal-Ausbruch (Momentum)
  mean_reversion  — BB + RSI Mittelwert-Rückkehr (Range-Märkte)

Regime → Strategie:
  TREND_UP / TREND_DOWN   → breakout (London Open) oder ema_crossover
  SIDEWAYS                → mean_reversion (geeignete Sessions)
  HIGH_VOLATILITY         → breakout (Momentum auf Vol-Spikes)

Session → Strategie-Präferenz:
  London Open  (07–09 UTC): breakout bevorzugt (große Eröffnungsbewegungen)
  London Main  (09–13 UTC): ema_crossover
  NY/Ldn Overlap (13–17 UTC): ema_crossover oder breakout
  NY Main      (17–21 UTC): ema_crossover
  Asia         (21–07 UTC): mean_reversion (für nicht-JPY Paare)
"""
import logging
from datetime import datetime, timezone

from forex_bot.strategy.forex_strategy import ForexSignal, generate_signal
from forex_bot.strategy.breakout import generate_breakout_signal
from forex_bot.strategy.mean_reversion import generate_mean_reversion_signal

log = logging.getLogger("forex_bot")


def _current_session(hour: int) -> str:
    """Gibt den Session-Namen für eine UTC-Stunde zurück."""
    if 7 <= hour < 9:   return "london_open"
    if 9 <= hour < 13:  return "london_main"
    if 13 <= hour < 17: return "ny_overlap"
    if 17 <= hour < 21: return "ny_main"
    if 21 <= hour:      return "asia_open"
    return "asia_main"   # 00–07 UTC


def select_strategy(regime: str, instrument: str, hour: int | None = None) -> str:
    """
    Gibt den Namen der optimalen Strategie zurück.

    Parameters
    ----------
    regime:     "TREND_UP" | "TREND_DOWN" | "SIDEWAYS" | "HIGH_VOLATILITY"
    instrument: z.B. "EUR_USD"
    hour:       UTC-Stunde (0-23), Standard: aktuelle Zeit

    Returns
    -------
    "ema_crossover" | "breakout" | "mean_reversion" | "none"
    """
    if hour is None:
        hour = datetime.now(timezone.utc).hour

    session = _current_session(hour)
    is_jpy  = "JPY" in instrument

    # Vol-Spike → Breakout-Momentum
    if regime == "HIGH_VOLATILITY":
        return "breakout"

    # Trending → Breakout bei London-Eröffnung, sonst EMA Crossover
    if regime in ("TREND_UP", "TREND_DOWN"):
        if session == "london_open":
            return "breakout"
        return "ema_crossover"

    # Seitwärts → Mean Reversion in geeigneten Sessions
    if regime == "SIDEWAYS":
        # JPY-Paare verhalten sich anders in Asien → kein Mean Reversion
        if not is_jpy and session in ("asia_open", "asia_main"):
            return "mean_reversion"
        if session == "london_main":
            return "mean_reversion"
        # Seitwärts während aktiver Sessions → zu viel Rauschen, überspringen
        return "none"

    return "ema_crossover"


def select_and_generate(
    candles:        list,
    instrument:     str,
    regime:         str,
    hour:           int | None = None,
    atr_multiplier: float = 1.5,
    rr_ratio:       float = 2.0,
) -> tuple[ForexSignal, str]:
    """
    Wählt die Strategie und generiert ein Signal.

    Parameters
    ----------
    candles:        Liste der OHLCV-Candles
    instrument:     z.B. "EUR_USD"
    regime:         Aktuelles Markt-Regime
    hour:           UTC-Stunde, Standard: aktuelle Zeit
    atr_multiplier: SL-Abstand in ATR-Vielfachen
    rr_ratio:       Reward:Risk Verhältnis

    Returns
    -------
    (signal: ForexSignal, strategy_name: str)
    strategy_name: "ema_crossover" | "breakout" | "mean_reversion" | "none"
    """
    if hour is None:
        hour = datetime.now(timezone.utc).hour

    strategy = select_strategy(regime, instrument, hour)

    if strategy == "none":
        hold = ForexSignal(
            instrument, "HOLD", 0, 0, 0, 0, 0, 0.0,
            f"Kein Signal: Regime={regime} passt nicht zur Session"
        )
        return hold, "none"

    if strategy == "breakout":
        signal = generate_breakout_signal(
            candles        = candles,
            instrument     = instrument,
            atr_multiplier = atr_multiplier,
            rr_ratio       = rr_ratio,
        )

    elif strategy == "mean_reversion":
        signal = generate_mean_reversion_signal(
            candles        = candles,
            instrument     = instrument,
            atr_multiplier = max(1.0, atr_multiplier * 0.8),
            rr_ratio       = max(1.3, rr_ratio * 0.75),
        )

    else:  # ema_crossover
        signal = generate_signal(
            candles        = candles,
            instrument     = instrument,
            atr_multiplier = atr_multiplier,
            rr_ratio       = rr_ratio,
        )

    # Regime-Richtungs-Enforcement (außer bei Mean Reversion — SIDEWAYS ist erlaubt)
    if strategy != "mean_reversion" and signal.direction != "HOLD":
        if regime == "TREND_UP" and signal.direction == "SELL":
            signal.direction  = "HOLD"
            signal.confidence = 0.0
            signal.reason     = f"Regime-Block: TREND_UP erlaubt kein SELL [{strategy}]"
        elif regime == "TREND_DOWN" and signal.direction == "BUY":
            signal.direction  = "HOLD"
            signal.confidence = 0.0
            signal.reason     = f"Regime-Block: TREND_DOWN erlaubt kein BUY [{strategy}]"

    log.info(
        f"{instrument} [{strategy}] → {signal.direction} "
        f"conf={signal.confidence:.2f} | {signal.reason[:70]}"
    )

    return signal, strategy
