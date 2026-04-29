"""
Macro Event Lockdown — Feature 7.

Extended pre/post event windows around tier-1 scheduled events.
Unlike the regular news pause (which uses a flat ±30 min window),
this module enforces asymmetric windows sized to event importance:

  FOMC / Fed rate decision  → 24h before, 2h after
  ECB / Bank of England     → 12h before, 2h after
  NFP / Employment          →  4h before, 1h after
  CPI / Consumer Price      →  4h before, 1h after
  GDP                       →  2h before, 1h after
  PMI                       →  2h before, 0h after

The regular economic_calendar.is_news_pause() still runs for other
High-Impact events with a smaller window.  Both checks run in sequence
inside bot.py.

Only HIGH-impact events trigger the lockdown.
"""
import logging
from datetime import datetime, timedelta, timezone

from forex_bot.calendar.economic_calendar import fetch_calendar

log = logging.getLogger("forex_bot")

# (keyword_in_title_lower, hours_before, hours_after)
LOCKDOWN_RULES: list[tuple[str, int, int]] = [
    ("fomc",              24, 2),
    ("federal open",      24, 2),
    ("fed rate",          24, 2),
    ("federal reserve",   24, 2),
    ("ecb",               12, 2),
    ("european central",  12, 2),
    ("bank of england",   12, 2),
    ("boe",               12, 2),
    ("interest rate",     12, 2),  # generic rate decision
    ("non-farm",           4, 1),
    ("nonfarm",            4, 1),
    ("nfp",                4, 1),
    ("employment change",  4, 1),
    ("jobs report",        4, 1),
    ("cpi",                4, 1),
    ("consumer price",     4, 1),
    ("inflation",          4, 1),
    ("gdp",                2, 1),
    ("gross domestic",     2, 1),
    ("unemployment",       2, 1),
    ("claimant",           2, 0),
    ("pmi",                2, 0),
    ("purchasing managers",2, 0),
    ("retail sales",       2, 0),
    ("trade balance",      2, 0),
]


def macro_lockdown_active(
    currencies: list,
    now:        datetime | None = None,
) -> tuple[bool, str, int]:
    """
    Check whether any scheduled macro event is within its lockdown window.

    Parameters
    ----------
    currencies:  list of currency codes, e.g. ["USD", "EUR", "GBP"]
    now:         UTC datetime override for testing (default: current time)

    Returns
    -------
    (locked: bool, reason: str, minutes_until_clear: int)
    locked=True → skip all new trades until minutes_until_clear == 0
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        events = fetch_calendar(currencies)
    except Exception as e:
        log.warning(f"Macro lockdown: calendar fetch failed: {e} — fail-safe active")
        # Fail-safe: wenn Kalender offline → bekannte Risikofenster prüfen
        from forex_bot.calendar.economic_calendar import _check_known_high_risk_window
        reason = _check_known_high_risk_window(now)
        if reason:
            return True, f"⚠️ Kalender offline — {reason}", 90
        return False, "", 0

    for ev in events:
        if ev.get("impact") != "High":
            continue

        title    = (ev.get("event") or "").lower()
        ev_time: datetime = ev["time"]

        for keyword, hours_before, hours_after in LOCKDOWN_RULES:
            if keyword not in title:
                continue

            window_start = ev_time - timedelta(hours=hours_before)
            window_end   = ev_time + timedelta(hours=hours_after)

            if window_start <= now <= window_end:
                remaining   = max(0.0, (window_end - now).total_seconds())
                minutes_clr = int(remaining / 60)

                if now < ev_time:
                    eta = int((ev_time - now).total_seconds() / 60)
                    timing = f"in {eta} min"
                else:
                    elapsed = int((now - ev_time).total_seconds() / 60)
                    timing  = f"{elapsed} min ago"

                reason = (
                    f"Macro lockdown: {ev['currency']} "
                    f"{ev.get('event', '')} ({timing}). "
                    f"Clear in {minutes_clr} min."
                )
                log.info(reason)
                return True, reason, minutes_clr

    return False, "", 0
