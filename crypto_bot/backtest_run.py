"""
Backtest ausführen — vor dem echten Betrieb!

Modi:
  --mode simple   Schneller Momentum-Backtest (Standard, gut für QNAP)
  --mode ai       AI-Pipeline Backtest — testet echte ML+Regime-Logic (empfohlen)
  --mode walk     Walk-Forward (Out-of-Sample Validierung)
  --mode monte    Monte Carlo Simulation

Beispiele:
  python -m crypto_bot.backtest_run                     # simple (Standard)
  python -m crypto_bot.backtest_run --mode ai           # AI-Pipeline (EMPFOHLEN)
  python -m crypto_bot.backtest_run --mode ai --days 90 # AI, letzten 90 Tage
  python -m crypto_bot.backtest_run --mode walk
  python -m crypto_bot.backtest_run --mode monte
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Trading Bot Backtest")
    parser.add_argument(
        "--mode",
        choices=["simple", "ai", "walk", "monte"],
        default="simple",
        help="Backtest-Modus: simple (schnell, Momentum-only) | ai (echte AI-Pipeline) | walk | monte",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Anzahl historischer Tage (Standard: BACKTEST_DAYS aus settings.py)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Zeige jede Entscheidung (nur --mode ai)",
    )
    args = parser.parse_args()

    if args.mode == "simple":
        from crypto_bot.backtest.engine import run_backtest
        run_backtest()

    elif args.mode == "ai":
        from crypto_bot.backtest.engine_ai import run_ai_backtest
        from crypto_bot.config.settings import BACKTEST_DAYS
        days = args.days if args.days else BACKTEST_DAYS
        run_ai_backtest(days=days, verbose=args.verbose)

    elif args.mode == "walk":
        from crypto_bot.backtest.walk_forward import run_walk_forward
        run_walk_forward()

    elif args.mode == "monte":
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        run_monte_carlo()


if __name__ == "__main__":
    main()
