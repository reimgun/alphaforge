"""
Shared Exposure Controller — Crypto + Forex Portfolio-Koordination.

Beide Bots schreiben ihren aktuellen Risikostatus in eine gemeinsame
JSON-Datei. Vor jedem neuen Trade prüfen beide Bots ob das kombinierte
Portfolio-Drawdown oder Risiko-Deployment sichere Grenzen überschreitet.

Dateipfad: SHARED_EXPOSURE_PATH (Standard: /tmp/trading_shared_exposure.json)
           Überschreibbar via ENV: SHARED_EXPOSURE_PATH

Status-Struktur:
{
  "forex": {
    "capital":       10000.0,
    "peak_capital":  10500.0,
    "open_risk_pct": 0.02,      # Gesamt-Risiko offener Forex-Trades
    "drawdown_pct":  2.1,
    "updated":       "2025-01-01T12:00:00+00:00"
  },
  "crypto": {
    "capital":       5000.0,
    ...
  },
  "global_risk_off":    false,  # wenn true → alle Bots pausieren neue Einträge
  "global_drawdown_pct": 3.5    # gewichteter Gesamt-Drawdown
}

Sicherheitsgrenzen:
  - Gesamt-Drawdown > 12%  → Global Risk-Off (alle Bots stoppen)
  - Gesamt-Risiko   > 8%   → Kein neuer Trade
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("forex_bot")

_DEFAULT_PATH = Path(os.getenv(
    "SHARED_EXPOSURE_PATH",
    "/tmp/trading_shared_exposure.json"
))

_MAX_COMBINED_DRAWDOWN_PCT = 12.0   # > 12% kombinierter DD → alle Bots stoppen
_MAX_TOTAL_OPEN_RISK_PCT   = 0.08   # > 8% Gesamt-Risiko deployed → kein neuer Trade


# ── File I/O ──────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _DEFAULT_PATH.exists():
            return json.loads(_DEFAULT_PATH.read_text())
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        _DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEFAULT_PATH.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.debug(f"SharedExposure write failed: {e}")


# ── State Update ──────────────────────────────────────────────────────────────

def update_forex_state(
    capital:       float,
    peak_capital:  float,
    open_risk_pct: float,
) -> None:
    """
    Aktualisiert den Forex-Bot-Status in der gemeinsamen Exposure-Datei.

    Einmal pro Zyklus aufrufen nachdem Trades synchronisiert wurden.

    Parameters
    ----------
    capital:       Aktuelles Kapital
    peak_capital:  Höchststand des Kapitals
    open_risk_pct: Gesamt-Risiko aller offenen Forex-Trades (z.B. 0.02 = 2%)
    """
    data = _load()

    drawdown_pct = 0.0
    if peak_capital > 0:
        drawdown_pct = (peak_capital - capital) / peak_capital * 100

    data["forex"] = {
        "capital":       round(capital, 2),
        "peak_capital":  round(peak_capital, 2),
        "open_risk_pct": round(open_risk_pct, 4),
        "drawdown_pct":  round(drawdown_pct, 2),
        "updated":       datetime.now(timezone.utc).isoformat(),
    }

    # Globalen Drawdown als gewichteten Durchschnitt neu berechnen
    forex_dd  = drawdown_pct
    crypto_dd = data.get("crypto", {}).get("drawdown_pct", 0.0)
    # Gewichtung nach Kapital wenn vorhanden, sonst einfacher Schnitt
    forex_cap  = data["forex"]["capital"]
    crypto_cap = data.get("crypto", {}).get("capital", forex_cap)
    total_cap  = forex_cap + crypto_cap

    if total_cap > 0:
        global_dd = (forex_dd * forex_cap + crypto_dd * crypto_cap) / total_cap
    else:
        global_dd = (forex_dd + crypto_dd) / 2

    data["global_drawdown_pct"] = round(global_dd, 2)

    # Global Risk-Off wenn kombinierter DD zu groß
    was_risk_off = data.get("global_risk_off", False)
    data["global_risk_off"] = global_dd > _MAX_COMBINED_DRAWDOWN_PCT

    if data["global_risk_off"] and not was_risk_off:
        log.warning(
            f"⛔ Global Risk-Off aktiviert: "
            f"kombinierter DD {global_dd:.1f}% > {_MAX_COMBINED_DRAWDOWN_PCT}%"
        )
    elif not data["global_risk_off"] and was_risk_off:
        log.info("✅ Global Risk-Off aufgehoben")

    _save(data)


# ── Trade-Gate ────────────────────────────────────────────────────────────────

def check_global_exposure(new_risk_pct: float = 0.01) -> tuple[bool, str]:
    """
    Prüft ob ein neuer Trade sicher ist.

    Parameters
    ----------
    new_risk_pct: Risiko des neuen Trades als Kapital-Anteil (z.B. 0.01 = 1%)

    Returns
    -------
    (allowed: bool, reason: str)
    allowed=False → Trade überspringen
    """
    data = _load()

    # Global Risk-Off Check
    if data.get("global_risk_off"):
        dd = data.get("global_drawdown_pct", 0)
        return (
            False,
            f"⛔ Global Risk-Off: DD={dd:.1f}% > {_MAX_COMBINED_DRAWDOWN_PCT}%",
        )

    # Gesamt-Risiko Check
    forex_risk  = data.get("forex",  {}).get("open_risk_pct", 0.0)
    crypto_risk = data.get("crypto", {}).get("open_risk_pct", 0.0)
    total_risk  = forex_risk + crypto_risk + new_risk_pct

    if total_risk > _MAX_TOTAL_OPEN_RISK_PCT:
        return (
            False,
            f"Max Gesamt-Risiko: forex={forex_risk:.1%} "
            f"crypto={crypto_risk:.1%} neu={new_risk_pct:.1%} "
            f"(Limit {_MAX_TOTAL_OPEN_RISK_PCT:.0%})",
        )

    return True, ""


def get_global_state() -> dict:
    """Gibt den aktuellen globalen Exposure-Status zurück (für Dashboard/Telegram)."""
    return _load()


# ── Regime Bus ────────────────────────────────────────────────────────────────

def publish_regime(
    regime:      str,
    source:      str = "forex",
    vix_level:   float | None = None,
    risk_regime: str | None   = None,
) -> None:
    """
    Publiziert aktuelles Marktregime in den Cross-Bot-Regime-Bus.

    Andere Bots können dieses Regime lesen und ihre Strategie anpassen.

    Parameters
    ----------
    regime:      Aktuelles Regime (TREND_UP/DOWN/SIDEWAYS/HIGH_VOLATILITY)
    source:      Bot-Identifier (z.B. "forex", "crypto")
    vix_level:   VIX-Level wenn verfügbar
    risk_regime: Risk-On / Risk-Off Label
    """
    data = _load()
    if "regime_bus" not in data:
        data["regime_bus"] = {}

    entry: dict = {
        "regime":     regime,
        "updated":    datetime.now(timezone.utc).isoformat(),
    }
    if vix_level is not None:
        entry["vix_level"] = round(float(vix_level), 2)
    if risk_regime is not None:
        entry["risk_regime"] = risk_regime

    data["regime_bus"][source] = entry
    _save(data)
    log.debug(f"Regime Bus: {source} → {regime}" + (f" (VIX {vix_level:.1f})" if vix_level else ""))


def get_shared_regime() -> dict:
    """
    Liest Regime-Informationen von allen Bots aus dem Bus.

    Returns
    -------
    Dict mit regime_bus und konsolidiertem Konsens-Regime.
    Beispiel: {"forex": {"regime": "TREND_UP"}, "crypto": {"regime": "HIGH_VOLATILITY"},
               "consensus": "TREND_UP"}
    """
    data       = _load()
    regime_bus = data.get("regime_bus", {})

    if not regime_bus:
        return {"consensus": "UNKNOWN"}

    # Konsens: häufigster Regime-Wert
    regimes = [v.get("regime", "UNKNOWN") for v in regime_bus.values()]
    consensus = max(set(regimes), key=regimes.count)

    # VIX aus irgendeiner Quelle
    vix_levels = [v.get("vix_level") for v in regime_bus.values() if v.get("vix_level") is not None]
    vix = round(sum(vix_levels) / len(vix_levels), 1) if vix_levels else None

    result: dict = {**regime_bus, "consensus": consensus}
    if vix is not None:
        result["vix_level"] = vix

    return result
