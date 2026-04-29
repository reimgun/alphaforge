"""
Session Quality Multiplier.

Gibt einen Positions-Größen-Multiplikator (0.0–1.3) zurück basierend auf:
  - UTC-Stunde
  - Währungspaar (verschiedene Paare sind in verschiedenen Sessions liquide)

Qualitäts-Stufen:
  < SKIP_THRESHOLD  → Trade überspringen (zu wenig Liquidität)
  0.35 – 0.80       → Reduzierte Positionsgröße
  0.80 – 1.00       → Volle Positionsgröße
  > 1.00            → Erhöhte Positionsgröße (hochwertige Session)

Datenbasis: BIS Triennial Central Bank Survey on FX Markets
  - EUR/USD: 80% der Tagesbewegung während London/NY Sessions
  - USD/JPY: Größte Moves während Asia und NY Open
  - GBP/USD: Liquideste während London Session
  - AUD/NZD: Aktivste während Asia Session (Sydney Open)
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("forex_bot")

# Unter diesem Wert → Trade überspringen
SKIP_THRESHOLD = 0.35

# Paar → {session_name: multiplier}
_SESSION_QUALITY: dict[str, dict[str, float]] = {
    "EUR_USD": {
        "london_open":  1.20,   # Starke EU-Eröffnungsbewegungen
        "london_main":  1.10,
        "ny_overlap":   1.10,   # Höchste Liquidität (beide Märkte offen)
        "ny_main":      0.90,
        "asia_open":    0.35,   # Sehr ruhig für EUR
        "asia_main":    0.30,
    },
    "GBP_USD": {
        "london_open":  1.30,   # GBP volatilste bei London-Öffnung
        "london_main":  1.15,
        "ny_overlap":   1.05,
        "ny_main":      0.85,
        "asia_open":    0.30,
        "asia_main":    0.25,
    },
    "USD_JPY": {
        "london_open":  0.80,
        "london_main":  0.85,
        "ny_overlap":   1.00,
        "ny_main":      1.00,
        "asia_open":    1.20,   # JPY aktiv während Tokyo-Öffnung
        "asia_main":    1.10,
    },
    "AUD_USD": {
        "london_open":  0.85,
        "london_main":  0.80,
        "ny_overlap":   0.90,
        "ny_main":      0.80,
        "asia_open":    1.15,   # AUD aktiv während Sydney/Tokyo
        "asia_main":    1.10,
    },
    "NZD_USD": {
        "london_open":  0.80,
        "london_main":  0.75,
        "ny_overlap":   0.85,
        "ny_main":      0.75,
        "asia_open":    1.15,   # NZD aktiv während Wellington/Tokyo
        "asia_main":    1.10,
    },
    "USD_CAD": {
        "london_open":  0.80,
        "london_main":  0.85,
        "ny_overlap":   1.20,   # CAD aktivste während NY (Ölmarkt)
        "ny_main":      1.10,
        "asia_open":    0.45,
        "asia_main":    0.40,
    },
    "USD_CHF": {
        "london_open":  1.15,
        "london_main":  1.10,
        "ny_overlap":   1.00,
        "ny_main":      0.85,
        "asia_open":    0.40,
        "asia_main":    0.35,
    },
    "EUR_GBP": {
        "london_open":  1.20,   # EUR und GBP beide aktiv bei London-Öffnung
        "london_main":  1.10,
        "ny_overlap":   0.85,
        "ny_main":      0.70,
        "asia_open":    0.35,
        "asia_main":    0.30,
    },
    "EUR_JPY": {
        "london_open":  1.10,
        "london_main":  1.00,
        "ny_overlap":   1.00,
        "ny_main":      0.90,
        "asia_open":    1.05,   # EUR/JPY gemischtes Liquiditätsprofil
        "asia_main":    0.95,
    },
    "GBP_JPY": {
        "london_open":  1.25,
        "london_main":  1.10,
        "ny_overlap":   1.00,
        "ny_main":      0.85,
        "asia_open":    0.90,
        "asia_main":    0.80,
    },
}

# Standard-Qualität für Paare ohne spezifische Definition
_DEFAULT_QUALITY: dict[str, float] = {
    "london_open": 1.00,
    "london_main": 1.00,
    "ny_overlap":  1.00,
    "ny_main":     0.90,
    "asia_open":   0.60,
    "asia_main":   0.55,
}


def _get_session(hour: int) -> str:
    """Gibt den Session-Namen für eine UTC-Stunde zurück."""
    if 7 <= hour < 9:   return "london_open"
    if 9 <= hour < 13:  return "london_main"
    if 13 <= hour < 17: return "ny_overlap"
    if 17 <= hour < 21: return "ny_main"
    if 21 <= hour:      return "asia_open"
    return "asia_main"   # 00–07 UTC


def session_quality(instrument: str, hour: int | None = None) -> tuple[float, str]:
    """
    Gibt (Qualitäts-Multiplikator, Session-Name) für ein Paar und UTC-Stunde zurück.

    Parameters
    ----------
    instrument: z.B. "EUR_USD"
    hour:       UTC-Stunde (0-23), Standard: aktuelle Zeit

    Returns
    -------
    (multiplier: float, session_name: str)

    multiplier:
      < SKIP_THRESHOLD (0.35) → Caller sollte Trade überspringen
      0.35 – 0.80             → Reduzierte Positionsgröße
      0.80 – 1.00             → Volle Positionsgröße
      > 1.00                  → Erhöhte Positionsgröße (beste Session)
    """
    if hour is None:
        hour = datetime.now(timezone.utc).hour

    session      = _get_session(hour)
    pair_quality = _SESSION_QUALITY.get(instrument, _DEFAULT_QUALITY)
    multiplier   = pair_quality.get(session, 1.0)

    log.debug(
        f"Session quality: {instrument} @ {hour:02d}:00 UTC "
        f"→ {session} × {multiplier:.2f}"
    )
    return round(multiplier, 2), session
