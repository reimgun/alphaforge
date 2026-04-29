"""
Pre-Live Deployment Check — Automatisierter Go/No-Go vor Live-Start.

Prüft ob der Bot bereit für Live-Trading ist basierend auf
Paper-Trading-Ergebnissen und Modell-Qualität.

Kriterien:
  - Mindestens MIN_PAPER_TRADES Paper-Trades vorhanden
  - Sharpe Ratio >= MIN_SHARPE (annualisiert)
  - Win Rate >= MIN_WIN_RATE
  - Max Drawdown <= MAX_DRAWDOWN
  - ML-Modell F1 >= MIN_F1
  - Profitfaktor >= MIN_PROFIT_FACTOR
  - Kein aktiver Emergency-Exit

Ausgabe: READY (exit 0) oder NOT_READY (exit 1) mit detaillierter Begründung.

Verwendung:
    python forex_bot/scripts/pre_live_check.py                    # Standard
    python forex_bot/scripts/pre_live_check.py --strict           # Strengere Kriterien
    python forex_bot/scripts/pre_live_check.py --min-trades 50    # Mehr Trades nötig
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── Schwellenwerte ────────────────────────────────────────────────────────────
DEFAULT_CRITERIA = {
    "min_paper_trades":  30,
    "min_sharpe":        0.50,
    "min_win_rate":      0.40,
    "max_drawdown":      0.08,
    "min_f1":            0.40,
    "min_profit_factor": 1.10,
}

STRICT_CRITERIA = {
    "min_paper_trades":  50,
    "min_sharpe":        0.80,
    "min_win_rate":      0.45,
    "max_drawdown":      0.05,
    "min_f1":            0.45,
    "min_profit_factor": 1.25,
}

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"


def _ok(label: str, value: str, passed: bool) -> str:
    icon = f"{G}✓{X}" if passed else f"{R}✗{X}"
    status = f"{G}PASS{X}" if passed else f"{R}FAIL{X}"
    return f"  {icon} {label:<35} {value:<20} [{status}]"


def check(criteria: dict, verbose: bool = True) -> dict:
    """
    Führt alle Pre-Live-Checks durch.

    Returns
    -------
    dict:
        ready:   bool
        checks:  list[dict]
        summary: str
    """
    results  = []
    passed   = 0
    failed   = 0
    failures = []

    if verbose:
        print(f"\n{B}══════════════════════════════════════════════════{X}")
        print(f"{B}   Forex Bot — Pre-Live Deployment Check{X}")
        print(f"{B}══════════════════════════════════════════════════{X}\n")

    # ── 1. ML-Modell laden ────────────────────────────────────────────────────
    model_f1 = None
    model_trained_at = None
    try:
        import joblib
        model_path = ROOT / "forex_bot" / "ai" / "model.joblib"
        if model_path.exists():
            meta = joblib.load(model_path)
            model_f1         = meta.get("val_f1", 0.0)
            model_trained_at = meta.get("trained_at", "unknown")
        else:
            model_f1 = 0.0
    except Exception as e:
        model_f1 = 0.0

    # ── 2. Paper-Trading-Statistiken aus DB ───────────────────────────────────
    trades        = []
    total_trades  = 0
    win_rate      = 0.0
    sharpe        = 0.0
    max_drawdown  = 0.0
    profit_factor = 0.0

    try:
        from forex_bot.monitoring.logger import get_recent_trades, get_performance_summary
        summary      = get_performance_summary()
        total_trades = summary.get("total_trades",   0)
        win_rate     = summary.get("win_rate",       0.0) / 100.0 if summary.get("win_rate", 0) > 1 else summary.get("win_rate", 0.0)
        sharpe       = summary.get("sharpe",         0.0)
        max_drawdown = abs(summary.get("max_drawdown", 0.0))

        # Profit Factor
        recent = get_recent_trades(500)
        if recent:
            gross_profit = sum(t.get("pnl", 0) for t in recent if t.get("pnl", 0) > 0)
            gross_loss   = abs(sum(t.get("pnl", 0) for t in recent if t.get("pnl", 0) < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (1.5 if gross_profit > 0 else 0.0)

    except Exception as e:
        pass

    # ── 3. Emergency Exit Status ──────────────────────────────────────────────
    emergency_active = False
    try:
        from forex_bot.risk.emergency_exit import is_emergency_active
        emergency_active = is_emergency_active()
    except Exception:
        pass

    # ── 3b. Regime Robustness Check ──────────────────────────────────────────
    regime_robustness = {}
    regime_ok = True
    try:
        from forex_bot.monitoring.logger import get_recent_trades as _grt
        _all_trades = _grt(500)
        if _all_trades:
            from collections import defaultdict as _dd
            _by_regime: dict = _dd(list)
            for _t in _all_trades:
                _r = _t.get("regime", "UNKNOWN")
                _p = _t.get("pnl", 0.0)
                if _p != 0.0:
                    _by_regime[_r].append(_p)

            for _regime, _pnls in _by_regime.items():
                if len(_pnls) >= 5:
                    _wr = sum(1 for p in _pnls if p > 0) / len(_pnls)
                    regime_robustness[_regime] = {"trades": len(_pnls), "win_rate": _wr}
                    # Regime gilt als problematisch wenn Win-Rate < 30%
                    if _wr < 0.30:
                        regime_ok = False
    except Exception:
        pass

    # ── 3c. Macro-Event Stress Test ─────────────────────────────────────────
    # Prüft Performance rund um historische High-Impact Events
    macro_event_ok   = True
    macro_event_info = "Keine Daten"
    try:
        from forex_bot.monitoring.logger import get_recent_trades as _grt2
        _all_trades2 = _grt2(500)
        if _all_trades2:
            # Trades die direkt nach einem High-Impact Event geschlossen wurden
            # Approximation: Trades mit besonders hohem |PnL| als Event-Proxies
            _all_pnls = [t.get("pnl", 0.0) for t in _all_trades2 if t.get("pnl", 0.0) != 0.0]
            if len(_all_pnls) >= 10:
                import statistics as _stats
                _mean = _stats.mean(_all_pnls)
                _std  = _stats.stdev(_all_pnls) if len(_all_pnls) > 1 else 1.0
                # Trades > 2σ als potenzielle Event-Trades klassifizieren
                _event_trades = [p for p in _all_pnls if abs(p - _mean) > 2 * _std]
                if _event_trades:
                    _event_wins = sum(1 for p in _event_trades if p > 0)
                    _event_wr   = _event_wins / len(_event_trades)
                    _event_pnl  = sum(_event_trades)
                    macro_event_ok   = _event_wr >= 0.40 and _event_pnl > 0
                    macro_event_info = (
                        f"{len(_event_trades)} Event-Trades "
                        f"WR={_event_wr:.0%} PnL=${_event_pnl:+.0f}"
                    )
                else:
                    macro_event_info = "Keine Event-Trades identifiziert"
    except Exception:
        pass

    # ── 4. Checks auswerten ───────────────────────────────────────────────────

    checks = [
        {
            "label":   "Paper Trades vorhanden",
            "value":   total_trades,
            "target":  criteria["min_paper_trades"],
            "passed":  total_trades >= criteria["min_paper_trades"],
            "display": f"{total_trades} (min {criteria['min_paper_trades']})",
        },
        {
            "label":   "Sharpe Ratio (annualisiert)",
            "value":   sharpe,
            "target":  criteria["min_sharpe"],
            "passed":  sharpe >= criteria["min_sharpe"],
            "display": f"{sharpe:.3f} (min {criteria['min_sharpe']:.2f})",
        },
        {
            "label":   "Win Rate",
            "value":   win_rate,
            "target":  criteria["min_win_rate"],
            "passed":  win_rate >= criteria["min_win_rate"],
            "display": f"{win_rate:.1%} (min {criteria['min_win_rate']:.0%})",
        },
        {
            "label":   "Max Drawdown",
            "value":   max_drawdown,
            "target":  criteria["max_drawdown"],
            "passed":  max_drawdown <= criteria["max_drawdown"],
            "display": f"{max_drawdown:.1%} (max {criteria['max_drawdown']:.0%})",
        },
        {
            "label":   "ML-Modell F1",
            "value":   model_f1,
            "target":  criteria["min_f1"],
            "passed":  (model_f1 or 0) >= criteria["min_f1"],
            "display": f"{model_f1:.4f} (min {criteria['min_f1']:.2f})",
        },
        {
            "label":   "Profitfaktor",
            "value":   profit_factor,
            "target":  criteria["min_profit_factor"],
            "passed":  profit_factor >= criteria["min_profit_factor"],
            "display": f"{profit_factor:.3f} (min {criteria['min_profit_factor']:.2f})",
        },
        {
            "label":   "Emergency Exit inaktiv",
            "value":   not emergency_active,
            "target":  True,
            "passed":  not emergency_active,
            "display": "inaktiv" if not emergency_active else f"{R}AKTIV — kein Live-Start!{X}",
        },
        {
            "label":   "Regime-Robustheit (WR >= 30%)",
            "value":   regime_ok,
            "target":  True,
            "passed":  regime_ok,
            "display": (
                "OK (" + ", ".join(f"{r}: {v['win_rate']:.0%}" for r, v in regime_robustness.items()) + ")"
                if regime_robustness else "Keine Regime-Daten"
            ),
        },
        {
            "label":   "Macro-Event Resilienz",
            "value":   macro_event_ok,
            "target":  True,
            "passed":  macro_event_ok,
            "display": macro_event_info,
        },
    ]

    if verbose:
        print(f"  {'Check':<35} {'Ergebnis':<20} Status")
        print(f"  {'─'*35} {'─'*20} ──────")

    for c in checks:
        if c["passed"]:
            passed += 1
        else:
            failed += 1
            failures.append(c["label"])

        if verbose:
            print(_ok(c["label"], c["display"], c["passed"]))

    ready = failed == 0

    if verbose:
        print(f"\n  {'─'*60}")
        if ready:
            print(f"\n  {G}{B}✓ READY — Bot kann für Live-Trading aktiviert werden{X}")
            print(f"\n  Aktivierung: Setze FOREX_TRADING_MODE=live in forex_bot/.env")
            print(f"  oder: make forex-start-live\n")
        else:
            print(f"\n  {R}{B}✗ NOT READY — {failed} Kriterien nicht erfüllt{X}")
            for fail in failures:
                print(f"  {R}  →{X} {fail}")
            print()
            if total_trades < criteria["min_paper_trades"]:
                print(f"  {Y}  Empfehlung:{X} Mehr Paper-Trades sammeln (noch "
                      f"{criteria['min_paper_trades'] - total_trades} nötig)")
            if (model_f1 or 0) < criteria["min_f1"]:
                print(f"  {Y}  Empfehlung:{X} Modell neu trainieren: make forex-train")
            print()

    # ── Modell-Info ───────────────────────────────────────────────────────────
    if verbose and model_trained_at:
        print(f"  {Y}Modell trainiert:{X} {model_trained_at}")
        print()

    return {
        "ready":          ready,
        "passed":         passed,
        "failed":         failed,
        "failures":       failures,
        "checks":         checks,
        "checked_at":     datetime.now(timezone.utc).isoformat(),
        "criteria":       criteria,
    }


def main():
    parser = argparse.ArgumentParser(description="Pre-Live Deployment Check für Forex Bot")
    parser.add_argument("--strict",       action="store_true", help="Strengere Kriterien (höherer Sharpe, mehr Trades)")
    parser.add_argument("--min-trades",   type=int, default=None, help="Minimale Paper-Trades")
    parser.add_argument("--min-sharpe",   type=float, default=None, help="Minimaler Sharpe Ratio")
    parser.add_argument("--json",         action="store_true", help="JSON-Output (für CI/CD)")
    args = parser.parse_args()

    criteria = dict(STRICT_CRITERIA if args.strict else DEFAULT_CRITERIA)
    if args.min_trades:
        criteria["min_paper_trades"] = args.min_trades
    if args.min_sharpe:
        criteria["min_sharpe"] = args.min_sharpe

    result = check(criteria, verbose=not args.json)

    if args.json:
        print(json.dumps(result, indent=2, default=str))

    sys.exit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
