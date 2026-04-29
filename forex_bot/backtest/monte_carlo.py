"""
Monte-Carlo Backtester — Robustheitsprüfung via Bootstrap-Simulation.

Generiert 1000 Permutationen der historischen Trade-Returns und berechnet:
  - Sharpe-Ratio-Verteilung (5th / 50th / 95th Perzentil)
  - Max-Drawdown-Verteilung
  - Final-Equity-Verteilung
  - Robustheitsscore: Anteil Simulationen die Mindestkriterien erfüllen

Unterschied zum deterministischen Walk-Forward:
  - Walk-Forward = eine zeitlich-geordnete Aufteilung
  - Monte Carlo = 1000 zufällige Permutationen der Trade-Reihenfolge
  → Testet ob Ergebnis von der Reihenfolge der Trades abhängt

Usage:
    from forex_bot.backtest.monte_carlo import run_monte_carlo
    result = run_monte_carlo(trade_returns=[-50, 120, -30, 80, ...])
    print(f"Sharpe P50: {result.sharpe_p50:.2f}")
    print(f"Robustheit: {result.robustness_score:.0%}")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("forex_bot")

# Mindestkriterien für Robustheitsscore
MIN_SHARPE_TARGET = 0.5
MAX_DD_TARGET     = 0.15   # 15% Max-Drawdown


@dataclass
class MonteCarloResult:
    n_simulations:    int
    n_trades:         int

    # Sharpe
    sharpe_p05:       float
    sharpe_p50:       float
    sharpe_p95:       float

    # Max Drawdown
    maxdd_p05:        float   # Beste 5% Szenarien (geringstes DD)
    maxdd_p50:        float
    maxdd_p95:        float   # Schlechteste 5% (höchstes DD)

    # Final Equity (normalisiert auf 1.0 = Startkapital)
    equity_p05:       float
    equity_p50:       float
    equity_p95:       float

    # Robustheit
    robustness_score: float   # Anteil Sims die Mindestkriterien erfüllen (0.0–1.0)
    prob_ruin:        float   # Wahrscheinlichkeit >50% Kapitalverlust

    ready:            bool    # True wenn robustness_score >= 0.60
    summary:          str


def _compute_equity_curve(returns_pct: np.ndarray) -> np.ndarray:
    """Berechnet Equity-Kurve aus prozentualen Returns."""
    equity = np.ones(len(returns_pct) + 1)
    for i, r in enumerate(returns_pct):
        equity[i + 1] = equity[i] * (1 + r)
    return equity


def _compute_max_drawdown(equity: np.ndarray) -> float:
    """Maximaler Drawdown aus Equity-Kurve."""
    peak = np.maximum.accumulate(equity)
    dd   = (peak - equity) / (peak + 1e-10)
    return float(np.max(dd))


def _compute_sharpe(returns_pct: np.ndarray) -> float:
    """Annualisierter Sharpe Ratio (252 Trading-Tage)."""
    if len(returns_pct) < 2 or np.std(returns_pct) < 1e-10:
        return 0.0
    return float(np.mean(returns_pct) / np.std(returns_pct) * np.sqrt(252))


def run_monte_carlo(
    trade_returns:   list[float],   # PnL in USD oder Pips pro Trade
    n_simulations:   int   = 1000,
    as_pct:          bool  = False, # True = returns sind bereits in % (z.B. 0.02 = 2%)
    initial_capital: float = 10000.0,
    seed:            int   = 42,
) -> MonteCarloResult:
    """
    Führt Monte-Carlo-Simulation der Handelshistorie durch.

    Parameters
    ----------
    trade_returns:   Liste der Trade-PnL-Werte (USD oder %)
    n_simulations:   Anzahl Bootstrap-Permutationen (default: 1000)
    as_pct:          True wenn Returns als Dezimalbrüche angegeben (0.02 = 2%)
    initial_capital: Startkapital für Equity-Berechnung
    seed:            Reproduzierbarer Seed

    Returns
    -------
    MonteCarloResult mit Verteilungsstatistiken und Robustheitsscore
    """
    if len(trade_returns) < 10:
        log.warning(f"Monte Carlo: Zu wenig Trades ({len(trade_returns)} < 10)")
        return MonteCarloResult(
            n_simulations=0, n_trades=len(trade_returns),
            sharpe_p05=0.0, sharpe_p50=0.0, sharpe_p95=0.0,
            maxdd_p05=0.0, maxdd_p50=0.0, maxdd_p95=1.0,
            equity_p05=0.5, equity_p50=1.0, equity_p95=2.0,
            robustness_score=0.0, prob_ruin=1.0,
            ready=False, summary="Zu wenig Trade-Daten",
        )

    rng      = np.random.default_rng(seed)
    returns  = np.array(trade_returns, dtype=float)

    # Konvertierung zu % wenn nötig
    if not as_pct:
        returns_pct = returns / initial_capital
    else:
        returns_pct = returns

    n_trades  = len(returns_pct)
    sharpes   = np.zeros(n_simulations)
    maxdds    = np.zeros(n_simulations)
    finals    = np.zeros(n_simulations)

    for i in range(n_simulations):
        perm  = rng.permutation(returns_pct)
        eq    = _compute_equity_curve(perm)
        sharpes[i] = _compute_sharpe(perm)
        maxdds[i]  = _compute_max_drawdown(eq)
        finals[i]  = eq[-1]

    # Perzentile
    def p(arr, q): return float(np.percentile(arr, q))

    # Robustheitsscore: Anteil Sims die beide Kriterien erfüllen
    passes = (sharpes >= MIN_SHARPE_TARGET) & (maxdds <= MAX_DD_TARGET)
    robustness = float(np.mean(passes))

    # Ruin-Wahrscheinlichkeit: Equity < 50% des Startkapitals
    prob_ruin = float(np.mean(finals < 0.5))

    ready = robustness >= 0.60

    summary = (
        f"Monte Carlo ({n_simulations} Sims, {n_trades} Trades): "
        f"Sharpe P50={p(sharpes, 50):.2f} [{p(sharpes, 5):.2f}/{p(sharpes, 95):.2f}] | "
        f"MaxDD P50={p(maxdds, 50):.1%} | "
        f"Robustheit {robustness:.0%} | "
        f"{'READY' if ready else 'NOT READY'}"
    )
    log.info(summary)

    return MonteCarloResult(
        n_simulations    = n_simulations,
        n_trades         = n_trades,
        sharpe_p05       = round(p(sharpes, 5),  3),
        sharpe_p50       = round(p(sharpes, 50), 3),
        sharpe_p95       = round(p(sharpes, 95), 3),
        maxdd_p05        = round(p(maxdds, 5),  4),
        maxdd_p50        = round(p(maxdds, 50), 4),
        maxdd_p95        = round(p(maxdds, 95), 4),
        equity_p05       = round(p(finals, 5),  4),
        equity_p50       = round(p(finals, 50), 4),
        equity_p95       = round(p(finals, 95), 4),
        robustness_score = round(robustness, 4),
        prob_ruin        = round(prob_ruin, 4),
        ready            = ready,
        summary          = summary,
    )


def run_monte_carlo_from_db(
    initial_capital: float = 10000.0,
    n_simulations:   int   = 1000,
) -> MonteCarloResult | None:
    """
    Lädt Trade-Returns aus SQLite-Datenbank und führt Monte Carlo durch.

    Returns None wenn keine Trade-Daten vorhanden.
    """
    try:
        from forex_bot.monitoring.logger import get_recent_trades
        trades = get_recent_trades(500)
        if not trades:
            log.info("Monte Carlo: Keine Trades in DB")
            return None

        pnls = [t.get("pnl", 0.0) for t in trades]
        pnls = [p for p in pnls if p != 0.0]   # Offene Trades ausschließen

        if len(pnls) < 10:
            log.info(f"Monte Carlo: Zu wenig abgeschlossene Trades ({len(pnls)})")
            return None

        return run_monte_carlo(pnls, n_simulations=n_simulations,
                               initial_capital=initial_capital)

    except Exception as e:
        log.error(f"Monte Carlo from DB: {e}")
        return None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    result = run_monte_carlo_from_db()
    if result:
        print(f"\n{result.summary}")
        print(f"\nSharpe-Verteilung:")
        print(f"  5%: {result.sharpe_p05:.2f} | 50%: {result.sharpe_p50:.2f} | 95%: {result.sharpe_p95:.2f}")
        print(f"\nMax-Drawdown-Verteilung:")
        print(f"  5%: {result.maxdd_p05:.1%} | 50%: {result.maxdd_p50:.1%} | 95%: {result.maxdd_p95:.1%}")
        print(f"\nRobustheitsscore: {result.robustness_score:.0%}")
        print(f"Ruin-Wahrscheinlichkeit: {result.prob_ruin:.1%}")
        sys.exit(0 if result.ready else 1)
    else:
        print("Keine Daten für Monte Carlo verfügbar")
        sys.exit(1)
