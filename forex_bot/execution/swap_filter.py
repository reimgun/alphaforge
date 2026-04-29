"""
Swap / Carry Cost Filter — Feature 4.

Fetches overnight swap rates per instrument and direction, then blocks
trades where the cumulative swap cost over the estimated hold period
exceeds a configurable pip threshold.

Positive swap = broker pays you (favorable carry trade).
Negative swap = you pay the broker (cost drag).

All values are in pips.

OANDA endpoint used (if client provided):
  GET /v3/accounts/{id}/instruments  →  financing field per instrument

Static fallback table is used when the client is unavailable or returns
an error.  Values reflect typical OANDA practice-account rates.
"""
import logging
from typing import Optional

log = logging.getLogger("forex_bot")

# Daily swap in pips (positive = receive, negative = pay)
# Source: typical OANDA practice-account values
_SWAP_FALLBACK: dict[str, dict[str, float]] = {
    "EUR_USD": {"BUY": -0.55, "SELL": +0.23},
    "GBP_USD": {"BUY": -0.42, "SELL": +0.18},
    "USD_JPY": {"BUY": +0.30, "SELL": -0.65},
    "USD_CHF": {"BUY": +0.22, "SELL": -0.55},
    "AUD_USD": {"BUY": -0.32, "SELL": +0.12},
    "NZD_USD": {"BUY": -0.28, "SELL": +0.10},
    "USD_CAD": {"BUY": -0.18, "SELL": +0.08},
    "GBP_JPY": {"BUY": -0.20, "SELL": -0.25},
    "EUR_JPY": {"BUY": -0.30, "SELL": -0.10},
    "EUR_GBP": {"BUY": -0.12, "SELL": +0.05},
    "AUD_JPY": {"BUY": +0.05, "SELL": -0.40},
    "CAD_JPY": {"BUY": +0.08, "SELL": -0.45},
}


def get_swap_daily(instrument: str, direction: str, client=None) -> float:
    """
    Return the daily swap rate in pips for a given instrument / direction.

    Tries the OANDA client first; falls back to the static table.

    Parameters
    ----------
    instrument: e.g. "EUR_USD"
    direction:  "BUY" or "SELL"
    client:     OandaClient instance (optional)

    Returns
    -------
    float: daily swap in pips (positive = receive, negative = pay)
    """
    if client is not None:
        try:
            data = client.get_instrument_financing(instrument)
            key  = "longFinancing" if direction == "BUY" else "shortFinancing"
            val  = float(data.get(key, 0))
            if val != 0.0:
                return val
        except Exception:
            pass

    return _SWAP_FALLBACK.get(instrument, {}).get(direction, 0.0)


def swap_filter(
    instrument:    str,
    direction:     str,
    client=None,
    avg_hold_days: float = 1.0,
    max_swap_pips: float = 2.0,
) -> tuple[bool, str]:
    """
    Decide whether the swap cost is acceptable for this trade.

    Parameters
    ----------
    instrument:    OANDA instrument, e.g. "EUR_USD"
    direction:     "BUY" or "SELL"
    client:        OandaClient (optional — for live swap fetch)
    avg_hold_days: estimated hold duration in days (H1 bot ≈ 1 day)
    max_swap_pips: maximum tolerable total swap cost (absolute pips)

    Returns
    -------
    (ok: bool, info: str)
    ok=False  → skip the trade (swap cost too high)
    ok=True   → proceed (swap within limits or favorable)
    """
    daily = get_swap_daily(instrument, direction, client)
    total = daily * avg_hold_days

    if total >= 0:
        return True, f"Swap favorable: +{total:.2f} pips over {avg_hold_days:.1f}d"

    cost = abs(total)
    if cost > max_swap_pips:
        return (
            False,
            f"Swap cost {cost:.2f} pips > limit {max_swap_pips:.1f} "
            f"over {avg_hold_days:.1f}d (daily={daily:.2f})",
        )

    return True, f"Swap cost {total:.2f} pips over {avg_hold_days:.1f}d (acceptable)"
