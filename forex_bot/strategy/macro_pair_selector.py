"""
Macro Pair Selector — Risk-On / Risk-Off Pair-Filterung.

Selektiert Forex-Paare basierend auf makroökonomischem Regime:
  - RISK_OFF:  USD/JPY, USD/CHF (Safe-Haven), EUR/USD möglich
  - RISK_ON:   AUD/USD, NZD/USD, GBP/USD, EUR/USD (Risk Currencies)
  - NEUTRAL:   Alle konfigurierten Paare gleichberechtigt

Regime-Erkennung:
  1. Shared-Exposure-Bus (cross-bot VIX-Regime wenn verfügbar)
  2. Macro-Context aus bot.py (vix_level, risk_regime)
  3. Statisches Fallback (alle Paare)

Integration in bot.py:
    from forex_bot.strategy.macro_pair_selector import filter_pairs_by_macro
    active_pairs = filter_pairs_by_macro(instruments, macro_ctx)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("forex_bot")

# Pair-Klassifikation nach Makro-Regime
RISK_OFF_PAIRS = {"USD_JPY", "USD_CHF", "EUR_CHF", "EUR_USD"}
RISK_ON_PAIRS  = {"AUD_USD", "NZD_USD", "GBP_USD", "EUR_USD", "GBP_JPY", "AUD_JPY"}
NEUTRAL_PAIRS  = set()   # Leer = alle Paare sind neutral-gültig

# VIX-Schwellenwerte für Regime-Bestimmung
VIX_RISK_OFF_THRESHOLD = 25.0   # VIX > 25 → RISK_OFF
VIX_RISK_ON_THRESHOLD  = 18.0   # VIX < 18 → RISK_ON


@dataclass
class MacroPairSelection:
    active_pairs:   list[str]
    regime:         str      # "RISK_OFF" | "RISK_ON" | "NEUTRAL"
    excluded_pairs: list[str]
    reason:         str


def _detect_regime_from_macro(macro_ctx: dict[str, Any]) -> str:
    """
    Bestimmt Regime aus Macro-Context.

    Erkennt: risk_regime (direkt), vix_level (numerisch),
             regime_label aus shared_exposure
    """
    if not macro_ctx:
        return "NEUTRAL"

    # Direktes risk_regime-Flag (von shared_exposure oder bot.py)
    risk_regime = str(macro_ctx.get("risk_regime", "")).upper()
    if risk_regime in ("RISK_OFF", "EXTREME_FEAR"):
        return "RISK_OFF"
    if risk_regime in ("RISK_ON", "GREED"):
        return "RISK_ON"

    # VIX-Level
    vix = macro_ctx.get("vix_level")
    if vix is not None:
        try:
            vix_f = float(vix)
            if vix_f >= VIX_RISK_OFF_THRESHOLD:
                return "RISK_OFF"
            if vix_f <= VIX_RISK_ON_THRESHOLD:
                return "RISK_ON"
        except (TypeError, ValueError):
            pass

    # Regime aus Shared-Exposure-Bus
    shared_regime = str(macro_ctx.get("shared_regime", "")).upper()
    if "BEAR" in shared_regime or "VOLATIL" in shared_regime:
        return "RISK_OFF"
    if "BULL" in shared_regime or "TREND_UP" in shared_regime:
        return "RISK_ON"

    return "NEUTRAL"


def filter_pairs_by_macro(
    instruments: list[str],
    macro_ctx:   dict[str, Any] | None = None,
) -> MacroPairSelection:
    """
    Filtert Instruments nach Makro-Regime.

    Parameters
    ----------
    instruments: Alle konfigurierten Instrumente
    macro_ctx:   Macro-Context (vix_level, risk_regime, etc.)

    Returns
    -------
    MacroPairSelection mit gefilterten aktiven Paaren
    """
    if not instruments:
        return MacroPairSelection(
            active_pairs=[], regime="NEUTRAL",
            excluded_pairs=[], reason="Keine Instrumente konfiguriert",
        )

    ctx     = macro_ctx or {}
    regime  = _detect_regime_from_macro(ctx)
    instr_set = set(instruments)

    if regime == "RISK_OFF":
        # Nur Safe-Haven-Paare
        valid = RISK_OFF_PAIRS & instr_set
        if not valid:
            # Kein konfiguriertes Safe-Haven-Pair → alle behalten, aber warnen
            log.warning(
                "RISK_OFF Regime erkannt aber keine Safe-Haven-Paare konfiguriert "
                f"(RISK_OFF_PAIRS={RISK_OFF_PAIRS & instr_set}) — alle Paare aktiv"
            )
            return MacroPairSelection(
                active_pairs=instruments,
                regime=regime,
                excluded_pairs=[],
                reason="RISK_OFF: Kein Safe-Haven konfiguriert — alle aktiv",
            )
        excluded = sorted(instr_set - valid)
        active   = sorted(valid)
        log.info(f"Macro Pair Selector: RISK_OFF → aktiv={active} | ausgeschlossen={excluded}")
        return MacroPairSelection(
            active_pairs=active, regime=regime,
            excluded_pairs=excluded,
            reason=f"VIX/Risk-Off Regime — nur Safe-Haven: {active}",
        )

    if regime == "RISK_ON":
        # Risk-Currency-Paare bevorzugen
        valid = RISK_ON_PAIRS & instr_set
        if not valid:
            log.debug("RISK_ON Regime aber keine Risk-On-Paare konfiguriert — alle aktiv")
            return MacroPairSelection(
                active_pairs=instruments, regime=regime,
                excluded_pairs=[],
                reason="RISK_ON: Kein Risk-On-Pair konfiguriert — alle aktiv",
            )
        excluded = sorted(instr_set - valid)
        active   = sorted(valid)
        log.info(f"Macro Pair Selector: RISK_ON → aktiv={active} | ausgeschlossen={excluded}")
        return MacroPairSelection(
            active_pairs=active, regime=regime,
            excluded_pairs=excluded,
            reason=f"Risk-On Regime — Risk Currencies: {active}",
        )

    # NEUTRAL — alle Paare aktiv
    return MacroPairSelection(
        active_pairs=sorted(instruments),
        regime="NEUTRAL",
        excluded_pairs=[],
        reason="Neutrales Makro-Umfeld — alle Paare aktiv",
    )
