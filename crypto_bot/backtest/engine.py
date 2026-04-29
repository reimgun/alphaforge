"""
Backtesting Engine — realistische Simulation mit:
- Lookahead-Bias-freier Execution (Signal auf Candle N → Ausführung auf Open N+1)
- Slippage + Fees pro Trade
- Intra-Candle Stop-Loss-Prüfung (High/Low der Candle)
- Max-Drawdown-Berechnung auf Equity-Kurve
- Benchmark-Vergleich (Buy & Hold)
- Sharpe Ratio
"""
import math
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from crypto_bot.data.fetcher import fetch_ohlcv
from crypto_bot.strategy.momentum import add_indicators
from crypto_bot.config.settings import (
    SYMBOL, TIMEFRAME, BACKTEST_DAYS, INITIAL_CAPITAL,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, SLIPPAGE_PCT, TRADING_FEE_PCT,
)

console = Console()


def _apply_costs(price: float, side: str) -> float:
    """Wendet Slippage und Fee auf einen Ausführungspreis an."""
    if side == "buy":
        return price * (1 + SLIPPAGE_PCT + TRADING_FEE_PCT)
    return price * (1 - SLIPPAGE_PCT - TRADING_FEE_PCT)


def run_backtest() -> dict:
    console.print(f"[bold cyan]Backtest: {SYMBOL} | {TIMEFRAME} | {BACKTEST_DAYS} Tage[/bold cyan]")
    console.print(f"[dim]Slippage: {SLIPPAGE_PCT*100:.1f}% | Fee: {TRADING_FEE_PCT*100:.1f}% pro Seite[/dim]")

    df = fetch_ohlcv(SYMBOL, TIMEFRAME, days=BACKTEST_DAYS)
    df = add_indicators(df)
    df.dropna(inplace=True)
    df = df.reset_index()  # Für numerischen Index

    capital = INITIAL_CAPITAL
    position = None
    trades = []
    equity_curve = [capital]  # Equity nach jedem Candle

    for i in range(1, len(df) - 1):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        next_open = df.iloc[i + 1]["open"]  # Execution auf nächstem Candle-Open

        # --- Offene Position: Intra-Candle SL/TP auf diesem Candle prüfen ---
        if position:
            # Prüfe High/Low des aktuellen Candles (nicht nur Close!)
            candle_low = row["low"]
            candle_high = row["high"]

            hit_sl = candle_low <= position["stop_loss"]
            hit_tp = candle_high >= position["take_profit"]

            if hit_sl and hit_tp:
                # Beide getroffen — konservativ: SL gewinnt (worst case)
                exit_price = _apply_costs(position["stop_loss"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append({
                    "entry": position["entry_raw"], "exit": exit_price,
                    "pnl": pnl, "reason": "SL",
                    "entry_time": position["entry_time"], "exit_time": row["timestamp"],
                })
                position = None

            elif hit_sl:
                exit_price = _apply_costs(position["stop_loss"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append({
                    "entry": position["entry_raw"], "exit": exit_price,
                    "pnl": pnl, "reason": "SL",
                    "entry_time": position["entry_time"], "exit_time": row["timestamp"],
                })
                position = None

            elif hit_tp:
                exit_price = _apply_costs(position["take_profit"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append({
                    "entry": position["entry_raw"], "exit": exit_price,
                    "pnl": pnl, "reason": "TP",
                    "entry_time": position["entry_time"], "exit_time": row["timestamp"],
                })
                position = None

        equity_curve.append(capital)

        if position:
            continue

        # --- Signal auf diesem Candle, Execution auf NÄCHSTEM Open ---
        # (kein Lookahead-Bias: wir handeln erst wenn Candle geschlossen ist)
        golden_cross = (prev["fast_ma"] <= prev["slow_ma"]) and (row["fast_ma"] > row["slow_ma"])
        rsi_ok = row["rsi"] < 70

        if golden_cross and rsi_ok:
            entry_raw = next_open
            entry_cost = _apply_costs(entry_raw, "buy")  # inklusive Slippage+Fee

            risk_amount = capital * 0.02
            stop_distance = entry_cost * STOP_LOSS_PCT
            if stop_distance <= 0:
                continue
            qty = risk_amount / stop_distance
            qty = min(qty, (capital * 0.95) / entry_cost)

            position = {
                "entry_raw": entry_raw,
                "entry_cost": entry_cost,
                "qty": qty,
                "stop_loss": entry_raw * (1 - STOP_LOSS_PCT),
                "take_profit": entry_raw * (1 + TAKE_PROFIT_PCT),
                "entry_time": df.iloc[i + 1]["timestamp"],
            }

    # Offene Position am Ende zum letzten Close schließen
    if position:
        exit_price = _apply_costs(df.iloc[-1]["close"], "sell")
        pnl = (exit_price - position["entry_cost"]) * position["qty"]
        capital += pnl
        trades.append({
            "entry": position["entry_raw"], "exit": exit_price,
            "pnl": pnl, "reason": "End",
            "entry_time": position["entry_time"], "exit_time": df.iloc[-1]["timestamp"],
        })
        equity_curve.append(capital)

    if not trades:
        console.print("[yellow]Keine Trades im Backtest-Zeitraum[/yellow]")
        return {}

    equity = np.array(equity_curve)
    result = _calculate_stats(trades, equity, df)
    _print_results(result, df)
    return result


def _calculate_stats(trades: list, equity: np.ndarray, df: pd.DataFrame) -> dict:
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # Max Drawdown auf Equity-Kurve (nicht nur auf Trade-Closes!)
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Sharpe Ratio (annualisiert, vereinfacht)
    returns = np.diff(equity) / equity[:-1]
    sharpe = 0.0
    if returns.std() > 0:
        # Annualisierung: 1h Kerzen → ~8760 Kerzen/Jahr
        periods_per_year = 8760
        sharpe = round((returns.mean() / returns.std()) * math.sqrt(periods_per_year), 2)

    # Profit Factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

    # Buy & Hold Benchmark
    bh_return = (df.iloc[-1]["close"] / df.iloc[0]["close"] - 1) * 100
    final_capital = equity[-1]

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "return_pct": round((final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": sharpe,
        "profit_factor": profit_factor,
        "buyhold_return_pct": round(bh_return, 2),
        "final_capital": round(final_capital, 2),
    }


def _print_results(result: dict, df: pd.DataFrame):
    table = Table(title=f"Backtest — {SYMBOL} | {BACKTEST_DAYS} Tage (mit Kosten)")
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="white")

    ts_col = "timestamp" if "timestamp" in df.columns else df.index.name or "index"
    try:
        start = pd.to_datetime(df["timestamp"].iloc[0]).date() if "timestamp" in df.columns else df.index[0].date()
        end = pd.to_datetime(df["timestamp"].iloc[-1]).date() if "timestamp" in df.columns else df.index[-1].date()
        table.add_row("Zeitraum", f"{start} → {end}")
    except Exception:
        pass

    table.add_row("Trades gesamt", str(result["trades"]))
    table.add_row("Gewinner / Verlierer", f"{result['wins']} / {result['losses']}")
    table.add_row("Win-Rate", f"{result['win_rate']}%")
    table.add_row("Profit Factor", str(result["profit_factor"]))
    table.add_row("Sharpe Ratio", str(result["sharpe_ratio"]))
    table.add_row("Gesamt PnL", f"{result['total_pnl']:+.2f} USDT")
    table.add_row("Strategie Rendite", f"{result['return_pct']:+.2f}%")
    table.add_row("Buy & Hold Rendite", f"{result['buyhold_return_pct']:+.2f}%")
    table.add_row("Ø Gewinn", f"{result['avg_win']:+.2f} USDT")
    table.add_row("Ø Verlust", f"{result['avg_loss']:+.2f} USDT")
    table.add_row("Max. Drawdown", f"{result['max_drawdown_pct']}%")
    table.add_row("Startkapital", f"{INITIAL_CAPITAL:.2f} USDT")
    table.add_row("Endkapital", f"{result['final_capital']:.2f} USDT")
    console.print(table)

    alpha = result["return_pct"] - result["buyhold_return_pct"]
    if result["return_pct"] > 0 and result["max_drawdown_pct"] < 15 and result["sharpe_ratio"] > 1.0:
        console.print(f"[bold green]Strategie solide — Alpha vs Buy&Hold: {alpha:+.1f}%[/bold green]")
    elif result["max_drawdown_pct"] >= 20:
        console.print("[bold red]Drawdown zu hoch (>20%) — Parameter anpassen![/bold red]")
    elif result["return_pct"] <= 0:
        console.print("[bold red]Negative Rendite nach Kosten — Strategie überdenken![/bold red]")
    else:
        console.print(f"[yellow]Strategie läuft, aber Alpha schwach ({alpha:+.1f}%) — weiter optimieren[/yellow]")
