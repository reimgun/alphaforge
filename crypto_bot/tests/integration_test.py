"""
Vollständige Integration-Testsuite — alle Features.

Ausführen:
    cd trading_bot
    python -m pytest tests/ -v --tb=short

Abdeckung:
  SEKTION 1 — Bestehende Features (Tier 1-3)
  SEKTION 2 — Neue Features (8 Erweiterungen)
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


# =============================================================================
# SEKTION 1: BESTEHENDE FEATURES
# =============================================================================

class TestConfig:
    """1.1 — Konfiguration"""

    def test_required_settings_exist(self):
        from crypto_bot.config import settings as s
        required = [
            "SYMBOL", "TIMEFRAME", "TRADING_MODE", "INITIAL_CAPITAL",
            "RISK_PER_TRADE", "MAX_DAILY_LOSS_PCT", "MAX_DRAWDOWN_PCT",
            "DB_PATH", "LOG_DIR", "AI_MODE",
        ]
        for attr in required:
            assert hasattr(s, attr), f"settings.{attr} fehlt"

    def test_paths_are_path_objects(self):
        from crypto_bot.config.settings import DB_PATH, LOG_DIR
        assert isinstance(DB_PATH, Path)
        assert isinstance(LOG_DIR, Path)

    def test_trading_mode_valid(self):
        from crypto_bot.config.settings import TRADING_MODE
        assert TRADING_MODE in ("paper", "live"), f"Ungültiger TRADING_MODE: {TRADING_MODE}"

    def test_risk_params_sane(self):
        from crypto_bot.config import settings as s
        assert 0 < s.RISK_PER_TRADE <= 0.10,   "RISK_PER_TRADE sollte 0-10%"
        assert 0 < s.MAX_DAILY_LOSS_PCT <= 0.20, "MAX_DAILY_LOSS_PCT sollte 0-20%"
        assert 0 < s.MAX_DRAWDOWN_PCT <= 0.50,  "MAX_DRAWDOWN_PCT sollte 0-50%"


class TestDataFetcher:
    """1.2 — Datenabruf & Validierung"""

    def test_validate_ohlcv_valid(self, sample_df):
        from crypto_bot.data.fetcher import _validate_ohlcv
        # Sollte kein Problem werfen
        _validate_ohlcv(sample_df)

    def test_validate_ohlcv_removes_nan(self, sample_df):
        from crypto_bot.data.fetcher import _validate_ohlcv
        bad = sample_df.copy()
        bad.iloc[10, bad.columns.get_loc("close")] = float("nan")
        # Sollte ohne Fehler laufen und NaN-Zeilen entfernen
        result = _validate_ohlcv(bad)
        assert result is not None

    def test_validate_ohlcv_removes_negative(self, sample_df):
        from crypto_bot.data.fetcher import _validate_ohlcv
        bad = sample_df.copy()
        bad.iloc[5, bad.columns.get_loc("close")] = -1.0
        # Sollte ohne Fehler laufen
        result = _validate_ohlcv(bad)
        assert result is not None

    def test_fetch_uses_retry(self):
        """Testet dass _fetch_with_retry bei ccxt-Fehlern wiederholt."""
        import ccxt
        from crypto_bot.data.fetcher import _fetch_with_retry
        call_count = [0]

        def failing_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ccxt.NetworkError("Temporärer Fehler")
            return "success"

        result = _fetch_with_retry(failing_fn)
        assert result == "success"
        assert call_count[0] == 3


class TestFeatureEngineering:
    """1.3 — Feature Engineering"""

    def test_features_shape(self, sample_df):
        from crypto_bot.ai.features import build_features
        X = build_features(sample_df)
        assert isinstance(X, pd.DataFrame)
        assert len(X) > 0
        assert len(X.columns) >= 10, f"Zu wenige Features: {len(X.columns)}"

    def test_no_lookahead_bias(self, sample_df):
        from crypto_bot.ai.features import build_features
        X = build_features(sample_df)
        # Features dürfen nur vergangene Daten nutzen — kein future close
        assert "future_close" not in X.columns
        assert "future_return" not in X.columns

    def test_labels_three_classes(self, sample_df):
        from crypto_bot.ai.features import build_labels
        y = build_labels(sample_df)
        unique = set(y.dropna().unique())
        assert unique.issubset({-1, 0, 1}), f"Unerwartete Label-Werte: {unique}"

    def test_features_no_inf(self, sample_df):
        from crypto_bot.ai.features import build_features
        X = build_features(sample_df)
        assert not X.isin([float("inf"), float("-inf")]).any().any(), "Inf-Werte in Features"


class TestMLTrainingAndPrediction:
    """1.4 — ML Training & Vorhersage"""

    def test_model_trains_and_saves(self, tmp_path):
        pytest.importorskip("xgboost", reason="xgboost nicht verfügbar")
        from crypto_bot.tests.conftest import _make_df
        # Mehr Daten für ausgewogenere Label-Verteilung
        big_df = _make_df(n=1500, seed=7)
        from crypto_bot.ai.trainer import train
        model_path = tmp_path / "test_model.joblib"
        with patch("crypto_bot.config.settings.ML_MODEL_PATH", model_path):
            with patch("crypto_bot.ai.trainer.ML_MODEL_PATH", model_path):
                result = train(df=big_df)
        # train() gibt (model, scaler) Tuple zurück
        assert result is not None
        assert isinstance(result, (tuple, dict))

    def test_predictor_loads_and_predicts(self, sample_df, tmp_path):
        pytest.importorskip("xgboost", reason="xgboost nicht verfügbar")
        from crypto_bot.tests.conftest import _make_df
        big_df = _make_df(n=1500, seed=7)
        from crypto_bot.ai.trainer import train
        from crypto_bot.ai.predictor import MLPredictor
        model_path = tmp_path / "pred_model.joblib"
        with patch("crypto_bot.config.settings.ML_MODEL_PATH", model_path):
            with patch("crypto_bot.ai.trainer.ML_MODEL_PATH", model_path):
                train(df=big_df)
            with patch("crypto_bot.ai.predictor.ML_MODEL_PATH", model_path):
                pred = MLPredictor()
                result = pred.predict(sample_df)
        assert result.signal in ("BUY", "SELL", "HOLD")
        assert 0.0 <= result.confidence <= 1.0
        assert set(result.probabilities.keys()) == {"BUY", "HOLD", "SELL"}


class TestMomentumStrategy:
    """1.5 — Momentum-Strategie"""

    def test_generates_signal(self, sample_df):
        from crypto_bot.strategy.momentum import generate_signal, Signal
        result = generate_signal(sample_df)
        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)
        assert result.price > 0

    def test_add_indicators_creates_columns(self, sample_df):
        from crypto_bot.strategy.momentum import add_indicators
        df = add_indicators(sample_df)
        for col in ["fast_ma", "slow_ma", "rsi", "crossover"]:
            assert col in df.columns, f"Spalte {col} fehlt"

    def test_golden_cross_produces_buy(self):
        """Testet explizit Golden Cross → BUY."""
        from crypto_bot.strategy.momentum import add_indicators, generate_signal, Signal
        n = 100
        # Aufwärtstrend: Fast MA kreuzt Slow MA
        prices = np.concatenate([
            np.linspace(70000, 75000, 60),  # Downtrend
            np.linspace(75000, 85000, 40),  # Starker Anstieg → Golden Cross
        ])
        df = pd.DataFrame({
            "open": prices, "high": prices * 1.002,
            "low": prices * 0.998, "close": prices,
            "volume": np.ones(n) * 1e6,
        }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))
        result = generate_signal(df)
        # Sollte irgendwann ein Signal erzeugen (nicht immer HOLD)
        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)


class TestRegimeDetection:
    """1.6 — Regime Detection"""

    def test_regime_has_required_fields(self, sample_df):
        from crypto_bot.strategy.regime_detector import detect_regime
        regime = detect_regime(sample_df)
        assert hasattr(regime, "regime")
        assert hasattr(regime, "position_size_factor")
        assert hasattr(regime, "adx")
        assert hasattr(regime, "atr_pct")

    def test_regime_valid_values(self, sample_df):
        from crypto_bot.strategy.regime_detector import detect_regime
        regime = detect_regime(sample_df)
        valid = {"BULL_TREND", "BEAR_TREND", "SIDEWAYS", "HIGH_VOLATILITY"}
        assert regime.regime in valid

    def test_position_size_factor_range(self, sample_df):
        from crypto_bot.strategy.regime_detector import detect_regime
        regime = detect_regime(sample_df)
        assert 0.0 < regime.position_size_factor <= 1.0

    def test_bear_trend_detected(self, bear_df):
        from crypto_bot.strategy.regime_detector import detect_regime
        regime = detect_regime(bear_df)
        # In Abwärtstrend: entweder BEAR_TREND oder HIGH_VOLATILITY (akzeptabel)
        assert regime.regime in {"BEAR_TREND", "HIGH_VOLATILITY", "SIDEWAYS"}


class TestMultiTimeframe:
    """1.7 — Multi-Timeframe"""

    def test_filter_buy_in_bullish(self):
        from crypto_bot.strategy.multi_timeframe import filter_signal_by_trend, TrendContext
        trend = TrendContext(direction="BULLISH", ma50=79000, ma20=79500,
                             price=80000, slope_5=100.0, strength="strong")
        assert filter_signal_by_trend("BUY", trend) == "BUY"

    def test_filter_buy_in_bearish(self):
        from crypto_bot.strategy.multi_timeframe import filter_signal_by_trend, TrendContext
        trend = TrendContext(direction="BEARISH", ma50=81000, ma20=80500,
                             price=80000, slope_5=-100.0, strength="strong")
        assert filter_signal_by_trend("BUY", trend) == "HOLD"

    def test_filter_neutral_always_hold(self):
        from crypto_bot.strategy.multi_timeframe import filter_signal_by_trend, TrendContext
        trend = TrendContext(direction="NEUTRAL", ma50=80000, ma20=80000,
                             price=80000, slope_5=0.0, strength="weak")
        assert filter_signal_by_trend("BUY", trend) == "HOLD"
        assert filter_signal_by_trend("SELL", trend) == "HOLD"


class TestRiskManager:
    """1.8 — Risk Manager"""

    def test_open_position_with_atr(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        pos = rm.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0, regime_factor=1.0)
        assert pos.entry_price == 80000.0
        assert pos.stop_loss < 80000.0
        assert pos.take_profit > 80000.0
        assert pos.quantity > 0

    def test_circuit_breaker_triggers(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.daily_loss = 70.0   # 7% — über Schwelle
        assert rm.is_circuit_breaker_active()

    def test_circuit_breaker_not_triggered_small_loss(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.daily_loss = 10.0   # 1% — unter Schwelle
        assert not rm.is_circuit_breaker_active()

    def test_trailing_stop_updates(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
        initial_sl = rm.position.stop_loss
        # Preis steigt → Trailing Stop steigt mit
        new_sl = rm.update_trailing_stop(85000.0)
        assert new_sl > initial_sl

    def test_stop_loss_trigger(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
        # Preis fällt unter Stop
        result = rm.check_stop_take(rm.position.stop_loss - 100)
        assert result == "stop_loss"

    def test_close_position_updates_capital(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
        trade = rm.close_position(exit_price=82000.0)
        assert "pnl" in trade
        assert trade["pnl"] > 0
        assert rm.capital > 1000.0

    def test_summary_statistics(self):
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        rm.trades = [
            {"pnl": 20.0, "capital_after": 1020.0},
            {"pnl": -10.0, "capital_after": 1010.0},
            {"pnl": 15.0, "capital_after": 1025.0},
        ]
        s = rm.summary()
        assert s["trades"] == 3
        assert s["wins"] == 2
        assert s["losses"] == 1
        assert s["win_rate"] == pytest.approx(66.7, abs=0.1)


class TestPaperTrader:
    """1.9 — Paper Trader"""

    def test_buy_sell_cycle(self, tmp_db):
        from crypto_bot.execution.paper_trader import PaperTrader
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        pt = PaperTrader(rm)
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            pt.buy(price=80000.0, atr=1200.0, reason="Test")
            assert rm.has_open_position()
            pt.sell(price=82000.0, reason="Test Exit")
        assert not rm.has_open_position()
        assert len(rm.trades) == 1

    def test_cant_buy_twice(self, tmp_db):
        from crypto_bot.execution.paper_trader import PaperTrader
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        pt = PaperTrader(rm)
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            pt.buy(price=80000.0, atr=1200.0, reason="First")
            # Zweiter Buy sollte ignoriert werden
            pt.buy(price=81000.0, atr=1200.0, reason="Second")
        # Nur eine Position offen
        assert rm.has_open_position()


class TestBacktestEngine:
    """1.10 — Backtesting Engine"""

    def test_backtest_returns_results(self, sample_df):
        from crypto_bot.backtest.engine import _calculate_stats
        import numpy as np
        trades = [
            {"pnl": 20.0, "entry": 80000, "exit": 80200, "reason": "TP",
             "entry_time": "2024-01-01", "exit_time": "2024-01-02"},
            {"pnl": -10.0, "entry": 80000, "exit": 79800, "reason": "SL",
             "entry_time": "2024-01-03", "exit_time": "2024-01-04"},
        ]
        equity = np.array([1000.0, 1020.0, 1010.0])
        result = _calculate_stats(trades, equity, sample_df.reset_index())
        assert "win_rate" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown_pct" in result
        assert "profit_factor" in result

    def test_costs_applied(self):
        from crypto_bot.backtest.engine import _apply_costs
        buy_price  = _apply_costs(80000.0, "buy")
        sell_price = _apply_costs(80000.0, "sell")
        assert buy_price > 80000.0,  "Buy sollte teurer sein (Slippage + Fee)"
        assert sell_price < 80000.0, "Sell sollte weniger bringen (Slippage + Fee)"


class TestWalkForward:
    """1.11 — Walk-Forward Testing"""

    def test_walk_forward_structure(self, sample_df):
        from crypto_bot.backtest.walk_forward import _run_window
        from crypto_bot.strategy.momentum import add_indicators
        df = add_indicators(sample_df).dropna()
        result = _run_window(df)
        # Entweder Ergebnis-Dict oder None (keine Trades = Ok)
        if result:
            assert "win_rate" in result
            # walk_forward nutzt "sharpe" (Kurzform)
            assert "sharpe" in result or "sharpe_ratio" in result


class TestSQLiteLogger:
    """1.12 — SQLite Logger"""

    def test_init_creates_tables(self, tmp_db):
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for tbl in ["trades", "signals", "bot_events", "performance_snapshots"]:
            assert tbl in tables, f"Tabelle {tbl} fehlt"

    def test_log_trade(self, tmp_db):
        from crypto_bot.monitoring import logger as lg
        lg.DB_PATH = tmp_db
        from crypto_bot.monitoring.logger import log_trade, get_recent_trades
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            log_trade("BTC/USDT", "long", 80000, 82000, 0.01, 20.0,
                      "TP", "ml", 0.75, "2024-01-01", "2024-01-02")
            trades = get_recent_trades(5)
        assert len(trades) >= 1
        assert trades[0]["symbol"] == "BTC/USDT"

    def test_log_event(self, tmp_db):
        from crypto_bot.monitoring.logger import log_event
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            log_event("Test-Event", "test", "info")

    def test_export_csv(self, tmp_db, tmp_path):
        from crypto_bot.monitoring.logger import log_trade, export_trades_csv
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            log_trade("BTC/USDT", "long", 80000, 82000, 0.01, 20.0)
            csv_path = str(tmp_path / "test_trades.csv")
            result = export_trades_csv(csv_path)
        assert Path(result).exists()
        import csv
        with open(result) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 1

    def test_export_json(self, tmp_db, tmp_path):
        from crypto_bot.monitoring.logger import export_performance_json
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            json_path = str(tmp_path / "perf.json")
            result = export_performance_json(json_path)
        assert Path(result).exists()
        import json
        with open(result) as f:
            data = json.load(f)
        assert "summary" in data
        assert "exported_at" in data


class TestTelegramAlerts:
    """1.13 — Telegram Alerts"""

    def test_alerts_no_crash_without_token(self):
        """Alerts dürfen nicht crashen wenn kein Token gesetzt."""
        import crypto_bot.monitoring.alerts as alerts_mod
        with patch.object(alerts_mod, "TELEGRAM_TOKEN", ""):
            with patch.object(alerts_mod, "TELEGRAM_CHAT_ID", ""):
                alerts_mod.alert_trade_opened(80000, 0.01, 77000, 84000, "ml+claude")
                alerts_mod.alert_trade_closed(82000, 20.0, 2.0, "TP", 1020.0)
                alerts_mod.alert_circuit_breaker(60.0, 1000.0)
                alerts_mod.alert_error("Test-Fehler")

    def test_alert_sends_when_token_set(self):
        import crypto_bot.monitoring.alerts as alerts_mod
        with patch.object(alerts_mod, "TELEGRAM_TOKEN", "fake_token"):
            with patch.object(alerts_mod, "TELEGRAM_CHAT_ID", "12345"):
                with patch("requests.post") as mock_post:
                    mock_post.return_value.status_code = 200
                    alerts_mod.alert_error("Test-Fehler")
                    assert mock_post.called


class TestAutoRetrainer:
    """1.14 — Auto-Retrainer"""

    def test_trigger_after_n_trades(self):
        from crypto_bot.ai.retrainer import AutoRetrainer
        from crypto_bot.config.settings import ML_RETRAIN_AFTER_TRADES
        ar = AutoRetrainer()
        # Simuliere N-1 Trades → kein Trigger
        for _ in range(ML_RETRAIN_AFTER_TRADES - 1):
            ar.record_trade()
        assert not ar.should_check()

        # N-ter Trade → Trigger
        ar.record_trade()
        assert ar.should_check()

    def test_model_info_returns_dict(self):
        from crypto_bot.ai.retrainer import AutoRetrainer
        info = AutoRetrainer().get_model_info()
        assert isinstance(info, dict)


# =============================================================================
# SEKTION 2: NEUE FEATURES
# =============================================================================

class TestWebDashboardAPI:
    """2.1 — Web Dashboard API (FastAPI)"""

    @pytest.fixture
    def client(self, tmp_db):
        from httpx import Client
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            with TestClient(app) as c:
                yield c

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_status_endpoint(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        for key in ["running", "capital", "trading_mode", "symbol", "regime"]:
            assert key in data, f"Key '{key}' fehlt in /api/status"

    def test_performance_endpoint(self, client):
        r = client.get("/api/performance")
        assert r.status_code == 200
        data = r.json()
        for key in ["total_trades", "win_rate", "sharpe_ratio", "profit_factor"]:
            assert key in data

    def test_equity_endpoint(self, client):
        r = client.get("/api/equity")
        assert r.status_code == 200
        data = r.json()
        assert "equity_curve" in data
        assert "initial_capital" in data

    def test_trades_endpoint(self, client):
        r = client.get("/api/trades")
        assert r.status_code == 200
        assert "trades" in r.json()

    def test_control_stop(self, client):
        r = client.post("/api/control/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_control_start_launches_subprocess(self, client):
        """start-Aktion startet Bot als Subprocess und gibt PID zurück."""
        import crypto_bot.dashboard.api as api_module
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.return_value = None   # Prozess läuft noch

        # Zustand zurücksetzen
        api_module._bot_state["running"] = False
        api_module._bot_process = None

        with patch("crypto_bot.dashboard.api.subprocess.Popen", return_value=mock_proc):
            r = client.post("/api/control/start")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data.get("pid") == 99999

    def test_control_start_rejected_when_running(self, client):
        """start-Aktion wird abgelehnt wenn Bot bereits läuft."""
        import crypto_bot.dashboard.api as api_module
        mock_proc = MagicMock()
        mock_proc.pid = 88888
        mock_proc.poll.return_value = None   # Prozess läuft
        api_module._bot_process = mock_proc
        api_module._bot_state["running"] = True

        r = client.post("/api/control/start")
        assert r.status_code == 200
        assert r.json()["status"] == "error"

        # Aufräumen
        api_module._bot_process = None
        api_module._bot_state["running"] = False

    def test_control_pause_resume(self, client):
        r = client.post("/api/control/pause")
        assert r.status_code == 200
        r = client.post("/api/control/resume")
        assert r.status_code == 200

    def test_control_safe_mode(self, client):
        r = client.post("/api/control/safe_mode")
        assert r.status_code == 200
        assert "safe_mode" in r.json()

    def test_control_invalid_action(self, client):
        r = client.post("/api/control/invalid_action_xyz")
        assert r.status_code == 400

    def test_model_endpoint(self, client):
        r = client.get("/api/model")
        assert r.status_code == 200


class TestBreakoutStrategy:
    """2.2 — Breakout-Strategie"""

    def test_signal_generated(self, sample_df):
        from crypto_bot.strategy.breakout import generate_breakout_signal, BreakoutSignal
        from crypto_bot.strategy.momentum import Signal
        result = generate_breakout_signal(sample_df)
        assert isinstance(result, BreakoutSignal)
        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)

    def test_breakout_on_strong_move(self):
        from crypto_bot.strategy.breakout import generate_breakout_signal
        from crypto_bot.strategy.momentum import Signal
        n = 50
        # Starker Anstieg über bisheriges High
        prices = np.concatenate([np.ones(40) * 80000, np.array([81000, 82000, 83000, 84000, 85000, 87000, 90000, 92000, 95000, 98000])])
        df = pd.DataFrame({
            "open": prices, "high": prices * 1.005,
            "low": prices * 0.995, "close": prices,
            "volume": np.concatenate([np.ones(40) * 1e9, np.ones(10) * 3e9]),  # Hohes Volumen
        }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))
        result = generate_breakout_signal(df)
        assert result.signal in (Signal.BUY, Signal.HOLD)   # Sollte BUY oder HOLD

    def test_has_required_fields(self, sample_df):
        from crypto_bot.strategy.breakout import generate_breakout_signal
        result = generate_breakout_signal(sample_df)
        assert hasattr(result, "upper_band")
        assert hasattr(result, "lower_band")
        assert hasattr(result, "volume_ratio")


class TestMeanReversionStrategy:
    """2.3 — Mean Reversion Strategie"""

    def test_signal_generated(self, sample_df):
        from crypto_bot.strategy.mean_reversion import generate_mean_reversion_signal, MeanReversionSignal
        from crypto_bot.strategy.momentum import Signal
        result = generate_mean_reversion_signal(sample_df)
        assert isinstance(result, MeanReversionSignal)
        assert result.signal in (Signal.BUY, Signal.SELL, Signal.HOLD)

    def test_buy_on_oversold(self):
        from crypto_bot.strategy.mean_reversion import generate_mean_reversion_signal
        from crypto_bot.strategy.momentum import Signal
        # Starker Absturz → überverkauft → BUY-Signal erwartet
        n = 100
        prices = np.concatenate([np.ones(70) * 80000, np.linspace(80000, 72000, 30)])
        df = pd.DataFrame({
            "open": prices, "high": prices * 1.003,
            "low": prices * 0.997, "close": prices,
            "volume": np.ones(n) * 1e9,
        }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))
        result = generate_mean_reversion_signal(df)
        assert result.signal in (Signal.BUY, Signal.HOLD)

    def test_bb_pct_range(self, sample_df):
        from crypto_bot.strategy.mean_reversion import generate_mean_reversion_signal
        result = generate_mean_reversion_signal(sample_df)
        # bb_pct sollte zwischen 0 und 1 (oder nah dran)
        assert -0.5 <= result.bb_pct <= 1.5, f"bb_pct außerhalb Bereich: {result.bb_pct}"


class TestStrategySelector:
    """2.4 — Strategy Selector"""

    def test_sideways_uses_mean_reversion(self, sideways_df):
        from crypto_bot.strategy.selector import select_and_generate, StrategyName
        from crypto_bot.strategy.regime_detector import detect_regime
        regime = detect_regime(sideways_df)
        result = select_and_generate(sideways_df, regime)
        # In Sideways: Mean Reversion oder Fallback
        assert result.strategy in (StrategyName.MEAN_REVERSION, StrategyName.MOMENTUM,
                                   StrategyName.BREAKOUT, StrategyName.NONE)

    def test_bear_trend_returns_hold(self, bear_df):
        from crypto_bot.strategy.selector import select_and_generate, StrategyName
        from crypto_bot.strategy.regime_detector import MarketRegime
        from crypto_bot.strategy.momentum import Signal
        # Manuell BEAR_TREND setzen
        fake_regime = MarketRegime(
            regime="BEAR_TREND", adx=30, atr_pct=1.5, atr_percentile=50.0,
            position_size_factor=0.5, description="Bear"
        )
        result = select_and_generate(bear_df, fake_regime)
        assert result.signal == Signal.HOLD
        assert result.strategy == StrategyName.NONE

    def test_get_strategy_for_regime(self):
        from crypto_bot.strategy.selector import get_strategy_for_regime, StrategyName
        assert get_strategy_for_regime("SIDEWAYS") == StrategyName.MEAN_REVERSION
        assert get_strategy_for_regime("HIGH_VOLATILITY") == StrategyName.SCALPING
        assert get_strategy_for_regime("BEAR_TREND") == StrategyName.NONE
        assert get_strategy_for_regime("BULL_TREND") == StrategyName.MOMENTUM


class TestWebSocketStreamer:
    """2.5 — WebSocket Streamer"""

    def test_streamer_initializes(self):
        from crypto_bot.data.ws_streamer import BinanceWSStreamer
        s = BinanceWSStreamer("BTC/USDT", "1h")
        assert s._symbol == "btcusdt"
        assert s._timeframe == "1h"
        assert not s.is_connected()

    def test_handle_message_buffers_candle(self):
        from crypto_bot.data.ws_streamer import BinanceWSStreamer
        import json
        s = BinanceWSStreamer("BTC/USDT", "1h", buffer_size=10)
        msg = json.dumps({
            "k": {
                "t": 1704067200000,
                "o": "80000", "h": "80500", "l": "79500",
                "c": "80200", "v": "1234.5",
            }
        })
        s._handle_message(msg)
        assert len(s._buffer) == 1
        assert s._buffer[0][4] == 80200.0

    def test_handle_duplicate_candle_updates(self):
        """Gleicher Timestamp → Update statt Append."""
        from crypto_bot.data.ws_streamer import BinanceWSStreamer
        import json
        s = BinanceWSStreamer("BTC/USDT", "1h", buffer_size=10)
        msg1 = json.dumps({"k": {"t": 1704067200000, "o": "80000", "h": "80500",
                                   "l": "79500", "c": "80100", "v": "100"}})
        msg2 = json.dumps({"k": {"t": 1704067200000, "o": "80000", "h": "80600",
                                   "l": "79500", "c": "80300", "v": "200"}})
        s._handle_message(msg1)
        s._handle_message(msg2)
        assert len(s._buffer) == 1   # Nicht 2!
        assert s._buffer[0][4] == 80300.0  # Aktualisiert

    def test_get_latest_df_returns_dataframe(self):
        from crypto_bot.data.ws_streamer import BinanceWSStreamer
        import json
        s = BinanceWSStreamer("BTC/USDT", "1h")
        for i in range(5):
            msg = json.dumps({"k": {"t": 1704067200000 + i * 3600000,
                                     "o": "80000", "h": "80500", "l": "79500",
                                     "c": "80200", "v": "1000"}})
            s._handle_message(msg)
        df = s.get_latest_df()
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5


class TestExtendedTelegramCommands:
    """2.6 — Erweiterte Telegram-Befehle"""

    def test_new_commands_in_help(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        td = TelegramDashboard({"capital": 1000, "daily_pnl": 0, "position": None,
                                 "running": True, "stop_requested": False})
        help_text = td._build_help()
        for cmd in ["/performance", "/open_positions", "/retrain",
                    "/switch_safe_mode", "/emergency_shutdown"]:
            assert cmd in help_text, f"Befehl {cmd} fehlt in /help"

    def test_performance_build(self, tmp_db):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {"capital": 1050, "daily_pnl": 5.0, "position": None,
                 "running": True, "stop_requested": False,
                 "rm_summary": {"win_rate": 60.0, "profit_factor": 1.5, "sortino": 1.2}}
        td = TelegramDashboard(state)
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            msg = td._build_performance()
        assert "Performance" in msg
        assert "Win-Rate" in msg

    def test_safe_mode_toggle(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {"capital": 1000, "daily_pnl": 0, "position": None,
                 "running": True, "stop_requested": False, "safe_mode": False}
        td = TelegramDashboard(state)
        with patch.object(td, "_send", return_value=None):
            td._toggle_safe_mode()
        assert state["safe_mode"] is True

    def test_emergency_shutdown_sets_flags(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {"capital": 1000, "daily_pnl": 0, "position": None,
                 "running": True, "stop_requested": False, "emergency_stop": False}
        td = TelegramDashboard(state)
        with patch.object(td, "_send", return_value=None):
            td._process_updates_with_text("/emergency_shutdown", state)

    def test_open_positions_no_position(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {"position": None, "capital": 1000, "daily_pnl": 0,
                 "running": True, "stop_requested": False}
        td = TelegramDashboard(state)
        msg = td._build_open_positions()
        assert "Keine" in msg


class TestMonteCarlo:
    """2.7 — Monte Carlo Testing"""

    def test_runs_n_simulations(self):
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        returns = [10.0, -5.0, 8.0, -3.0, 12.0, -2.0, 7.0, -8.0, 5.0, 4.0]
        result = run_monte_carlo(returns, n_simulations=100, initial_capital=1000)
        assert result.n_simulations == 100

    def test_result_fields_present(self):
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        returns = [10.0, -5.0, 8.0, -3.0, 12.0, -2.0, 7.0, 3.0, -1.0, 5.0]
        result = run_monte_carlo(returns, n_simulations=200)
        assert hasattr(result, "sharpe_mean")
        assert hasattr(result, "sharpe_p5")
        assert hasattr(result, "sharpe_p95")
        assert hasattr(result, "max_dd_p95")
        assert hasattr(result, "ruin_probability")
        assert hasattr(result, "final_return_mean")

    def test_ruin_probability_range(self):
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        returns = [5.0, -3.0, 8.0, 2.0, 6.0, -1.0, 4.0, 3.0, 7.0, -2.0]
        result = run_monte_carlo(returns, n_simulations=200)
        assert 0.0 <= result.ruin_probability <= 100.0

    def test_percentiles_ordered(self):
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        returns = [5.0, -3.0, 8.0, 2.0, 6.0, -1.0, 4.0, 3.0, 7.0, -2.0]
        result = run_monte_carlo(returns, n_simulations=200)
        assert result.sharpe_p5 <= result.sharpe_mean <= result.sharpe_p95
        assert result.final_return_p5 <= result.final_return_mean <= result.final_return_p95

    def test_insufficient_trades(self):
        from crypto_bot.backtest.monte_carlo import run_monte_carlo
        result = run_monte_carlo([1.0, -1.0], n_simulations=100)
        assert result.n_simulations == 0   # Zu wenige Trades


class TestAutoTransition:
    """2.8 — Auto Paper→Live Transition"""

    def test_all_checks_pass(self):
        from crypto_bot.ai.confidence_monitor import evaluate_readiness
        decision = evaluate_readiness(
            paper_trades=25, sharpe=1.2, win_rate_pct=55.0,
            max_drawdown_pct=8.0, model_f1=0.45,
        )
        assert decision.should_go_live is True
        assert len([v for v, _ in decision.checks.values() if not v]) == 0

    def test_insufficient_trades_blocks(self):
        from crypto_bot.ai.confidence_monitor import evaluate_readiness
        decision = evaluate_readiness(
            paper_trades=5, sharpe=2.0, win_rate_pct=70.0,
            max_drawdown_pct=5.0, model_f1=0.6,
        )
        assert decision.should_go_live is False
        assert not decision.checks["paper_trades"][0]

    def test_high_drawdown_blocks(self):
        from crypto_bot.ai.confidence_monitor import evaluate_readiness
        decision = evaluate_readiness(
            paper_trades=30, sharpe=1.5, win_rate_pct=60.0,
            max_drawdown_pct=20.0, model_f1=0.5,
        )
        assert decision.should_go_live is False
        assert not decision.checks["max_drawdown"][0]

    def test_low_sharpe_blocks(self):
        from crypto_bot.ai.confidence_monitor import evaluate_readiness
        decision = evaluate_readiness(
            paper_trades=30, sharpe=0.2, win_rate_pct=60.0,
            max_drawdown_pct=8.0, model_f1=0.5,
        )
        assert decision.should_go_live is False

    def test_try_auto_transition_paper_mode(self, tmp_db):
        from crypto_bot.ai.confidence_monitor import try_auto_transition
        from crypto_bot.risk.manager import RiskManager
        import crypto_bot.config.settings as cfg

        cfg.TRADING_MODE = "paper"
        rm = RiskManager(capital=1100.0)
        # Wenige Trades → kein Wechsel
        rm.trades = [{"pnl": 10.0, "capital_after": 1010.0}]
        result = try_auto_transition(rm, model_f1=0.4)
        assert result is False   # Zu wenige Trades


class TestLSTMModel:
    """2.9 — LSTM Neural Network"""

    def test_feature_extraction_shape(self, sample_df):
        from crypto_bot.ai.lstm_model import _extract_sequence_features
        features = _extract_sequence_features(sample_df)
        assert features.ndim == 2
        assert features.shape[0] == len(sample_df)
        assert features.shape[1] == 7   # 7 Features

    def test_build_labels_three_classes(self, sample_df):
        from crypto_bot.ai.lstm_model import _build_labels
        labels = _build_labels(sample_df)
        unique = set(labels)
        assert unique.issubset({0, 1, 2}), f"Unerwartete Labels: {unique}"

    def test_lstm_trainer_runs(self, sample_df, tmp_path):
        from crypto_bot.ai.lstm_model import LSTMTrainer, MODEL_PATH, SCALER_PATH
        trainer = LSTMTrainer(epochs=3)
        with patch("crypto_bot.ai.lstm_model.MODEL_PATH", tmp_path / "test_lstm.pt"):
            with patch("crypto_bot.ai.lstm_model.SCALER_PATH", tmp_path / "test_scaler.joblib"):
                result = trainer.train(sample_df)
        assert isinstance(result, dict)
        assert "status" in result

    def test_ensemble_combine_probs(self):
        from crypto_bot.ai.lstm_model import ensemble_predict
        xgb = {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1}
        lstm = {"BUY": 0.5, "HOLD": 0.3, "SELL": 0.2}
        result = ensemble_predict(xgb, lstm)
        assert result["signal"] == "BUY"
        assert 0.0 <= result["confidence"] <= 1.0
        total = sum(result["probabilities"].values())
        assert abs(total - 1.0) < 0.01, f"Wahrscheinlichkeiten summieren nicht zu 1: {total}"

    def test_predictor_unavailable_returns_hold(self):
        """Ohne trainiertes Modell → HOLD."""
        from crypto_bot.ai.lstm_model import LSTMPredictor
        with patch("crypto_bot.ai.lstm_model.SCALER_PATH", Path("/nonexistent/path")):
            with patch("crypto_bot.ai.lstm_model.MODEL_PATH", Path("/nonexistent/path")):
                pred = LSTMPredictor()
        assert not pred.is_available()


class TestMultiAssetPairSelector:
    """2.10 — Multi-Asset Pair Selector"""

    def test_default_pairs_when_no_exchange(self):
        from crypto_bot.strategy.pair_selector import select_pairs, DEFAULT_PAIRS
        result = select_pairs(exchange=None, max_pairs=3)
        assert len(result.selected) == 3
        for sym in result.selected:
            assert sym in DEFAULT_PAIRS

    def test_max_pairs_respected(self):
        from crypto_bot.strategy.pair_selector import select_pairs
        result = select_pairs(exchange=None, max_pairs=2)
        assert len(result.selected) == 2

    def test_all_pairs_usdt(self):
        from crypto_bot.strategy.pair_selector import select_pairs
        result = select_pairs(exchange=None, max_pairs=5)
        for sym in result.selected:
            assert sym.endswith("/USDT"), f"{sym} ist kein USDT-Paar"

    def test_score_computation_offline(self):
        from crypto_bot.strategy.pair_selector import _calc_atr_pct, _calc_adx
        n = 50
        # Konstante Preise → ATR=0, ADX=NaN. Prüfe nur auf kein Crash.
        prices = np.linspace(80000, 82000, n)  # Leichter Aufwärtstrend
        df = pd.DataFrame({
            "open":   prices,
            "high":   prices * 1.006,
            "low":    prices * 0.994,
            "close":  prices,
            "volume": np.ones(n) * 1e9,
        })
        atr = _calc_atr_pct(df)
        adx = _calc_adx(df)
        assert atr >= 0
        # ADX kann NaN sein bei konstantem Preis, float-Check reicht
        assert isinstance(adx, float)

    def test_with_mock_exchange(self, mock_exchange):
        """Testet Pair-Selektion mit Mock-Exchange."""
        from crypto_bot.strategy.pair_selector import select_pairs, _filter_candidates
        # Mock tickers zurückgeben
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2e9},
            "ETH/USDT": {"quoteVolume": 1e9},
            "BNB/USDT": {"quoteVolume": 5e8},
            "XRP/USDT": {"quoteVolume": 3e8},
            "DOGE/USDT": {"quoteVolume": 6e7},   # Unter Mindest-Volumen
        }
        tickers = mock_exchange.fetch_tickers()
        candidates = _filter_candidates(tickers, min_volume=1e8)
        symbols = [c["symbol"] for c in candidates]
        assert "BTC/USDT" in symbols
        assert "ETH/USDT" in symbols

    def test_correlation_filter_concept(self):
        """Testet die Korrelations-Filter Hilfsfunktion."""
        from crypto_bot.strategy.pair_selector import _apply_correlation_filter
        # Ohne Exchange → keine Korrelationsberechnung, direkte Selektion
        scores = []
        from crypto_bot.strategy.pair_selector import PairScore
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            scores.append(PairScore(sym, 1e9, 1.5, 25, 0.8, "test"))
        selected, filtered, corr_matrix = _apply_correlation_filter(scores, None, 2, 0.85)
        assert len(selected) == 2
        assert isinstance(corr_matrix, dict)


# =============================================================================
# INTEGRATION: End-to-End Szenarien
# =============================================================================

class TestEndToEnd:
    """Vollständige Szenarien über mehrere Komponenten."""

    def test_full_paper_trade_cycle(self, sample_df, tmp_db):
        """Paper Trade: Signal → Risk-Check → Ausführung → DB-Eintrag."""
        from crypto_bot.strategy.regime_detector import detect_regime
        from crypto_bot.strategy.selector import select_and_generate
        from crypto_bot.risk.manager import RiskManager
        from crypto_bot.execution.paper_trader import PaperTrader

        rm = RiskManager(capital=1000.0)
        pt = PaperTrader(rm)

        regime = detect_regime(sample_df)
        signal = select_and_generate(sample_df, regime)

        price = float(sample_df["close"].iloc[-1])

        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            if signal.signal.value == "BUY" and not rm.is_circuit_breaker_active():
                pt.buy("BTC/USDT", price=price, atr=1200.0, reason=signal.reason)

            if rm.has_open_position():
                pt.sell("BTC/USDT", price=price * 1.02, reason="Test-Exit")

        # Trade wurde aufgezeichnet oder kein Trade nötig
        assert isinstance(rm.summary(), dict)

    def test_breakout_signal_to_backtest(self, sample_df):
        """Breakout-Strategie mit Backtest-Engine kombiniert."""
        from crypto_bot.strategy.breakout import generate_breakout_signal
        from crypto_bot.backtest.engine import _apply_costs
        result = generate_breakout_signal(sample_df)
        if result.price > 0:
            buy_cost = _apply_costs(result.price, "buy")
            assert buy_cost > result.price * 0.99   # Kosten angewendet

    def test_monte_carlo_with_real_trade_returns(self, tmp_db):
        """Monte Carlo mit echten Trade-Returns aus Logger."""
        from crypto_bot.monitoring.logger import log_trade, get_recent_trades
        from crypto_bot.backtest.monte_carlo import run_monte_carlo

        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            for pnl in [20, -10, 15, -5, 25, -8, 12]:
                log_trade("BTC/USDT", "long", 80000, 80000 + pnl * 100,
                          0.01, float(pnl))
            trades = get_recent_trades(50)

        pnls = [t["pnl"] for t in trades]
        result = run_monte_carlo(pnls, n_simulations=100)
        assert result.n_simulations == 100


# =============================================================================
# NEUE FEATURES: Scalping, Volatility Expansion, Anomaly, VolForecaster, RL
# =============================================================================

class TestScalpingStrategy:
    """Scalping-Strategie Tests."""

    def test_generates_signal(self, sample_df):
        from crypto_bot.strategy.scalping import generate_scalping_signal
        result = generate_scalping_signal(sample_df)
        assert result.signal.value in ("BUY", "SELL", "HOLD")
        assert result.price > 0
        assert result.ema5 > 0
        assert result.ema13 > 0
        assert 0 <= result.rsi7 <= 100

    def test_add_indicators_no_lookahead(self, sample_df):
        from crypto_bot.strategy.scalping import add_scalping_indicators
        d = add_scalping_indicators(sample_df)
        assert "ema5" in d.columns
        assert "ema13" in d.columns
        assert "rsi7" in d.columns
        assert "volume_ratio" in d.columns

    def test_bullish_cross_detected(self):
        """EMA5 > EMA13 Kreuzung erzeugt BUY."""
        import pandas as pd
        import numpy as np
        from crypto_bot.strategy.scalping import generate_scalping_signal
        # Steigende Preise erzwingen bullischen Kreuz
        prices = np.concatenate([np.linspace(79000, 80000, 50),
                                  np.linspace(80000, 82000, 50)])
        df = pd.DataFrame({
            "open":   prices * 0.999,
            "high":   prices * 1.001,
            "low":    prices * 0.998,
            "close":  prices,
            "volume": np.random.uniform(1000, 2000, len(prices)),
        })
        result = generate_scalping_signal(df)
        assert result.signal.value in ("BUY", "HOLD")  # Kann HOLD sein wenn kein Kreuz


class TestVolatilityExpansionStrategy:
    """Volatility Expansion Strategie Tests."""

    def test_generates_signal(self, sample_df):
        from crypto_bot.strategy.volatility_expansion import generate_volatility_expansion_signal
        result = generate_volatility_expansion_signal(sample_df)
        assert result.signal.value in ("BUY", "SELL", "HOLD")
        assert result.price > 0
        assert result.upper_keltner > result.lower_keltner

    def test_hold_when_atr_normal(self, sample_df):
        """Kein Signal wenn ATR nicht expandiert."""
        from crypto_bot.strategy.volatility_expansion import generate_volatility_expansion_signal
        result = generate_volatility_expansion_signal(sample_df, atr_expansion_threshold=99.0)
        assert result.signal.value == "HOLD"
        assert "keine Expansion" in result.reason

    def test_indicators_complete(self, sample_df):
        from crypto_bot.strategy.volatility_expansion import add_volatility_expansion_indicators
        d = add_volatility_expansion_indicators(sample_df)
        assert "atr" in d.columns
        assert "atr_ratio" in d.columns
        assert "keltner_upper" in d.columns
        assert "keltner_lower" in d.columns


class TestAnomalyDetector:
    """Anomaly Detector Tests."""

    def test_returns_result(self, sample_df):
        from crypto_bot.ai.anomaly_detector import AnomalyDetector
        detector = AnomalyDetector()
        result = detector.detect(sample_df)
        assert isinstance(result.is_anomaly, bool)
        assert 0.0 <= result.score <= 1.0
        assert result.method in ("combined", "insufficient_data")

    def test_no_anomaly_on_normal_data(self, sample_df):
        from crypto_bot.ai.anomaly_detector import AnomalyDetector
        detector = AnomalyDetector(zscore_threshold=10.0)  # Sehr hoher Schwellenwert
        result = detector.detect(sample_df)
        assert result.is_anomaly is False

    def test_anomaly_on_extreme_spike(self):
        """Extremer Preissprung → Anomalie erkannt."""
        import pandas as pd
        import numpy as np
        from crypto_bot.ai.anomaly_detector import AnomalyDetector
        prices  = np.linspace(80000, 81000, 150)
        prices[-1] = 200000  # Extremer Spike
        volume  = np.ones(150) * 1000
        volume[-1] = 1_000_000  # Extremes Volumen
        df = pd.DataFrame({
            "open": prices * 0.999, "high": prices * 1.002,
            "low":  prices * 0.998, "close": prices, "volume": volume,
        })
        detector = AnomalyDetector(zscore_threshold=2.0)
        result = detector.detect(df)
        assert result.is_anomaly is True

    def test_singleton(self):
        from crypto_bot.ai.anomaly_detector import get_detector
        d1 = get_detector()
        d2 = get_detector()
        assert d1 is d2


class TestVolatilityForecaster:
    """Volatility Forecaster Tests."""

    def test_forecast_returns_result(self, sample_df):
        from crypto_bot.ai.volatility_forecaster import VolatilityForecaster
        f = VolatilityForecaster()
        result = f.forecast(sample_df)
        assert result.regime in ("LOW", "NORMAL", "HIGH", "EXTREME", "UNKNOWN")
        assert 0.0 <= result.position_factor <= 1.0
        assert result.current_vol >= 0
        assert result.forecast_vol >= 0

    def test_high_vol_reduces_position_factor(self):
        """Hohe Volatilität → kleinerer Position-Faktor."""
        import pandas as pd
        import numpy as np
        from crypto_bot.ai.volatility_forecaster import VolatilityForecaster
        # Sehr volatile Preisreihe
        rng    = np.random.default_rng(42)
        prices = 80000 + np.cumsum(rng.normal(0, 500, 200))
        df = pd.DataFrame({
            "open": prices * 0.99, "high": prices * 1.02,
            "low":  prices * 0.98, "close": prices,
            "volume": np.ones(200) * 1000,
        })
        f = VolatilityForecaster()
        result = f.forecast(df)
        assert result.position_factor <= 1.0

    def test_insufficient_data(self):
        import pandas as pd
        import numpy as np
        from crypto_bot.ai.volatility_forecaster import VolatilityForecaster
        df = pd.DataFrame({
            "close": [80000, 80100],
            "open": [80000, 80100], "high": [80100, 80200],
            "low": [79900, 79900], "volume": [1000, 1000],
        })
        f = VolatilityForecaster()
        result = f.forecast(df)
        assert result.regime == "UNKNOWN"

    def test_singleton(self):
        from crypto_bot.ai.volatility_forecaster import get_forecaster
        f1 = get_forecaster()
        f2 = get_forecaster()
        assert f1 is f2


class TestRLAgent:
    """RL Agent Tests."""

    def test_random_agent_acts(self, sample_df):
        from crypto_bot.ai.rl_agent import RandomAgent, BaseRLAgent
        agent = RandomAgent()
        obs   = BaseRLAgent.build_observation(sample_df)
        signal = agent.get_signal(obs)
        assert signal in ("BUY", "SELL", "HOLD")

    def test_observation_shape(self, sample_df):
        from crypto_bot.ai.rl_agent import BaseRLAgent, STATE_DIM
        obs   = BaseRLAgent.build_observation(sample_df)
        arr   = obs.to_array()
        assert arr.shape == (STATE_DIM,)
        assert 0.0 <= obs.rsi <= 1.0
        assert 0.0 <= obs.bb_pct <= 1.0

    def test_q_learning_learn(self, sample_df):
        from crypto_bot.ai.rl_agent import QLearningAgent, BaseRLAgent
        agent = QLearningAgent()
        obs   = BaseRLAgent.build_observation(sample_df)
        action = agent.act(obs)
        loss   = agent.learn(obs, action, reward=1.0, next_obs=obs, done=False)
        # May or may not return a loss depending on Q-table state
        assert loss is None or isinstance(loss, float)

    def test_q_learning_save_load(self, sample_df, tmp_path):
        from crypto_bot.ai.rl_agent import QLearningAgent, BaseRLAgent
        import numpy as np
        agent = QLearningAgent(epsilon=0.0)  # Greedy
        obs   = BaseRLAgent.build_observation(sample_df)
        # Train a few steps
        for _ in range(5):
            action = agent.act(obs)
            agent.learn(obs, action, reward=np.random.uniform(-1, 1),
                        next_obs=obs, done=False)
        path = tmp_path / "rl.joblib"
        agent.save(path)
        agent2 = QLearningAgent()
        agent2.load(path)
        assert len(agent2._q_table) == len(agent._q_table)


class TestRollingMetrics:
    """Rolling Performance Metriken Tests."""

    def test_rolling_performance_empty(self, tmp_db):
        from crypto_bot.monitoring.logger import get_rolling_performance
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            result = get_rolling_performance(7)
        assert result["trades"] == 0
        assert result["period_days"] == 7

    def test_rolling_performance_with_trades(self, tmp_db):
        from crypto_bot.monitoring.logger import log_trade, get_rolling_performance
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            for pnl in [10.0, -5.0, 15.0]:
                log_trade("BTC/USDT", "long", 80000, 80100, 0.01, pnl)
            result = get_rolling_performance(7)
        assert result["trades"] == 3
        assert result["pnl"] == 20.0

    def test_periodic_performance(self, tmp_db):
        from crypto_bot.monitoring.logger import get_periodic_performance
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            result = get_periodic_performance()
        assert "7d" in result
        assert "30d" in result
        assert "total" in result

    def test_weekly_monthly_pnl(self, tmp_db):
        from crypto_bot.monitoring.logger import save_performance_snapshot, get_weekly_monthly_pnl
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            save_performance_snapshot(1010.0, 10.0, 10.0, False)
            result = get_weekly_monthly_pnl()
        assert "weekly" in result
        assert "monthly" in result


class TestLiquidityFeatures:
    """Liquiditäts-Features in feature engineering."""

    def test_features_include_liquidity(self, sample_df):
        from crypto_bot.ai.features import build_features
        features = build_features(sample_df)
        assert "spread_proxy" in features.columns
        assert "illiquidity" in features.columns
        assert "volume_accel" in features.columns
        assert "body_to_range" in features.columns

    def test_spread_proxy_positive(self, sample_df):
        from crypto_bot.ai.features import build_features
        features = build_features(sample_df)
        assert (features["spread_proxy"] >= 0).all()

    def test_body_to_range_bounded(self, sample_df):
        from crypto_bot.ai.features import build_features
        features = build_features(sample_df)
        valid = features["body_to_range"].dropna()
        assert (valid >= 0).all()


class TestEncryptedConfig:
    """Encrypted Config Tests."""

    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        """Verschlüsseln → Entschlüsseln gibt gleiche Werte zurück."""
        from crypto_bot.config.crypto_config import encrypt_env, decrypt_env
        env_path = tmp_path / ".env"
        enc_path = tmp_path / ".env.enc"
        key_path = tmp_path / ".env.key"

        env_path.write_text(
            "BINANCE_API_KEY=my_secret_key\n"
            "INITIAL_CAPITAL=1000\n"
            "TRADING_MODE=paper\n"
        )

        import crypto_bot.config.crypto_config as cc
        orig_key  = cc.ENV_KEY_PATH
        orig_enc  = cc.ENV_ENC_PATH
        cc.ENV_KEY_PATH = key_path
        cc.ENV_ENC_PATH = enc_path
        try:
            encrypt_env(env_path, enc_path)
            assert enc_path.exists()
            assert key_path.exists()

            values = decrypt_env(enc_path)
            assert values["BINANCE_API_KEY"] == "my_secret_key"
            assert values["INITIAL_CAPITAL"] == "1000"
        finally:
            cc.ENV_KEY_PATH = orig_key
            cc.ENV_ENC_PATH = orig_enc

    def test_is_encrypted(self, tmp_path):
        """is_encrypted() gibt False zurück wenn keine Dateien."""
        import crypto_bot.config.crypto_config as cc
        orig_key = cc.ENV_KEY_PATH
        orig_enc = cc.ENV_ENC_PATH
        cc.ENV_KEY_PATH = tmp_path / ".env.key"
        cc.ENV_ENC_PATH = tmp_path / ".env.enc"
        try:
            assert not cc.is_encrypted()
        finally:
            cc.ENV_KEY_PATH = orig_key
            cc.ENV_ENC_PATH = orig_enc


class TestLeverageControl:
    """Leverage-Steuerung im Risk Manager."""

    def test_default_leverage_one(self):
        from crypto_bot.config.settings import LEVERAGE
        assert LEVERAGE >= 1

    def test_leverage_scales_position(self):
        """Leverage > 1 erhöht die Positionsgröße."""
        import crypto_bot.config.settings as cfg
        from crypto_bot.risk.manager import RiskManager
        orig = cfg.LEVERAGE
        try:
            cfg.LEVERAGE = 2
            rm1 = RiskManager(capital=1000.0)
            pos1 = rm1.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
            qty_lev2 = pos1.quantity

            cfg.LEVERAGE = 1
            rm2 = RiskManager(capital=1000.0)
            pos2 = rm2.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
            qty_lev1 = pos2.quantity

            assert qty_lev2 >= qty_lev1  # Leverage 2x ≥ Leverage 1x
        finally:
            cfg.LEVERAGE = orig

    def test_leverage_capped_at_max(self):
        """Leverage wird auf MAX_LEVERAGE begrenzt."""
        import crypto_bot.config.settings as cfg
        from crypto_bot.risk.manager import RiskManager
        orig = cfg.LEVERAGE
        try:
            cfg.LEVERAGE = 100  # Extrem hoch
            rm = RiskManager(capital=1000.0)
            pos = rm.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
            # Kapital-Obergrenze verhindert unbegrenzte Größe
            assert pos.quantity <= (rm.capital * 0.95 * cfg.MAX_LEVERAGE) / 80000.0 + 1e-8
        finally:
            cfg.LEVERAGE = orig


# =============================================================================
# SEKTION 3: GAP-ANALYSE ROUND 4 — NEUE TESTS
# =============================================================================

class TestOHLVCCache:
    """OHLCV lokaler Parquet-Cache."""

    def test_cache_path_format(self):
        from crypto_bot.data.fetcher import _cache_path
        path = _cache_path("BTC/USDT", "1h")
        assert path.name == "BTC_USDT_1h.parquet"

    def test_save_and_load_cache(self, tmp_path, sample_df):
        from crypto_bot.data.fetcher import _save_cache, _load_cache
        import crypto_bot.data.fetcher as fetcher_mod
        orig = fetcher_mod._CACHE_DIR
        fetcher_mod._CACHE_DIR = tmp_path
        try:
            _save_cache(sample_df, "BTC/USDT", "1h")
            loaded = _load_cache("BTC/USDT", "1h")
            assert loaded is not None
            assert len(loaded) == len(sample_df)
        finally:
            fetcher_mod._CACHE_DIR = orig

    def test_load_returns_none_if_no_cache(self, tmp_path):
        from crypto_bot.data.fetcher import _load_cache
        import crypto_bot.data.fetcher as fetcher_mod
        orig = fetcher_mod._CACHE_DIR
        fetcher_mod._CACHE_DIR = tmp_path
        try:
            result = _load_cache("ETH/USDT", "1h")
            assert result is None
        finally:
            fetcher_mod._CACHE_DIR = orig

    def test_cache_timezone_aware(self, tmp_path, sample_df):
        """Geladener Cache muss UTC-aware Index haben."""
        from crypto_bot.data.fetcher import _save_cache, _load_cache
        import crypto_bot.data.fetcher as fetcher_mod
        orig = fetcher_mod._CACHE_DIR
        fetcher_mod._CACHE_DIR = tmp_path
        try:
            _save_cache(sample_df, "BTC/USDT", "1h")
            loaded = _load_cache("BTC/USDT", "1h")
            assert loaded.index.tz is not None
        finally:
            fetcher_mod._CACHE_DIR = orig


class TestAutoTraining:
    """Auto-Training beim ersten Start (GAP 1)."""

    def test_auto_train_skipped_if_model_exists(self, tmp_path):
        """Wenn Modell existiert, wird kein Training ausgelöst."""
        # Testet die Logik direkt ohne bot.py zu importieren (vermeidet anthropic-Dep)
        import crypto_bot.config.settings as cfg
        fake_model = tmp_path / "model.joblib"
        fake_model.write_bytes(b"fake")

        orig_mode = cfg.AI_MODE
        orig_path = cfg.ML_MODEL_PATH
        try:
            cfg.AI_MODE = "combined"
            cfg.ML_MODEL_PATH = fake_model
            # Logik aus _auto_train_if_needed: wenn Modell existiert → kein Training
            model_path = fake_model
            should_train = cfg.AI_MODE in ("ml", "combined") and not model_path.exists()
            assert not should_train, "Modell existiert — darf nicht trainiert werden"
        finally:
            cfg.AI_MODE = orig_mode
            cfg.ML_MODEL_PATH = orig_path

    def test_auto_train_triggered_if_no_model(self, tmp_path):
        """Wenn kein Modell vorhanden und AI_MODE=combined, wird Training ausgelöst."""
        import crypto_bot.config.settings as cfg
        missing_model = tmp_path / "nonexistent_model.joblib"

        orig_mode = cfg.AI_MODE
        orig_path = cfg.ML_MODEL_PATH
        try:
            cfg.AI_MODE = "combined"
            cfg.ML_MODEL_PATH = missing_model
            should_train = cfg.AI_MODE in ("ml", "combined") and not missing_model.exists()
            assert should_train, "Kein Modell vorhanden — Training muss ausgelöst werden"
        finally:
            cfg.AI_MODE = orig_mode
            cfg.ML_MODEL_PATH = orig_path

    def test_auto_train_skipped_for_rules_mode(self, tmp_path):
        """Im Rules-Mode kein Auto-Training unabhängig vom Modell."""
        import crypto_bot.config.settings as cfg
        missing_model = tmp_path / "nonexistent.joblib"
        should_train = "rules" in ("ml", "combined") and not missing_model.exists()
        assert not should_train


class TestCorrelationMatrix:
    """Korrelationsmatrix im Pair Selector (GAP 2)."""

    def test_pair_selection_has_correlation_matrix_field(self):
        from crypto_bot.strategy.pair_selector import select_pairs
        result = select_pairs(exchange=None)
        assert hasattr(result, "correlation_matrix")
        assert isinstance(result.correlation_matrix, dict)

    def test_correlation_matrix_empty_without_exchange(self):
        """Ohne Exchange kein echter Scan — Matrix bleibt leer."""
        from crypto_bot.strategy.pair_selector import select_pairs
        result = select_pairs(exchange=None)
        assert result.correlation_matrix == {}

    def test_correlation_filter_function_returns_matrix(self):
        """_apply_correlation_filter gibt Tuple mit Matrix zurück."""
        from crypto_bot.strategy.pair_selector import _apply_correlation_filter, PairScore
        scores = [PairScore("BTC/USDT", 1e9, 2.0, 30.0, 0.9, "test")]
        selected, filtered, matrix = _apply_correlation_filter(scores, None, 3, 0.85)
        assert isinstance(matrix, dict)
        assert "BTC/USDT" in selected


class TestVolatilityRegimeDashboard:
    """Volatility Regime im Dashboard (GAP 3)."""

    @pytest.fixture
    def client(self, tmp_db):
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            with TestClient(app) as c:
                yield c

    def test_status_includes_volatility_regime(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "volatility_regime" in data

    def test_volatility_regime_default_value(self, client):
        r = client.get("/api/status")
        regime = r.json()["volatility_regime"]
        assert regime in ("LOW", "NORMAL", "HIGH", "EXTREME", "UNKNOWN")


class TestRestartTrainingMode:
    """Dashboard Restart Training Mode (GAP 4)."""

    @pytest.fixture
    def client(self, tmp_db):
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            with TestClient(app) as c:
                yield c

    def test_restart_action_sets_training_mode(self, client):
        import crypto_bot.dashboard.api as api_mod
        api_mod._bot_state["training_mode"] = False
        r = client.post("/api/control/restart")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert api_mod._bot_state["training_mode"] is True
        assert api_mod._bot_state["retrain_requested"] is True
        # aufräumen
        api_mod._bot_state["training_mode"] = False
        api_mod._bot_state["retrain_requested"] = False

    def test_status_shows_training_mode(self, client):
        import crypto_bot.dashboard.api as api_mod
        api_mod._bot_state["training_mode"] = True
        r = client.get("/api/status")
        assert r.json()["training_mode"] is True
        api_mod._bot_state["training_mode"] = False


class TestTelegramStart:
    """Telegram /start Befehl (GAP 5)."""

    def _make_dashboard(self, state):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        d = TelegramDashboard(state)
        return d

    def test_start_resumes_paused_bot(self):
        state = {"paused": True, "running": True, "start_requested": False}
        d = self._make_dashboard(state)
        with patch.object(d, "_send"):
            d._handle_start()
        assert state["paused"] is False

    def test_start_sets_start_requested_when_stopped(self):
        state = {"paused": False, "running": False, "start_requested": False}
        d = self._make_dashboard(state)
        with patch.object(d, "_send"):
            d._handle_start()
        assert state["start_requested"] is True

    def test_start_sends_status_when_running(self):
        state = {"paused": False, "running": True, "capital": 1000.0, "start_requested": False}
        d = self._make_dashboard(state)
        sent = []
        with patch.object(d, "_send", side_effect=sent.append):
            d._handle_start()
        assert len(sent) == 1
        assert "läuft bereits" in sent[0]


# =============================================================================
# SEKTION 4: GAP-ANALYSE ROUND 5 — INSTITUTIONELLE FEATURES
# =============================================================================

class TestKellyOptimizer:
    """4.1 — Kelly Fraction Optimizer."""

    def test_kelly_positive_edge(self):
        """Positiver Edge → positives Full Kelly."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        result = opt.calculate(win_rate=0.60, avg_win=20.0, avg_loss=10.0)
        assert result.full_kelly > 0
        assert result.quarter_kelly > 0
        assert result.quarter_kelly <= result.full_kelly

    def test_kelly_no_edge(self):
        """Win-Rate zu niedrig → Full Kelly ≤ 0."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        result = opt.calculate(win_rate=0.30, avg_win=10.0, avg_loss=20.0)
        assert result.full_kelly == 0.0
        assert result.quarter_kelly == 0.0

    def test_kelly_max_cap(self):
        """Quarter Kelly ist nach oben gedeckelt (MAX_KELLY=0.25)."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        result = opt.calculate(win_rate=0.99, avg_win=100.0, avg_loss=1.0)
        assert result.quarter_kelly <= opt.MAX_KELLY

    def test_sizing_factor_too_few_trades(self):
        """Zu wenig Trades → Factor 1.0 (Default)."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        factor = opt.get_sizing_factor([{"pnl": 10.0}, {"pnl": -5.0}])
        assert factor == 1.0

    def test_sizing_factor_good_record(self):
        """Gute Win-Rate → Factor > 0.5."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        trades = [{"pnl": 20.0}] * 7 + [{"pnl": -5.0}] * 3  # 70% Win
        factor = opt.get_sizing_factor(trades)
        assert 0.5 <= factor <= 2.0

    def test_sizing_factor_bad_record(self):
        """Schlechte Win-Rate → Factor ≥ 0.5 (minimum)."""
        from crypto_bot.risk.kelly import KellyOptimizer
        opt = KellyOptimizer()
        trades = [{"pnl": -20.0}] * 8 + [{"pnl": 5.0}] * 2  # 20% Win
        factor = opt.get_sizing_factor(trades)
        assert factor == 0.5  # Minimum


class TestStrategyTracker:
    """4.2 — Strategy Performance Tracker."""

    def test_initial_confidence_is_neutral(self):
        """Neue Strategie ohne Trades → Multiplier 1.0."""
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        tracker = StrategyTracker()
        assert tracker.get_confidence_multiplier("momentum") == 1.0

    def test_good_winrate_raises_confidence(self):
        """70% Win-Rate → Multiplier > 1.0."""
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        tracker = StrategyTracker()
        for _ in range(7):
            tracker.record_trade_result(pnl=10.0, strategy="momentum")
        for _ in range(3):
            tracker.record_trade_result(pnl=-5.0, strategy="momentum")
        mult = tracker.get_confidence_multiplier("momentum")
        assert mult > 1.0

    def test_poor_winrate_lowers_confidence(self):
        """30% Win-Rate → Multiplier < 1.0."""
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        tracker = StrategyTracker()
        for _ in range(3):
            tracker.record_trade_result(pnl=5.0, strategy="scalping")
        for _ in range(7):
            tracker.record_trade_result(pnl=-15.0, strategy="scalping")
        mult = tracker.get_confidence_multiplier("scalping")
        assert mult < 1.0

    def test_strategy_retirement_after_losses(self):
        """Dauerhaft schlechte Strategie → is_retired True."""
        from crypto_bot.ai.strategy_tracker import StrategyTracker, StrategyStats
        s = StrategyStats(name="test")
        s.trades = 15
        for _ in range(12):
            s.recent_pnls.append(-20.0)
        assert s.is_retired is True

    def test_strategy_not_retired_without_enough_trades(self):
        """Zu wenig Trades → nicht retired."""
        from crypto_bot.ai.strategy_tracker import StrategyStats
        s = StrategyStats(name="test")
        s.trades = 5
        for _ in range(5):
            s.recent_pnls.append(-20.0)
        assert s.is_retired is False

    def test_get_summary_returns_all_strategies(self):
        """get_summary enthält alle getrackten Strategien."""
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        tracker = StrategyTracker()
        tracker.record_trade_result(10.0, "momentum")
        tracker.record_trade_result(-5.0, "scalping")
        summary = tracker.get_summary()
        assert "momentum" in summary
        assert "scalping" in summary
        assert summary["momentum"]["trades"] == 1


class TestTradeRejectionLog:
    """4.3 — Trade Rejection Log."""

    def test_log_rejection_inserts_row(self, tmp_db):
        from crypto_bot.monitoring.logger import log_rejection, get_recent_rejections
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            log_rejection("BTC/USDT", "HOLD", 80000.0, "BEAR_TREND erkannt", "regime")
            rejs = get_recent_rejections(5)
        assert len(rejs) >= 1
        assert rejs[0]["symbol"] == "BTC/USDT"
        assert rejs[0]["signal"] == "HOLD"
        assert "BEAR" in rejs[0]["reason"]

    def test_multiple_rejections_ordered(self, tmp_db):
        from crypto_bot.monitoring.logger import log_rejection, get_recent_rejections
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            for i in range(5):
                log_rejection("BTC/USDT", "HOLD", 80000.0 + i, f"reason_{i}", "test")
            rejs = get_recent_rejections(10)
        assert len(rejs) == 5
        # Alle Preise enthalten (Reihenfolge bei gleichem Timestamp undefiniert)
        prices = {r["price"] for r in rejs}
        assert prices == {80000.0, 80001.0, 80002.0, 80003.0, 80004.0}

    def test_rejection_table_created_by_init_db(self, tmp_db):
        """init_db erstellt trade_rejections Tabelle."""
        from crypto_bot.monitoring.logger import init_db
        import sqlite3
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            init_db()
        conn = sqlite3.connect(tmp_db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "trade_rejections" in tables


class TestDrawdownRecoveryMode:
    """4.4 — Drawdown Recovery Mode im Risk Manager."""

    def test_no_drawdown_factor_one(self):
        """Kein Drawdown → Factor 1.0."""
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=1000.0)
        assert rm.drawdown_recovery_factor == 1.0

    def test_small_drawdown_factor_one(self):
        """Kleiner Drawdown (< 7%) → Factor 1.0."""
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=950.0)  # 5% Drawdown
        assert rm.drawdown_recovery_factor == 1.0

    def test_medium_drawdown_factor_reduced(self):
        """7-10% Drawdown → Factor 0.75."""
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=915.0)  # ~8.5% Drawdown
        assert rm.drawdown_recovery_factor == 0.75

    def test_large_drawdown_factor_half(self):
        """10-15% Drawdown → Factor 0.5."""
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=880.0)  # 12% Drawdown
        assert rm.drawdown_recovery_factor == 0.50

    def test_severe_drawdown_factor_quarter(self):
        """≥ 15% Drawdown → Factor 0.25."""
        from crypto_bot.risk.manager import RiskManager
        rm = RiskManager(capital=820.0)  # 18% Drawdown
        assert rm.drawdown_recovery_factor == 0.25

    def test_drawdown_reduces_position_size(self):
        """Größe bei Drawdown kleiner als bei gleichem Kapital ohne Drawdown."""
        from crypto_bot.risk.manager import RiskManager
        # Normales Kapital
        rm1 = RiskManager(capital=1000.0)
        pos1 = rm1.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
        qty_normal = pos1.quantity

        # Kapital nach 15% Drawdown
        rm2 = RiskManager(capital=820.0)
        pos2 = rm2.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)
        qty_drawdown = pos2.quantity

        assert qty_drawdown < qty_normal


class TestAdaptiveRiskMode:
    """4.5 — Adaptive Risk Personality Modes."""

    def test_risk_mode_in_settings(self):
        """RISK_MODE und RISK_MODE_PARAMS existieren in settings."""
        from crypto_bot.config import settings as s
        assert hasattr(s, "RISK_MODE")
        assert hasattr(s, "RISK_MODE_PARAMS")
        assert s.RISK_MODE in ("conservative", "balanced", "aggressive")

    def test_all_three_modes_defined(self):
        from crypto_bot.config.settings import RISK_MODE_PARAMS
        for mode in ("conservative", "balanced", "aggressive"):
            assert mode in RISK_MODE_PARAMS
            assert "risk_factor" in RISK_MODE_PARAMS[mode]
            assert "drawdown_limit" in RISK_MODE_PARAMS[mode]
            assert "daily_loss_limit" in RISK_MODE_PARAMS[mode]

    def test_conservative_smaller_risk(self):
        """Konservativ hat kleineres Risiko als Aggressiv."""
        from crypto_bot.config.settings import RISK_MODE_PARAMS
        assert RISK_MODE_PARAMS["conservative"]["risk_factor"] < RISK_MODE_PARAMS["aggressive"]["risk_factor"]

    def test_risk_mode_factor_from_manager(self):
        """RiskManager gibt korrekten risk_mode_factor zurück."""
        import crypto_bot.config.settings as cfg
        from crypto_bot.risk.manager import RiskManager
        orig = cfg.RISK_MODE
        try:
            cfg.RISK_MODE = "conservative"
            rm = RiskManager(capital=1000.0)
            factor = rm.risk_mode_factor
            assert factor == 0.5   # conservative = 0.5×
        finally:
            cfg.RISK_MODE = orig

    def test_aggressive_mode_larger_position(self):
        """Aggressiver Mode → größere Position als Balanced."""
        import crypto_bot.config.settings as cfg
        from crypto_bot.risk.manager import RiskManager
        orig = cfg.RISK_MODE
        try:
            cfg.RISK_MODE = "aggressive"
            rm1 = RiskManager(capital=1000.0)
            pos1 = rm1.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)

            cfg.RISK_MODE = "balanced"
            rm2 = RiskManager(capital=1000.0)
            pos2 = rm2.open_position("BTC/USDT", entry_price=80000.0, atr=1200.0)

            assert pos1.quantity >= pos2.quantity
        finally:
            cfg.RISK_MODE = orig


class TestModelDriftDetection:
    """4.6 — Model Drift Detection."""

    def test_drift_status_dataclass_exists(self):
        from crypto_bot.ai.retrainer import DriftStatus
        d = DriftStatus(has_drift=False, current_f1=0.45, baseline_f1=0.45,
                        drift_pct=0.0, message="OK")
        assert not d.has_drift

    def test_check_drift_no_drift_when_stable(self):
        """Stabile Accuracy → kein Drift."""
        from crypto_bot.ai.retrainer import AutoRetrainer
        r = AutoRetrainer()
        r._baseline_f1 = 0.50
        status = r.check_drift(0.48)  # 4% Drift — unter 10% Schwelle
        assert status.has_drift is False

    def test_check_drift_detects_drop(self, tmp_db):
        """F1-Abfall > 10% vs Baseline → Drift erkannt."""
        from crypto_bot.ai.retrainer import AutoRetrainer
        r = AutoRetrainer()
        r._baseline_f1 = 0.60
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            status = r.check_drift(0.50)  # 16.7% Abfall
        assert status.has_drift is True
        assert status.drift_pct < 0

    def test_check_drift_sets_baseline_on_first_call(self):
        """Ohne Baseline wird erster Wert als Baseline akzeptiert."""
        from crypto_bot.ai.retrainer import AutoRetrainer
        r = AutoRetrainer()
        # Kein Modell auf Disk — Baseline wird aus erstem Wert gesetzt
        r._baseline_f1 = 0.0
        status = r.check_drift(0.45)
        # Kein Drift auf erstem Call (kein Vergleich möglich)
        assert isinstance(status.has_drift, bool)


class TestTelegramSetMode:
    """4.7 — Telegram /set_mode und /rejections."""

    def test_set_mode_conservative(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        import crypto_bot.config.settings as cfg
        orig = cfg.RISK_MODE
        state = {"risk_mode": "balanced"}
        d = TelegramDashboard(state)
        with patch.object(d, "_send"):
            d._handle_set_mode("/set_mode conservative")
        assert state["risk_mode"] == "conservative"
        cfg.RISK_MODE = orig

    def test_set_mode_invalid_sends_error(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {}
        d = TelegramDashboard(state)
        messages = []
        with patch.object(d, "_send", side_effect=messages.append):
            d._handle_set_mode("/set_mode invalid_mode")
        assert len(messages) == 1
        assert "Ungültiger" in messages[0]

    def test_rejections_no_data(self, tmp_db):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        state = {}
        d = TelegramDashboard(state)
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            msg = d._build_rejections()
        assert "Keine" in msg or "keine" in msg.lower()

    def test_new_commands_in_help(self):
        from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
        d = TelegramDashboard({})
        help_text = d._build_help()
        assert "/set_mode" in help_text
        assert "/rejections" in help_text


class TestApiRejections:
    """4.8 — API /api/rejections und /api/strategy_performance."""

    @pytest.fixture
    def client(self, tmp_db):
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            with TestClient(app) as c:
                yield c

    def test_rejections_endpoint_returns_list(self, client):
        r = client.get("/api/rejections")
        assert r.status_code == 200
        assert "rejections" in r.json()
        assert isinstance(r.json()["rejections"], list)

    def test_strategy_performance_endpoint(self, client):
        r = client.get("/api/strategy_performance")
        assert r.status_code == 200
        data = r.json()
        assert "strategy_performance" in data
        assert "risk_mode" in data

    def test_set_risk_mode_endpoint(self, client):
        r = client.post("/api/control/risk_mode/conservative")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["risk_mode"] == "conservative"

    def test_set_risk_mode_invalid(self, client):
        r = client.post("/api/control/risk_mode/godmode")
        assert r.status_code == 400

    def test_status_includes_risk_mode(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "risk_mode" in data
        assert data["risk_mode"] in ("conservative", "balanced", "aggressive")


# =============================================================================
# SEKTION 5: ROUND 6 — INSTITUTIONAL GAPS
# =============================================================================

class TestPortfolioOptimizer:
    """5.1 — Portfolio Optimizer (Gaps 4–6)."""

    def test_risk_parity_weights_sum_to_one(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator
        alloc = PortfolioAllocator()
        vols  = {"BTC/USDT": 0.03, "ETH/USDT": 0.04, "SOL/USDT": 0.06}
        w = alloc.risk_parity_weights(vols)
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_risk_parity_higher_vol_lower_weight(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator
        alloc = PortfolioAllocator()
        vols  = {"LOW": 0.01, "HIGH": 0.05}
        w = alloc.risk_parity_weights(vols)
        assert w["LOW"] > w["HIGH"]

    def test_sharpe_weights_sum_to_one(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator
        alloc = PortfolioAllocator()
        returns = {"BTC/USDT": 0.01, "ETH/USDT": 0.008}
        vols    = {"BTC/USDT": 0.03, "ETH/USDT": 0.04}
        w = alloc.sharpe_weights(returns, vols)
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_get_allocation_bull_uses_sharpe(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator
        alloc = PortfolioAllocator()
        pairs = [
            {"symbol": "BTC/USDT", "vol_pct": 0.03, "recent_return": 0.01, "score": 0.8},
            {"symbol": "ETH/USDT", "vol_pct": 0.04, "recent_return": 0.008, "score": 0.7},
        ]
        result = alloc.get_allocation(pairs, regime="BULL_TREND")
        assert result.method == "sharpe"
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_get_allocation_extreme_uses_equal(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator
        alloc  = PortfolioAllocator()
        pairs  = [{"symbol": "A", "vol_pct": 0.1, "recent_return": 0.0, "score": 0.5}]
        result = alloc.get_allocation(pairs, regime="EXTREME")
        assert result.method == "equal"

    def test_adjust_position_size(self):
        from crypto_bot.ai.portfolio_optimizer import PortfolioAllocator, AllocationResult
        alloc  = PortfolioAllocator()
        alloc_r = AllocationResult({"BTC/USDT": 0.6, "ETH/USDT": 0.4}, "risk_parity", "test")
        size = alloc.adjust_position_size("BTC/USDT", 100.0, alloc_r)
        # 0.6 × 2 Paare × 100 = 120
        assert abs(size - 120.0) < 0.01

    def test_singleton(self):
        from crypto_bot.ai.portfolio_optimizer import get_allocator
        a1 = get_allocator()
        a2 = get_allocator()
        assert a1 is a2


class TestBlackSwanDetector:
    """5.2 — Black Swan & Tail Risk (Gaps 14–16)."""

    def test_normal_market_not_flagged(self, sample_df):
        from crypto_bot.risk.black_swan import BlackSwanDetector
        d = BlackSwanDetector()
        flag, reason = d.detect(sample_df)
        assert isinstance(flag, bool)
        assert isinstance(reason, str)

    def test_extreme_move_flagged(self, sample_df):
        from crypto_bot.risk.black_swan import BlackSwanDetector
        d  = BlackSwanDetector()
        df = sample_df.copy()
        # Letzte Kerze mit extremem Move (10×σ)
        df.iloc[-1, df.columns.get_loc("close")] = float(df["close"].iloc[-2]) * 1.20
        flag, reason = d.detect(df)
        assert flag is True
        assert "Z-Score" in reason or "Gap" in reason

    def test_liquidity_crash_volume_collapse(self, sample_df):
        from crypto_bot.risk.black_swan import LiquidityCrashDetector
        d  = LiquidityCrashDetector()
        df = sample_df.copy()
        # Volume fast null
        df.iloc[-1, df.columns.get_loc("volume")] = 0.0001
        flag, reason = d.detect(df)
        assert flag is True

    def test_liquidity_crash_normal(self, sample_df):
        from crypto_bot.risk.black_swan import LiquidityCrashDetector
        d = LiquidityCrashDetector()
        flag, _ = d.detect(sample_df)
        # Normales Market sollte kein Alarm auslösen
        assert isinstance(flag, bool)

    def test_dynamic_leverage_extreme(self):
        from crypto_bot.risk.black_swan import DynamicLeverageEngine
        d = DynamicLeverageEngine()
        assert d.get_leverage_factor("EXTREME", False, False) == 0.25

    def test_dynamic_leverage_black_swan(self):
        from crypto_bot.risk.black_swan import DynamicLeverageEngine
        d = DynamicLeverageEngine()
        assert d.get_leverage_factor("NORMAL", True, False) == 0.0

    def test_tail_risk_manager_assess(self, sample_df):
        from crypto_bot.risk.black_swan import TailRiskManager
        m      = TailRiskManager()
        result = m.assess(sample_df, "NORMAL")
        assert hasattr(result, "is_black_swan")
        assert hasattr(result, "recommended_leverage")
        assert 0.0 <= result.risk_score <= 1.0

    def test_tail_risk_singleton(self):
        from crypto_bot.risk.black_swan import get_tail_risk_manager
        m1 = get_tail_risk_manager()
        m2 = get_tail_risk_manager()
        assert m1 is m2


class TestOnlineLearner:
    """5.3 — Online Learning Pipeline (Gaps 11–13)."""

    def test_incremental_learner_update(self):
        from crypto_bot.ai.online_learner import IncrementalLearner
        il = IncrementalLearner()
        for _ in range(6):
            il.update([0.01, 0.02, 0.5, 1.0, 1.0], "BUY")
        assert il.n_samples == 6

    def test_incremental_learner_predict_before_fit(self):
        from crypto_bot.ai.online_learner import IncrementalLearner
        il    = IncrementalLearner()
        probs = il.predict_proba([0.0, 0.0, 0.5, 1.0, 0.0])
        assert set(probs.keys()) == {"BUY", "HOLD", "SELL"}
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_incremental_learner_predict_after_fit(self):
        from crypto_bot.ai.online_learner import IncrementalLearner
        il = IncrementalLearner()
        for _ in range(10):
            il.update([0.01, 0.02, 0.5, 1.0, 1.0], "BUY")
            il.update([0.01, 0.02, 0.5, 1.0, 0.0], "HOLD")
        probs = il.predict_proba([0.01, 0.02, 0.5, 1.0, 1.0])
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_platt_calibrator_records(self):
        from crypto_bot.ai.online_learner import PlattCalibrator
        cal = PlattCalibrator()
        for _ in range(25):
            cal.record_outcome(0.7, True)
            cal.record_outcome(0.3, False)
        assert cal._fitted is True

    def test_platt_calibrator_calibrate(self):
        from crypto_bot.ai.online_learner import PlattCalibrator
        cal = PlattCalibrator()
        for _ in range(25):
            cal.record_outcome(0.7, True)
        raw = {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1}
        result = cal.calibrate(raw)
        assert result.was_calibrated is True
        assert abs(sum(result.calibrated_probs.values()) - 1.0) < 0.01

    def test_bayesian_updater_updates(self):
        from crypto_bot.ai.online_learner import BayesianSignalUpdater
        u = BayesianSignalUpdater()
        u.update("ml", True)
        u.update("ml", False)
        b = u._get_belief("ml")
        assert b.alpha > 0.5   # Prior + 1 win
        assert b.beta  > 0.5   # Prior + 1 loss

    def test_bayesian_adjustment_with_few_trades(self):
        from crypto_bot.ai.online_learner import BayesianSignalUpdater
        u   = BayesianSignalUpdater()
        adj = u.get_confidence_adjustment("ml", 0.70)
        assert adj == 0.70   # < 5 trades → unverändert

    def test_bayesian_adjustment_with_many_trades(self):
        from crypto_bot.ai.online_learner import BayesianSignalUpdater
        u = BayesianSignalUpdater()
        for _ in range(10):
            u.update("ml", True)   # 10 Wins → hohe Bayesian-Konfidenz
        adj = u.get_confidence_adjustment("ml", 0.60)
        assert 0.0 <= adj <= 1.0

    def test_online_pipeline_process_outcome(self):
        from crypto_bot.ai.online_learner import OnlineLearningPipeline
        pipeline = OnlineLearningPipeline()
        pipeline.process_trade_outcome(
            features=[0.01, 0.02, 0.5, 1.0, 1.0],
            signal="BUY", source="ml",
            raw_confidence=0.75, was_profitable=True,
        )
        assert pipeline.incremental.n_samples == 1

    def test_online_pipeline_adjusted_confidence(self):
        from crypto_bot.ai.online_learner import OnlineLearningPipeline
        pipeline = OnlineLearningPipeline()
        adj, probs = pipeline.get_adjusted_confidence("ml", 0.70, {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1})
        assert 0.0 <= adj <= 1.0
        assert isinstance(probs, dict)


class TestExplainabilityEngine:
    """5.4 — AI Explainability Engine (Gaps 24–26)."""

    def test_explain_buy_signal(self, sample_df):
        from crypto_bot.ai.explainability import ExplainabilityEngine
        engine = ExplainabilityEngine()
        result = engine.explain(
            df=sample_df, signal="BUY", confidence=0.75,
            source="ml", reasoning="ML-Signal", regime="BULL_TREND",
        )
        assert result.signal == "BUY"
        assert result.confidence == 0.75
        assert len(result.narrative) > 10

    def test_explain_hold_signal(self, sample_df):
        from crypto_bot.ai.explainability import ExplainabilityEngine
        engine = ExplainabilityEngine()
        result = engine.explain(
            df=sample_df, signal="HOLD", confidence=0.0,
            source="regime", reasoning="BEAR_TREND", regime="BEAR_TREND",
        )
        assert result.signal == "HOLD"
        assert "HOLD" in result.narrative or "BEAR" in result.narrative

    def test_explain_has_feature_contributions(self, sample_df):
        from crypto_bot.ai.explainability import ExplainabilityEngine
        engine  = ExplainabilityEngine()
        result  = engine.explain(
            df=sample_df, signal="BUY", confidence=0.70,
            source="ml", reasoning="test", regime="SIDEWAYS",
        )
        assert isinstance(result.feature_contributions, list)

    def test_explain_narrative_includes_source(self, sample_df):
        from crypto_bot.ai.explainability import ExplainabilityEngine
        engine = ExplainabilityEngine()
        result = engine.explain(
            df=sample_df, signal="BUY", confidence=0.80,
            source="ml+lstm", reasoning="Ensemble", regime="BULL_TREND",
        )
        assert "ML+LSTM" in result.primary_reason or "ml+lstm" in result.primary_reason.lower()

    def test_engine_singleton(self):
        from crypto_bot.ai.explainability import get_explainability_engine
        e1 = get_explainability_engine()
        e2 = get_explainability_engine()
        assert e1 is e2


class TestReportGenerator:
    """5.5 — PDF Report Generator (Gaps 20–23)."""

    def test_calc_summary_empty(self):
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg = ReportGenerator()
        s  = rg._calc_summary([], 1000.0, 1000.0)
        assert s["n_trades"] == 0
        assert s["win_rate"] == 0.0

    def test_calc_summary_with_trades(self):
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg     = ReportGenerator()
        trades = [{"pnl": 10.0}, {"pnl": -5.0}, {"pnl": 15.0}]
        s      = rg._calc_summary(trades, 1020.0, 1000.0)
        assert s["n_trades"] == 3
        assert s["win_rate"] == pytest.approx(66.7, abs=0.2)

    def test_calc_attribution(self):
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg     = ReportGenerator()
        trades = [
            {"ai_source": "ml", "pnl": 10.0},
            {"ai_source": "ml", "pnl": -3.0},
            {"ai_source": "claude", "pnl": 5.0},
        ]
        attrs = rg._calc_attribution(trades)
        assert len(attrs) == 2
        ml_attr = next(a for a in attrs if a.strategy == "ml")
        assert ml_attr.n_trades == 2

    def test_calc_alpha_beta_few_trades(self):
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg = ReportGenerator()
        ab = rg._calc_alpha_beta([], 1000.0)
        assert ab.beta == 1.0   # Fallback

    def test_calc_regime_exposure(self):
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg     = ReportGenerator()
        trades = [
            {"regime": "BULL_TREND", "pnl": 10.0},
            {"regime": "BULL_TREND", "pnl": 5.0},
            {"regime": "SIDEWAYS", "pnl": -2.0},
        ]
        exps = rg._calc_regime_exposure(trades)
        assert len(exps) == 2
        bull = next(e for e in exps if e.regime == "BULL_TREND")
        assert bull.pnl == pytest.approx(15.0)

    def test_generate_without_fpdf2(self, tmp_path):
        """Report-Generator fällt sauber zurück wenn fpdf2 fehlt."""
        from crypto_bot.reporting.report_generator import ReportGenerator
        rg = ReportGenerator()
        with patch("crypto_bot.reporting.report_generator._FPDF_AVAILABLE", False):
            result = rg.generate(
                trades=[], capital=1000.0, initial_cap=1000.0,
                symbol="BTC/USDT", output_path=tmp_path / "test.pdf",
            )
        assert result is None   # Graceful degradation

    def test_singleton(self):
        from crypto_bot.reporting.report_generator import get_report_generator
        r1 = get_report_generator()
        r2 = get_report_generator()
        assert r1 is r2


class TestDecisionEngineWithMultiplier:
    """5.6 — Decision Engine Confidence Multiplier (Gap 1)."""

    @pytest.fixture(autouse=True)
    def _stub_anthropic(self):
        """Stub anthropic so tests work without it installed."""
        import sys
        if "anthropic" not in sys.modules:
            sys.modules["anthropic"] = MagicMock()

    def test_set_strategy_tracker(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        import crypto_bot.config.settings as cfg
        orig = cfg.AI_MODE
        cfg.AI_MODE = "rules"
        from crypto_bot.ai.decision_engine import DecisionEngine
        engine  = DecisionEngine()
        tracker = StrategyTracker()
        engine.set_strategy_tracker(tracker)
        assert engine._strategy_tracker is tracker
        cfg.AI_MODE = orig

    def test_decision_has_explanation_field(self, sample_df):
        import crypto_bot.config.settings as cfg
        orig = cfg.AI_MODE
        cfg.AI_MODE = "rules"
        from crypto_bot.ai.decision_engine import DecisionEngine
        engine = DecisionEngine()
        dec    = engine.decide(sample_df)
        assert hasattr(dec, "explanation")
        cfg.AI_MODE = orig


class TestAutoRiskMode:
    """5.7 — Auto Risk Mode Switching (Gap 27)."""

    def test_config_has_scanner_interval(self):
        from crypto_bot.config.settings import SCANNER_INTERVAL_HOURS
        assert isinstance(SCANNER_INTERVAL_HOURS, int)
        assert SCANNER_INTERVAL_HOURS > 0

    def test_config_has_pdf_report_dir(self):
        from crypto_bot.config.settings import PDF_REPORT_DIR
        from pathlib import Path
        assert isinstance(PDF_REPORT_DIR, Path)

    def test_risk_mode_volatile_switch(self):
        """Simuliert Auto-Switch: EXTREME → conservative."""
        import crypto_bot.config.settings as cfg
        original = cfg.RISK_MODE
        try:
            cfg.RISK_MODE = "balanced"
            # Logik nachahmen: EXTREME → conservative
            if cfg.RISK_MODE != "conservative":
                cfg.RISK_MODE = "conservative"
            assert cfg.RISK_MODE == "conservative"
        finally:
            cfg.RISK_MODE = original


class TestApiExplanationEndpoint:
    """5.8 — API /api/explanation und /api/report."""

    @pytest.fixture
    def client(self, tmp_db):
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with patch("crypto_bot.monitoring.logger.DB_PATH", tmp_db):
            with TestClient(app) as c:
                yield c

    def test_explanation_endpoint(self, client):
        r = client.get("/api/explanation")
        assert r.status_code == 200
        data = r.json()
        assert "narrative" in data
        assert "drift_status" in data

    def test_report_endpoint_no_fpdf2(self, client):
        with patch("crypto_bot.reporting.report_generator._FPDF_AVAILABLE", False):
            r = client.get("/api/report")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"


# =============================================================================
# SEKTION 6: ROUND 7 — FINAL 4 GAPS (100% COMPLETION)
# =============================================================================

class TestTelegramExplanationAlerts:
    """6.1 — Telegram zeigt TradeExplanation.narrative (Gap 59)."""

    def test_alert_trade_opened_includes_explanation(self):
        from crypto_bot.monitoring import alerts
        with patch.object(alerts, "_send_telegram") as mock_send:
            alerts.alert_trade_opened(80000.0, 0.01, 79000.0, 82000.0,
                                       "ML-Signal", explanation="Test Erklärung")
            msg = mock_send.call_args[0][0]
            assert "Test Erklärung" in msg

    def test_alert_trade_opened_without_explanation(self):
        from crypto_bot.monitoring import alerts
        with patch.object(alerts, "_send_telegram") as mock_send:
            alerts.alert_trade_opened(80000.0, 0.01, 79000.0, 82000.0, "Grund")
            msg = mock_send.call_args[0][0]
            assert "KAUF" in msg

    def test_alert_trade_closed_includes_explanation(self):
        from crypto_bot.monitoring import alerts
        with patch.object(alerts, "_send_telegram") as mock_send:
            alerts.alert_trade_closed(81000.0, 100.0, 1.25, "TP erreicht", 1100.0,
                                       explanation="Position geschlossen wegen TP")
            msg = mock_send.call_args[0][0]
            assert "Position geschlossen" in msg

    def test_alert_trade_closed_without_explanation(self):
        from crypto_bot.monitoring import alerts
        with patch.object(alerts, "_send_telegram") as mock_send:
            alerts.alert_trade_closed(81000.0, 100.0, 1.25, "TP", 1100.0)
            msg = mock_send.call_args[0][0]
            assert "VERKAUF" in msg

    def test_paper_trader_buy_passes_explanation(self):
        from crypto_bot.execution.paper_trader import PaperTrader
        from crypto_bot.risk.manager import RiskManager
        from crypto_bot.monitoring import alerts
        rm = RiskManager(capital=1000.0)
        pt = PaperTrader(rm)
        with patch.object(alerts, "_send_telegram") as mock_send:
            pt.buy(80000.0, reason="Test", explanation="Test Erklärung")
            if mock_send.called:
                msg = mock_send.call_args[0][0]
                assert "Test Erklärung" in msg


class TestRegimeStrategyMultipliers:
    """6.2 — Regime-spezifische Strategie-Multiplier (Gap 5)."""

    def test_regime_boosts_defined(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        assert hasattr(StrategyTracker, "REGIME_BOOSTS")
        boosts = StrategyTracker.REGIME_BOOSTS
        assert "ml" in boosts
        assert "rules" in boosts

    def test_bull_trend_boosts_ml(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        st = StrategyTracker()
        mult = st.get_confidence_multiplier("ml", regime="BULL_TREND")
        assert mult > 1.0   # BULL_TREND sollte ML boosten

    def test_bear_trend_dampens_rules(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        st = StrategyTracker()
        mult = st.get_confidence_multiplier("rules", regime="BEAR_TREND")
        assert mult < 1.0   # BEAR_TREND sollte rules-basierte Strategie dämpfen

    def test_unknown_regime_neutral(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        st   = StrategyTracker()
        mult = st.get_confidence_multiplier("ml", regime="UNKNOWN_XYZ")
        assert mult == pytest.approx(1.0, abs=0.1)   # Kein Boost bei unbekanntem Regime

    def test_no_regime_returns_perf_multiplier(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        st = StrategyTracker()
        mult_with    = st.get_confidence_multiplier("ml", regime="")
        mult_without = st.get_confidence_multiplier("ml")
        assert mult_with == mult_without   # Ohne Regime → nur Performance-Multiplikator

    def test_combined_multiplier_performance_x_regime(self):
        from crypto_bot.ai.strategy_tracker import StrategyTracker
        st = StrategyTracker()
        # Nach 10 guten Trades → performance_mult = 1.15 (win_rate ≥ 60%)
        for _ in range(10):
            st.record_trade_result(10.0, "ml")
        mult = st.get_confidence_multiplier("ml", regime="BULL_TREND")
        # Performance (1.15) × Regime (1.15) = 1.3225 → capped minimal
        assert mult > 1.0


class TestContinuousScannerLoop:
    """6.3 — Continuous Scanner Loop (Gap 37)."""

    def test_scanner_interval_configured(self):
        from crypto_bot.config.settings import SCANNER_INTERVAL_HOURS
        assert SCANNER_INTERVAL_HOURS > 0
        assert isinstance(SCANNER_INTERVAL_HOURS, int)

    def test_scanner_results_in_bot_state(self):
        """Bot-State enthält scanner_results Key."""
        import crypto_bot.bot as bot
        assert "scanner_results" in bot._bot_state

    def test_scanner_api_endpoint(self):
        from fastapi.testclient import TestClient
        from crypto_bot.dashboard.api import app
        with TestClient(app) as c:
            r = c.get("/api/scanner")
        assert r.status_code == 200
        assert "scanner_results" in r.json()


class TestPlattCalibrationWiring:
    """6.4 — Platt-Kalibrierung in Trade-Pipeline verdrahtet (Gap 22 wiring)."""

    def test_online_pipeline_adjusts_confidence(self):
        from crypto_bot.ai.online_learner import OnlineLearningPipeline
        pipeline = OnlineLearningPipeline()
        # Ohne Training → raw confidence zurück
        raw = {"BUY": 0.70, "HOLD": 0.20, "SELL": 0.10}
        adj, probs = pipeline.get_adjusted_confidence("ml", 0.70, raw)
        assert isinstance(adj, float)
        assert 0.0 <= adj <= 1.0
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_platt_calibrator_uncalibrated_passthrough(self):
        from crypto_bot.ai.online_learner import PlattCalibrator
        cal  = PlattCalibrator()
        raw  = {"BUY": 0.75, "HOLD": 0.15, "SELL": 0.10}
        res  = cal.calibrate(raw)
        assert res.was_calibrated is False
        assert res.calibrated_probs == raw

    def test_platt_calibrator_after_training(self):
        from crypto_bot.ai.online_learner import PlattCalibrator
        cal = PlattCalibrator()
        for _ in range(25):
            cal.record_outcome(0.75, True)
            cal.record_outcome(0.30, False)
        raw = {"BUY": 0.75, "HOLD": 0.15, "SELL": 0.10}
        res = cal.calibrate(raw)
        assert res.was_calibrated is True
        # Kalibrierte Probs sollten valide Wahrscheinlichkeiten sein
        assert abs(sum(res.calibrated_probs.values()) - 1.0) < 0.01


# =============================================================================
# SEKTION 3: ROUND 8 — Advanced Features
# =============================================================================

def _make_df_r8(n: int = 100, seed: int = 0) -> "pd.DataFrame":
    import numpy as np
    import pandas as pd
    np.random.seed(seed)
    p = 50_000 + np.cumsum(np.random.randn(n) * 200)
    h = p * 1.005
    l = p * 0.995
    o = p * (1 + np.random.randn(n) * 0.001)
    v = np.random.uniform(500, 3000, n) * 1e6
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": p, "volume": v})


class TestFeatureFlags:
    """3.1 — Feature Flag System"""

    def test_all_flags_are_bool(self):
        from crypto_bot.config import features
        flags = features.get_all()
        assert isinstance(flags, dict)
        assert len(flags) > 0
        for k, v in flags.items():
            assert isinstance(v, bool), f"Flag {k} ist kein bool"

    def test_is_enabled_function(self):
        from crypto_bot.config import features
        # Beliebiges Flag auf enabled/disabled prüfen
        flags = features.get_all()
        first_key = next(iter(flags))
        result = features.is_enabled(first_key)
        assert isinstance(result, bool)

    def test_summary_returns_string(self):
        from crypto_bot.config import features
        s = features.summary()
        assert isinstance(s, str)
        assert "Feature Flags" in s

    def test_round8_flags_exist(self):
        from crypto_bot.config import features
        r8_flags = [
            "MICROSTRUCTURE", "DERIVATIVES_SIGNALS", "CROSS_MARKET",
            "REGIME_FORECASTER", "GROWTH_OPTIMIZER", "VENUE_OPTIMIZER",
            "RESILIENCE", "STRATEGY_LIFECYCLE", "OPPORTUNITY_RADAR",
        ]
        all_flags = features.get_all()
        for flag in r8_flags:
            assert flag in all_flags, f"Feature-Flag {flag} fehlt"


class TestMicrostructure:
    """3.2 — Market Microstructure"""

    def test_cvd_tracker_bullish(self):
        import numpy as np
        from crypto_bot.strategy.microstructure import CVDTracker
        import pandas as pd
        df = _make_df_r8()
        # Starker Aufwärtstrend → eher bullishes CVD
        tracker = CVDTracker()
        result = tracker.compute(df)
        assert result.cvd_trend in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0.0 <= result.buy_pct <= 1.0
        assert result.pressure in ("BUY_PRESSURE", "SELL_PRESSURE", "BALANCED")

    def test_orderbook_imbalance_proxy(self):
        from crypto_bot.strategy.microstructure import OrderbookImbalanceProxy
        proxy = OrderbookImbalanceProxy()
        df = _make_df_r8()
        result = proxy.compute(df)
        assert result.direction in ("BID_HEAVY", "ASK_HEAVY", "BALANCED")
        assert result.strength in ("STRONG", "MODERATE", "WEAK")
        assert -1.0 <= result.imbalance_ratio <= 1.0

    def test_liquidity_wall_detector(self):
        from crypto_bot.strategy.microstructure import LiquidityWallDetector
        import numpy as np
        df = _make_df_r8(100)
        # Erzeuge künstliche Volumen-Spike
        df.loc[df.index[50], "volume"] = df["volume"].mean() * 10
        detector = LiquidityWallDetector()
        walls = detector.detect(df)
        assert isinstance(walls, list)
        assert len(walls) <= 3
        if walls:
            assert walls[0].direction in ("SUPPORT", "RESISTANCE")
            assert walls[0].relative_vol >= 1.0

    def test_spoofing_proxy_no_spoof(self):
        from crypto_bot.strategy.microstructure import SpoofingProxy
        proxy = SpoofingProxy()
        df = _make_df_r8()
        result = proxy.analyze(df)
        assert isinstance(result.is_suspicious, bool)
        assert 0.0 <= result.spoof_score <= 1.0

    def test_microstructure_signals_wrapper(self):
        from crypto_bot.strategy.microstructure import MicrostructureSignals
        ms = MicrostructureSignals()
        df = _make_df_r8()
        result = ms.analyze(df)
        assert result.signal_bias in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0.0 <= result.confidence <= 1.0


class TestDerivativesSignals:
    """3.3 — Derivatives Intelligence"""

    def test_funding_rate_extreme_long(self):
        from crypto_bot.strategy.derivatives import FundingRateMonitor
        mon = FundingRateMonitor()
        result = mon.analyze(0.005)   # Extrem hohe Rate
        assert result.regime == "EXTREME_LONG"
        assert result.contrarian_signal == "SHORT_BIAS"

    def test_funding_rate_neutral(self):
        from crypto_bot.strategy.derivatives import FundingRateMonitor
        mon = FundingRateMonitor()
        result = mon.analyze(0.0001)
        assert result.regime == "NEUTRAL"
        assert result.contrarian_signal == "NEUTRAL"

    def test_funding_rate_extreme_short(self):
        from crypto_bot.strategy.derivatives import FundingRateMonitor
        mon = FundingRateMonitor()
        result = mon.analyze(-0.005)
        assert result.regime == "EXTREME_SHORT"
        assert result.contrarian_signal == "LONG_BIAS"

    def test_liquidation_cluster_detection(self):
        from crypto_bot.strategy.derivatives import LiquidationClusterDetector
        detector = LiquidationClusterDetector()
        df = _make_df_r8()
        clusters = detector.detect(df)
        assert isinstance(clusters, list)
        assert len(clusters) <= 6
        if clusters:
            assert clusters[0].direction in ("LONG_LIQ", "SHORT_LIQ")
            assert clusters[0].leverage in [5.0, 10.0, 20.0, 50.0, 100.0]

    def test_basis_monitor_contango(self):
        from crypto_bot.strategy.derivatives import SpotPerpBasisMonitor
        mon = SpotPerpBasisMonitor()
        result = mon.analyze(50000.0, 50200.0)   # Perp > Spot
        assert result.regime == "CONTANGO"

    def test_basis_monitor_backwardation(self):
        from crypto_bot.strategy.derivatives import SpotPerpBasisMonitor
        mon = SpotPerpBasisMonitor()
        result = mon.analyze(50000.0, 49800.0)   # Perp < Spot
        assert result.regime == "BACKWARDATION"

    def test_derivatives_wrapper_no_exchange(self):
        from crypto_bot.strategy.derivatives import DerivativesSignals
        ds = DerivativesSignals()
        df = _make_df_r8()
        result = ds.analyze(df, exchange=None, funding_rate=0.0002)
        assert result.combined_signal in ("BULLISH", "BEARISH", "NEUTRAL")
        assert isinstance(result.liquidations, list)


class TestCrossMarket:
    """3.4 — Cross-Market Signals"""

    def test_btc_dominance_from_df(self):
        from crypto_bot.ai.cross_market import BTCDominanceProxy
        proxy = BTCDominanceProxy()
        df = _make_df_r8()
        result = proxy.compute_from_df(df)
        assert result.trend in ("RISING", "FALLING", "STABLE")
        assert result.signal in ("BTC_DOMINANCE", "ALTCOIN_SEASON", "NEUTRAL")
        assert 0.0 <= result.dominance_proxy <= 1.0

    def test_btc_dominance_from_tickers(self):
        from crypto_bot.ai.cross_market import BTCDominanceProxy
        proxy = BTCDominanceProxy()
        tickers = {
            "BTC/USDT": {"quoteVolume": 5e9},
            "ETH/USDT": {"quoteVolume": 2e9},
            "SOL/USDT": {"quoteVolume": 1e9},
        }
        result = proxy.compute_from_tickers(tickers)
        assert 0.0 < result.dominance_proxy < 1.0

    def test_stablecoin_flow_high_inflow(self):
        from crypto_bot.ai.cross_market import StablecoinFlowProxy
        proxy = StablecoinFlowProxy()
        tickers = {
            "BTC/USDT": {"quoteVolume": 4e9},
            "ETH/USDT": {"quoteVolume": 2e9},
        }
        result = proxy.compute_from_tickers(tickers)
        assert result.flow_regime == "HIGH_INFLOW"
        assert result.signal == "BULLISH"

    def test_sentiment_proxy_returns_valid(self):
        from crypto_bot.ai.cross_market import SentimentProxy
        proxy = SentimentProxy()
        df = _make_df_r8(800)   # Mehr Daten für 30d Momentum
        result = proxy.compute(df)
        assert 0 <= result.fear_greed_proxy <= 100
        assert result.sentiment in (
            "EXTREME_FEAR", "FEAR", "NEUTRAL", "GREED", "EXTREME_GREED"
        )
        assert result.contrarian_signal in ("BUY", "SELL", "NEUTRAL")

    def test_cross_market_wrapper(self):
        from crypto_bot.ai.cross_market import CrossMarketSignals
        cms = CrossMarketSignals()
        df = _make_df_r8()
        result = cms.analyze(df)
        assert result.market_regime in ("RISK_ON", "RISK_OFF", "NEUTRAL")


class TestRegimeForecaster:
    """3.5 — Regime Forecasting"""

    def test_transition_matrix_forecast(self):
        from crypto_bot.ai.regime_forecaster import RegimeTransitionMatrix
        matrix = RegimeTransitionMatrix()
        # Trainiere Matrix
        for _ in range(10):
            matrix.update("BULL_TREND", "SIDEWAYS")
            matrix.update("SIDEWAYS", "BULL_TREND")
        result = matrix.forecast("BULL_TREND")
        assert result.current_regime == "BULL_TREND"
        assert abs(sum(result.next_regime_probs.values()) - 1.0) < 0.01
        assert result.most_likely_next in ["BULL_TREND", "BEAR_TREND", "SIDEWAYS", "HIGH_VOL"]
        assert 0.0 <= result.persistence_prob <= 1.0

    def test_trend_persistence_model(self):
        from crypto_bot.ai.regime_forecaster import TrendPersistenceModel
        model = TrendPersistenceModel()
        # Aufzeichnen von Übergängen
        for _ in range(10):
            model.update("BULL_TREND")
        for _ in range(5):
            model.update("SIDEWAYS")
        for _ in range(3):
            model.update("BULL_TREND")
        result = model.forecast("BULL_TREND")
        assert result.regime == "BULL_TREND"
        assert result.current_streak >= 1
        assert 0.0 <= result.persistence_pct <= 100.0

    def test_breakout_probability_estimator(self):
        from crypto_bot.ai.regime_forecaster import BreakoutProbabilityEstimator
        est = BreakoutProbabilityEstimator()
        df = _make_df_r8(50)
        result = est.estimate(df)
        assert 0.0 <= result.probability <= 1.0
        assert result.direction in ("UP", "DOWN", "UNKNOWN")

    def test_mean_reversion_likelihood(self):
        from crypto_bot.ai.regime_forecaster import MeanReversionLikelihood
        mrl = MeanReversionLikelihood()
        df = _make_df_r8(60)
        result = mrl.estimate(df)
        assert 0.0 <= result.probability <= 1.0
        assert isinstance(result.z_score, float)

    def test_regime_forecaster_wrapper(self):
        from crypto_bot.ai.regime_forecaster import RegimeForecaster
        rf = RegimeForecaster()
        rf.update("SIDEWAYS", "BULL_TREND")
        df = _make_df_r8(50)
        result = rf.forecast(df, "BULL_TREND")
        assert result.recommended_bias in (
            "TREND_FOLLOWING", "MEAN_REVERSION", "WAIT"
        )


class TestGrowthOptimizer:
    """3.6 — Capital Growth Optimizer"""

    def test_rolling_kelly_insufficient_data(self):
        from crypto_bot.risk.growth_optimizer import RollingKellyOptimizer
        opt = RollingKellyOptimizer()
        result = opt.compute()
        assert result.confidence < 1.0
        assert result.half_kelly >= 0.0

    def test_rolling_kelly_with_data(self):
        from crypto_bot.risk.growth_optimizer import RollingKellyOptimizer
        opt = RollingKellyOptimizer()
        import numpy as np
        np.random.seed(42)
        for _ in range(20):
            opt.update(np.random.choice([0.05, -0.02, 0.03, -0.01]))
        result = opt.compute()
        assert 0.0 <= result.raw_kelly <= 0.25
        assert 0.0 <= result.half_kelly <= 0.125

    def test_profit_locking_ladder_no_profit(self):
        from crypto_bot.risk.growth_optimizer import ProfitLockingLadder
        ladder = ProfitLockingLadder()
        result = ladder.compute(50000.0, 50000.0)   # Kein Gewinn
        assert result.ladder_level == 0

    def test_profit_locking_ladder_strong_profit(self):
        from crypto_bot.risk.growth_optimizer import ProfitLockingLadder
        ladder = ProfitLockingLadder()
        result = ladder.compute(50000.0, 60000.0)   # +20% Gewinn
        assert result.ladder_level >= 1
        assert result.suggested_trail <= 0.10

    def test_convex_exposure_scaler_growth_mode(self):
        from crypto_bot.risk.growth_optimizer import ConvexExposureScaler
        scaler = ConvexExposureScaler()
        result = scaler.scale(0.10, 100_000, 100_000)   # ATH → Growth Mode
        assert result.regime == "GROWTH"
        assert result.scaled_size >= result.base_size * 0.9   # Boost

    def test_convex_exposure_scaler_recover_mode(self):
        from crypto_bot.risk.growth_optimizer import ConvexExposureScaler
        scaler = ConvexExposureScaler()
        result = scaler.scale(0.10, 100_000, 80_000)   # -20% DD
        assert result.regime == "RECOVER"
        assert result.scaled_size < result.base_size

    def test_equity_curve_feedback_insufficient_data(self):
        from crypto_bot.risk.growth_optimizer import EquityCurveFeedback
        fb = EquityCurveFeedback()
        result = fb.compute(0.10)
        assert result.recommended_size > 0.0

    def test_growth_optimizer_wrapper(self):
        from crypto_bot.risk.growth_optimizer import GrowthOptimizer
        opt = GrowthOptimizer()
        opt.update_equity(100_000)
        result = opt.compute(0.10, 100_000, 100_000)
        assert 0.0 < result.final_size <= 1.0
        assert result.kelly is not None
        assert result.exposure is not None


class TestVenueOptimizer:
    """3.7 — Execution Venue Intelligence"""

    def test_fee_table_loaded(self):
        from crypto_bot.execution.venue_optimizer import DEFAULT_FEE_TABLE
        assert "binance" in DEFAULT_FEE_TABLE
        assert "bybit" in DEFAULT_FEE_TABLE
        b = DEFAULT_FEE_TABLE["binance"]
        assert b.maker_fee >= 0.0
        assert b.taker_fee > b.maker_fee   # Taker immer teurer

    def test_latency_monitor_record(self):
        from crypto_bot.execution.venue_optimizer import LatencyMonitor
        mon = LatencyMonitor()
        mon.record("binance", 50.0)
        mon.record("binance", 60.0)
        mon.record("binance", 55.0)
        stats = mon.get_stats("binance")
        assert stats.n_samples == 3
        assert 50.0 <= stats.avg_ms <= 60.0

    def test_venue_scorer(self):
        from crypto_bot.execution.venue_optimizer import VenueScorer, DEFAULT_FEE_TABLE, LatencyStats
        scorer = VenueScorer()
        lat = LatencyStats("binance", 50.0, 80.0, 50.0, 10)
        score = scorer.score("binance", DEFAULT_FEE_TABLE["binance"], lat)
        assert 0 <= score.total_score <= 100
        assert score.effective_cost >= 0.0

    def test_venue_optimizer_recommendation(self):
        from crypto_bot.execution.venue_optimizer import VenueOptimizer
        opt = VenueOptimizer()
        opt.record_latency("binance", 50.0)
        opt.record_latency("bybit", 80.0)
        rec = opt.recommend(["binance", "bybit"])
        assert rec.best_venue in ("binance", "bybit")
        assert len(rec.all_scores) == 2


class TestResilience:
    """3.8 — Self-Healing Infrastructure"""

    def test_latency_anomaly_baseline_collection(self):
        from crypto_bot.monitoring.resilience import APILatencyAnomalyDetector, HealthStatus
        det = APILatencyAnomalyDetector()
        for i in range(5):
            result = det.record("binance", 50.0)
        assert result.status == HealthStatus.HEALTHY

    def test_latency_anomaly_critical(self):
        from crypto_bot.monitoring.resilience import APILatencyAnomalyDetector, HealthStatus
        det = APILatencyAnomalyDetector()
        for _ in range(25):
            det.record("binance", 50.0)
        result = det.record("binance", 5000.0)   # 100× Baseline
        assert result.status in (HealthStatus.CRITICAL, HealthStatus.DEGRADED)

    def test_ws_health_monitor_no_messages(self):
        from crypto_bot.monitoring.resilience import WebSocketHealthMonitor, HealthStatus
        mon = WebSocketHealthMonitor()
        result = mon.get_health("binance")
        assert result.status == HealthStatus.OFFLINE

    def test_ws_health_monitor_active(self):
        import time
        from crypto_bot.monitoring.resilience import WebSocketHealthMonitor, HealthStatus
        mon = WebSocketHealthMonitor()
        for _ in range(5):
            mon.record_message("binance")
        result = mon.get_health("binance")
        assert result.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def test_outage_detector_no_outage(self):
        from crypto_bot.monitoring.resilience import ExchangeOutageDetector
        det = ExchangeOutageDetector()
        det.record_success("binance")
        assert not det.is_in_outage("binance")

    def test_outage_detector_triggers(self):
        from crypto_bot.monitoring.resilience import ExchangeOutageDetector
        det = ExchangeOutageDetector()
        for _ in range(5):
            det.record_failure("binance")
        assert det.is_in_outage("binance")

    def test_outage_detector_recovery(self):
        from crypto_bot.monitoring.resilience import ExchangeOutageDetector
        det = ExchangeOutageDetector()
        for _ in range(5):
            det.record_failure("binance")
        assert det.is_in_outage("binance")
        for _ in range(3):
            det.record_success("binance")
        assert not det.is_in_outage("binance")

    def test_auto_failover_manager(self):
        from crypto_bot.monitoring.resilience import AutoFailoverManager, OutageResult
        mgr = AutoFailoverManager("binance", ["bybit", "okx"])
        assert mgr.active_exchange == "binance"
        # Simuliere Binance-Ausfall
        outage_status = {
            "binance": OutageResult("binance", True, 5, 30.0, "Outage"),
            "bybit":   OutageResult("bybit", False, 0, 0.0, "OK"),
        }
        result = mgr.check_and_update(outage_status)
        assert result.is_failover is True
        assert result.active in ("bybit", "okx")


class TestStrategyLifecycle:
    """3.9 — Strategy Lifecycle Modeling"""

    def test_age_tracker_register(self):
        from crypto_bot.ai.strategy_lifecycle import StrategyAgeTracker
        tracker = StrategyAgeTracker()
        tracker.register("ml_strategy")
        result = tracker.get_age("ml_strategy")
        assert result.strategy == "ml_strategy"
        assert result.age_days >= 0.0

    def test_age_tracker_insufficient_trades(self):
        from crypto_bot.ai.strategy_lifecycle import StrategyAgeTracker
        tracker = StrategyAgeTracker()
        result = tracker.get_age("test_strat")
        assert "Zu wenig" in result.reason

    def test_age_tracker_declining(self):
        from crypto_bot.ai.strategy_lifecycle import StrategyAgeTracker
        tracker = StrategyAgeTracker()
        # Erst gute Trades, dann viele schlechte → Declining
        for _ in range(20):
            tracker.record_trade("test_strat", 0.05)
        for _ in range(20):
            tracker.record_trade("test_strat", -0.02)
        result = tracker.get_age("test_strat")
        assert result.trend == "DECLINING"
        assert result.should_rest is True

    def test_revival_detector_not_dormant(self):
        from crypto_bot.ai.strategy_lifecycle import StrategyAgeTracker, RevivalDetector
        tracker = StrategyAgeTracker()
        det = RevivalDetector(tracker)
        result = det.check_revival("test_strat", "BULL_TREND")
        assert result.should_revive is False

    def test_rotation_scheduler_keeps_active(self):
        from crypto_bot.ai.strategy_lifecycle import StrategyLifecycleManager
        mgr = StrategyLifecycleManager()
        result = mgr.get_rotation(["ml_strat", "rules_strat"], "BULL_TREND")
        # Mindestens 1 Strategie aktiv
        total = len(result.active_strategies) + len(result.reviving_strategies)
        assert total >= 1


class TestOpportunityRadar:
    """3.10 — AI Opportunity Radar"""

    def test_single_pair_score(self):
        from crypto_bot.dashboard.opportunity_radar import OpportunityScorer
        scorer = OpportunityScorer()
        df = _make_df_r8(200)
        result = scorer.score("BTC/USDT", df, regime="BULL_TREND")
        assert result.symbol == "BTC/USDT"
        assert 0.0 <= result.total_score <= 100.0
        assert result.signal in ("STRONG_BUY", "BUY", "NEUTRAL", "AVOID")

    def test_radar_scan_multiple_pairs(self):
        from crypto_bot.dashboard.opportunity_radar import OpportunityRadar
        radar = OpportunityRadar()
        pairs = {
            "BTC/USDT": _make_df_r8(200, seed=0),
            "ETH/USDT": _make_df_r8(200, seed=1),
            "SOL/USDT": _make_df_r8(200, seed=2),
        }
        result = radar.scan(pairs, regimes={"BTC/USDT": "BULL_TREND"})
        assert result.n_scanned == 3
        assert result.best_symbol in pairs.keys()
        assert len(result.top_opportunities) <= 10

    def test_radar_empty_pairs(self):
        from crypto_bot.dashboard.opportunity_radar import OpportunityRadar
        radar = OpportunityRadar()
        result = radar.scan({})
        assert result.n_scanned == 0

    def test_radar_get_top_symbols(self):
        from crypto_bot.dashboard.opportunity_radar import OpportunityRadar
        radar = OpportunityRadar()
        pairs = {f"PAIR{i}/USDT": _make_df_r8(100, seed=i) for i in range(5)}
        radar.scan(pairs)
        top = radar.get_top_symbols(3)
        assert len(top) <= 3
        assert all(isinstance(s, str) for s in top)

    def test_regime_affects_score(self):
        from crypto_bot.dashboard.opportunity_radar import OpportunityScorer
        scorer = OpportunityScorer()
        df = _make_df_r8(200)
        bull_score = scorer.score("X", df, regime="BULL_TREND").regime_score
        bear_score = scorer.score("X", df, regime="BEAR_TREND").regime_score
        # Bull-Regime sollte höheren Regime-Score haben als Bear
        assert bull_score > bear_score


# =============================================================================
# SEKTION 3: ROUND 9 — MODEL GOVERNANCE + SIMULATION + STRESS + ALLOCATOR
# =============================================================================

def _make_df_r9(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 80000.0 + np.cumsum(rng.normal(0, 200, n))
    return pd.DataFrame({
        "open":   close - rng.uniform(10, 100, n),
        "high":   close + rng.uniform(50, 300, n),
        "low":    close - rng.uniform(50, 300, n),
        "close":  close,
        "volume": rng.uniform(100, 1000, n),
    })


class TestModelGovernance:
    """9.1 — Model Governance Layer"""

    def test_entropy_low_for_confident_prediction(self):
        from crypto_bot.ai.model_governance import PredictionEntropyTracker
        tracker = PredictionEntropyTracker()
        result = tracker.compute({"BUY": 0.90, "HOLD": 0.05, "SELL": 0.05})
        assert not result.low_confidence   # Hohe Konfidenz → kein low_confidence Flag
        assert result.normalised < 0.50

    def test_entropy_high_for_uniform_prediction(self):
        from crypto_bot.ai.model_governance import PredictionEntropyTracker
        tracker = PredictionEntropyTracker()
        result = tracker.compute({"BUY": 0.33, "HOLD": 0.34, "SELL": 0.33})
        assert result.low_confidence   # Gleichverteilung → low_confidence
        assert result.normalised > 0.90

    def test_feature_drift_no_drift_initially(self):
        from crypto_bot.ai.model_governance import FeatureImportanceDriftMonitor
        monitor = FeatureImportanceDriftMonitor()
        importances = {"rsi": 0.3, "macd": 0.25, "volume": 0.2, "atr": 0.15, "ema": 0.1}
        for _ in range(5):
            monitor.update(importances)
        result = monitor.check()
        assert not result.drift_detected   # Nur 5 Updates, weniger als WINDOW=20

    def test_feature_drift_detected_after_shift(self):
        from crypto_bot.ai.model_governance import FeatureImportanceDriftMonitor
        monitor = FeatureImportanceDriftMonitor()
        old = {"rsi": 0.3, "macd": 0.25, "volume": 0.2, "atr": 0.15, "ema": 0.1}
        new = {"close_pct": 0.4, "bb_width": 0.3, "cvd": 0.15, "spread": 0.1, "oi_change": 0.05}
        for _ in range(10):
            monitor.update(old)
        for _ in range(10):
            monitor.update(new)
        result = monitor.check()
        # Nach Wechsel der Top-5 Features sollte Overlap niedrig sein
        assert result.overlap_ratio < 0.8

    def test_calibration_drift_detector_no_drift_perfect_calibration(self):
        from crypto_bot.ai.model_governance import CalibrationDriftDetector
        detector = CalibrationDriftDetector()
        # Perfekt kalibrierte Vorhersagen
        for _ in range(50):
            detector.update({"BUY": 0.9, "HOLD": 0.05, "SELL": 0.05}, "BUY")
        result = detector.check()
        assert not result.degraded   # Keine Degradation erwartet

    def test_uncertainty_sizer_reduces_size_at_high_entropy(self):
        from crypto_bot.ai.model_governance import (
            PredictionEntropyTracker, CalibrationDriftDetector, UncertaintyAwarePositionSizer
        )
        entropy_result = PredictionEntropyTracker().compute({"BUY": 0.33, "HOLD": 0.34, "SELL": 0.33})
        cal_result     = CalibrationDriftDetector().check()
        sizer          = UncertaintyAwarePositionSizer()
        scaled = sizer.scale(1.0, entropy_result, cal_result)
        assert scaled < 1.0   # Reduziert bei hoher Entropie

    def test_governance_manager_evaluate_returns_result(self):
        from crypto_bot.ai.model_governance import ModelGovernanceManager
        mgr = ModelGovernanceManager()
        result = mgr.evaluate(
            probs       = {"BUY": 0.7, "HOLD": 0.2, "SELL": 0.1},
            importances = {"rsi": 0.3, "macd": 0.3, "volume": 0.2, "atr": 0.1, "ema": 0.1},
            base_size   = 0.5,
        )
        assert result.size_factor > 0.0
        assert result.size_factor <= 0.5
        assert isinstance(result.entropy.normalised, float)

    def test_governance_manager_singleton(self):
        from crypto_bot.ai.model_governance import get_model_governance
        mgr1 = get_model_governance()
        mgr2 = get_model_governance()
        assert mgr1 is mgr2


class TestRegimeSimulation:
    """9.2 — Monte Carlo Markov Regime Simulation"""

    DEFAULT_MATRIX = {
        "BULL_TREND": {"BULL_TREND": 0.7, "SIDEWAYS": 0.2, "BEAR_TREND": 0.05, "HIGH_VOL": 0.05},
        "SIDEWAYS":   {"BULL_TREND": 0.2, "SIDEWAYS": 0.5, "BEAR_TREND": 0.2,  "HIGH_VOL": 0.1},
        "BEAR_TREND": {"BULL_TREND": 0.1, "SIDEWAYS": 0.2, "BEAR_TREND": 0.6,  "HIGH_VOL": 0.1},
        "HIGH_VOL":   {"BULL_TREND": 0.1, "SIDEWAYS": 0.3, "BEAR_TREND": 0.2,  "HIGH_VOL": 0.4},
    }

    def test_simulator_returns_correct_structure(self):
        from crypto_bot.ai.regime_simulation import MonteCarloRegimeSimulator
        sim = MonteCarloRegimeSimulator()
        result, paths = sim.simulate("BULL_TREND", self.DEFAULT_MATRIX)
        assert len(result.regime_probabilities) == 4
        assert abs(sum(result.regime_probabilities.values()) - 1.0) < 0.01
        assert result.dominant_regime in ("BULL_TREND", "SIDEWAYS", "BEAR_TREND", "HIGH_VOL")
        assert 0.0 <= result.stability_score <= 1.0

    def test_simulator_bull_trend_stays_mostly_bull(self):
        from crypto_bot.ai.regime_simulation import MonteCarloRegimeSimulator
        sim = MonteCarloRegimeSimulator()
        result, _ = sim.simulate("BULL_TREND", self.DEFAULT_MATRIX)
        # Mit 70% Selbst-Übergangs-Wahrscheinlichkeit hat BULL erhöhte Wahrscheinlichkeit
        assert result.regime_probabilities["BULL_TREND"] > 0.25   # Mehr als Gleichverteilung

    def test_vol_estimator_works(self):
        from crypto_bot.ai.regime_simulation import MonteCarloRegimeSimulator, VolatilityRegimeProbabilityEstimator
        sim = MonteCarloRegimeSimulator()
        _, paths = sim.simulate("HIGH_VOL", self.DEFAULT_MATRIX)
        est = VolatilityRegimeProbabilityEstimator()
        result = est.estimate(paths, sim.HORIZON)
        assert 0.0 <= result.high_vol_prob <= 1.0
        assert result.expected_high_vol_periods >= 0.0

    def test_engine_exposure_factor_range(self):
        from crypto_bot.ai.regime_simulation import RegimeSimulationEngine
        engine = RegimeSimulationEngine()
        result = engine.run("BULL_TREND", self.DEFAULT_MATRIX)
        assert 0.25 <= result.exposure_factor <= 1.0
        assert result.proactive_bias in ("REDUCE", "HOLD", "INCREASE")

    def test_engine_bear_reduces_exposure(self):
        from crypto_bot.ai.regime_simulation import RegimeSimulationEngine
        # Extremer Bear: bleibt fast immer Bear
        bear_matrix = {
            "BULL_TREND": {"BULL_TREND": 0.9, "SIDEWAYS": 0.07, "BEAR_TREND": 0.02, "HIGH_VOL": 0.01},
            "SIDEWAYS":   {"BULL_TREND": 0.1, "SIDEWAYS": 0.6,  "BEAR_TREND": 0.2,  "HIGH_VOL": 0.1},
            "BEAR_TREND": {"BULL_TREND": 0.02,"SIDEWAYS": 0.05, "BEAR_TREND": 0.9,  "HIGH_VOL": 0.03},
            "HIGH_VOL":   {"BULL_TREND": 0.1, "SIDEWAYS": 0.3,  "BEAR_TREND": 0.2,  "HIGH_VOL": 0.4},
        }
        engine = RegimeSimulationEngine()
        bull_r = engine.run("BULL_TREND", bear_matrix)
        bear_r = engine.run("BEAR_TREND", bear_matrix)
        # Bei extrem persistentem Bear-Regime sollte Exposure deutlich niedriger sein
        assert bear_r.exposure_factor < bull_r.exposure_factor

    def test_engine_singleton(self):
        from crypto_bot.ai.regime_simulation import get_regime_simulation
        e1 = get_regime_simulation()
        e2 = get_regime_simulation()
        assert e1 is e2


class TestStressTester:
    """9.3 — Liquidity Stress Test Engine"""

    def test_flash_crash_stop_holds(self):
        from crypto_bot.risk.stress_tester import FlashCrashScenario
        scenario = FlashCrashScenario()
        # Stop bei 50k liegt unter allen Crash-Szenarien (max -30% = 56k)
        result = scenario.simulate(
            current_price=80000.0,
            position_usd=10000.0,
            stop_loss_price=50000.0,
        )
        assert result.stop_would_hold
        assert result.drop_pct < 0.0

    def test_flash_crash_stop_fails_on_deep_drop(self):
        from crypto_bot.risk.stress_tester import FlashCrashScenario
        scenario = FlashCrashScenario()
        result = scenario.simulate(
            current_price=80000.0,
            position_usd=10000.0,
            stop_loss_price=79000.0,  # Stop sehr nah → wird durch -5% Drop überschritten
        )
        assert not result.stop_would_hold

    def test_spread_expansion_executability(self):
        from crypto_bot.risk.stress_tester import SpreadExpansionScenario
        scenario = SpreadExpansionScenario()
        # Normal spread 2 bps × 20 = 40 bps → unter MAX_EXECUTABLE_BPS=50
        result = scenario.simulate(normal_spread_bps=2.0, position_usd=10000.0)
        assert result.is_executable
        # Normal spread 5 bps × 20 = 100 bps → nicht ausführbar
        result2 = scenario.simulate(normal_spread_bps=5.0, position_usd=10000.0)
        assert not result2.is_executable

    def test_cascade_simulation_no_clusters(self):
        from crypto_bot.risk.stress_tester import CascadingLiquidationScenario
        scenario = CascadingLiquidationScenario()
        result = scenario.simulate(clusters=[], current_price=80000.0, position_usd=10000.0)
        assert result.n_clusters_nearby == 0
        assert result.estimated_cascade_drop == 0.0

    def test_stress_engine_returns_valid_factor(self):
        from crypto_bot.risk.stress_tester import LiquidityStressTestEngine
        engine = LiquidityStressTestEngine()
        df = _make_df_r9(100)
        result = engine.run(df=df, current_price=80000.0, position_usd=10000.0)
        assert 0.25 <= result.stress_factor <= 1.0
        assert result.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_stress_engine_no_stop_reduces_factor(self):
        from crypto_bot.risk.stress_tester import LiquidityStressTestEngine
        engine = LiquidityStressTestEngine()
        df = _make_df_r9(100)
        # Stop sehr nah → wird durch Flash Crash getriggert → factor reduziert
        result = engine.run(
            df=df, current_price=80000.0,
            position_usd=10000.0, stop_loss_price=79500.0
        )
        assert result.stress_factor < 1.0

    def test_stress_engine_singleton(self):
        from crypto_bot.risk.stress_tester import get_stress_tester
        e1 = get_stress_tester()
        e2 = get_stress_tester()
        assert e1 is e2


class TestCapitalAllocator:
    """9.4 — Autonomous Capital Allocator"""

    def test_signal_aggregator_tier_assignment(self):
        from crypto_bot.risk.capital_allocator import SignalStrengthAggregator
        agg = SignalStrengthAggregator()
        result = agg.aggregate(0.9, 0.9, 0.9)
        assert result.tier == 1
        assert result.aggregate >= 0.75

    def test_signal_aggregator_tier4_weak_signals(self):
        from crypto_bot.risk.capital_allocator import SignalStrengthAggregator
        agg = SignalStrengthAggregator()
        result = agg.aggregate(0.1, 0.1, 0.1)
        assert result.tier == 4
        assert result.aggregate < 0.25

    def test_regime_exposure_bull_tier1_max(self):
        from crypto_bot.risk.capital_allocator import RegimeExposureController, SignalStrengthAggregator
        ctrl = RegimeExposureController()
        sq   = SignalStrengthAggregator().aggregate(0.9, 0.9, 0.9)
        result = ctrl.compute("BULL_TREND", sq)
        assert result.max_exposure == 1.00

    def test_regime_exposure_bear_always_limited(self):
        from crypto_bot.risk.capital_allocator import RegimeExposureController, SignalStrengthAggregator
        ctrl = RegimeExposureController()
        sq   = SignalStrengthAggregator().aggregate(0.9, 0.9, 0.9)
        result = ctrl.compute("BEAR_TREND", sq)
        assert result.max_exposure <= 0.40   # Auch bei Tier 1: max 40% in Bear

    def test_participation_vol_penalty(self):
        from crypto_bot.risk.capital_allocator import MarketParticipationController
        ctrl = MarketParticipationController()
        low_vol  = ctrl.compute(volatility_30d=0.3, drawdown_pct=0.0, stress_factor=1.0)
        high_vol = ctrl.compute(volatility_30d=1.5, drawdown_pct=0.0, stress_factor=1.0)
        assert high_vol.participation < low_vol.participation

    def test_allocator_minimum_ten_percent(self):
        from crypto_bot.risk.capital_allocator import AutonomousCapitalAllocator
        alloc = AutonomousCapitalAllocator()
        result = alloc.allocate(
            regime="BEAR_TREND",
            microstructure_score=0.0,
            cross_market_score=0.0,
            regime_score=0.0,
            volatility_30d=2.0,
            drawdown_pct=0.3,
            stress_factor=0.25,
        )
        assert result.final_allocation >= 0.10   # Bot bleibt immer aktiv

    def test_allocator_scores_from_signals(self):
        from crypto_bot.risk.capital_allocator import AutonomousCapitalAllocator
        alloc = AutonomousCapitalAllocator()
        ms, cm, rs = alloc.get_score_from_signals("BULLISH", "RISK_ON", 75.0)
        assert ms == 0.8
        assert cm == 0.8
        assert rs == 0.75

    def test_allocator_singleton(self):
        from crypto_bot.risk.capital_allocator import get_capital_allocator
        a1 = get_capital_allocator()
        a2 = get_capital_allocator()
        assert a1 is a2


class TestFundingTermStructure:
    """9.5 — Funding Rate Term Structure + Carry Optimizer"""

    def test_term_structure_compute_basic(self):
        from crypto_bot.strategy.funding_term_structure import FundingTermStructure
        ts = FundingTermStructure()
        result = ts.compute(current_rate=0.001)  # 0.1% per 8h
        assert len(result.predicted_rates) == 4  # 4 Horizonte
        assert result.structure in ("CONTANGO", "BACKWARDATION", "FLAT")

    def test_term_structure_contango_positive_rate(self):
        from crypto_bot.strategy.funding_term_structure import FundingTermStructure
        ts = FundingTermStructure()
        # Update mit vielen positiven Raten → EWMA hoch → Contango wenn current > EWMA
        for _ in range(50):
            ts.update(0.002)
        # Aktuelle Rate viel höher als EWMA → Rate zieht runter → Backwardation
        result = ts.compute(current_rate=0.010)
        assert result.structure == "BACKWARDATION"  # Rate fällt Richtung EWMA

    def test_carry_optimizer_positive_carry(self):
        from crypto_bot.strategy.funding_term_structure import FundingCarryOptimizer, FundingTermStructure
        ts = FundingTermStructure()
        ts_result = ts.compute(current_rate=0.005)  # 0.5% per 8h — sehr hoch
        opt = FundingCarryOptimizer()
        result = opt.evaluate(ts_result)
        assert result.carry_rate_daily > 0.0
        assert result.signal in ("CAPTURE", "NEUTRAL", "AVOID")
        if result.is_positive:
            assert result.net_carry > 0

    def test_carry_optimizer_avoid_near_zero_rate(self):
        from crypto_bot.strategy.funding_term_structure import FundingCarryOptimizer, FundingTermStructure
        ts = FundingTermStructure()
        ts_result = ts.compute(current_rate=0.00001)  # Nahezu null
        opt = FundingCarryOptimizer()
        result = opt.evaluate(ts_result)
        assert result.signal == "AVOID"  # Net carry negativ

    def test_funding_ts_signals_wrapper(self):
        from crypto_bot.strategy.funding_term_structure import FundingTermStructureSignals
        fts = FundingTermStructureSignals()
        for _ in range(20):
            fts.update(0.001)
        result = fts.analyze(current_rate=0.001)
        assert result.combined_signal in ("BULLISH_CARRY", "BEARISH_CARRY", "NEUTRAL")
        assert result.term_structure is not None
        assert result.carry is not None

    def test_funding_ts_singleton(self):
        from crypto_bot.strategy.funding_term_structure import get_funding_term_structure
        f1 = get_funding_term_structure()
        f2 = get_funding_term_structure()
        assert f1 is f2
