"""
Pluggable Hyperopt-Loss-Funktionen.

Auswahl via Umgebungsvariable:
    HYPEROPT_LOSS=sharpe          # Standard: Risk/Return balanciert
    HYPEROPT_LOSS=sortino         # Nur Downside-Risiko bestrafen
    HYPEROPT_LOSS=calmar          # Rendite / Max Drawdown (defensiv)
    HYPEROPT_LOSS=profit_drawdown # Profit × (1 - Drawdown)
    HYPEROPT_LOSS=only_profit     # Nur Rendite (Vorsicht: Drawdown ignoriert)
    HYPEROPT_LOSS=multi_metric    # Sharpe + WinRate + ProfitFactor (empfohlen)

Verwendung:
    from crypto_bot.optimization.loss_functions import get_loss_function
    loss_fn = get_loss_function("calmar")
    score   = loss_fn(backtest_result)   # → float, höher = besser
"""
from __future__ import annotations

import logging

log = logging.getLogger("trading_bot")


def sharpe(result: dict) -> float:
    """Sharpe Ratio. Inakzeptabel wenn Drawdown > 30%."""
    if result.get("max_drawdown_pct", 100) > 30 or result.get("trades", 0) < 3:
        return 0.0
    return max(0.0, float(result.get("sharpe_ratio", 0.0)))


def sortino(result: dict) -> float:
    """Sortino Ratio — bestraft nur negative Renditen."""
    if result.get("max_drawdown_pct", 100) > 30 or result.get("trades", 0) < 3:
        return 0.0
    return max(0.0, float(result.get("sortino_ratio", 0.0)))


def calmar(result: dict) -> float:
    """Calmar Ratio — annualisierte Rendite / Max Drawdown."""
    if result.get("trades", 0) < 3:
        return 0.0
    return max(0.0, float(result.get("calmar_ratio", 0.0)))


def profit_drawdown(result: dict) -> float:
    """Profit × (1 - Drawdown/100) — balanciert Gewinn und Risiko."""
    ret = float(result.get("return_pct",      0.0))
    dd  = float(result.get("max_drawdown_pct", 100.0))
    if ret <= 0 or dd >= 50 or result.get("trades", 0) < 3:
        return 0.0
    return ret * (1.0 - dd / 100.0)


def only_profit(result: dict) -> float:
    """Nur Gesamt-Rendite. Drawdown wird ignoriert — nur für Experimente."""
    if result.get("trades", 0) < 3:
        return 0.0
    return max(0.0, float(result.get("return_pct", 0.0)))


def multi_metric(result: dict) -> float:
    """
    Multi-Metric Score: Sharpe + Win-Rate-Bonus + Profit-Faktor-Bonus.
    Drawdown-Strafe ab 10%, Abbruch ab 25%.
    Empfohlene Standard-Metrik.
    """
    if result.get("max_drawdown_pct", 100) >= 25 or result.get("trades", 0) < 3:
        return 0.0

    sharpe_v   = float(result.get("sharpe_ratio",   0.0))
    max_dd     = float(result.get("max_drawdown_pct", 0.0))
    win_rate   = float(result.get("win_rate",        0.0))
    pf         = float(result.get("profit_factor",   0.0))

    dd_penalty = max(0.0, (max_dd - 10.0) / 15.0)           # 10–25% → 0.0–1.0
    wr_bonus   = max(0.0, (win_rate - 50.0) / 100.0)        # +0.0–0.5
    pf_bonus   = min(0.5, max(0.0, (pf - 1.0) * 0.2))      # +0.0–0.5

    return max(0.0, sharpe_v * (1.0 - dd_penalty) + wr_bonus + pf_bonus)


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, callable] = {
    "sharpe":          sharpe,
    "sortino":         sortino,
    "calmar":          calmar,
    "profit_drawdown": profit_drawdown,
    "only_profit":     only_profit,
    "multi_metric":    multi_metric,
}


def get_loss_function(name: str):
    """Loss-Funktion nach Name zurückgeben. Fallback: multi_metric."""
    fn = _REGISTRY.get(name.lower())
    if fn is None:
        log.warning(f"Unbekannte Loss-Funktion '{name}' — verwende 'multi_metric'")
        return multi_metric
    return fn


def list_loss_functions() -> list[dict]:
    """Alle verfügbaren Loss-Funktionen für Dashboard/API."""
    _desc = {
        "sharpe":          "Sharpe Ratio — Risk/Return balanciert (Standard)",
        "sortino":         "Sortino Ratio — nur Downside-Risiko bestraft",
        "calmar":          "Calmar Ratio — Rendite / Max Drawdown (defensiv)",
        "profit_drawdown": "Profit × (1 − Drawdown) — balanciert",
        "only_profit":     "Nur Rendite — Drawdown ignoriert (Vorsicht!)",
        "multi_metric":    "Multi-Metric — Sharpe + WinRate + ProfitFactor (empfohlen)",
    }
    return [{"name": k, "description": _desc.get(k, "")} for k in _REGISTRY]
