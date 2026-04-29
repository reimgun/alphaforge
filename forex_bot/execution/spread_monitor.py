"""
Spread Shock Detector — Feature 8.

Maintains a rolling EMA of observed spreads per instrument.
Raises an alert when the current spread is significantly above
the rolling average (e.g. 2.5× normal) — which often signals:
  - Imminent news release
  - Illiquid session (early Tokyo / late Friday)
  - Broker maintenance window
  - Flash-crash / liquidity gap

In-memory only (resets on bot restart — EMA rebuilds within a few cycles).

Usage:
    from forex_bot.execution.spread_monitor import is_spread_shock, update_spread

    shock, reason = is_spread_shock(instrument, current_spread)
    if shock:
        log.info(reason)
        continue   # skip this instrument
    # update EMA after passing the check
    update_spread(instrument, current_spread)
"""
import logging

log = logging.getLogger("forex_bot")

SHOCK_MULTIPLIER  = 2.5   # spread > 2.5× rolling average = shock
ABSOLUTE_MAX_PIPS = 8.0   # always block if spread ≥ 8 pips
EMA_ALPHA         = 0.10  # EMA smoothing (≈ 19-period EMA)
MIN_OBSERVATIONS  = 5     # minimum samples before shock detection activates

_spread_ema:   dict[str, float] = {}
_spread_count: dict[str, int]   = {}


def update_spread(instrument: str, spread_pips: float) -> None:
    """
    Update the rolling spread EMA for an instrument.

    Call this each cycle after determining the trade is allowed (or after
    checking but not blocking) to keep the EMA representative of normal
    trading conditions.
    """
    if instrument not in _spread_ema:
        _spread_ema[instrument]   = spread_pips
        _spread_count[instrument] = 1
    else:
        _spread_ema[instrument]   = (
            EMA_ALPHA * spread_pips
            + (1 - EMA_ALPHA) * _spread_ema[instrument]
        )
        _spread_count[instrument] += 1


def is_spread_shock(instrument: str, spread_pips: float) -> tuple[bool, str]:
    """
    Determine whether the current spread is abnormally high.

    Also calls update_spread() internally so callers only need one call.

    Parameters
    ----------
    instrument:  e.g. "EUR_USD"
    spread_pips: current spread in pips from OandaClient.get_spread_pips()

    Returns
    -------
    (shocked: bool, reason: str)
    shocked=True → skip this instrument this cycle
    """
    # Hard cap — block regardless of history
    if spread_pips >= ABSOLUTE_MAX_PIPS:
        update_spread(instrument, spread_pips)
        return (
            True,
            f"{instrument}: spread {spread_pips:.1f} pips ≥ "
            f"absolute max {ABSOLUTE_MAX_PIPS:.0f} pips",
        )

    count = _spread_count.get(instrument, 0)
    if count < MIN_OBSERVATIONS:
        # Not enough history — update and allow (give benefit of doubt)
        update_spread(instrument, spread_pips)
        return False, ""

    ema   = _spread_ema.get(instrument, spread_pips)
    ratio = spread_pips / (ema + 1e-10)

    update_spread(instrument, spread_pips)

    if ratio >= SHOCK_MULTIPLIER:
        return (
            True,
            f"{instrument}: spread shock {spread_pips:.1f} pips "
            f"= {ratio:.1f}× normal ({ema:.1f} pips avg)",
        )

    return False, ""


def get_spread_ema(instrument: str) -> float:
    """Return the current rolling average spread (pips) for an instrument."""
    return round(_spread_ema.get(instrument, 0.0), 2)


def spread_stats() -> dict:
    """Return current spread EMAs for all tracked instruments (for dashboard)."""
    return {instr: round(val, 2) for instr, val in _spread_ema.items()}
