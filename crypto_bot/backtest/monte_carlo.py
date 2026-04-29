"""
Monte Carlo Robustness Testing.

Bootstrapped Resampling der Trade-Returns → Konfidenzintervalle für Performance-Metriken.
Schätzt Ruinwahrscheinlichkeit und Worst-Case Drawdown.
"""
import math
import numpy as np
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class MonteCarloResult:
    n_simulations: int
    sharpe_mean: float
    sharpe_p5: float
    sharpe_p95: float
    max_dd_mean: float
    max_dd_p95: float       # Worst-Case Drawdown (95. Perzentil)
    ruin_probability: float  # P(Kapital < 50% des Start)
    final_return_mean: float
    final_return_p5: float
    final_return_p95: float


def run_monte_carlo(
    trade_returns: list[float],
    initial_capital: float = 1000.0,
    n_simulations: int = 1000,
    ruin_threshold: float = 0.5,
) -> MonteCarloResult:
    """
    Bootstrapped Monte Carlo Simulation.

    Args:
        trade_returns:  Liste von Trade-PnL in USDT (aus Backtest oder Live-Trades)
        initial_capital: Startkapital
        n_simulations:  Anzahl Simulationen
        ruin_threshold: Ruin = Kapital fällt unter X% des Start (default 50%)
    """
    if len(trade_returns) < 5:
        console.print("[yellow]Monte Carlo: zu wenige Trades (min. 5)[/yellow]")
        return MonteCarloResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    returns_arr = np.array(trade_returns)
    n_trades    = len(returns_arr)

    sharpes       = []
    max_drawdowns = []
    final_returns = []
    ruin_count    = 0

    for _ in range(n_simulations):
        # Bootstrap: Zufällige Auswahl mit Zurücklegen
        sampled = np.random.choice(returns_arr, size=n_trades, replace=True)

        # Equity-Kurve simulieren
        equity = initial_capital
        equities = [equity]
        for r in sampled:
            equity += r
            equity = max(equity, 0.01)  # Kein Negativkapital
            equities.append(equity)

        eq = np.array(equities)

        # Ruin-Check
        if eq.min() < initial_capital * ruin_threshold:
            ruin_count += 1

        # Max Drawdown
        peak = eq[0]
        dd   = 0.0
        for v in eq:
            if v > peak:
                peak = v
            dd = max(dd, (peak - v) / peak * 100)
        max_drawdowns.append(dd)

        # Sharpe Ratio
        sim_returns = np.diff(eq) / eq[:-1]
        if sim_returns.std() > 0:
            periods_per_year = 8760
            s = (sim_returns.mean() / sim_returns.std()) * math.sqrt(periods_per_year)
        else:
            s = 0.0
        sharpes.append(s)

        # Final Return %
        final_returns.append((eq[-1] - initial_capital) / initial_capital * 100)

    sharpes       = np.array(sharpes)
    max_drawdowns = np.array(max_drawdowns)
    final_returns = np.array(final_returns)

    result = MonteCarloResult(
        n_simulations      = n_simulations,
        sharpe_mean        = round(float(sharpes.mean()), 2),
        sharpe_p5          = round(float(np.percentile(sharpes, 5)), 2),
        sharpe_p95         = round(float(np.percentile(sharpes, 95)), 2),
        max_dd_mean        = round(float(max_drawdowns.mean()), 2),
        max_dd_p95         = round(float(np.percentile(max_drawdowns, 95)), 2),
        ruin_probability   = round(ruin_count / n_simulations * 100, 2),
        final_return_mean  = round(float(final_returns.mean()), 2),
        final_return_p5    = round(float(np.percentile(final_returns, 5)), 2),
        final_return_p95   = round(float(np.percentile(final_returns, 95)), 2),
    )

    _print_results(result)
    return result


def _print_results(r: MonteCarloResult):
    table = Table(title=f"Monte Carlo ({r.n_simulations:,} Simulationen)")
    table.add_column("Metrik", style="cyan")
    table.add_column("Mean", style="white")
    table.add_column("P5 (Schlecht)", style="red")
    table.add_column("P95 (Gut)", style="green")

    table.add_row("Sharpe Ratio",   str(r.sharpe_mean),       str(r.sharpe_p5),       str(r.sharpe_p95))
    table.add_row("Rendite %",      f"{r.final_return_mean:+.1f}%",
                  f"{r.final_return_p5:+.1f}%", f"{r.final_return_p95:+.1f}%")
    table.add_row("Max Drawdown",   f"{r.max_dd_mean:.1f}%", "—", f"{r.max_dd_p95:.1f}% (worst)")

    console.print(table)

    ruin_color = "red" if r.ruin_probability > 10 else "yellow" if r.ruin_probability > 3 else "green"
    console.print(f"[{ruin_color}]Ruinwahrscheinlichkeit (Kapital < 50%): {r.ruin_probability:.1f}%[/{ruin_color}]")
