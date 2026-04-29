"""
Carry Trade Portfolio Mode — Tier 3.

Systematischer Carry Trade als eigenständige Alpha-Quelle wenn:
  - risk_regime == "ON"
  - VIX < 20 (VIX < 15 = ideal)
  - vol_regime normal
  - Zinsdifferential ≥ 2.0%

Carry Trade Prinzip:
  Kaufe die Währung mit dem höheren Zinssatz.
  Der tägliche Swap-Gewinn kompensiert kleine Gegenbewegungen.
  Historisch ~3–8% p.a. allein aus Carry-Yield, vor Kursgewinnen.

Attraktivste Carry-Pairs (aktuelle Leitzinsen):
  USD_JPY BUY  (5.5% − 0.1% = +5.4% p.a.)
  GBP_JPY BUY  (5.25% − 0.1% = +5.15% p.a.)
  AUD_JPY BUY  (4.35% − 0.1% = +4.25% p.a.)
  NZD_JPY BUY  (5.5% − 0.1% = +5.4% p.a.)
  USD_CHF BUY  (5.5% − 1.75% = +3.75% p.a.)

Exit-Bedingungen:
  - VIX > 20 (Risk-Off — JPY Rückfluss beginnt)
  - risk_regime == "OFF"
  - Normaler SL/TP greift (SL wird bewusst weiter gesetzt: 2× ATR)

Verwendung:
    signals = get_carry_trade_signals(macro_ctx, cot_ctx)
    for sig in signals:
        # sig.instrument, sig.direction, sig.carry_score, sig.reason

    exit_now, reason = should_exit_carry(trade, macro_ctx)
"""
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("forex_bot")

# ── Konfiguration ─────────────────────────────────────────────────────────────
CARRY_MIN_DIFFERENTIAL = 2.0   # Mindest-Zinsdifferential in % p.a.
CARRY_VIX_MAX          = 20.0  # Kein Carry wenn VIX > 20
CARRY_VIX_IDEAL        = 15.0  # Ideale Carry-Bedingung
CARRY_SL_ATR_MULT      = 2.5   # Carry-Trades haben weiteren SL (Kurzfristig-Volatilität tolerieren)


@dataclass
class CarrySignal:
    instrument:   str
    direction:    str    # immer "BUY" (Hochzinswährung kaufen)
    carry_score:  float  # 0–1 (normiert)
    differential: float  # Zinsdifferential in % p.a.
    atr_mult:     float  # empfohlener SL-Multiplikator
    reason:       str


# ── Carry-Umfeld-Check ────────────────────────────────────────────────────────

def is_carry_environment(macro_ctx: dict) -> tuple[bool, str]:
    """
    Prüft ob die Marktbedingungen für Carry Trade geeignet sind.

    Returns (suitable, reason)
    """
    if not macro_ctx:
        return False, "Keine Makro-Daten"

    risk_regime = macro_ctx.get("risk_regime", "UNCERTAIN")
    vix         = macro_ctx.get("vix", 18.0)

    if risk_regime == "OFF":
        return False, f"Risk-OFF (VIX={vix:.1f}) — Carry Trade nicht sicher"

    if vix > CARRY_VIX_MAX:
        return False, f"VIX {vix:.1f} > {CARRY_VIX_MAX} — zu volatil für Carry"

    if risk_regime == "UNCERTAIN" and vix > 18:
        return False, f"Unsicheres Regime (VIX={vix:.1f}) — Carry zurückstellen"

    return True, f"Carry-Umfeld OK: Risk={risk_regime}, VIX={vix:.1f}"


# ── Signal-Generator ──────────────────────────────────────────────────────────

def get_carry_trade_signals(
    macro_ctx:  dict,
    cot_ctx:    Optional[dict] = None,
    max_trades: int = 2,
) -> list[CarrySignal]:
    """
    Generiert Carry Trade Signale nach Zinsdifferential-Attraktivität.

    Gibt maximal `max_trades` Signale zurück, sortiert nach Carry-Score.

    Parameters
    ----------
    macro_ctx  : Output von get_macro_context()
    cot_ctx    : Output von get_cot_context() (optional, für COT-Filter)
    max_trades : Maximale Anzahl Carry Signals

    Returns
    -------
    list[CarrySignal] oder [] wenn Bedingungen nicht erfüllt
    """
    suitable, reason = is_carry_environment(macro_ctx)
    if not suitable:
        log.debug(f"Carry Trade: {reason}")
        return []

    rates = macro_ctx.get("rates", {})
    if not rates:
        return []

    vix = macro_ctx.get("vix", 18.0)

    # Alle potentiellen Carry-Pairs mit Basis/Quote
    candidates = [
        ("USD_JPY", "USD", "JPY"),
        ("GBP_JPY", "GBP", "JPY"),
        ("AUD_JPY", "AUD", "JPY"),
        ("NZD_JPY", "NZD", "JPY"),
        ("EUR_JPY", "EUR", "JPY"),
        ("USD_CHF", "USD", "CHF"),
        ("AUD_USD", "AUD", "USD"),
        ("NZD_USD", "NZD", "USD"),
        ("GBP_USD", "GBP", "USD"),
    ]

    signals: list[CarrySignal] = []

    for instrument, base, quote in candidates:
        base_rate  = rates.get(base,  2.0)
        quote_rate = rates.get(quote, 2.0)
        diff       = base_rate - quote_rate

        if diff < CARRY_MIN_DIFFERENTIAL:
            continue

        # COT-Filter: EXTREME_LONG bei Basiswährung → bereits überfüllt
        if cot_ctx and cot_ctx.get("source") != "unavailable":
            base_cot = cot_ctx.get(base, {})
            if base_cot.get("sentiment") == "EXTREME_LONG":
                log.debug(f"Carry {instrument}: {base} EXTREME_LONG — übersprungen")
                continue

        # Score: Differential normiert auf 0–1 + VIX-Bonus
        score = min(diff / 6.0, 1.0)         # 6% Differential = maximaler Score
        if vix < CARRY_VIX_IDEAL:
            score = min(score * 1.20, 1.0)   # Ideal-Bedingungen Bonus

        # SL-Multiplikator für Carry: weiter als normal (Kurzfrist-Noise tolerieren)
        atr_mult = CARRY_SL_ATR_MULT

        signals.append(CarrySignal(
            instrument   = instrument,
            direction    = "BUY",
            carry_score  = round(score, 3),
            differential = round(diff, 2),
            atr_mult     = atr_mult,
            reason       = (
                f"CARRY: {base} {base_rate:.2f}% − {quote} {quote_rate:.2f}% "
                f"= +{diff:.2f}%p.a. | VIX={vix:.1f} | Score={score:.2f}"
            ),
        ))

    signals.sort(key=lambda s: s.carry_score, reverse=True)
    selected = signals[:max_trades]

    if selected:
        log.info(
            "Carry Trade Signale: " +
            ", ".join(f"{s.instrument} +{s.differential:.1f}%" for s in selected)
        )

    return selected


# ── Exit-Check ────────────────────────────────────────────────────────────────

def should_exit_carry(trade, macro_ctx: dict) -> tuple[bool, str]:
    """
    Prüft ob ein Carry Trade vorzeitig geschlossen werden soll.

    Carry Trades haben normalerweise weiten SL — dieser Exit-Check
    dient als zusätzliche Regime-basierte Absicherung.

    Returns (should_exit, reason)
    """
    if not macro_ctx:
        return False, ""
    if not getattr(trade, "reason", "").startswith("CARRY"):
        return False, ""   # Kein Carry Trade

    vix         = macro_ctx.get("vix", 18.0)
    risk_regime = macro_ctx.get("risk_regime", "UNCERTAIN")

    if risk_regime == "OFF":
        return True, f"Carry Exit: Risk-OFF (VIX={vix:.1f}) — JPY-Rückfluss"

    if vix > CARRY_VIX_MAX:
        return True, f"Carry Exit: VIX {vix:.1f} > {CARRY_VIX_MAX}"

    return False, ""
