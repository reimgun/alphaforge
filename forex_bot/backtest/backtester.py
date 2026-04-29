"""
Forex Backtester.

Loads historical H1 candles from OANDA (up to 5000 per instrument),
simulates the bot cycle with realistic spread modelling.

Usage:
    python -m forex_bot.backtest.backtester
    python -m forex_bot.backtest.backtester --instrument EUR_USD --candles 2000

Output:
  - Total trades, win rate, total pips, Sharpe ratio
  - Max drawdown
  - Per-month breakdown
  - Saves report to forex_bot/reports/backtest_YYYYMMDD_HHMMSS.json
"""
import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

REPORTS_DIR = Path(__file__).parent.parent / "reports"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    df["ema_fast"]  = _ema(df["close"], 20)
    df["ema_slow"]  = _ema(df["close"], 50)
    df["ema_trend"] = _ema(df["close"], 200)

    delta   = df["close"].diff()
    gain    = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss    = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

    prev = df["close"].shift(1)
    tr   = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"]  - prev).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()

    ema12      = _ema(df["close"], 12)
    ema26      = _ema(df["close"], 26)
    macd       = ema12 - ema26
    macd_sig   = macd.ewm(span=9, adjust=False).mean()
    df["macd_h"] = macd - macd_sig

    df["bb_mid"]   = df["close"].rolling(20).mean()
    df["bb_std"]   = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    return df


def _generate_signal(row: pd.Series, prev: pd.Series, instrument: str) -> tuple[str, float]:
    """
    Replicates forex_strategy.generate_signal() logic for backtesting.

    Returns (direction, confidence) where direction is "BUY", "SELL", or "HOLD".
    """
    bull_trend = (row.ema_fast > row.ema_slow > row.ema_trend)
    bear_trend = (row.ema_fast < row.ema_slow < row.ema_trend)
    bull_cross = (prev.ema_fast <= prev.ema_slow) and (row.ema_fast > row.ema_slow)
    bear_cross = (prev.ema_fast >= prev.ema_slow) and (row.ema_fast < row.ema_slow)
    macd_bull  = (row.macd_h > 0) and (row.macd_h > prev.macd_h)
    macd_bear  = (row.macd_h < 0) and (row.macd_h < prev.macd_h)
    rsi_buy    = 40 < row.rsi < 65
    rsi_sell   = 35 < row.rsi < 60

    if bull_trend and bull_cross and macd_bull and rsi_buy:
        conf = 0.55
        if row.rsi < 55:    conf += 0.10
        if row.close > row.bb_mid: conf += 0.05
        return "BUY", round(min(conf, 1.0), 2)

    if bear_trend and bear_cross and macd_bear and rsi_sell:
        conf = 0.55
        if row.rsi > 45:    conf += 0.10
        if row.close < row.bb_mid: conf += 0.05
        return "SELL", round(min(conf, 1.0), 2)

    return "HOLD", 0.0


# ── Main backtest ─────────────────────────────────────────────────────────────

def run_backtest(
    instrument:  str   = "EUR_USD",
    n_candles:   int   = 2000,
    spread_pips: float = 0.8,
    risk_mode:   str   = "balanced",
) -> dict:
    """
    Walk-forward simulation on H1 candles.

    For each candle (starting after indicator warm-up at index 210):
      1. Generate signal from candles[0:i]
      2. If signal meets confidence threshold, simulate trade
      3. Scan forward candles to determine SL or TP hit (no look-ahead)
      4. Account for spread on entry

    Parameters
    ----------
    instrument:  OANDA instrument, e.g. "EUR_USD"
    n_candles:   number of H1 candles to fetch
    spread_pips: simulated half-spread added to entry on BUY (or subtracted on SELL)
    risk_mode:   "conservative" | "balanced" | "aggressive"

    Returns
    -------
    dict with keys: trades, win_rate, total_pips, sharpe, max_drawdown,
                    profit_factor, per_month, instrument, risk_mode
    """
    from forex_bot.config import settings as cfg
    from forex_bot.execution.oanda_client import OandaClient
    from forex_bot.risk.risk_modes import get_mode

    mode = get_mode(risk_mode)

    client = OandaClient(cfg.OANDA_API_KEY, cfg.OANDA_ACCOUNT_ID, cfg.OANDA_ENV)

    log.info(f"Backtesting {instrument} — fetching {n_candles} H1 candles...")
    raw = client.get_candles(instrument, "H1", count=min(n_candles, 5000))

    if len(raw) < 250:
        raise ValueError(f"Not enough candles for backtest: {len(raw)} (need ≥ 250)")

    df = pd.DataFrame(raw)
    df = _compute_indicators(df)
    df = df.reset_index(drop=True)

    pip_size       = 0.01 if "JPY" in instrument else 0.0001
    spread_price   = spread_pips * pip_size
    atr_multiplier = mode.atr_multiplier
    rr_ratio       = mode.rr_ratio
    min_confidence = mode.min_confidence

    trade_results: list[dict] = []
    in_trade      = False
    n             = len(df)
    warmup        = 210  # need EMA200 + margin

    for i in range(warmup, n - 1):
        if in_trade:
            continue  # one trade at a time for simplicity

        row  = df.iloc[i]
        prev = df.iloc[i - 1]

        if pd.isna(row.atr) or row.atr <= 0:
            continue

        direction, confidence = _generate_signal(row, prev, instrument)

        if direction == "HOLD" or confidence < min_confidence:
            continue

        # Entry price including spread
        entry = float(row.close)
        if direction == "BUY":
            entry += spread_price / 2   # pay spread on entry
        else:
            entry -= spread_price / 2

        sl_dist = float(row.atr) * atr_multiplier
        tp_dist = sl_dist * rr_ratio

        if direction == "BUY":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        # Walk forward to find SL or TP hit
        result_pips = None
        exit_idx    = None
        for j in range(i + 1, min(i + 1 + 48, n)):
            fut = df.iloc[j]
            h   = float(fut.high)
            l   = float(fut.low)

            if direction == "BUY":
                if l <= sl:
                    result_pips = (sl - entry) / pip_size
                    exit_idx = j
                    break
                if h >= tp:
                    result_pips = (tp - entry) / pip_size
                    exit_idx = j
                    break
            else:
                if h >= sl:
                    result_pips = (entry - sl) / pip_size
                    exit_idx = j
                    break
                if l <= tp:
                    result_pips = (entry - tp) / pip_size
                    exit_idx = j
                    break

        if result_pips is None:
            # Trade not resolved within 48 candles — close at last candle price
            last_close = float(df.iloc[min(i + 48, n - 1)].close)
            if direction == "BUY":
                result_pips = (last_close - entry) / pip_size
            else:
                result_pips = (entry - last_close) / pip_size
            exit_idx = min(i + 48, n - 1)

        # Get the candle timestamp for the entry
        entry_time = df.iloc[i].get("time", "") if "time" in df.columns else ""
        month_key  = str(entry_time)[:7] if entry_time else "unknown"  # "YYYY-MM"

        trade_results.append({
            "entry_idx":   i,
            "exit_idx":    exit_idx,
            "direction":   direction,
            "confidence":  confidence,
            "entry":       round(entry, 5),
            "sl":          round(sl, 5),
            "tp":          round(tp, 5),
            "pnl_pips":    round(result_pips, 2),
            "won":         result_pips > 0,
            "month":       month_key,
        })

        # Prevent overlapping trades: advance past exit
        in_trade = False

    # ── Compute aggregate metrics ─────────────────────────────────────────────
    if not trade_results:
        return {
            "instrument": instrument, "risk_mode": risk_mode,
            "trades": 0, "win_rate": 0.0, "total_pips": 0.0,
            "sharpe": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0,
            "per_month": {},
        }

    pips_seq   = [t["pnl_pips"] for t in trade_results]
    wins       = [t for t in trade_results if t["won"]]
    win_rate   = round(len(wins) / len(trade_results) * 100, 1)
    total_pips = round(sum(pips_seq), 2)

    # Sharpe (annualised from hourly pip sequence)
    arr    = np.array(pips_seq, dtype=float)
    mean_p = float(arr.mean())
    std_p  = float(arr.std())
    sharpe = round(mean_p / (std_p + 1e-10) * (252 ** 0.5), 2) if std_p > 0 else 0.0

    # Max drawdown (pip-based)
    cumulative = np.cumsum(arr)
    peak       = np.maximum.accumulate(cumulative)
    drawdowns  = (peak - cumulative) / (np.abs(peak) + 1e-10) * 100
    max_dd     = round(float(drawdowns.max()), 2)

    # Profit factor
    gross_profit = sum(p for p in pips_seq if p > 0)
    gross_loss   = abs(sum(p for p in pips_seq if p < 0))
    profit_factor = round(gross_profit / (gross_loss + 1e-10), 2)

    # Per-month breakdown
    per_month: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pips": 0.0, "wins": 0})
    for t in trade_results:
        m = t["month"]
        per_month[m]["trades"] += 1
        per_month[m]["pips"]   += t["pnl_pips"]
        if t["won"]:
            per_month[m]["wins"] += 1

    per_month_clean = {
        m: {
            "trades":   v["trades"],
            "pips":     round(v["pips"], 2),
            "win_rate": round(v["wins"] / v["trades"] * 100, 1),
        }
        for m, v in sorted(per_month.items())
    }

    return {
        "instrument":    instrument,
        "risk_mode":     risk_mode,
        "n_candles":     len(df),
        "spread_pips":   spread_pips,
        "trades":        len(trade_results),
        "win_rate":      win_rate,
        "total_pips":    total_pips,
        "sharpe":        sharpe,
        "max_drawdown":  max_dd,
        "profit_factor": profit_factor,
        "per_month":     per_month_clean,
        "run_at":        datetime.now(timezone.utc).isoformat(),
    }


def run_multi_pair_backtest(
    instruments: list[str]  | None = None,
    n_candles:   int               = 2000,
    spread_pips: float             = 0.8,
    risk_mode:   str               = "balanced",
) -> dict:
    """
    Multi-Pair Robustness Test — Feature 6.

    Runs run_backtest() for each instrument independently, then computes
    portfolio-level aggregates (assuming equal capital allocation).

    Parameters
    ----------
    instruments: list of OANDA instruments; defaults to cfg.INSTRUMENTS
    n_candles:   candles per instrument
    spread_pips: simulated spread per instrument
    risk_mode:   risk mode to test

    Returns
    -------
    dict with:
      per_pair  — {instrument: backtest_result}
      portfolio — aggregate stats (avg win_rate, total_pips, combined sharpe, etc.)
      run_at    — ISO timestamp
    """
    from forex_bot.config import settings as cfg

    if instruments is None:
        instruments = cfg.INSTRUMENTS

    per_pair: dict[str, dict] = {}
    all_pips: list[float]     = []

    for instr in instruments:
        try:
            result = run_backtest(instr, n_candles, spread_pips, risk_mode)
            per_pair[instr] = result
            all_pips.extend([
                t for t in ([result.get("total_pips", 0.0)] if result.get("trades", 0) > 0 else [])
            ])
            log.info(
                f"Multi-pair {instr}: trades={result.get('trades', 0)}, "
                f"wr={result.get('win_rate', 0):.1f}%, "
                f"pips={result.get('total_pips', 0):+.1f}"
            )
        except Exception as e:
            log.warning(f"Multi-pair backtest failed for {instr}: {e}")
            per_pair[instr] = {"instrument": instr, "error": str(e)}

    valid = [v for v in per_pair.values() if "error" not in v and v.get("trades", 0) > 0]
    if not valid:
        portfolio = {"error": "No valid backtest results"}
    else:
        avg_wr         = round(sum(v["win_rate"]     for v in valid) / len(valid), 1)
        total_pips_sum = round(sum(v["total_pips"]   for v in valid), 2)
        avg_sharpe     = round(sum(v["sharpe"]        for v in valid) / len(valid), 2)
        avg_dd         = round(sum(v["max_drawdown"]  for v in valid) / len(valid), 2)
        avg_pf         = round(sum(v["profit_factor"] for v in valid) / len(valid), 2)
        total_trades   = sum(v["trades"] for v in valid)
        pairs_tested   = len(valid)
        pairs_positive = sum(1 for v in valid if v["total_pips"] > 0)

        portfolio = {
            "pairs_tested":    pairs_tested,
            "pairs_positive":  pairs_positive,
            "total_trades":    total_trades,
            "avg_win_rate":    avg_wr,
            "total_pips":      total_pips_sum,
            "avg_sharpe":      avg_sharpe,
            "avg_max_drawdown": avg_dd,
            "avg_profit_factor": avg_pf,
            "robustness_score": round(pairs_positive / pairs_tested * 100, 1),
        }
        log.info(
            f"Multi-pair portfolio: {pairs_positive}/{pairs_tested} profitable, "
            f"avg WR={avg_wr}%, avg Sharpe={avg_sharpe}"
        )

    return {
        "per_pair":  per_pair,
        "portfolio": portfolio,
        "risk_mode": risk_mode,
        "run_at":    datetime.now(timezone.utc).isoformat(),
    }


def print_multi_report(results: dict):
    """Print a formatted multi-pair backtest report to console."""
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  MULTI-PAIR BACKTEST REPORT")
    print(sep)
    portfolio = results.get("portfolio", {})
    if "error" not in portfolio:
        print(f"  Pairs tested:    {portfolio.get('pairs_tested', 0)}")
        print(f"  Profitable pairs:{portfolio.get('pairs_positive', 0)}")
        print(f"  Robustness:      {portfolio.get('robustness_score', 0):.0f}%")
        print(f"  Total trades:    {portfolio.get('total_trades', 0)}")
        print(f"  Avg Win Rate:    {portfolio.get('avg_win_rate', 0):.1f}%")
        print(f"  Total Pips:      {portfolio.get('total_pips', 0):+.1f}")
        print(f"  Avg Sharpe:      {portfolio.get('avg_sharpe', 0):.2f}")
        print(f"  Avg Max DD:      {portfolio.get('avg_max_drawdown', 0):.1f}%")
        print(f"  Avg PF:          {portfolio.get('avg_profit_factor', 0):.2f}")

    print(f"\n  {'Pair':<12} {'Trades':>7} {'WR%':>7} {'Pips':>9} {'Sharpe':>8}")
    print(f"  {'─'*12} {'─'*7} {'─'*7} {'─'*9} {'─'*8}")
    for instr, data in sorted(results.get("per_pair", {}).items()):
        if "error" in data:
            print(f"  {instr:<12}  ERROR: {data['error']}")
        else:
            print(
                f"  {instr:<12} {data.get('trades', 0):>7} "
                f"{data.get('win_rate', 0):>7.1f} "
                f"{data.get('total_pips', 0):>+9.1f} "
                f"{data.get('sharpe', 0):>8.2f}"
            )
    print(sep)


def print_report(results: dict):
    """Print a formatted backtest report to console."""
    sep = "─" * 50
    print(f"\n{sep}")
    print(f"  FOREX BACKTEST REPORT")
    print(sep)
    print(f"  Instrument:    {results.get('instrument', '?')}")
    print(f"  Risk Mode:     {results.get('risk_mode', '?')}")
    print(f"  Candles used:  {results.get('n_candles', '?')}")
    print(f"  Spread:        {results.get('spread_pips', '?')} pips")
    print(sep)
    print(f"  Trades:        {results.get('trades', 0)}")
    print(f"  Win Rate:      {results.get('win_rate', 0):.1f}%")
    print(f"  Total Pips:    {results.get('total_pips', 0):+.1f}")
    print(f"  Sharpe Ratio:  {results.get('sharpe', 0):.2f}")
    print(f"  Max Drawdown:  {results.get('max_drawdown', 0):.1f}%")
    print(f"  Profit Factor: {results.get('profit_factor', 0):.2f}")

    per_month = results.get("per_month", {})
    if per_month:
        print(f"\n  {'Month':<10} {'Trades':>7} {'Pips':>9} {'WinRate':>9}")
        print(f"  {'-'*10} {'-'*7} {'-'*9} {'-'*9}")
        for month, data in sorted(per_month.items()):
            print(
                f"  {month:<10} {data['trades']:>7} "
                f"{data['pips']:>+9.1f} {data['win_rate']:>8.1f}%"
            )
    print(sep)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Forex Backtester")
    parser.add_argument("--instrument", default="EUR_USD",
                        help="OANDA instrument (ignored when --multi is set)")
    parser.add_argument("--candles",    type=int, default=2000, help="Number of H1 candles")
    parser.add_argument("--spread",     type=float, default=0.8, help="Spread in pips")
    parser.add_argument("--mode",       default="balanced",  help="Risk mode")
    parser.add_argument("--multi",      action="store_true",
                        help="Run multi-pair robustness test across all configured instruments")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.multi:
        results     = run_multi_pair_backtest(
            n_candles=   args.candles,
            spread_pips= args.spread,
            risk_mode=   args.mode,
        )
        print_multi_report(results)
        report_path = REPORTS_DIR / f"backtest_multi_{timestamp}.json"
    else:
        results = run_backtest(
            instrument=  args.instrument,
            n_candles=   args.candles,
            spread_pips= args.spread,
            risk_mode=   args.mode,
        )
        print_report(results)
        report_path = REPORTS_DIR / f"backtest_{timestamp}.json"

    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport saved: {report_path}")
