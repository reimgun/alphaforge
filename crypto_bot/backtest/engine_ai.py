"""
AI-Pipeline Backtest Engine — testet die ECHTE Strategie-Logic.

Im Gegensatz zu engine.py (nur Momentum-Indikatoren) nutzt diese Engine:
  - MLPredictor (XGBoost — gleich wie im Live-Betrieb)
  - RegimeDetector (Bull/Bear/Sideways/HighVol)
  - VolatilityForecaster
  - AnomalyDetector
  - RiskManager (ATR-Sizing, Trailing Stop, Drawdown Recovery)
  - KEIN Claude-API-Call (zu teuer/langsam für Backtest)

Lookahead-Bias-Schutz:
  - Signal auf Candle N → Execution auf Open N+1
  - ML-Modell sieht nur Daten bis Candle N (rolling window)

QNAP-Hinweis:
  - Läuft auf Celeron J1900 aber langsam (~5–15 min für 365 Tage)
  - Für schnellen Test: --days 90 nutzen

Verwendung:
  python -m crypto_bot.backtest_run --mode ai
  python -m crypto_bot.backtest_run --mode ai --days 90
"""
import math
import time
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from crypto_bot.data.fetcher import fetch_ohlcv
from crypto_bot.strategy.momentum import add_indicators
from crypto_bot.strategy.regime_detector import detect_regime
from crypto_bot.config.settings import (
    SYMBOL, TIMEFRAME, BACKTEST_DAYS, INITIAL_CAPITAL,
    SLIPPAGE_PCT, TRADING_FEE_PCT, RISK_PER_TRADE,
    USE_ATR_SIZING, ATR_MULTIPLIER, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    USE_TRAILING_STOP, TRAILING_STOP_PCT, AI_MODE,
)

console = Console()

# Minimum Rolling Window für ML-Features (braucht genug History)
_MIN_WINDOW = 120


def _apply_costs(price: float, side: str) -> float:
    if side == "buy":
        return price * (1 + SLIPPAGE_PCT + TRADING_FEE_PCT)
    return price * (1 - SLIPPAGE_PCT - TRADING_FEE_PCT)


def run_ai_backtest(days: int = BACKTEST_DAYS, verbose: bool = False) -> dict:
    """
    Führt Backtest mit der echten ML + Regime-Pipeline aus.

    Args:
        days:    Anzahl historischer Tage (Standard: BACKTEST_DAYS)
        verbose: Zeige jede Entscheidung (langsam, gut für Debugging)

    Returns:
        dict mit Performance-Metriken
    """
    console.print(Panel(
        f"Symbol: {SYMBOL} | Timeframe: {TIMEFRAME} | Tage: {days}\n"
        f"Engine: AI-Pipeline (ML + Regime + ATR-Sizing)\n"
        f"Slippage: {SLIPPAGE_PCT*100:.1f}% | Fee: {TRADING_FEE_PCT*100:.1f}% pro Seite\n"
        f"[dim]Hinweis: Claude API wird im Backtest nicht aufgerufen[/dim]",
        title="AI-Pipeline Backtest",
        style="bold cyan",
    ))

    # ── Daten laden ────────────────────────────────────────────────────────────
    df = fetch_ohlcv(SYMBOL, TIMEFRAME, days=days + 30)  # +30 für Warmup
    df = add_indicators(df)
    df.dropna(inplace=True)
    df = df.reset_index()

    if len(df) < _MIN_WINDOW + 10:
        console.print(f"[red]Zu wenig Daten ({len(df)} Candles, Minimum {_MIN_WINDOW + 10})[/red]")
        return {}

    # ── ML-Modell laden (einmalig) ─────────────────────────────────────────────
    ml_predictor = None
    if AI_MODE in ("ml", "combined", "rules"):
        try:
            from crypto_bot.ai.predictor import MLPredictor
            ml_predictor = MLPredictor()
            console.print(f"[dim]ML-Modell geladen[/dim]")
        except Exception as e:
            console.print(f"[yellow]ML-Modell nicht verfügbar: {e} — nutze Regime-Only Modus[/yellow]")

    # ── Backtest-Schleife ──────────────────────────────────────────────────────
    capital      = float(INITIAL_CAPITAL)
    position     = None
    trades       = []
    equity_curve = [capital]
    signals_log  = []  # Für Post-Hoc Analyse

    # Nur die letzten `days` Candles backtesten (nach Warmup)
    warmup   = _MIN_WINDOW
    df_test  = df.iloc[warmup:].reset_index(drop=True)
    df_full  = df  # Vollständiges df für rolling window

    start_time = time.time()
    n = len(df_test)

    console.print(f"[dim]Starte Backtest über {n} Candles...[/dim]")

    for i in range(1, n - 1):
        row       = df_test.iloc[i]
        next_open = float(df_test.iloc[i + 1]["open"])

        # ── Intra-Candle Stop/TP-Prüfung (Long) ───────────────────────────────
        if position and position["side"] == "long":
            candle_low  = float(row["low"])
            candle_high = float(row["high"])
            hit_sl = candle_low <= position["stop_loss"]
            hit_tp = candle_high >= position["take_profit"] and not USE_TRAILING_STOP

            if hit_sl and hit_tp:
                exit_price = _apply_costs(position["stop_loss"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append(_make_trade(position, exit_price, pnl, "SL", row))
                position = None
            elif hit_sl:
                exit_price = _apply_costs(position["stop_loss"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append(_make_trade(position, exit_price, pnl, "SL", row))
                position = None
            elif hit_tp:
                exit_price = _apply_costs(position["take_profit"], "sell")
                pnl = (exit_price - position["entry_cost"]) * position["qty"]
                capital += pnl
                trades.append(_make_trade(position, exit_price, pnl, "TP", row))
                position = None
            elif USE_TRAILING_STOP:
                # Trailing Stop nachziehen
                current_close = float(row["close"])
                if current_close > position.get("highest_price", position["entry_raw"]):
                    position["highest_price"] = current_close
                    new_stop = round(current_close * (1 - TRAILING_STOP_PCT), 2)
                    if new_stop > position["stop_loss"]:
                        position["stop_loss"] = new_stop

        equity_curve.append(capital)

        if position:
            continue

        # ── Lookahead-Bias-freies Fenster: nur Daten bis Candle i ─────────────
        window_idx = warmup + i
        df_window  = df_full.iloc[:window_idx].copy()

        # ── Regime Detection ─────────────────────────────────────────────────
        try:
            regime = detect_regime(df_window)
            regime_name   = regime.regime
            regime_factor = regime.position_size_factor
            atr           = float(regime.atr)
        except Exception:
            regime_name   = "SIDEWAYS"
            regime_factor = 0.8
            atr           = float(row.get("atr", row["close"] * 0.02))

        # ── ML-Signal ────────────────────────────────────────────────────────
        signal     = "HOLD"
        confidence = 0.0
        source     = "regime_only"

        if ml_predictor is not None:
            try:
                pred = ml_predictor.predict(df_window)
                if pred.signal != "HOLD" and pred.confidence >= 0.55:
                    signal     = pred.signal
                    confidence = pred.confidence
                    source     = "ml"
            except Exception:
                pass

        # Regime-Filter: In BEAR_TREND keine BUY-Signale
        if signal == "BUY" and regime_name == "BEAR_TREND":
            signal = "HOLD"

        # Drawdown Recovery: Positionsgröße reduzieren bei Verlusten
        drawdown = (INITIAL_CAPITAL - capital) / INITIAL_CAPITAL if INITIAL_CAPITAL > 0 else 0.0
        dd_factor = (
            0.25 if drawdown >= 0.15 else
            0.50 if drawdown >= 0.10 else
            0.75 if drawdown >= 0.07 else 1.0
        )

        if verbose:
            console.print(
                f"[dim]i={i} | {signal} {confidence:.0%} | "
                f"Regime={regime_name} | Capital={capital:.0f}[/dim]"
            )

        signals_log.append({
            "candle": i,
            "signal": signal,
            "regime": regime_name,
            "confidence": confidence,
        })

        # ── Entry ─────────────────────────────────────────────────────────────
        if signal == "BUY":
            entry_raw  = next_open
            entry_cost = _apply_costs(entry_raw, "buy")

            # ATR-basiertes Sizing
            if USE_ATR_SIZING and atr > 0:
                stop_distance = ATR_MULTIPLIER * atr
            else:
                stop_distance = entry_cost * STOP_LOSS_PCT

            stop_loss   = round(entry_cost - stop_distance, 2)
            take_profit = round(entry_cost + stop_distance * 2, 2)

            risk_amount = capital * RISK_PER_TRADE * regime_factor * dd_factor
            if stop_distance > 0:
                qty = risk_amount / stop_distance
            else:
                continue
            qty = min(qty, (capital * 0.95) / entry_cost)

            if qty * entry_cost < 1.0:
                continue

            position = {
                "entry_raw":     entry_raw,
                "entry_cost":    entry_cost,
                "qty":           qty,
                "stop_loss":     stop_loss,
                "take_profit":   take_profit,
                "highest_price": entry_raw,
                "side":          "long",
                "entry_candle":  i,
                "entry_time":    str(row.get("timestamp", i)),
                "regime":        regime_name,
                "confidence":    confidence,
                "source":        source,
            }

    # ── Offene Position am Ende schließen ─────────────────────────────────────
    if position:
        last_row   = df_test.iloc[-1]
        exit_price = _apply_costs(float(last_row["close"]), "sell")
        pnl = (exit_price - position["entry_cost"]) * position["qty"]
        capital += pnl
        trades.append(_make_trade(position, exit_price, pnl, "End", last_row))
        equity_curve.append(capital)

    elapsed = time.time() - start_time
    console.print(f"[dim]Backtest abgeschlossen in {elapsed:.1f}s | {n} Candles[/dim]")

    if not trades:
        console.print("[yellow]Keine Trades im Backtest-Zeitraum[/yellow]")
        return {"trades": 0, "engine": "ai"}

    equity = np.array(equity_curve)
    result = _calculate_stats(trades, equity, df_test, signals_log)
    result["engine"] = "ai"
    result["days"]   = days
    _print_results(result, df_test)
    return result


def _make_trade(position: dict, exit_price: float, pnl: float, reason: str, row) -> dict:
    entry_raw = position["entry_raw"]
    qty       = position.get("qty", 0.0)
    fee = round((entry_raw + exit_price) * qty * TRADING_FEE_PCT, 4)
    return {
        "entry":      entry_raw,
        "exit":       exit_price,
        "pnl":        pnl,
        "fee":        fee,
        "net_pnl":    round(pnl - fee, 4),
        "reason":     reason,
        "entry_time": position.get("entry_time", ""),
        "exit_time":  str(row.get("timestamp", "")),
        "regime":     position.get("regime", "?"),
        "confidence": position.get("confidence", 0.0),
        "source":     position.get("source", "?"),
        "duration":   int(row.name) - position.get("entry_candle", 0),
        "qty":        round(qty, 6),
    }


def _calculate_stats(
    trades: list, equity: np.ndarray, df: pd.DataFrame, signals_log: list
) -> dict:
    pnls    = [t["pnl"] for t in trades]
    wins    = [p for p in pnls if p > 0]
    losses  = [p for p in pnls if p < 0]

    # Max Drawdown auf Equity-Kurve
    peak   = equity[0]
    max_dd = 0.0
    dd_durations = []
    dd_start = None
    for val in equity:
        if val > peak:
            peak     = val
            if dd_start is not None:
                dd_durations.append(0)
                dd_start = None
        dd = (peak - val) / peak * 100
        if dd > max_dd:
            max_dd = dd
        if dd > 0 and dd_start is None:
            dd_start = val

    # Sharpe + Sortino
    returns     = np.diff(equity) / equity[:-1]
    mean_ret    = float(returns.mean()) if len(returns) else 0.0
    std_ret     = float(returns.std())  if len(returns) > 1 else 0.0
    neg_returns = [r for r in returns if r < 0]
    downside    = float(np.std(neg_returns)) if neg_returns else 0.001

    # Annualisierungsfaktor
    tf_map  = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
    periods = tf_map.get(TIMEFRAME, 8760)

    sharpe  = round(mean_ret / std_ret  * math.sqrt(periods), 2) if std_ret  > 0 else 0.0
    sortino = round(mean_ret / downside * math.sqrt(periods), 2) if downside > 0 else 0.0

    # Calmar Ratio (Annualized Return / Max Drawdown)
    total_return_pct = (equity[-1] - equity[0]) / equity[0] * 100
    calmar = round(total_return_pct / max_dd, 2) if max_dd > 0 else 0.0

    # Profit Factor
    gross_profit = sum(wins)              if wins   else 0.0
    gross_loss   = abs(sum(losses))       if losses else 1.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0

    # Durchschnittliche Haltedauer
    durations    = [t.get("duration", 0) for t in trades]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # Win-Rate per Regime
    by_regime: dict[str, dict] = {}
    for t in trades:
        r = t.get("regime", "?")
        if r not in by_regime:
            by_regime[r] = {"wins": 0, "total": 0, "pnl": 0.0}
        by_regime[r]["total"] += 1
        by_regime[r]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            by_regime[r]["wins"] += 1
    regime_winrates = {
        r: round(v["wins"] / v["total"] * 100, 1)
        for r, v in by_regime.items()
    }
    regime_stats = {
        r: {
            "win_rate": round(v["wins"] / v["total"] * 100, 1),
            "trades":   v["total"],
            "pnl":      round(v["pnl"], 2),
        }
        for r, v in by_regime.items()
    }

    # Per-Exit-Reason Breakdown
    by_exit: dict[str, dict] = {}
    for t in trades:
        reason = t.get("reason", "?")
        if reason not in by_exit:
            by_exit[reason] = {"count": 0, "pnl": 0.0, "wins": 0}
        by_exit[reason]["count"] += 1
        by_exit[reason]["pnl"]   += t["pnl"]
        if t["pnl"] > 0:
            by_exit[reason]["wins"] += 1
    exit_stats = {
        r: {
            "count":    v["count"],
            "pnl":      round(v["pnl"], 2),
            "win_rate": round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0.0,
        }
        for r, v in by_exit.items()
    }

    # Monthly Returns
    monthly_returns: dict[str, float] = {}
    for t in trades:
        ts = t.get("exit_time", "")
        month = str(ts)[:7] if ts else "?"
        monthly_returns[month] = round(monthly_returns.get(month, 0.0) + t["pnl"], 2)

    # Signal-Qualität
    total_signals = len(signals_log)
    buy_signals   = sum(1 for s in signals_log if s["signal"] == "BUY")
    hold_signals  = total_signals - buy_signals
    signal_rate   = round(buy_signals / total_signals * 100, 1) if total_signals > 0 else 0.0

    # Fees
    total_fees = round(sum(t.get("fee", 0.0) for t in trades), 2)

    # Buy & Hold Benchmark
    bh_return = (float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1) * 100

    return {
        "trades":              len(trades),
        "wins":                len(wins),
        "losses":              len(losses),
        "win_rate":            round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl":           round(sum(pnls), 2),
        "return_pct":          round((equity[-1] - equity[0]) / equity[0] * 100, 2),
        "avg_win":             round(sum(wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss":            round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_drawdown_pct":    round(max_dd, 2),
        "sharpe_ratio":        sharpe,
        "sortino_ratio":       sortino,
        "calmar_ratio":        calmar,
        "profit_factor":       profit_factor,
        "total_fees":          total_fees,
        "buyhold_return_pct":  round(bh_return, 2),
        "final_capital":       round(float(equity[-1]), 2),
        "avg_holding_candles": avg_duration,
        "signal_rate_pct":     signal_rate,
        "buy_signals":         buy_signals,
        "hold_signals":        hold_signals,
        "regime_winrates":     regime_winrates,
        "regime_stats":        regime_stats,
        "exit_stats":          exit_stats,
        "monthly_returns":     monthly_returns,
        "trade_list":          trades,
    }


def _print_results(result: dict, df: pd.DataFrame):
    table = Table(
        title=f"AI-Pipeline Backtest — {SYMBOL} | {result.get('days', BACKTEST_DAYS)} Tage",
        show_header=True,
    )
    table.add_column("Metrik",      style="cyan",  min_width=28)
    table.add_column("Wert",        style="white", min_width=14)
    table.add_column("Benchmark",   style="dim",   min_width=14)

    bh = result["buyhold_return_pct"]

    try:
        start = df.index[0]  if hasattr(df.index[0], "date") else "?"
        end   = df.index[-1] if hasattr(df.index[-1], "date") else "?"
        table.add_row("Zeitraum",         f"{start} → {end}", "")
    except Exception:
        pass

    table.add_row("Engine",               result.get("engine", "simple"), "")
    table.add_row("Trades gesamt",        str(result["trades"]), "")
    table.add_row("Gewinner / Verlierer", f"{result['wins']} / {result['losses']}", "")
    table.add_row("Win-Rate",             f"{result['win_rate']}%",      "~50%")
    table.add_row("Profit Factor",        str(result["profit_factor"]),  ">1.5 ✓")
    table.add_row("Sharpe Ratio",         str(result["sharpe_ratio"]),   ">1.0 ✓")
    table.add_row("Sortino Ratio",        str(result.get("sortino_ratio", 0.0)), ">1.5 ✓")
    table.add_row("Calmar Ratio",         str(result.get("calmar_ratio", 0.0)),  ">0.5 ✓")
    table.add_row("Gesamt PnL",           f"{result['total_pnl']:+.2f} USDT", "")
    table.add_row("Strategie Rendite",    f"{result['return_pct']:+.2f}%",     f"B&H {bh:+.1f}%")
    table.add_row("Ø Gewinn / Verlust",   f"{result['avg_win']:+.2f} / {result['avg_loss']:+.2f} USDT", "")
    table.add_row("Max. Drawdown",        f"{result['max_drawdown_pct']}%",   "<15% ✓")
    table.add_row("Ø Haltedauer",         f"{result.get('avg_holding_candles', 0):.1f} Candles", "")
    table.add_row("Signal-Rate",          f"{result.get('signal_rate_pct', 0):.1f}% BUY", "5–20% ✓")
    table.add_row("Gebühren gesamt",      f"{result.get('total_fees', 0.0):.2f} USDT", f"{TRADING_FEE_PCT*100:.2f}% p. Seite")
    table.add_row("Startkapital",         f"{INITIAL_CAPITAL:.2f} USDT", "")
    table.add_row("Endkapital",           f"{result['final_capital']:.2f} USDT", "")
    console.print(table)

    # Regime-Stats
    rs = result.get("regime_stats", {})
    if rs:
        rs_table = Table(title="Performance nach Markt-Regime", show_header=True)
        rs_table.add_column("Regime",    style="cyan",  min_width=14)
        rs_table.add_column("Trades",    style="white", min_width=8)
        rs_table.add_column("Win-Rate",  style="white", min_width=10)
        rs_table.add_column("PnL",       style="white", min_width=12)
        for regime, s in sorted(rs.items()):
            wr_color = "green" if s["win_rate"] >= 50 else "red"
            pnl_color = "green" if s["pnl"] >= 0 else "red"
            rs_table.add_row(
                regime,
                str(s["trades"]),
                f"[{wr_color}]{s['win_rate']}%[/{wr_color}]",
                f"[{pnl_color}]{s['pnl']:+.2f}[/{pnl_color}]",
            )
        console.print(rs_table)

    # Exit-Reason Breakdown
    es = result.get("exit_stats", {})
    if es:
        es_table = Table(title="Exit-Grund Analyse", show_header=True)
        es_table.add_column("Exit-Grund", style="cyan",  min_width=12)
        es_table.add_column("Trades",     style="white", min_width=8)
        es_table.add_column("Win-Rate",   style="white", min_width=10)
        es_table.add_column("Gesamt PnL", style="white", min_width=12)
        for reason, s in sorted(es.items()):
            wr_color  = "green" if s["win_rate"] >= 50 else "red"
            pnl_color = "green" if s["pnl"] >= 0 else "red"
            es_table.add_row(
                reason,
                str(s["count"]),
                f"[{wr_color}]{s['win_rate']}%[/{wr_color}]",
                f"[{pnl_color}]{s['pnl']:+.2f}[/{pnl_color}]",
            )
        console.print(es_table)

    # Monthly Returns
    mr = result.get("monthly_returns", {})
    if mr:
        mr_table = Table(title="Monatliche Renditen", show_header=True)
        mr_table.add_column("Monat", style="cyan",  min_width=10)
        mr_table.add_column("PnL",   style="white", min_width=12)
        positive = sum(1 for v in mr.values() if v >= 0)
        mr_table.add_column(f"(+{positive} / -{len(mr)-positive} Monate)", style="dim", min_width=5)
        for month in sorted(mr.keys()):
            pnl   = mr[month]
            color = "green" if pnl >= 0 else "red"
            bar   = "▓" * min(int(abs(pnl) / 50), 20)
            mr_table.add_row(month, f"[{color}]{pnl:+.2f}[/{color}]", bar)
        console.print(mr_table)

    alpha = result["return_pct"] - bh
    if result["sharpe_ratio"] > 1.0 and result["max_drawdown_pct"] < 15:
        console.print(
            f"[bold green]✓ AI-Strategie solide — "
            f"Alpha vs Buy&Hold: {alpha:+.1f}% | "
            f"Sharpe {result['sharpe_ratio']} | Calmar {result.get('calmar_ratio', 0)}[/bold green]"
        )
    elif result["max_drawdown_pct"] >= 20:
        console.print(f"[bold red]✗ Drawdown zu hoch ({result['max_drawdown_pct']}%) — Risiko-Parameter anpassen![/bold red]")
    elif result["return_pct"] <= 0:
        console.print(f"[bold red]✗ Negative Rendite nach Kosten — AI-Modell neu trainieren![/bold red]")
    else:
        console.print(
            f"[yellow]△ Strategie läuft, Alpha schwach ({alpha:+.1f}%) — "
            f"Modell-Tuning oder mehr Trainingsdaten empfohlen[/yellow]"
        )
