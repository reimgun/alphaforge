"""
Wirtschaftskalender-Integration.

Datenquelle: ForexFactory (inoffizielles JSON-Feed)
  https://nfs.faireconomy.media/ff_calendar_thisweek.json
  https://nfs.faireconomy.media/ff_calendar_nextweek.json

Gibt zurück:
  - is_news_pause()      → True wenn High-Impact-Event ±N Minuten
  - get_upcoming_events()→ Events der nächsten N Stunden
  - get_week_events()    → Alle Events diese + nächste Woche

Kein API-Key nötig.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("forex_bot")

_FF_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FF_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

_HEADERS       = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
_CACHE_TTL     = 4 * 3600   # 4 Stunden zwischen Requests (ForexFactory rate-limitet stark)
_WARN_INTERVAL = 6 * 3600   # Max. 1 WARNING pro 6 Stunden wenn Feed offline

# Modul-Level Cache — überlebt Container-Restarts nicht, aber verhindert Hammer-Requests
_cache: dict = {"events": [], "ts": 0.0, "last_warn_ts": 0.0}


def _fetch_raw(url: str) -> list:
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _parse_events(raw: list, currencies: list = None) -> list:
    """
    Parst rohe ForexFactory-Events.

    Filtert:
      - Nur "High" und "Medium" Impact
      - Optional: nur bestimmte Währungen
    """
    events = []
    for ev in raw:
        impact = ev.get("impact", "")
        if impact not in ("High", "Medium"):
            continue

        currency = ev.get("currency", "")
        if currencies and currency not in currencies:
            continue

        date_str = ev.get("date", "")
        if not date_str:
            continue

        try:
            # ForexFactory liefert ISO-8601 mit oder ohne Timezone
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        events.append({
            "time":     dt,
            "currency": currency,
            "event":    ev.get("title", ""),
            "impact":   impact,
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        })

    return sorted(events, key=lambda x: x["time"])


def _first_friday_of_month(year: int, month: int) -> int:
    """Gibt den Tag des ersten Freitags im Monat zurück."""
    from calendar import monthcalendar
    for week in monthcalendar(year, month):
        if week[4]:   # Freitag = Index 4
            return week[4]
    return 1


def _second_tuesday_of_month(year: int, month: int) -> int:
    """Gibt den Tag des zweiten Dienstags im Monat zurück (typischer US-CPI-Tag)."""
    from calendar import monthcalendar
    tuesdays = [week[1] for week in monthcalendar(year, month) if week[1]]
    return tuesdays[1] if len(tuesdays) >= 2 else tuesdays[0]


# FOMC-Sitzungsmonate (8x pro Jahr: Jan, Mar, Mai, Jun, Jul, Sep, Nov, Dez)
_FOMC_MONTHS = {1, 3, 5, 6, 7, 9, 11, 12}


def _check_known_high_risk_window(now: datetime) -> str:
    """
    Fail-safe: prüft ob wir gerade in einem bekannten Hochrisiko-Zeitfenster
    sind, auch wenn der Kalender-Feed offline ist.

    Berechnet exakte Termine für wiederkehrende High-Impact-Events:
      - NFP: erster Freitag im Monat 13:00–14:30 UTC
      - US CPI: zweiter Dienstag im Monat 12:30–14:00 UTC
      - FOMC: Mittwoch 18:00–20:30 UTC (in FOMC-Monaten)
      - Fallback: konservative Wochentag-Fenster wenn Datum unklar
    """
    weekday = now.weekday()   # 0=Montag, 4=Freitag
    hour    = now.hour
    minute  = now.minute
    h_frac  = hour + minute / 60.0
    day     = now.day
    month   = now.month
    year    = now.year

    # NFP: erster Freitag im Monat, 13:00–14:30 UTC
    if weekday == 4 and 13.0 <= h_frac <= 14.5:
        nfp_day = _first_friday_of_month(year, month)
        if day == nfp_day:
            return f"NFP-Tag (erster Freitag {day}.{month}), 13:00–14:30 UTC"
        # Konservativer Fallback: alle Freitage im NFP-Fenster
        return "Freitag 13:00–14:30 UTC (mögliches US-Jobs-Fenster)"

    # US CPI: zweiter Dienstag im Monat, 12:30–14:00 UTC
    if weekday == 1 and 12.5 <= h_frac <= 14.0:
        cpi_day = _second_tuesday_of_month(year, month)
        if day == cpi_day:
            return f"US-CPI-Tag (zweiter Dienstag {day}.{month}), 12:30–14:00 UTC"

    # FOMC: Mittwoch 18:00–20:30 UTC — nur in FOMC-Monaten
    if weekday == 2 and 18.0 <= h_frac <= 20.5:
        if month in _FOMC_MONTHS:
            return f"Mittwoch 18:00–20:30 UTC (FOMC-Monat {month})"
        # Konservativer Fallback: alle Mittwoche
        return "Mittwoch 18:00–20:30 UTC (mögliches FOMC-Fenster)"

    # US PPI / Mittwoch CPI Spill-over
    if weekday == 2 and 12.5 <= h_frac <= 14.0:
        return "Mi 12:30–14:00 UTC (mögliches US-PPI-Fenster)"

    return ""


def fetch_calendar(currencies: list = None) -> list:
    """
    Lädt und cached Kalender-Events (diese + nächste Woche).

    Nutzt 4-Stunden-Cache um ForexFactory Rate-Limits zu vermeiden.
    Bei 429/404: Cache-Daten verwenden, kein Spam in den Logs.

    currencies: z.B. ["USD", "EUR", "GBP"] — None = alle
    """
    now_ts = time.time()
    cache_age = now_ts - _cache["ts"]

    if cache_age < _CACHE_TTL and _cache["events"]:
        # Cache noch frisch — direkt filtern und zurückgeben
        all_events = _cache["events"]
    else:
        # Neue Daten laden
        fresh: list = []
        fetch_ok    = False
        for url in (_FF_THIS_WEEK, _FF_NEXT_WEEK):
            try:
                raw    = _fetch_raw(url)
                fresh += _parse_events(raw, None)   # Alle laden, unten filtern
                fetch_ok = True
            except Exception as e:
                status = str(e)
                if "429" in status:
                    log.debug(f"Kalender rate-limited ({url}) — Cache wird genutzt")
                elif "404" in status:
                    log.debug(f"Kalender-Feed {url} nicht gefunden (normal für nächste Woche)")
                else:
                    since_warn = now_ts - _cache["last_warn_ts"]
                    if since_warn > _WARN_INTERVAL:
                        log.warning(f"Kalender-Feed nicht verfügbar ({url}): {e}")
                        _cache["last_warn_ts"] = now_ts

        if fetch_ok:
            _cache["events"] = sorted(fresh, key=lambda x: x["time"])
            _cache["ts"]     = now_ts

        all_events = _cache["events"]

    if currencies:
        all_events = [e for e in all_events if e["currency"] in currencies]
    return sorted(all_events, key=lambda x: x["time"])


def is_news_pause(
    currencies:    list,
    pause_minutes: int = 30,
) -> tuple[bool, str]:
    """
    Gibt (True, Grund) zurück wenn gerade ein High-Impact-Event
    innerhalb von ±pause_minutes Minuten stattfindet.

    Nur "High"-Impact-Events lösen Pause aus.

    Fail-safe: wenn der Kalender nicht erreichbar ist und eine bekannte
    High-Impact Zeit in der Nähe ist (z.B. 13:30 UTC freitags für NFP),
    wird trotzdem pausiert. Im schlimmsten Fall pausiert der Bot kurz
    unnötig — das ist sicherer als während eines Events zu handeln.

    Beispiel:
        paused, reason = is_news_pause(["USD","EUR"])
        if paused:
            log.info(f"Keine Trades: {reason}")
    """
    try:
        events = fetch_calendar(currencies)
    except Exception as e:
        log.warning(f"Kalender nicht erreichbar: {e} — prüfe bekannte Hochrisiko-Zeiten")
        # Fail-safe: pausiere während bekannter Hochrisiko-Zeitfenster
        # auch wenn der Kalender offline ist
        now = datetime.now(timezone.utc)
        reason = _check_known_high_risk_window(now)
        if reason:
            return True, f"⚠️ Kalender offline — {reason}"
        return False, ""

    now = datetime.now(timezone.utc)

    for ev in events:
        if ev["impact"] != "High":
            continue

        diff_sec = (ev["time"] - now).total_seconds()
        diff_min = diff_sec / 60

        if -pause_minutes <= diff_min <= pause_minutes:
            if diff_min > 0:
                direction = f"in {int(diff_min)} Min."
            else:
                direction = f"vor {int(abs(diff_min))} Min."

            reason = (
                f"📰 {ev['currency']} {ev['event']} — {direction} "
                f"(High Impact)"
            )
            return True, reason

    return False, ""


def get_upcoming_events(currencies: list, hours: int = 24) -> list:
    """
    Gibt Events der nächsten N Stunden zurück.

    Nützlich für Telegram /news oder Dashboard-Anzeige.
    """
    try:
        events = fetch_calendar(currencies)
    except Exception:
        return []

    now    = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours)
    return [e for e in events if now <= e["time"] <= cutoff]


def get_today_events(currencies: list = None) -> list:
    """Alle Events des heutigen Tages (UTC)."""
    try:
        events = fetch_calendar(currencies)
    except Exception:
        return []

    today = datetime.now(timezone.utc).date()
    return [e for e in events if e["time"].date() == today]


def format_events_telegram(events: list, max_events: int = 10) -> str:
    """
    Formatiert Event-Liste als Telegram-HTML.

    Beispiel-Output:
      🔴 14:30 USD Non-Farm Payrolls (High)
      🟡 16:00 EUR EZB Pressekonferenz (Medium)
    """
    if not events:
        return "Keine relevanten Events in diesem Zeitraum."

    lines = []
    for ev in events[:max_events]:
        icon    = "🔴" if ev["impact"] == "High" else "🟡"
        time_str = ev["time"].strftime("%H:%M UTC")
        forecast = f" · Prognose: {ev['forecast']}" if ev.get("forecast") else ""
        lines.append(f"{icon} {time_str} <b>{ev['currency']}</b> {ev['event']}{forecast}")

    return "\n".join(lines)
