"""
Performance Report Generator — Monatlicher Handelsbericht.

Erstellt strukturierten Text-Report (NAS-kompatibel, kein PDF/Browser nötig):
  - Equity-Kurve (ASCII)
  - Trade-Statistiken (gesamt + pro Pair + pro Strategie)
  - Session-Performance (London / NY / Asian / Overlap)
  - Drawdown-Analyse
  - Regime-Performance
  - Monte-Carlo-Robustheit (wenn aktiviert)

Ausgabe: reports/forex_report_YYYY-MM.txt

Usage:
    from forex_bot.reporting.report_generator import generate_monthly_report
    path = generate_monthly_report()
    print(f"Report gespeichert: {path}")

CLI:
    python -m forex_bot.reporting.report_generator
    python -m forex_bot.reporting.report_generator --month 2025-11
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("forex_bot")

ROOT        = Path(__file__).parent.parent.parent
REPORTS_DIR = ROOT / "reports"


# ── ASCII Equity Curve ────────────────────────────────────────────────────────

def _ascii_equity(equity_values: list[float], width: int = 60, height: int = 12) -> str:
    """Rendert eine simple ASCII Equity-Kurve."""
    if not equity_values or len(equity_values) < 2:
        return "  [Keine Equity-Daten]"

    mn = min(equity_values)
    mx = max(equity_values)
    r  = mx - mn
    if r < 1e-6:
        r = 1.0

    # Downsample auf width Datenpunkte
    n      = len(equity_values)
    step   = max(1, n // width)
    sampled = [equity_values[i] for i in range(0, n, step)]
    if sampled[-1] != equity_values[-1]:
        sampled.append(equity_values[-1])

    # Grid aufbauen
    grid = [[" "] * len(sampled) for _ in range(height)]
    for col, val in enumerate(sampled):
        row = height - 1 - int((val - mn) / r * (height - 1))
        row = max(0, min(height - 1, row))
        grid[row][col] = "█"

    lines  = []
    start  = sampled[0]
    end    = sampled[-1]
    change = ((end - start) / start * 100) if start > 0 else 0.0

    lines.append(f"  ${mx:>10,.2f} ┐")
    for i, row in enumerate(grid):
        prefix = "  " + " " * 12 + "│"
        lines.append(prefix + "".join(row))
    lines.append(f"  ${mn:>10,.2f} └" + "─" * len(sampled))
    lines.append(f"  Start: ${start:,.2f}  →  Ende: ${end:,.2f}  ({change:+.1f}%)")
    return "\n".join(lines)


# ── Statistics Helpers ────────────────────────────────────────────────────────

def _sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    import math
    mean = sum(pnls) / len(pnls)
    std  = (sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)) ** 0.5
    return round(mean / std * math.sqrt(252), 3) if std > 0 else 0.0


def _max_drawdown(pnls: list[float], initial: float = 10000.0) -> float:
    eq     = initial
    peak   = initial
    max_dd = 0.0
    for p in pnls:
        eq    += p
        peak   = max(peak, eq)
        dd     = (peak - eq) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def _profit_factor(pnls: list[float]) -> float:
    wins   = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    return round(wins / losses, 3) if losses > 0 else (1.5 if wins > 0 else 0.0)


# ── Session Labeling ──────────────────────────────────────────────────────────

def _session_label(hour_utc: int | None) -> str:
    if hour_utc is None:
        return "Unknown"
    if 13 <= hour_utc < 16:
        return "London/NY Overlap"
    if 7 <= hour_utc < 13:
        return "London"
    if 16 <= hour_utc < 21:
        return "New York"
    return "Asian"


# ── Report Builder ────────────────────────────────────────────────────────────

def _build_report(
    trades:          list[dict],
    month_label:     str,
    initial_capital: float = 10000.0,
) -> str:
    lines = []
    sep   = "═" * 68

    lines.append(sep)
    lines.append(f"  FOREX BOT — PERFORMANCE REPORT  {month_label}")
    lines.append(f"  Generiert: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(sep)

    if not trades:
        lines.append("\n  Keine abgeschlossenen Trades im Berichtszeitraum.\n")
        return "\n".join(lines)

    pnls     = [t.get("pnl", 0.0) for t in trades]
    pips     = [t.get("pnl_pips", 0.0) for t in trades]
    wins     = [p for p in pnls if p > 0]
    losses   = [p for p in pnls if p < 0]
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    total_pnl = sum(pnls)

    # ── Gesamt-Statistiken ────────────────────────────────────────────────────
    lines.append("\n  GESAMT\n  " + "─" * 40)
    lines.append(f"  Trades gesamt:     {len(trades):>8}")
    lines.append(f"  Gewinner:          {len(wins):>8}  ({win_rate:.1%})")
    lines.append(f"  Verlierer:         {len(losses):>8}")
    lines.append(f"  Gesamt-PnL:       ${total_pnl:>+10,.2f}")
    lines.append(f"  Gesamt-Pips:      {sum(pips):>+10.1f}")
    lines.append(f"  Ø Gewinn:         ${sum(wins)/len(wins):>+10,.2f}" if wins else "  Ø Gewinn:         N/A")
    lines.append(f"  Ø Verlust:        ${sum(losses)/len(losses):>+10,.2f}" if losses else "  Ø Verlust:         N/A")
    lines.append(f"  Profit Factor:     {_profit_factor(pnls):>8.3f}")
    lines.append(f"  Sharpe Ratio:      {_sharpe(pnls):>8.3f}")
    lines.append(f"  Max Drawdown:      {_max_drawdown(pnls, initial_capital):>8.1%}")

    # ── Equity-Kurve ──────────────────────────────────────────────────────────
    equity = [initial_capital]
    for p in pnls:
        equity.append(equity[-1] + p)

    lines.append("\n  EQUITY-KURVE\n  " + "─" * 40)
    lines.append(_ascii_equity(equity))

    # ── Pro Pair ───────────────────────────────────────────────────────────────
    by_pair: dict[str, list[float]] = {}
    for t in trades:
        instr = t.get("instrument", "?")
        by_pair.setdefault(instr, []).append(t.get("pnl", 0.0))

    lines.append("\n  PRO PAIR\n  " + "─" * 40)
    lines.append(f"  {'Pair':<14} {'Trades':>7} {'Win%':>7} {'PnL':>10} {'Sharpe':>8}")
    lines.append("  " + "─" * 50)
    for pair, ppnls in sorted(by_pair.items(), key=lambda x: -sum(x[1])):
        wrate = sum(1 for p in ppnls if p > 0) / len(ppnls)
        lines.append(
            f"  {pair:<14} {len(ppnls):>7} {wrate:>7.1%} "
            f"${sum(ppnls):>+9,.2f} {_sharpe(ppnls):>7.3f}"
        )

    # ── Pro Strategie ──────────────────────────────────────────────────────────
    by_strategy: dict[str, list[float]] = {}
    for t in trades:
        strat = t.get("strategy", t.get("reason", "unknown"))[:20]
        by_strategy.setdefault(strat, []).append(t.get("pnl", 0.0))

    if any(k != "unknown" for k in by_strategy):
        lines.append("\n  PRO STRATEGIE\n  " + "─" * 40)
        lines.append(f"  {'Strategie':<22} {'Trades':>7} {'Win%':>7} {'PnL':>10}")
        lines.append("  " + "─" * 50)
        for strat, spnls in sorted(by_strategy.items(), key=lambda x: -sum(x[1])):
            wrate = sum(1 for p in spnls if p > 0) / len(spnls)
            lines.append(
                f"  {strat:<22} {len(spnls):>7} {wrate:>7.1%} ${sum(spnls):>+9,.2f}"
            )

    # ── Pro Session ───────────────────────────────────────────────────────────
    by_session: dict[str, list[float]] = {}
    for t in trades:
        opened_at = t.get("opened_at", "")
        try:
            if isinstance(opened_at, str):
                hour = int(opened_at[11:13]) if len(opened_at) > 12 else None
            elif hasattr(opened_at, "hour"):
                hour = opened_at.hour
            else:
                hour = None
        except Exception:
            hour = None
        sess = _session_label(hour)
        by_session.setdefault(sess, []).append(t.get("pnl", 0.0))

    lines.append("\n  PRO SESSION\n  " + "─" * 40)
    for sess, spnls in sorted(by_session.items(), key=lambda x: -sum(x[1])):
        wrate = sum(1 for p in spnls if p > 0) / len(spnls)
        lines.append(
            f"  {sess:<22} {len(spnls):>4} Trades | "
            f"WR {wrate:.1%} | PnL ${sum(spnls):+,.2f}"
        )

    # ── Tages-Breakdown ────────────────────────────────────────────────────────
    dow_map  = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    by_dow: dict[str, list[float]] = {}
    for t in trades:
        opened_at = t.get("opened_at", "")
        try:
            if isinstance(opened_at, str):
                from datetime import datetime as _dt
                dt  = _dt.fromisoformat(opened_at.replace("Z", "+00:00"))
                dow = dow_map.get(dt.weekday(), "?")
            else:
                dow = "?"
        except Exception:
            dow = "?"
        by_dow.setdefault(dow, []).append(t.get("pnl", 0.0))

    lines.append("\n  PRO WOCHENTAG\n  " + "─" * 40)
    for dow in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        dpnls = by_dow.get(dow, [])
        if not dpnls:
            continue
        wrate = sum(1 for p in dpnls if p > 0) / len(dpnls)
        lines.append(
            f"  {dow}:  {len(dpnls):>3} Trades | WR {wrate:.1%} | PnL ${sum(dpnls):+,.2f}"
        )

    lines.append("\n" + sep + "\n")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_monthly_report(
    month:           str | None = None,   # "YYYY-MM" oder None für aktuellen Monat
    initial_capital: float      = 10000.0,
    save:            bool       = True,
) -> Path | None:
    """
    Generiert monatlichen Performance-Report.

    Parameters
    ----------
    month:           "2025-11" oder None (= aktueller Monat)
    initial_capital: Startkapital für Drawdown-Berechnung
    save:            True = Datei in reports/ speichern

    Returns
    -------
    Path zur Report-Datei oder None bei Fehler
    """
    try:
        from forex_bot.monitoring.logger import get_recent_trades
    except ImportError:
        log.error("Logger-Modul nicht verfügbar")
        return None

    now          = datetime.now(timezone.utc)
    month_label  = month or now.strftime("%Y-%m")

    try:
        # Alle verfügbaren Trades laden und nach Monat filtern
        all_trades = get_recent_trades(2000)
        if month:
            filtered = [
                t for t in all_trades
                if str(t.get("opened_at", "")).startswith(month)
            ]
        else:
            filtered = all_trades   # Aktueller Monat ist bereits recent

        report_text = _build_report(filtered, month_label, initial_capital)

        if save:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            fname = REPORTS_DIR / f"forex_report_{month_label}.txt"
            fname.write_text(report_text, encoding="utf-8")
            log.info(f"Report gespeichert: {fname}")
            return fname

        print(report_text)
        return None

    except Exception as e:
        log.error(f"Report generation: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Forex Performance Report")
    parser.add_argument("--month", type=str, default=None, help="Monat (YYYY-MM)")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Nur ausgeben, nicht speichern")
    args = parser.parse_args()

    path = generate_monthly_report(
        month=args.month,
        save=not args.print_only,
    )
    if path:
        print(f"Report: {path}")
        sys.exit(0)
    else:
        sys.exit(1)
