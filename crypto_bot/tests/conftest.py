"""
Shared test fixtures — benutzt von allen Test-Modulen.
"""
import sys
import os
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# Tests laufen immer mit INITIAL_CAPITAL=1000 — unabhängig von .env
# (Drawdown-Tests und Position-Sizing-Tests bauen auf diesem Wert auf)
os.environ["INITIAL_CAPITAL"] = "1000"

import numpy as np
import pandas as pd
import pytest
import tempfile
from unittest.mock import MagicMock, patch

# Sicherstellen dass settings.INITIAL_CAPITAL auch im bereits importierten Modul 1000 ist
try:
    import crypto_bot.config.settings as _s
    _s.INITIAL_CAPITAL = 1000.0
except Exception:
    pass


# ── Sample DataFrames ──────────────────────────────────────────────────────────

def _make_df(n: int = 300, start: float = 80_000.0, seed: int = 42,
             trend: float = 0.0) -> pd.DataFrame:
    """Generiert synthetische OHLCV-Daten."""
    np.random.seed(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.randn() * 0.005 + trend))
    prices = np.array(prices, dtype=float)

    high   = prices * (1 + np.random.uniform(0.001, 0.012, n))
    low    = prices * (1 - np.random.uniform(0.001, 0.012, n))
    open_  = prices * (1 + np.random.uniform(-0.003, 0.003, n))
    volume = np.random.uniform(200, 2000, n) * 1e6

    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=pd.date_range("2023-01-01", periods=n, freq="1h"))


@pytest.fixture(scope="session")
def sample_df():
    return _make_df(300)


@pytest.fixture(scope="session")
def bull_df():
    """Klar aufwärts trendierender DataFrame."""
    return _make_df(300, trend=0.0008)   # ~0.08% pro Stunde aufwärts


@pytest.fixture(scope="session")
def bear_df():
    """Klar abwärts trendierender DataFrame."""
    return _make_df(300, trend=-0.0008)


@pytest.fixture(scope="session")
def sideways_df():
    """Seitwärts-Markt ohne klaren Trend."""
    np.random.seed(99)
    n = 300
    prices = 80_000 + np.random.randn(n).cumsum() * 50   # Wenig Drift
    high   = prices + np.random.uniform(100, 400, n)
    low    = prices - np.random.uniform(100, 400, n)
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": np.random.uniform(100, 500, n) * 1e6,
    }, index=pd.date_range("2023-01-01", periods=n, freq="1h"))


# ── Temporäre Datenbank ────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Temporäre SQLite-Datenbank — isoliert pro Test."""
    db_path = tmp_path / "test_trades.db"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr("crypto_bot.config.settings.DB_PATH", db_path)
    monkeypatch.setattr("crypto_bot.config.settings.LOG_DIR", log_dir)

    # Module neu laden damit sie die gepatchten Paths nutzen
    import crypto_bot.monitoring.logger as logger_mod
    monkeypatch.setattr(logger_mod, "DB_PATH", db_path)
    monkeypatch.setattr(logger_mod, "LOG_DIR", log_dir)

    from crypto_bot.monitoring.logger import init_db
    init_db()
    return db_path


# ── Mock Exchange ──────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_exchange():
    ex = MagicMock()
    ex.fetch_ohlcv.return_value = [
        [1_704_067_200_000 + i * 3_600_000, 80_000, 80_500, 79_500, 80_200, 1_000_000]
        for i in range(300)
    ]
    ex.fetch_ticker.return_value = {"last": 80_200.0}
    ex.create_order.return_value = {
        "id": "TEST123", "status": "closed",
        "price": 80_000.0, "amount": 0.01, "filled": 0.01,
    }
    return ex
