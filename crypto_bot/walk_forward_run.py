"""Walk-Forward Test starten."""
from crypto_bot.backtest.walk_forward import run_walk_forward

if __name__ == "__main__":
    run_walk_forward(total_days=720, n_windows=6, train_ratio=0.7)
