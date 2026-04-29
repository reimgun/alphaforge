"""
Multi-Timeframe Analysis (MTF).

Checks higher-timeframe trend alignment before allowing a trade entry.
The primary signal is generated on H1; this module checks H4 and D1
to confirm the trade direction has the "wind at its back".

EMA-based trend classification:
  UP      — EMA20 > EMA50 > EMA200
  DOWN    — EMA20 < EMA50 < EMA200
  NEUTRAL — neither of the above

Conservative mode requires BOTH H4 and D1 to agree with the signal.
Balanced / Aggressive requires at least H4 to agree.
"""
import logging

import pandas as pd

log = logging.getLogger("forex_bot")


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def get_htf_trend(client, instrument: str, timeframe: str = "H4") -> str:
    """
    Returns 'UP', 'DOWN', or 'NEUTRAL' based on EMA20/50/200 on the given timeframe.

    Parameters
    ----------
    client:      OandaClient instance
    instrument:  e.g. "EUR_USD"
    timeframe:   OANDA granularity string, e.g. "H4" or "D"

    Returns
    -------
    "UP" | "DOWN" | "NEUTRAL"
    """
    try:
        candles = client.get_candles(instrument, timeframe, count=210)
        if len(candles) < 50:
            log.warning(f"MTF {instrument} {timeframe}: only {len(candles)} candles — NEUTRAL")
            return "NEUTRAL"

        closes = pd.Series([float(c["close"]) for c in candles])

        ema20  = _ema(closes, 20).iloc[-1]
        ema50  = _ema(closes, 50).iloc[-1]
        ema200 = _ema(closes, 200).iloc[-1] if len(candles) >= 200 else None

        if ema200 is not None:
            if ema20 > ema50 > ema200:
                return "UP"
            if ema20 < ema50 < ema200:
                return "DOWN"
        else:
            # fallback when not enough candles for EMA200: use EMA20/50 only
            if ema20 > ema50:
                return "UP"
            if ema20 < ema50:
                return "DOWN"

        return "NEUTRAL"

    except Exception as e:
        log.warning(f"MTF trend fetch failed ({instrument} {timeframe}): {e}")
        return "NEUTRAL"


def mtf_confirmation(
    client,
    instrument: str,
    signal_direction: str,
    require_both: bool = True,
) -> tuple[bool, str]:
    """
    Checks H4 and D1 trend alignment with the proposed trade direction.

    Parameters
    ----------
    client:           OandaClient instance
    instrument:       e.g. "EUR_USD"
    signal_direction: "BUY" or "SELL"
    require_both:     True  → both H4 AND D1 must align (conservative)
                      False → H4 alone is sufficient (balanced/aggressive)

    Returns
    -------
    (confirmed: bool, reason: str)
    """
    if signal_direction not in ("BUY", "SELL"):
        return False, f"Invalid signal direction: {signal_direction}"

    expected_trend = "UP" if signal_direction == "BUY" else "DOWN"

    h4_trend = get_htf_trend(client, instrument, "H4")
    d1_trend = get_htf_trend(client, instrument, "D")

    h4_aligned = (h4_trend == expected_trend)
    d1_aligned = (d1_trend == expected_trend)

    log.debug(
        f"MTF {instrument} {signal_direction}: "
        f"H4={h4_trend} D1={d1_trend} "
        f"(h4_aligned={h4_aligned}, d1_aligned={d1_aligned})"
    )

    if require_both:
        if h4_aligned and d1_aligned:
            return True, f"MTF confirmed: H4={h4_trend}, D1={d1_trend}"
        missing = []
        if not h4_aligned:
            missing.append(f"H4={h4_trend}")
        if not d1_aligned:
            missing.append(f"D1={d1_trend}")
        return False, f"MTF mismatch: {', '.join(missing)} vs expected {expected_trend}"

    else:
        # H4 alone is sufficient
        if h4_aligned:
            return True, f"MTF H4 confirmed: H4={h4_trend}, D1={d1_trend}"
        return False, f"MTF H4 mismatch: H4={h4_trend} vs expected {expected_trend}"
