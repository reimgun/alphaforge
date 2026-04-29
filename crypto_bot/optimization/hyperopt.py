"""
Hyperparameter-Optimierung mit Bayesian Search (Optuna).

Optimiert die wichtigsten Bot-Parameter durch automatisches Backtesting:
  - ATR_MULTIPLIER    (Stop-Loss Weite)
  - ML_MIN_CONFIDENCE (ML-Signal Schwelle)
  - TRAILING_STOP_PCT (Trailing-Stop Enge)
  - RISK_PER_TRADE    (Positionsgröße)
  - ML_LABEL_THRESHOLD (Training-Label-Schwelle)

QNAP-Hinweis: Lokal auf Mac ausführen (CPU-intensiv), dann Ergebnisse deployen.
Ergebnis wird in crypto_bot/optimization/best_params.json gespeichert.

Verwendung:
  cd trading_bot
  python -m crypto_bot.optimization.hyperopt --trials 50 --days 180
  python -m crypto_bot.optimization.hyperopt --trials 100 --days 365 --jobs 4

Ergebnis anwenden:
  Die best_params.json kann direkt in .env übertragen werden.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

_BEST_PARAMS_FILE = Path(__file__).parent / "best_params.json"


def _objective(trial, days: int, verbose: bool = False) -> float:
    """
    Optuna-Objective: führt Backtest mit Trial-Parametern aus, gibt Sharpe zurück.
    Negativer Sharpe weil Optuna minimiert.
    """
    import crypto_bot.config.settings as cfg

    # ── Parameter-Raum ────────────────────────────────────────────────────────
    cfg.ATR_MULTIPLIER      = trial.suggest_float("atr_multiplier",      1.0, 3.5, step=0.25)
    cfg.ML_MIN_CONFIDENCE   = trial.suggest_float("ml_min_confidence",   0.50, 0.75, step=0.025)
    cfg.TRAILING_STOP_PCT   = trial.suggest_float("trailing_stop_pct",   0.008, 0.03, step=0.002)
    cfg.RISK_PER_TRADE      = trial.suggest_float("risk_per_trade",       0.01, 0.04, step=0.005)
    cfg.ML_LABEL_THRESHOLD  = trial.suggest_float("ml_label_threshold",   0.008, 0.025, step=0.002)

    try:
        from crypto_bot.backtest.engine_ai import run_ai_backtest
        result = run_ai_backtest(days=days, verbose=verbose)

        if not result or result.get("trades", 0) < 3:
            return 0.0  # Zu wenige Trades → schlechter Score

        from crypto_bot.config.settings import HYPEROPT_LOSS
        from crypto_bot.optimization.loss_functions import get_loss_function
        loss_fn = get_loss_function(HYPEROPT_LOSS)
        return loss_fn(result)

    except Exception as e:
        if verbose:
            print(f"Trial {trial.number} Fehler: {e}")
        return 0.0


def run_hyperopt(n_trials: int = 50, days: int = 180, n_jobs: int = 1) -> dict:
    """
    Startet Bayesian Parameter-Optimierung.

    Args:
        n_trials: Anzahl Backtest-Durchläufe (mehr = besser, langsamer)
        days:     Backtest-Zeitraum in Tagen
        n_jobs:   Parallele Trials (nur mit Optuna, >1 braucht mehr RAM)

    Returns:
        dict mit besten Parametern + Sharpe-Score
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        _has_optuna = True
    except ImportError:
        _has_optuna = False

    if not _has_optuna:
        print("Optuna nicht installiert — nutze Random Search als Fallback")
        print("Installieren: pip install optuna")
        return _random_search(n_trials=n_trials, days=days)

    print(f"\nHyperopt gestartet: {n_trials} Trials × {days} Tage Backtest")
    print("Parameter-Raum:")
    print("  ATR_MULTIPLIER:     1.0 – 3.5")
    print("  ML_MIN_CONFIDENCE:  0.50 – 0.75")
    print("  TRAILING_STOP_PCT:  0.8% – 3.0%")
    print("  RISK_PER_TRADE:     1.0% – 4.0%")
    print("  ML_LABEL_THRESHOLD: 0.8% – 2.5%")
    print()

    start = time.time()
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=5),
    )

    import functools
    objective_fn = functools.partial(_objective, days=days, verbose=False)

    study.optimize(
        objective_fn,
        n_trials=n_trials,
        n_jobs=n_jobs,
        show_progress_bar=True,
        catch=(Exception,),
    )

    elapsed = time.time() - start
    best = study.best_trial

    result = {
        "best_params": {
            "ATR_MULTIPLIER":     round(best.params["atr_multiplier"],    2),
            "ML_MIN_CONFIDENCE":  round(best.params["ml_min_confidence"], 3),
            "TRAILING_STOP_PCT":  round(best.params["trailing_stop_pct"], 3),
            "RISK_PER_TRADE":     round(best.params["risk_per_trade"],    3),
            "ML_LABEL_THRESHOLD": round(best.params["ml_label_threshold"],3),
        },
        "best_score":    round(best.value, 4),
        "n_trials":      n_trials,
        "backtest_days": days,
        "elapsed_sec":   round(elapsed, 1),
        "timestamp":     __import__("datetime").datetime.now().isoformat(),
    }

    _save_results(result, study)

    print(f"\nBeste Parameter (Score: {best.value:.4f}):")
    for k, v in result["best_params"].items():
        print(f"  {k} = {v}")
    print(f"\nAbgeschlossen in {elapsed:.0f}s")
    print(f"Ergebnis gespeichert: {_BEST_PARAMS_FILE}")

    return result


def _random_search(n_trials: int = 30, days: int = 180) -> dict:
    """Fallback wenn Optuna nicht installiert: zufällige Parameter-Suche."""
    import random
    random.seed(42)

    param_space = {
        "atr_multiplier":     [round(x * 0.25, 2) for x in range(4, 15)],  # 1.0–3.5
        "ml_min_confidence":  [round(x * 0.025, 3) for x in range(20, 31)], # 0.50–0.75
        "trailing_stop_pct":  [round(x * 0.002, 3) for x in range(4, 16)],  # 0.008–0.03
        "risk_per_trade":     [round(x * 0.005, 3) for x in range(2, 9)],   # 0.01–0.04
        "ml_label_threshold": [round(x * 0.002, 3) for x in range(4, 13)],  # 0.008–0.024
    }

    best_score  = -1.0
    best_params = {}
    results     = []

    print(f"Random Search: {n_trials} Trials × {days} Tage")

    for i in range(n_trials):
        params = {k: random.choice(v) for k, v in param_space.items()}
        trial  = _MockTrial(i, params)
        score  = _objective(trial, days=days)
        results.append({"params": params, "score": score})

        if score > best_score:
            best_score  = score
            best_params = params.copy()

        print(f"  Trial {i+1}/{n_trials}: score={score:.4f} | {params}")

    result = {
        "best_params": {
            "ATR_MULTIPLIER":     best_params.get("atr_multiplier",     2.0),
            "ML_MIN_CONFIDENCE":  best_params.get("ml_min_confidence",  0.55),
            "TRAILING_STOP_PCT":  best_params.get("trailing_stop_pct",  0.015),
            "RISK_PER_TRADE":     best_params.get("risk_per_trade",      0.02),
            "ML_LABEL_THRESHOLD": best_params.get("ml_label_threshold",  0.015),
        },
        "best_score":    round(best_score, 4),
        "method":        "random_search",
        "n_trials":      n_trials,
        "backtest_days": days,
        "timestamp":     __import__("datetime").datetime.now().isoformat(),
    }

    _save_results(result)
    return result


class _MockTrial:
    """Minimal Trial-Interface für Random Search (ohne Optuna)."""
    def __init__(self, number: int, params: dict):
        self.number = number
        self._params = params

    def suggest_float(self, name: str, low: float, high: float, **kwargs) -> float:
        return self._params.get(name, (low + high) / 2)

    def suggest_int(self, name: str, low: int, high: int, **kwargs) -> int:
        return self._params.get(name, (low + high) // 2)


def _save_results(result: dict, study=None) -> None:
    """Speichert beste Parameter als JSON + env-kompatibles Format."""
    _BEST_PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # JSON speichern
    _BEST_PARAMS_FILE.write_text(json.dumps(result, indent=2))

    # .env-kompatibles Format ausgeben
    env_file = _BEST_PARAMS_FILE.parent / "best_params.env"
    lines = ["# Optimierte Parameter — kopieren in .env\n"]
    for k, v in result["best_params"].items():
        lines.append(f"{k}={v}\n")
    env_file.write_text("".join(lines))

    # Optuna-Visualisierung (wenn verfügbar)
    if study is not None:
        try:
            import optuna.visualization as vis
            fig = vis.plot_optimization_history(study)
            fig.write_html(str(_BEST_PARAMS_FILE.parent / "optimization_history.html"))
            fig2 = vis.plot_param_importances(study)
            fig2.write_html(str(_BEST_PARAMS_FILE.parent / "param_importances.html"))
            print("Visualisierung gespeichert: optimization_history.html, param_importances.html")
        except Exception:
            pass


def print_comparison(current: dict, best: dict) -> None:
    """Zeigt Vergleich: aktuell vs. optimiert."""
    import crypto_bot.config.settings as cfg
    current_vals = {
        "ATR_MULTIPLIER":     cfg.ATR_MULTIPLIER,
        "ML_MIN_CONFIDENCE":  cfg.ML_MIN_CONFIDENCE,
        "TRAILING_STOP_PCT":  cfg.TRAILING_STOP_PCT,
        "RISK_PER_TRADE":     cfg.RISK_PER_TRADE,
        "ML_LABEL_THRESHOLD": cfg.ML_LABEL_THRESHOLD,
    }

    print("\n── Parameter-Vergleich ──────────────────────────")
    print(f"{'Parameter':<22} {'Aktuell':>10} {'Optimiert':>12} {'Δ':>8}")
    print("─" * 55)
    for k in best:
        cur = current_vals.get(k, "?")
        opt = best[k]
        delta = f"{opt - cur:+.3f}" if isinstance(cur, float) else "?"
        arrow = "↑" if isinstance(cur, float) and opt > cur else "↓"
        print(f"{k:<22} {str(cur):>10} {str(opt):>12} {delta:>7} {arrow}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hyperparameter-Optimierung für den Trading Bot")
    parser.add_argument("--trials", type=int, default=50,  help="Anzahl Backtest-Trials (default: 50)")
    parser.add_argument("--days",   type=int, default=180, help="Backtest-Zeitraum in Tagen (default: 180)")
    parser.add_argument("--jobs",   type=int, default=1,   help="Parallele Trials (default: 1)")
    parser.add_argument("--show-best", action="store_true", help="Beste Parameter aus letztem Run anzeigen")
    args = parser.parse_args()

    if args.show_best:
        if _BEST_PARAMS_FILE.exists():
            data = json.loads(_BEST_PARAMS_FILE.read_text())
            print(f"\nBeste Parameter (Score: {data['best_score']:.4f}, "
                  f"{data['n_trials']} Trials, {data['backtest_days']}d):")
            for k, v in data["best_params"].items():
                print(f"  {k} = {v}")
            print(f"\n.env-Format gespeichert unter: {_BEST_PARAMS_FILE.parent}/best_params.env")
        else:
            print("Noch kein Hyperopt durchgeführt. Starte mit: python -m crypto_bot.optimization.hyperopt")
    else:
        result = run_hyperopt(n_trials=args.trials, days=args.days, n_jobs=args.jobs)
        print_comparison({}, result["best_params"])
