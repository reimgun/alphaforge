"""
Volatility-based Risk Mode Auto-Switching — Feature 2.

Analyses current market conditions each cycle and suggests the most
appropriate risk mode.  Can automatically switch modes if no manual
override is active.

Logic:
  → conservative  : VIX > 25  OR  ATR% > 0.12%  OR  ≥ 3 High-Impact events in 4h
  → aggressive    : VIX < 15  AND ATR% < 0.06%  AND 0 High-Impact events in 8h
  → balanced      : everything else

Integration with bot.py:
    from forex_bot.risk.auto_mode import auto_switch_mode, mark_manual_override

    # When user manually sets mode (Telegram / API):
    mark_manual_override()

    # Each cycle, after computing ATR:
    auto_switch_mode(atr_pct, vix, high_impact_count, current_mode.name, set_current_mode)
"""
import logging

log = logging.getLogger("forex_bot")

_last_auto_mode:    str  = ""
_manual_override:   bool = False


def mark_manual_override():
    """Disable auto-switching after a manual /set_mode command."""
    global _manual_override
    _manual_override = True
    log.info("Auto-mode switching disabled — manual override active")


def clear_manual_override():
    """Re-enable auto-switching (e.g. at midnight reset)."""
    global _manual_override
    _manual_override = False


def suggest_auto_mode(
    atr_pct:           float,
    vix:               float,
    high_impact_count: int,
    current_mode:      str = "balanced",
) -> tuple[str, str]:
    """
    Suggest the most appropriate risk mode for current conditions.

    Parameters
    ----------
    atr_pct:           ATR expressed as fraction of close price (e.g. 0.08 = 0.08%)
    vix:               current VIX level
    high_impact_count: number of High-Impact events scheduled in the next 4 hours
    current_mode:      current active mode name

    Returns
    -------
    (mode_name: str, reason: str)
    """
    reasons: list[str] = []

    # ── High-volatility → conservative ───────────────────────────────────────
    high_vol = False
    if vix > 25:
        reasons.append(f"VIX={vix:.1f} (>25)")
        high_vol = True
    if atr_pct > 0.12:
        reasons.append(f"ATR%={atr_pct:.3f} (>0.12%)")
        high_vol = True
    if high_impact_count >= 3:
        reasons.append(f"{high_impact_count} High-Impact events in next 4h")
        high_vol = True

    if high_vol:
        return "conservative", "High volatility detected: " + ", ".join(reasons)

    # ── Low-volatility → aggressive ───────────────────────────────────────────
    if vix < 15 and atr_pct < 0.06 and high_impact_count == 0:
        if current_mode in ("balanced", "aggressive"):
            return "aggressive", (
                f"Low volatility: VIX={vix:.1f}, "
                f"ATR%={atr_pct:.4f}, no events"
            )

    # ── Elevated but not extreme → balanced ───────────────────────────────────
    return "balanced", f"Normal conditions: VIX={vix:.1f}, ATR%={atr_pct:.3f}"


def auto_switch_mode(
    atr_pct:           float,
    vix:               float,
    high_impact_count: int,
    current_mode:      str,
    set_mode_fn,
) -> tuple[str, bool]:
    """
    Evaluate market conditions and switch risk mode if warranted.

    Parameters
    ----------
    atr_pct:           ATR as % of close price
    vix:               current VIX
    high_impact_count: High-Impact events in next 4h
    current_mode:      current mode name
    set_mode_fn:       callable(name: str) → RiskMode — e.g. bot.set_current_mode

    Returns
    -------
    (active_mode_name: str, was_switched: bool)
    """
    global _last_auto_mode

    if _manual_override:
        return current_mode, False

    suggested, reason = suggest_auto_mode(atr_pct, vix, high_impact_count, current_mode)

    if suggested == current_mode:
        _last_auto_mode = suggested
        return current_mode, False

    _last_auto_mode = suggested
    set_mode_fn(suggested)
    log.info(f"Auto-mode: {current_mode} → {suggested} | {reason}")
    return suggested, True
