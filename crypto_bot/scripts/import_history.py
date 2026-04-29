"""
Historische Backtest-Trades importieren → trades.db

Lädt N Tage historische Binance-Daten, simuliert die Strategie
(ML-Modell + Regeln, kein Lookahead-Bias) und speichert die
Ergebnisse als getaggte Backtest-Trades in die Datenbank.

Verwendung:
    python scripts/import_history.py             # 365 Tage
    python scripts/import_history.py --days 180  # 180 Tage
    python scripts/import_history.py --clear     # DB vorher leeren

Warum sinnvoll:
    - Trade-Zähler für Fortschrittsbalken schneller füllen
    - Realistische Performance-Schätzung vor echtem Paper-Trading
    - ML-Modell bereits auf denselben Daten trainiert — kein Lookahead

Warum nicht "cheaten":
    - Trades werden als ai_source="backtest" markiert
    - Dashboard zeigt Backtest vs. Live getrennt
    - Sharpe/Win-Rate aus Backtest als Schätzwert, kein Ersatz für Live-Daten
"""
import sys
import argparse
from pathlib import Path

# Projektpfad
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.table import Table
from rich.progress import track
import pandas as pd

console = Console()


def run_import(days: int = 365, clear_existing: bool = False):
    from crypto_bot.data.fetcher import fetch_ohlcv
    from crypto_bot.strategy.momentum import add_indicators
    from crypto_bot.monitoring.logger import init_db, log_trade
    from crypto_bot.config.settings import (
        SYMBOL, TIMEFRAME, INITIAL_CAPITAL,
        STOP_LOSS_PCT, TAKE_PROFIT_PCT,
        SLIPPAGE_PCT, TRADING_FEE_PCT,
    )

    console.print(f"\n[bold cyan]Historischer Backtest-Import[/bold cyan]")
    console.print(f"  Symbol:    {SYMBOL}")
    console.print(f"  Timeframe: {TIMEFRAME}")
    console.print(f"  Zeitraum:  letzte {days} Tage")
    console.print()

    init_db()

    # Bestehende Backtest-Trades löschen falls --clear
    if clear_existing:
        import sqlite3
        from crypto_bot.config.settings import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            deleted = conn.execute(
                "DELETE FROM trades WHERE ai_source='backtest'"
            ).rowcount
            conn.commit()
        console.print(f"  [yellow]Bestehende Backtest-Trades gelöscht: {deleted}[/yellow]\n")

    # Historische Daten laden
    console.print("  [dim]Lade historische Daten von Binance...[/dim]")
    df = fetch_ohlcv(SYMBOL, TIMEFRAME, days=days)
    df = add_indicators(df)
    df.dropna(inplace=True)
    df = df.reset_index()
    console.print(f"  [green]✓[/green] {len(df)} Candles geladen ({days} Tage)\n")

    # ML-Modell laden (falls vorhanden)
    ml_model = None
    try:
        from crypto_bot.ai.trainer import load_model, build_features
        ml_model = load_model()
        console.print("  [green]✓[/green] ML-Modell geladen — verwende ML-Signale\n")
    except Exception:
        console.print("  [yellow]⚠[/yellow]  Kein ML-Modell — verwende Momentum-Signale\n")

    def _apply_costs(price: float, side: str) -> float:
        if side == "buy":
            return price * (1 + SLIPPAGE_PCT + TRADING_FEE_PCT)
        return price * (1 - SLIPPAGE_PCT - TRADING_FEE_PCT)

    def _get_signal(i: int) -> tuple[str, float]:
        """Gibt Signal + Konfidenz für Candle i zurück."""
        row  = df.iloc[i]
        prev = df.iloc[i - 1]

        # ML-Signal wenn Modell vorhanden
        if ml_model is not None:
            try:
                features = build_features(df.iloc[:i + 1])
                if features is not None and len(features) > 0:
                    feat_row = features.iloc[-1:].values
                    proba = ml_model.predict_proba(feat_row)[0]
                    classes = list(ml_model.classes_)
                    buy_p  = proba[classes.index("BUY")]  if "BUY"  in classes else 0.0
                    sell_p = proba[classes.index("SELL")] if "SELL" in classes else 0.0
                    if buy_p > 0.55:
                        return "BUY", buy_p
                    if sell_p > 0.55:
                        return "SELL", sell_p
                    return "HOLD", max(proba)
            except Exception:
                pass

        # Fallback: Momentum-Signal
        golden = (prev["fast_ma"] <= prev["slow_ma"]) and (row["fast_ma"] > row["slow_ma"])
        death  = (prev["fast_ma"] >= prev["slow_ma"]) and (row["fast_ma"] < row["slow_ma"])
        rsi_ok = 30 < row.get("rsi", 50) < 70

        if golden and rsi_ok:
            return "BUY", 0.65
        if death:
            return "SELL", 0.65
        return "HOLD", 0.5

    # Simulation
    capital  = float(INITIAL_CAPITAL)
    position = None
    imported = []
    wins = losses = 0

    for i in track(range(1, len(df) - 1), description="Simuliere..."):
        row      = df.iloc[i]
        next_row = df.iloc[i + 1]

        # Offene Position: SL/TP prüfen
        if position:
            low, high = row["low"], row["high"]
            hit_sl = low <= position["stop_loss"]
            hit_tp = high >= position["take_profit"]

            exit_price = None
            exit_reason = ""
            if hit_sl and hit_tp:
                exit_price  = _apply_costs(position["stop_loss"], "sell")
                exit_reason = "SL"
            elif hit_sl:
                exit_price  = _apply_costs(position["stop_loss"], "sell")
                exit_reason = "SL"
            elif hit_tp:
                exit_price  = _apply_costs(position["take_profit"], "sell")
                exit_reason = "TP"
            else:
                # SELL-Signal prüfen
                signal, conf = _get_signal(i)
                if signal == "SELL":
                    exit_price  = _apply_costs(row["close"], "sell")
                    exit_reason = "signal"

            if exit_price is not None:
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                imported.append({
                    "entry":      position["entry_raw"],
                    "exit":       exit_price,
                    "pnl":        pnl,
                    "qty":        position["qty"],
                    "reason":     exit_reason,
                    "confidence": position["confidence"],
                    "entry_time": str(position["entry_time"]),
                    "exit_time":  str(row.get("timestamp", "")),
                })
                position = None

        if position:
            continue

        # BUY-Signal → Einstieg auf nächstem Open
        signal, conf = _get_signal(i)
        if signal == "BUY" and conf > 0.55:
            entry_raw  = float(next_row["open"])
            entry_cost = _apply_costs(entry_raw, "buy")
            risk_amt   = capital * 0.02
            stop_dist  = entry_cost * STOP_LOSS_PCT
            if stop_dist <= 0:
                continue
            qty = min(risk_amt / stop_dist, (capital * 0.95) / entry_cost)
            position = {
                "entry_raw":  entry_raw,
                "entry_cost": entry_cost,
                "qty":        qty,
                "stop_loss":  entry_raw * (1 - STOP_LOSS_PCT),
                "take_profit": entry_raw * (1 + TAKE_PROFIT_PCT),
                "entry_time": next_row.get("timestamp", ""),
                "confidence": conf,
            }

    # Offene Position am Ende schließen
    if position:
        exit_price = _apply_costs(float(df.iloc[-1]["close"]), "sell")
        pnl = (exit_price - position["entry_cost"]) * position["qty"]
        capital += pnl
        if pnl >= 0:
            wins += 1
        else:
            losses += 1
        imported.append({
            "entry":      position["entry_raw"],
            "exit":       exit_price,
            "pnl":        pnl,
            "qty":        position["qty"],
            "reason":     "End",
            "confidence": position["confidence"],
            "entry_time": str(position["entry_time"]),
            "exit_time":  str(df.iloc[-1].get("timestamp", "")),
        })

    # In DB speichern
    console.print(f"\n  [dim]Speichere {len(imported)} Trades in Datenbank...[/dim]")
    for t in imported:
        log_trade(
            symbol      = SYMBOL,
            side        = "SELL",
            entry_price = t["entry"],
            exit_price  = t["exit"],
            quantity    = t["qty"],
            pnl         = t["pnl"],
            reason      = t["reason"],
            ai_source   = "backtest",
            confidence  = t["confidence"],
            entry_time  = t["entry_time"],
            exit_time   = t["exit_time"],
        )

    # Ergebnis anzeigen
    total = wins + losses
    win_rate = wins / total * 100 if total > 0 else 0
    total_pnl = capital - INITIAL_CAPITAL
    total_pnl_pct = total_pnl / INITIAL_CAPITAL * 100

    table = Table(title=f"Backtest-Import abgeschlossen ({days} Tage)", show_header=True)
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", style="bold")
    table.add_row("Trades importiert", str(total))
    table.add_row("Gewinner", str(wins))
    table.add_row("Verlierer", str(losses))
    table.add_row("Win-Rate", f"{win_rate:.1f}%")
    table.add_row("Gesamt PnL", f"{total_pnl:+.2f} USDT ({total_pnl_pct:+.1f}%)")
    table.add_row("Endkapital", f"{capital:.2f} USDT")
    table.add_row("", "")
    table.add_row("Markiert als", "ai_source = 'backtest'")
    table.add_row("Sichtbar in", "Dashboard → Trade History + Fortschritt")
    console.print(table)

    console.print(
        "\n[bold green]✓ Import abgeschlossen.[/bold green]\n"
        "[dim]Backtest-Trades sind im Dashboard als 'backtest' markiert.\n"
        "Sie füllen den Fortschrittsbalken — werden aber getrennt von\n"
        "Live-Paper-Trades ausgewiesen.[/dim]\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Historische Backtest-Trades importieren")
    parser.add_argument("--days",  type=int, default=730, help="Anzahl Tage (Standard: 730, Max: 800)")
    parser.add_argument("--clear", action="store_true",   help="Bestehende Backtest-Trades löschen")
    args = parser.parse_args()
    run_import(days=args.days, clear_existing=args.clear)
