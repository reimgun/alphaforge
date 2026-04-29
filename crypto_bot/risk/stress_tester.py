"""
Liquidity Stress Test Engine — Adverse Execution Scenarios.

  FlashCrashScenario:           Simulation plötzlicher Preiseinbrüche
  SpreadExpansionScenario:      Simulation extremer Spread-Ausweitungen
  CascadingLiquidationScenario: Kaskaden-Effekte durch Liquidations-Cluster
  LiquidityStressTestEngine:    Wrapper — gibt stress_factor für Risk Engine zurück

Feature-Flag: FEATURE_STRESS_TESTER=true|false
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")


# ── Flash Crash Scenario ──────────────────────────────────────────────────────

@dataclass
class FlashCrashResult:
    drop_pct:          float   # Schwerster Drawdown der simuliert wird
    pnl_impact_usd:    float   # USD-Auswirkung auf aktuelle Position
    slippage_at_crash: float   # Zusätzliches Slippage bei Crash (%)
    stop_would_hold:   bool    # Würde der Stop-Loss die Position schützen?
    worst_case_loss:   float   # Worst-Case Verlust in USD (mit Slippage)
    reason:            str


class FlashCrashScenario:
    """
    Simuliert plötzliche Preiseinbrüche und deren Auswirkung auf Position.
    Berücksichtigt: Gap-Down (Stop-Loss kann nicht mehr exakt ausgeführt werden).

    Slippage-Annahme: Bei -10% Crash → +0.5% zusätzliches Slippage.
    """
    DROP_SCENARIOS       = [-0.05, -0.10, -0.15, -0.20, -0.30]
    BASE_SLIPPAGE_FACTOR = 0.05   # 5% des Drops als zusätzliches Slippage

    def simulate(
        self,
        current_price:  float,
        position_usd:   float,
        stop_loss_price: float,
        entry_price:    float = 0.0,
    ) -> FlashCrashResult:
        try:
            if current_price <= 0:
                return FlashCrashResult(0, 0, 0, True, 0, "Ungültiger Preis")

            worst_drop = 0.0
            worst_pnl  = 0.0
            worst_loss = 0.0
            slippage   = 0.0
            stop_holds = True

            for drop in self.DROP_SCENARIOS:
                crashed_price = current_price * (1 + drop)
                slippage_pct  = abs(drop) * self.BASE_SLIPPAGE_FACTOR
                exec_price    = crashed_price * (1 - slippage_pct)  # Schlechtere Ausführung

                pnl = (exec_price - current_price) / current_price * position_usd
                loss = min(0.0, pnl)

                # Stop hält wenn Crash-Preis über Stop-Loss liegt
                if crashed_price < stop_loss_price:
                    stop_holds = False
                    # Tatsächliche Ausführung bei Stop: exec_price (Gap-Down)
                    worst_drop = drop
                    worst_pnl  = pnl
                    worst_loss = loss
                    slippage   = slippage_pct
                    break   # Schlimmstes Szenario gefunden

            if stop_holds:
                # Kein Szenario triggert Stop → kleinsten Einbruch nehmen
                drop       = self.DROP_SCENARIOS[0]
                crashed    = current_price * (1 + drop)
                slip_pct   = abs(drop) * self.BASE_SLIPPAGE_FACTOR
                exec_p     = crashed * (1 - slip_pct)
                worst_drop = drop
                worst_pnl  = (exec_p - current_price) / current_price * position_usd
                worst_loss = min(0.0, worst_pnl)
                slippage   = slip_pct

            reason = (
                f"Flash Crash {worst_drop:.0%}: PnL {worst_pnl:+.0f}$ | "
                f"Slippage {slippage:.2%} | "
                f"Stop {'hält' if stop_holds else 'gap-down, kein Schutz'}"
            )
            return FlashCrashResult(
                drop_pct          = round(worst_drop, 3),
                pnl_impact_usd    = round(worst_pnl, 2),
                slippage_at_crash = round(slippage, 4),
                stop_would_hold   = stop_holds,
                worst_case_loss   = round(worst_loss, 2),
                reason            = reason,
            )
        except Exception as e:
            log.debug(f"FlashCrashScenario Fehler: {e}")
            return FlashCrashResult(-0.10, 0.0, 0.005, True, 0.0, f"Fehler: {e}")


# ── Spread Expansion Scenario ─────────────────────────────────────────────────

@dataclass
class SpreadExpansionResult:
    normal_spread_bps:    float
    expanded_spread_bps:  float
    expansion_factor:     float
    effective_cost_usd:   float   # Kosten auf die aktuelle Positionsgröße
    is_executable:        bool    # False wenn Spread > MAX_SPREAD_BPS
    reason:               str


class SpreadExpansionScenario:
    """
    Simuliert extreme Spread-Ausweitungen (z.B. bei Flash Crashes, Low-Liquidity Stunden).
    Prüft ob Execution noch wirtschaftlich sinnvoll ist.
    """
    EXPANSION_SCENARIOS = [3, 5, 10, 20]   # Multiplikatoren
    MAX_EXECUTABLE_BPS  = 50.0             # > 50 bps Spread = nicht mehr sinnvoll

    def simulate(
        self,
        normal_spread_bps: float,
        position_usd: float,
    ) -> SpreadExpansionResult:
        try:
            # Schlimmstes Szenario
            worst_factor   = self.EXPANSION_SCENARIOS[-1]
            expanded_bps   = normal_spread_bps * worst_factor
            cost_usd       = position_usd * (expanded_bps / 10_000)
            is_executable  = expanded_bps <= self.MAX_EXECUTABLE_BPS

            reason = (
                f"Spread {normal_spread_bps:.1f}bps → {expanded_bps:.0f}bps "
                f"({worst_factor}×) | Kosten {cost_usd:.2f}$ | "
                f"{'ausführbar' if is_executable else 'NICHT ausführbar'}"
            )
            return SpreadExpansionResult(
                normal_spread_bps  = round(normal_spread_bps, 2),
                expanded_spread_bps= round(expanded_bps, 1),
                expansion_factor   = float(worst_factor),
                effective_cost_usd = round(cost_usd, 2),
                is_executable      = is_executable,
                reason             = reason,
            )
        except Exception as e:
            log.debug(f"SpreadExpansionScenario Fehler: {e}")
            return SpreadExpansionResult(2.0, 20.0, 10.0, 0.0, True, f"Fehler: {e}")


# ── Cascading Liquidation Scenario ────────────────────────────────────────────

@dataclass
class CascadingLiquidationResult:
    n_clusters_nearby:      int
    estimated_cascade_drop: float   # Geschätzter Preis-Rückgang durch Kaskade (%)
    contagion_factor:       float   # 0.0–1.0 (Stärke des Ansteckungs-Effekts)
    price_impact_usd:       float
    reason:                 str


class CascadingLiquidationScenario:
    """
    Modelliert Kaskaden-Effekte wenn Liquidations-Cluster in der Nähe sind.

    Annahme: Jeder Cluster in < 5% Reichweite erhöht den geschätzten Drawdown.
    Kaskade = Preis fällt zum ersten Cluster → löst weiteren aus → etc.
    """
    PROXIMITY_PCT    = 0.05    # Cluster innerhalb 5% = gefährdet
    PER_CLUSTER_DROP = 0.008   # Jeder Cluster = ~0.8% zusätzlicher Drop
    CASCADE_MULTIPLIER = 1.3   # Kaskade verstärkt sich

    def simulate(
        self,
        clusters: list,   # list[LiquidationCluster] aus derivatives.py
        current_price: float,
        position_usd: float,
    ) -> CascadingLiquidationResult:
        try:
            nearby = [
                c for c in clusters
                if c.distance_pct / 100 < self.PROXIMITY_PCT
            ]

            if not nearby:
                return CascadingLiquidationResult(
                    0, 0.0, 0.0, 0.0, "Keine Liquidations-Cluster in der Nähe"
                )

            n = len(nearby)
            # Kaskade: erster Cluster löst Rückgang aus → mehr Cluster werden erreicht
            cascade_drop = 0.0
            for i in range(n):
                cascade_drop += self.PER_CLUSTER_DROP * (self.CASCADE_MULTIPLIER ** i)

            cascade_drop = min(0.20, cascade_drop)   # Max. 20%
            contagion    = min(1.0, n / 5.0)         # 5 Cluster = voller Ansteckungs-Effekt
            price_impact = position_usd * cascade_drop * -1

            reason = (
                f"{n} Cluster in <{self.PROXIMITY_PCT:.0%} Reichweite | "
                f"Geschätzter Kaskaden-Drop: {cascade_drop:.1%} | "
                f"Impact: {price_impact:+.0f}$"
            )
            return CascadingLiquidationResult(
                n_clusters_nearby      = n,
                estimated_cascade_drop = round(cascade_drop, 4),
                contagion_factor       = round(contagion, 3),
                price_impact_usd       = round(price_impact, 2),
                reason                 = reason,
            )
        except Exception as e:
            log.debug(f"CascadingLiquidationScenario Fehler: {e}")
            return CascadingLiquidationResult(0, 0.0, 0.0, 0.0, f"Fehler: {e}")


# ── Stress Test Result ─────────────────────────────────────────────────────────

@dataclass
class StressTestResult:
    flash_crash:   FlashCrashResult
    spread_exp:    SpreadExpansionResult
    cascade:       CascadingLiquidationResult
    stress_factor: float   # 0.25–1.0 Multiplikator für Risk Engine
    severity:      str     # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    reason:        str


# ── Liquidity Stress Test Engine (Wrapper) ────────────────────────────────────

class LiquidityStressTestEngine:
    """
    Wrapper — führt alle Stress-Szenarien aus und gibt stress_factor zurück.
    Dieser Faktor wird in der Risk Engine als zusätzlicher Größen-Multiplikator verwendet.
    """

    def __init__(self):
        self.flash_crash = FlashCrashScenario()
        self.spread_exp  = SpreadExpansionScenario()
        self.cascade     = CascadingLiquidationScenario()

    def run(
        self,
        df:               pd.DataFrame,
        current_price:    float,
        position_usd:     float     = 1000.0,
        stop_loss_price:  float     = 0.0,
        entry_price:      float     = 0.0,
        normal_spread_bps: float    = 2.0,
        liq_clusters:     list      | None = None,
    ) -> StressTestResult:
        try:
            if stop_loss_price <= 0:
                # Fallback: 5% unter aktuellem Preis
                stop_loss_price = current_price * 0.95

            fc_r  = self.flash_crash.simulate(
                current_price, position_usd, stop_loss_price, entry_price
            )
            sp_r  = self.spread_exp.simulate(normal_spread_bps, position_usd)
            cas_r = self.cascade.simulate(
                liq_clusters or [], current_price, position_usd
            )

            # stress_factor zusammensetzen
            # Jedes aktive Risiko reduziert den Faktor
            factor = 1.0

            if not fc_r.stop_would_hold:
                factor *= 0.70   # Flash Crash ohne Stop-Schutz
            elif abs(fc_r.drop_pct) > 0.15:
                factor *= 0.85

            if not sp_r.is_executable:
                factor *= 0.60   # Spread zu weit
            elif sp_r.expansion_factor >= 10:
                factor *= 0.80

            if cas_r.contagion_factor > 0.6:
                factor *= 0.65
            elif cas_r.contagion_factor > 0.3:
                factor *= 0.80

            factor = max(0.25, min(1.0, factor))

            # Severity
            if factor < 0.5:
                severity = "CRITICAL"
            elif factor < 0.65:
                severity = "HIGH"
            elif factor < 0.85:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            reason = (
                f"Stress-Faktor {factor:.0%} ({severity}) | "
                f"Flash Crash {fc_r.drop_pct:.0%} | "
                f"Spread {sp_r.expansion_factor}× | "
                f"Kaskade {cas_r.n_clusters_nearby} Cluster"
            )
            return StressTestResult(
                flash_crash   = fc_r,
                spread_exp    = sp_r,
                cascade       = cas_r,
                stress_factor = round(factor, 3),
                severity      = severity,
                reason        = reason,
            )
        except Exception as e:
            log.debug(f"LiquidityStressTestEngine Fehler: {e}")
            return StressTestResult(
                flash_crash   = FlashCrashResult(-0.10, 0, 0.005, True, 0, ""),
                spread_exp    = SpreadExpansionResult(2.0, 20.0, 10.0, 0.0, True, ""),
                cascade       = CascadingLiquidationResult(0, 0.0, 0.0, 0.0, ""),
                stress_factor = 0.75,
                severity      = "MEDIUM",
                reason        = f"Fehler: {e}",
            )


_stress_engine: LiquidityStressTestEngine | None = None


def get_stress_tester() -> LiquidityStressTestEngine:
    global _stress_engine
    if _stress_engine is None:
        _stress_engine = LiquidityStressTestEngine()
    return _stress_engine
