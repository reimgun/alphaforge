"""
Walk-Forward Testing — Out-of-Sample Validierung.

Teilt Daten in mehrere Zeitfenster:
  [────Train────|─Test─] → [────Train────|─Test─] → ...

Zeigt ob die Strategie auf ungesehenen Daten funktioniert
oder ob sie nur auf historische Daten overfit ist.
"""
import math
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from crypto_bot.data.fetcher import fetch_ohlcv
from crypto_bot.strategy.momentum import add_indicators
from crypto_bot.config.settings import (
    SYMBOL, TIMEFRAME, INITIAL_CAPITAL, STOP_LOSS_PCT,
    TAKE_PROFIT_PCT, SLIPPAGE_PCT, TRADING_FEE_PCT,
)

console = Console()


def _apply_costs(price: float, side: str) -> float:
    if side == "buy":
        return price * (1 + SLIPPAGE_PCT + TRADING_FEE_PCT)
    return price * (1 - SLIPPAGE_PCT - TRADING_FEE_PCT)


def _run_window(df: pd.DataFrame) -> dict:
    """Führt einen einzelnen Backtest-Lauf auf einem Daten-Window aus."""
    capital   = INITIAL_CAPITAL
    position  = None
    trades    = []
    equity    = [capital]
    df        = df.reset_index(drop=True)

    for i in range(1, len(df) - 1):
        row  = df.iloc[i]
        prev = df.iloc[i - 1]
        next_open = df.iloc[i + 1]["open"]

        if position:
            if row["low"] <= position["stop_loss"]:
                exit_p = _apply_costs(position["stop_loss"], "sell")
                pnl = (exit_p - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append({"pnl": pnl, "reason": "SL"})
                position = None
            elif row["high"] >= position["take_profit"]:
                exit_p = _apply_costs(position["take_profit"], "sell")
                pnl = (exit_p - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append({"pnl": pnl, "reason": "TP"})
                position = None

        equity.append(capital)
        if position:
            continue

        gc = (prev["fast_ma"] <= prev["slow_ma"]) and (row["fast_ma"] > row["slow_ma"])
        if gc and row["rsi"] < 70:
            entry_cost = _apply_costs(next_open, "buy")
            stop_dist  = entry_cost * STOP_LOSS_PCT
            qty = min(capital * 0.02 / stop_dist, capital * 0.95 / entry_cost)
            position = {
                "entry_cost": entry_cost,
                "qty": qty,
                "stop_loss":  next_open * (1 - STOP_LOSS_PCT),
                "take_profit": next_open * (1 + TAKE_PROFIT_PCT),
            }

    if position:
        exit_p = _apply_costs(df.iloc[-1]["close"], "sell")
        pnl = (exit_p - position["entry_cost"]) * position["qty"]
        capital += pnl
        trades.append({"pnl": pnl, "reason": "End"})
        equity.append(capital)

    if not trades:
        return {"trades": 0, "return_pct": 0, "max_dd": 0, "sharpe": 0, "win_rate": 0}

    pnls   = [t["pnl"] for t in trades]
    wins   = [p for p in pnls if p > 0]

    eq     = np.array(equity)
    peak   = eq[0]; max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100)

    rets   = np.diff(eq) / eq[:-1]
    sharpe = 0.0
    if rets.std() > 0:
        sharpe = round((rets.mean() / rets.std()) * math.sqrt(8760), 2)

    return {
        "trades":     len(trades),
        "return_pct": round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "max_dd":     round(max_dd, 2),
        "sharpe":     sharpe,
        "win_rate":   round(len(wins) / len(trades) * 100, 1) if trades else 0,
    }


def run_walk_forward(total_days: int = 720, n_windows: int = 6, train_ratio: float = 0.7) -> list[dict]:
    """
    Führt Walk-Forward Test aus.
    total_days: Gesamtzeitraum der Daten
    n_windows: Anzahl der Test-Fenster
    train_ratio: Anteil Trainingsdaten pro Fenster (0.7 = 70% Train, 30% Test)
    """
    console.print(f"[bold cyan]Walk-Forward Test: {n_windows} Fenster | {total_days} Tage[/bold cyan]")

    df = fetch_ohlcv(SYMBOL, TIMEFRAME, days=total_days)
    df = add_indicators(df)
    df.dropna(inplace=True)
    df = df.reset_index()

    window_size = len(df) // n_windows
    results     = []

    for i in range(n_windows):
        start = i * window_size
        end   = start + window_size
        if end > len(df):
            break

        window = df.iloc[start:end].copy()
        split  = int(len(window) * train_ratio)

        # Nur Test-Portion backtesten (Train-Daten werden im ML genutzt)
        test_window = window.iloc[split:].copy()

        if len(test_window) < 50:
            continue

        period_start = window["timestamp"].iloc[0].date() if "timestamp" in window.columns else f"Window {i+1} Start"
        period_end   = window["timestamp"].iloc[-1].date() if "timestamp" in window.columns else f"Window {i+1} End"

        result = _run_window(test_window)
        result["window"]  = i + 1
        result["period"]  = f"{period_start} → {period_end}"
        result["test_days"] = len(test_window)
        results.append(result)

        icon = "✓" if result["return_pct"] > 0 else "✗"
        console.print(
            f"  Fenster {i+1}: [{icon}] {result['return_pct']:+.1f}% | "
            f"Trades={result['trades']} | DD={result['max_dd']:.1f}% | "
            f"Sharpe={result['sharpe']:.2f} | {period_start}"
        )

    _print_wf_summary(results)
    return results


def _print_wf_summary(results: list[dict]):
    if not results:
        return

    returns   = [r["return_pct"] for r in results]
    win_count = sum(1 for r in returns if r > 0)

    table = Table(title="Walk-Forward Summary")
    table.add_column("Metrik",  style="cyan")
    table.add_column("Wert",    style="white")

    table.add_row("Test-Fenster",         str(len(results)))
    table.add_row("Profitable Fenster",   f"{win_count}/{len(results)}")
    table.add_row("Ø Rendite pro Fenster", f"{np.mean(returns):+.2f}%")
    table.add_row("Beste Rendite",         f"{max(returns):+.2f}%")
    table.add_row("Schlechteste Rendite",  f"{min(returns):+.2f}%")
    table.add_row("Ø Sharpe",             f"{np.mean([r['sharpe'] for r in results]):.2f}")
    table.add_row("Ø Max Drawdown",       f"{np.mean([r['max_dd'] for r in results]):.1f}%")
    console.print(table)

    consistency = win_count / len(results) * 100
    if consistency >= 70 and np.mean(returns) > 0:
        console.print("[bold green]Walk-Forward bestanden — Strategie generalisiert gut[/bold green]")
    elif consistency >= 50:
        console.print("[yellow]Strategie inkonsistent — weitere Optimierung empfohlen[/yellow]")
    else:
        console.print("[bold red]Walk-Forward nicht bestanden — Strategie overfit auf historische Daten[/bold red]")
