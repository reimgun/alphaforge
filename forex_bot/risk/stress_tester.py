"""
Forex Stress Tester — Liquidity & Flash Crash Szenarien.

Simuliert historische und hypothetische Stressszenarien:

  Szenarien:
    1. SPREAD_5X:     Spread auf 5× Normal-Spread ausgeweitet (Liquidity Crisis)
    2. FLASH_CRASH:   Kurs fällt -3% innerhalb von 3 Candles
    3. GAP_UP/DOWN:   Wochenend-Gap von ±2%
    4. TRENDING_DD:   Trendfolge-Drawdown 10 Candles gegen Position
    5. BLACK_THURSDAY:Flash Crash + Spread-Ausweitung kombiniert

Bewertet ob Strategie unter Stress profitabel / überlebensfähig bleibt:
  - Max Loss pro Szenario
  - Survival Rate (% Szenarien wo Capital > 80% erhalten)
  - Empfehlung: SAFE / MODERATE_RISK / HIGH_RISK / CRITICAL

Usage:
    from forex_bot.risk.stress_tester import run_stress_test
    result = run_stress_test(pnls, spread_pips, initial_capital)
    print(result.recommendation)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("forex_bot")

# Szenario-Konfiguration
SPREAD_MULTIPLIER  = 5.0    # 5× normaler Spread bei Liquidity Crisis
FLASH_CRASH_PCT    = 0.03   # 3% Flash Crash
GAP_PCT            = 0.02   # 2% Wochenend-Gap
TRENDING_DD_N      = 10     # 10 aufeinanderfolgende Verlust-Trades
DD_SURVIVAL_FLOOR  = 0.80   # Capital > 80% nach Stress = Survival


@dataclass
class ScenarioResult:
    name:          str
    max_loss_pct:  float    # Max. Kapitalverlust in %
    final_capital: float    # Restkapital nach Szenario
    survived:      bool     # Capital > DD_SURVIVAL_FLOOR


@dataclass
class StressTestResult:
    scenarios:       list[ScenarioResult]
    survival_rate:   float    # % überlebte Szenarien
    max_drawdown:    float    # Schlechtestes Szenario
    recommendation:  str      # "SAFE" | "MODERATE_RISK" | "HIGH_RISK" | "CRITICAL"
    summary:         str


def _run_spread_crisis(
    pnls:            list[float],
    spread_pips:     float,
    pip_value:       float,
    initial_capital: float,
) -> ScenarioResult:
    """5× Spread auf alle Trades anwenden."""
    extra_cost = spread_pips * (SPREAD_MULTIPLIER - 1.0) * pip_value
    stressed   = [p - extra_cost for p in pnls]
    total_loss = sum(stressed)
    final      = initial_capital + total_loss
    loss_pct   = abs(min(0.0, total_loss)) / initial_capital
    return ScenarioResult(
        name="SPREAD_5X",
        max_loss_pct=round(loss_pct, 4),
        final_capital=round(final, 2),
        survived=final >= initial_capital * DD_SURVIVAL_FLOOR,
    )


def _run_flash_crash(
    pnls:            list[float],
    initial_capital: float,
    direction:       int = -1,   # -1 = crash down, +1 = spike up
) -> ScenarioResult:
    """3% Flash Crash der zu N Trade-Verlusten führt."""
    crash_loss = initial_capital * FLASH_CRASH_PCT * direction
    stressed   = pnls + [crash_loss]   # Füge Crash als extra Trade hinzu
    total_loss = sum(stressed)
    final      = initial_capital + total_loss
    loss_pct   = abs(min(0.0, total_loss)) / initial_capital
    return ScenarioResult(
        name="FLASH_CRASH",
        max_loss_pct=round(loss_pct, 4),
        final_capital=round(final, 2),
        survived=final >= initial_capital * DD_SURVIVAL_FLOOR,
    )


def _run_gap(
    pnls:            list[float],
    initial_capital: float,
    direction:       int = -1,
) -> ScenarioResult:
    """Wochenend-Gap (±2%) wirkt sich als einmaliger PnL-Hit aus."""
    gap_loss = initial_capital * GAP_PCT * direction
    stressed = pnls + [gap_loss]
    total    = sum(stressed)
    final    = initial_capital + total
    loss_pct = abs(min(0.0, total)) / initial_capital
    return ScenarioResult(
        name="GAP_DOWN" if direction < 0 else "GAP_UP",
        max_loss_pct=round(loss_pct, 4),
        final_capital=round(final, 2),
        survived=final >= initial_capital * DD_SURVIVAL_FLOOR,
    )


def _run_trending_dd(
    pnls:            list[float],
    initial_capital: float,
) -> ScenarioResult:
    """Schlimmste N aufeinanderfolgende Verluste wiederholen sich."""
    losses = sorted([p for p in pnls if p < 0])[:TRENDING_DD_N]
    if not losses:
        return ScenarioResult(
            name="TRENDING_DD", max_loss_pct=0.0,
            final_capital=initial_capital, survived=True,
        )
    worst_streak = sum(losses)
    final    = initial_capital + worst_streak
    loss_pct = abs(worst_streak) / initial_capital
    return ScenarioResult(
        name="TRENDING_DD",
        max_loss_pct=round(loss_pct, 4),
        final_capital=round(final, 2),
        survived=final >= initial_capital * DD_SURVIVAL_FLOOR,
    )


def _run_black_thursday(
    pnls:            list[float],
    spread_pips:     float,
    pip_value:       float,
    initial_capital: float,
) -> ScenarioResult:
    """Flash Crash + Spread 5× kombiniert."""
    extra_cost = spread_pips * (SPREAD_MULTIPLIER - 1.0) * pip_value
    crash_loss = initial_capital * FLASH_CRASH_PCT
    stressed   = [p - extra_cost for p in pnls] + [-crash_loss]
    total      = sum(stressed)
    final      = initial_capital + total
    loss_pct   = abs(min(0.0, total)) / initial_capital
    return ScenarioResult(
        name="BLACK_THURSDAY",
        max_loss_pct=round(loss_pct, 4),
        final_capital=round(final, 2),
        survived=final >= initial_capital * DD_SURVIVAL_FLOOR,
    )


def run_stress_test(
    pnls:            list[float],
    spread_pips:     float  = 1.5,
    pip_value:       float  = 10.0,
    initial_capital: float  = 10000.0,
) -> StressTestResult:
    """
    Führt alle Stress-Szenarien durch.

    Parameters
    ----------
    pnls:            Liste historischer Trade-PnL (USD)
    spread_pips:     Normaler Spread in Pips
    pip_value:       Wert eines Pips in USD
    initial_capital: Startkapital

    Returns
    -------
    StressTestResult mit Bewertung
    """
    if len(pnls) < 5:
        return StressTestResult(
            scenarios=[],
            survival_rate=1.0,
            max_drawdown=0.0,
            recommendation="SAFE",
            summary="Zu wenig Trades für Stress-Test",
        )

    scenarios = [
        _run_spread_crisis(pnls, spread_pips, pip_value, initial_capital),
        _run_flash_crash(pnls, initial_capital),
        _run_gap(pnls, initial_capital),
        _run_trending_dd(pnls, initial_capital),
        _run_black_thursday(pnls, spread_pips, pip_value, initial_capital),
    ]

    survived_n    = sum(1 for s in scenarios if s.survived)
    survival_rate = survived_n / len(scenarios)
    max_dd        = max(s.max_loss_pct for s in scenarios)

    if max_dd >= 0.50 or survival_rate < 0.40:
        recommendation = "CRITICAL"
    elif max_dd >= 0.25 or survival_rate < 0.60:
        recommendation = "HIGH_RISK"
    elif max_dd >= 0.15 or survival_rate < 0.80:
        recommendation = "MODERATE_RISK"
    else:
        recommendation = "SAFE"

    worst = max(scenarios, key=lambda s: s.max_loss_pct)
    summary = (
        f"Stress Test: {survived_n}/{len(scenarios)} Szenarien überlebt | "
        f"Max DD {max_dd:.1%} ({worst.name}) | {recommendation}"
    )
    log.info(summary)

    return StressTestResult(
        scenarios=scenarios,
        survival_rate=round(survival_rate, 3),
        max_drawdown=round(max_dd, 4),
        recommendation=recommendation,
        summary=summary,
    )
