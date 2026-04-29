"""
FastAPI Dashboard Backend — REST API für das Web-Dashboard.

Endpunkte:
  GET  /api/status       — Bot-Status, Kapital, Position, Regime
  GET  /api/trades       — Letzte Trades
  GET  /api/performance  — KPIs (Sharpe, Win-Rate, etc.)
  GET  /api/equity       — Equity-Kurve
  GET  /api/signals      — Letzte Signale
  GET  /api/model        — ML-Modell Info
  POST /api/control/{action} — start|stop|safe_mode|retrain|simulation
  POST /api/control/symbol/{symbol} — Handelspaar wechseln (schreibt in .env)
  GET  /api/exchange          — Aktueller Exchange + verfügbare Exchanges
  POST /api/exchange/{name}   — Exchange wechseln (binance|bybit|okx|kraken)
  POST /api/exchange/credentials — Neue Exchange-Credentials in .env speichern

Start:
    uvicorn dashboard.api:app --host 0.0.0.0 --port 8000
    oder:  make dashboard-api
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Projektpfad zum sys.path hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from crypto_bot.config.settings import INITIAL_CAPITAL, SYMBOL, TIMEFRAME, AI_MODE, TRADING_MODE
from crypto_bot.monitoring.logger import (
    get_recent_trades, get_performance_summary, get_equity_curve,
    export_trades_csv, export_performance_json, init_db,
    get_rolling_performance, get_periodic_performance, get_weekly_monthly_pnl,
    get_recent_rejections,
)

app = FastAPI(
    title="Trading Bot API",
    description="Dashboard API für den AI-Trading Bot",
    version="1.0.0",
)

@app.on_event("startup")
async def _prewarm_imports():
    """Pre-load heavy modules at startup so first requests don't spike RAM."""
    import logging as _lg
    _log = _lg.getLogger("api.prewarm")
    for mod in [
        "pandas", "numpy",
        "crypto_bot.strategy.loader",
        "crypto_bot.strategy.marketplace",
        "crypto_bot.optimization.loss_functions",
        "crypto_bot.config.features",
        "crypto_bot.benchmark.runner",
    ]:
        try:
            __import__(mod)
        except Exception as e:
            _log.warning(f"prewarm {mod}: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Optionaler API-Key Schutz ─────────────────────────────────────────────────
# Wenn DASHBOARD_API_KEY in .env gesetzt ist, wird er bei jedem Request geprüft.
# Ohne Key läuft das Dashboard offen (Rückwärtskompatibilität im LAN).
_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check_api_key(key: str = Security(_api_key_header)):
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger API-Key")

# Shared state (wird von bot.py befüllt wenn im selben Prozess)
_bot_state: dict = {
    "running":          False,
    "capital":          INITIAL_CAPITAL,
    "daily_pnl":        0.0,
    "position":         None,
    "current_price":    0.0,
    "regime":           "UNKNOWN",
    "ai_confidence":    0.0,
    "active_strategy":  "momentum",
    "stop_requested":    False,
    "retrain_requested": False,
    "safe_mode":         False,
    "trading_mode":      TRADING_MODE,
    "last_update":       None,
    "bot_pid":           None,
    "volatility_regime": "UNKNOWN",
    "training_mode":     False,
    "risk_mode":         "balanced",
    "last_rejection":    None,
    "drift_status":      None,
    "strategy_performance": {},
    "last_explanation":  None,
    "symbol":            SYMBOL,
    "symbol_changed":    False,
}

# Subprocess-Handle wenn Bot über Dashboard gestartet wurde
_bot_process: subprocess.Popen | None = None


_STATE_FILE = Path(__file__).parent.parent / "data_store" / "bot_state.json"


def _load_state_from_file():
    """Liest Bot-State aus Datei — für Multi-Container-Betrieb (z.B. QNAP)."""
    try:
        if _STATE_FILE.exists():
            import json
            data = json.loads(_STATE_FILE.read_text())
            _bot_state.update(data)
    except Exception:
        pass


def get_bot_state() -> dict:
    _load_state_from_file()
    return _bot_state


def update_bot_state(updates: dict):
    _bot_state.update(updates)
    _bot_state["last_update"] = datetime.now(timezone.utc).isoformat()


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    """Aktueller Bot-Status."""
    global _bot_process
    init_db()
    _load_state_from_file()

    # Subprocess-Liveness prüfen (wenn Bot über Dashboard gestartet)
    if _bot_process is not None:
        if _bot_process.poll() is not None:
            # Prozess ist beendet
            _bot_state["running"] = False
            _bot_state["bot_pid"] = None
            _bot_process = None
        else:
            _bot_state["running"] = True

    pos = _bot_state.get("position")
    pos_data = None
    if pos:
        pos_data = {
            "symbol":      getattr(pos, "symbol", SYMBOL),
            "entry_price": getattr(pos, "entry_price", 0),
            "stop_loss":   getattr(pos, "stop_loss", 0),
            "take_profit": getattr(pos, "take_profit", 0),
            "quantity":    getattr(pos, "quantity", 0),
        }

    return {
        "running":         _bot_state["running"],
        "trading_mode":    _bot_state["trading_mode"],
        "safe_mode":       _bot_state["safe_mode"],
        "symbol":          SYMBOL,
        "timeframe":       TIMEFRAME,
        "ai_mode":         AI_MODE,
        "capital":         round(_bot_state["capital"], 2),
        "initial_capital": INITIAL_CAPITAL,
        "daily_pnl":       round(_bot_state["daily_pnl"], 2),
        "current_price":   _bot_state["current_price"],
        "regime":          _bot_state["regime"],
        "ai_confidence":   round(_bot_state["ai_confidence"], 4),
        "active_strategy": _bot_state["active_strategy"],
        "position":          pos_data,
        "last_update":       _bot_state["last_update"],
        "bot_pid":           _bot_state.get("bot_pid"),
        "volatility_regime":        _bot_state.get("volatility_regime", "UNKNOWN"),
        "training_mode":            _bot_state.get("training_mode", False),
        "risk_mode":                _bot_state.get("risk_mode", "balanced"),
        "last_rejection":           _bot_state.get("last_rejection"),
        "drift_status":             _bot_state.get("drift_status"),
        "live_transition_pending":  _bot_state.get("live_transition_pending", False),
        "symbol_changed":           _bot_state.get("symbol_changed", False),
        "exchange_connected":        _bot_state.get("exchange_connected", None),
        "exchange_error":            _bot_state.get("exchange_error", ""),
        "exchange":                  _bot_state.get("exchange", "binance"),
        "timestamp":                datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/trades")
def trades(limit: int = 50):
    """Letzte Trades aus der Datenbank."""
    init_db()
    return {"trades": get_recent_trades(limit=limit)}


@app.get("/api/performance")
def performance():
    """Hedge-Fund-Style Performance KPIs."""
    init_db()
    db_summary = get_performance_summary()
    rm_summary = _bot_state.get("rm_summary", {})

    total      = db_summary.get("total_trades") or 0
    wins       = db_summary.get("wins") or 0
    win_rate   = round(wins / total * 100, 1) if total > 0 else 0.0
    total_pnl  = db_summary.get("total_pnl") or 0.0
    return_pct = round(total_pnl / INITIAL_CAPITAL * 100, 2) if INITIAL_CAPITAL > 0 else 0.0

    return {
        "total_trades":       total,
        "wins":               wins,
        "losses":             db_summary.get("losses") or 0,
        "win_rate":           win_rate,
        "total_pnl":          total_pnl,
        "return_pct":         return_pct,
        "avg_win":            db_summary.get("avg_win") or 0.0,
        "avg_loss":           db_summary.get("avg_loss") or 0.0,
        "sharpe_ratio":       rm_summary.get("sharpe", 0.0),
        "sortino_ratio":      rm_summary.get("sortino", 0.0),
        "calmar_ratio":       rm_summary.get("calmar", 0.0),
        "omega_ratio":        rm_summary.get("omega", 0.0),
        "rolling_sharpe_20":  rm_summary.get("rolling_sharpe_20", 0.0),
        "profit_factor":      rm_summary.get("profit_factor", 0.0),
        "max_drawdown":       rm_summary.get("max_drawdown_pct", 0.0),
        "avg_hold_hours":     rm_summary.get("avg_hold_hours", 0.0),
        "max_win_streak":     rm_summary.get("max_win_streak", 0),
        "max_loss_streak":    rm_summary.get("max_loss_streak", 0),
        "current_capital":    round(_bot_state["capital"], 2),
        "initial_capital":    INITIAL_CAPITAL,
    }


@app.get("/api/equity")
def equity():
    """Equity-Kurve für Chart."""
    init_db()
    curve = get_equity_curve()
    # Startpunkt hinzufügen
    if not curve:
        curve = [{"snapshot_date": "start", "capital": INITIAL_CAPITAL}]
    return {"equity_curve": curve, "initial_capital": INITIAL_CAPITAL}


@app.get("/api/signals")
def signals(limit: int = 20):
    """Letzte AI-Signale."""
    from crypto_bot.monitoring.logger import _db
    init_db()
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"signals": [dict(r) for r in rows]}


@app.get("/api/logs")
def logs(lines: int = 200, level: str = ""):
    """Letzte N Zeilen aus bot.log. Optional: level=INFO/WARNING/ERROR zum Filtern."""
    log_path = Path(__file__).parent.parent.parent / "logs" / "bot.log"
    if not log_path.exists():
        return {"lines": [], "path": str(log_path), "exists": False}
    try:
        # Read only the last 2MB from the end — avoids OOM on multi-GB log files.
        # With ~150 bytes/line average, 2MB covers ~13k lines (more than enough for filtering).
        _TAIL_BYTES = 2_000_000
        with open(log_path, "rb") as _f:
            _f.seek(0, 2)
            _size = _f.tell()
            _f.seek(max(0, _size - _TAIL_BYTES))
            _raw = _f.read()
        text = _raw.decode("utf-8", errors="replace").splitlines()
        if level:
            text = [l for l in text if level.upper() in l]
        return {"lines": text[-lines:], "total": len(text), "exists": True, "truncated": _size > _TAIL_BYTES}
    except Exception as e:
        return {"lines": [], "error": str(e), "exists": False}


@app.get("/api/model")
def model_info():
    """ML-Modell Informationen."""
    try:
        from crypto_bot.ai.retrainer import AutoRetrainer
        info = AutoRetrainer().get_model_info()
        return info
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/progress")
def progress():
    """Fortschritt Paper→Live mit Kriterien-Breakdown."""
    init_db()
    try:
        from crypto_bot.ai.confidence_monitor import get_phase_progress
        perf = get_performance_summary()
        from crypto_bot.monitoring.logger import get_recent_trades
        all_trades  = get_recent_trades(limit=9999)
        live_trades = [t for t in all_trades if t.get("ai_source") != "backtest"]
        bt_trades   = [t for t in all_trades if t.get("ai_source") == "backtest"]
        trade_count = len(all_trades)
        sharpe      = perf.get("sharpe_ratio", 0.0) or 0.0
        win_rate    = perf.get("win_rate", 0.0) or 0.0
        drawdown    = perf.get("max_drawdown", 0.0) or 0.0

        try:
            # Use the cached model info instead of loading the model on every call
            f1 = (_model_info_cache.get("val_f1") or 0.0) if _model_info_cache else 0.0
        except Exception:
            f1 = 0.0

        # Datum des ersten Trades für ETA-Schätzung
        first_trade_date = None
        if all_trades:
            oldest = min(
                (t.get("created_at") or t.get("timestamp") or "" for t in all_trades),
                default=None,
            )
            if oldest:
                first_trade_date = oldest

        prog = get_phase_progress(
            paper_trades=trade_count,
            sharpe=sharpe,
            win_rate_pct=win_rate,
            max_drawdown_pct=drawdown,
            model_f1=f1,
            trading_mode=_bot_state.get("trading_mode", TRADING_MODE),
            first_trade_date=first_trade_date,
        )
        return {
            "phase":           prog.phase,
            "overall_pct":     prog.overall_pct,
            "passed_count":    prog.passed_count,
            "total_count":     prog.total_count,
            "next_phase":      prog.next_phase,
            "next_phase_hint": prog.next_phase_hint,
            "days_to_next":    prog.days_to_next,
            "eta_label":       prog.eta_label,
            "trade_breakdown": {
                "total":    trade_count,
                "live":     len(live_trades),
                "backtest": len(bt_trades),
            },
            "criteria": [
                {
                    "name":    c.name,
                    "label":   c.label,
                    "current": c.current,
                    "target":  c.target,
                    "pct":     round(c.pct, 1),
                    "passed":  c.passed,
                    "unit":    c.unit,
                }
                for c in prog.criteria
            ],
        }
    except Exception as e:
        return {"error": str(e), "phase": "PAPER", "overall_pct": 0.0, "criteria": []}


@app.get("/api/candles")
def get_candles(symbol: str = "", timeframe: str = "1h", limit: int = 150):
    """OHLCV candles — direct Binance REST call, no CCXT instantiation (RAM-light)."""
    import requests as _req
    from datetime import timezone as _utc
    sym = (symbol or SYMBOL).replace("/", "")  # BTC/USDT → BTCUSDT
    _tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
               "1h": "1h", "4h": "4h", "1d": "1d"}
    interval = _tf_map.get(timeframe, "1h")
    try:
        resp = _req.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": interval, "limit": min(limit, 200)},
            timeout=10,
        )
        resp.raise_for_status()
        candles = [
            {
                "time":   datetime.fromtimestamp(row[0] / 1000, tz=_utc.utc).isoformat(),
                "open":   float(row[1]),
                "high":   float(row[2]),
                "low":    float(row[3]),
                "close":  float(row[4]),
                "volume": float(row[5]),
            }
            for row in resp.json()
        ]
        return {"symbol": symbol or SYMBOL, "timeframe": timeframe, "candles": candles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exposure")
def exposure():
    """Global Exposure Controller Status."""
    _load_state_from_file()
    return {"exposure": _bot_state.get("exposure", {})}


@app.post("/api/control/symbol/{symbol}")
def set_symbol(symbol: str, _: None = Security(_check_api_key)):
    """Setzt das Handelspaar und schreibt es in .env. Bot-Neustart erforderlich."""
    symbol = symbol.upper().replace("-", "/")
    if "/" not in symbol or not symbol.endswith("USDT"):
        raise HTTPException(400, "Ungültiges Symbol. Beispiel: BTC/USDT, ETH/USDT")

    import crypto_bot.config.settings as cfg
    env_path = Path(__file__).parent.parent / ".env"

    # .env lesen, SYMBOL-Zeile ersetzen oder anhängen
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("SYMBOL="):
                new_lines.append(f"SYMBOL={symbol}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"SYMBOL={symbol}")
        env_path.write_text("\n".join(new_lines) + "\n")
    else:
        with env_path.open("a") as f:
            f.write(f"\nSYMBOL={symbol}\n")

    # Laufzeit-Update
    os.environ["SYMBOL"] = symbol
    cfg.SYMBOL = symbol
    _bot_state["symbol"] = symbol
    _bot_state["symbol_changed"] = True

    return {
        "status": "ok",
        "message": f"Symbol auf {symbol} gesetzt — Bot neu starten + Modell neu trainieren!",
        "symbol": symbol,
        "retrain_required": True,
    }


@app.post("/api/control/risk_mode/{mode}")
def set_risk_mode(mode: str, _: None = Security(_check_api_key)):
    """Setzt Risk Personality Mode: conservative | balanced | aggressive."""
    valid_modes = {"conservative", "balanced", "aggressive"}
    if mode not in valid_modes:
        raise HTTPException(400, f"Ungültiger Modus. Gültig: {valid_modes}")
    import os
    import crypto_bot.config.settings as cfg
    os.environ["RISK_MODE"] = mode
    cfg.RISK_MODE = mode
    _bot_state["risk_mode"] = mode
    icons = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}
    return {"status": "ok", "message": f"{icons.get(mode, '')} Risk Mode: {mode.upper()}",
            "risk_mode": mode}


@app.post("/api/control/{action}")
def control(action: str, _: None = Security(_check_api_key)):
    """Bot-Steuerung: start|stop|pause|resume|safe_mode|retrain|simulation."""
    global _bot_process
    valid_actions = {"start", "stop", "pause", "resume", "safe_mode", "retrain", "simulation", "restart", "approve_live"}
    if action not in valid_actions:
        raise HTTPException(400, f"Ungültige Aktion. Gültig: {valid_actions}")

    if action == "start":
        # Bereits laufenden Prozess prüfen
        if _bot_process and _bot_process.poll() is None:
            return {"status": "error", "message": f"Bot läuft bereits (PID {_bot_process.pid})",
                    "pid": _bot_process.pid}
        if _bot_state.get("running"):
            return {"status": "error", "message": "Bot meldet sich bereits als aktiv"}

        bot_script = Path(__file__).parent.parent / "bot.py"
        _log_dir = Path(__file__).parent.parent / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        with open(_log_dir / "bot_subprocess.log", "a") as _bot_log:
            _bot_process = subprocess.Popen(
                [sys.executable, str(bot_script)],
                stdout=_bot_log,
                stderr=_bot_log,
                start_new_session=True,   # Prozess unabhängig vom API-Prozess
            )
        _bot_state["bot_pid"] = _bot_process.pid
        _bot_state["running"] = True
        _bot_state["stop_requested"] = False
        return {"status": "ok", "message": f"Bot gestartet (PID {_bot_process.pid})",
                "pid": _bot_process.pid}

    if action == "stop":
        _bot_state["stop_requested"] = True
        # Subprocess terminieren falls vorhanden
        if _bot_process and _bot_process.poll() is None:
            _bot_process.terminate()
            _bot_state["bot_pid"] = None
            _bot_state["running"] = False
        return {"status": "ok", "message": "Stop-Signal gesendet"}

    if action == "pause":
        _bot_state["paused"] = True
        return {"status": "ok", "message": "Bot pausiert — kein Trading bis Resume"}

    if action == "resume":
        _bot_state["paused"] = False
        return {"status": "ok", "message": "Bot fortgesetzt"}

    if action == "safe_mode":
        _bot_state["safe_mode"] = not _bot_state["safe_mode"]
        mode = "aktiviert" if _bot_state["safe_mode"] else "deaktiviert"
        return {"status": "ok", "message": f"Safe Mode {mode}",
                "safe_mode": _bot_state["safe_mode"]}

    if action == "retrain":
        _bot_state["retrain_requested"] = True
        return {"status": "ok", "message": "Retraining angefordert"}

    if action == "simulation":
        _bot_state["trading_mode"] = "paper"
        return {"status": "ok", "message": "Auf Paper-Modus gewechselt"}

    if action == "restart":
        # Vollständiges Retraining + Reset in Training Mode
        _bot_state["retrain_requested"] = True
        _bot_state["training_mode"] = True
        return {"status": "ok", "message": "Training Mode neu gestartet — vollständiges Retraining angefordert"}

    if action == "approve_live":
        if not _bot_state.get("live_transition_pending"):
            raise HTTPException(400, "Kein Live-Wechsel ausstehend — Kriterien noch nicht erfüllt")
        _bot_state["approve_live"] = True
        return {
            "status": "ok",
            "message": "Live-Trading bestätigt — wird beim nächsten Zyklus aktiviert",
        }

    return {"status": "ok", "action": action}


@app.get("/api/performance/rolling")
def performance_rolling(days: int = 7):
    """Rolling Performance für die letzten N Tage."""
    init_db()
    return get_rolling_performance(days)


@app.get("/api/performance/periods")
def performance_periods():
    """Performance für 7d, 30d und gesamt."""
    init_db()
    return get_periodic_performance()


@app.get("/api/performance/periods/chart")
def performance_chart():
    """Wöchentliche und monatliche PnL-Aggregation für Charts."""
    init_db()
    return get_weekly_monthly_pnl()


@app.get("/api/export/csv")
def export_csv():
    """Exportiert Trades als CSV."""
    path = export_trades_csv()
    return {"status": "ok", "path": path}


@app.get("/api/export/json")
def export_json():
    """Exportiert Performance als JSON."""
    path = export_performance_json()
    return {"status": "ok", "path": path}


@app.get("/api/rejections")
def rejections(limit: int = 10):
    """Letzte abgelehnte Trades (HOLD-Entscheidungen mit Grund)."""
    init_db()
    return {"rejections": get_recent_rejections(limit=limit)}


@app.get("/api/strategy_performance")
def strategy_performance():
    """Strategy-Performance pro Strategie (aus Bot-State)."""
    return {
        "strategy_performance": _bot_state.get("strategy_performance", {}),
        "risk_mode":            _bot_state.get("risk_mode", "balanced"),
    }


@app.get("/api/scanner")
def scanner_results():
    """Letzter Pair-Scanner Lauf — Top-Paare nach Score."""
    return {
        "scanner_results": _bot_state.get("scanner_results", {}),
        "scanner_interval_hours": None,
    }


@app.get("/api/explanation")
def explanation():
    """Letzte Trade-Erklärung (AI Explainability)."""
    return {
        "narrative":        _bot_state.get("last_explanation"),
        "last_rejection":   _bot_state.get("last_rejection"),
        "drift_status":     _bot_state.get("drift_status"),
    }


@app.get("/api/report")
def generate_report():
    """Generiert PDF-Performance-Report (synchron)."""
    try:
        from crypto_bot.reporting.report_generator import get_report_generator
        import sqlite3, json
        from crypto_bot.config.settings import INITIAL_CAPITAL as IC, SYMBOL as SYM
        from crypto_bot.monitoring.logger import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            trades_list = [dict(r) for r in rows]
        path = get_report_generator().generate(
            trades      = trades_list,
            capital     = _bot_state.get("capital", IC),
            initial_cap = IC,
            symbol      = SYM,
        )
        if path:
            return {"status": "ok", "path": str(path)}
        return {"status": "error", "message": "fpdf2 nicht installiert — pip install fpdf2"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Round 8: Advanced Intelligence Endpoints ──────────────────────────────────

@app.get("/api/microstructure")
def microstructure():
    """CVD, Orderbook-Imbalanz, Wick-Analyse."""
    return {"microstructure": _bot_state.get("microstructure", {})}


@app.get("/api/cross_market")
def cross_market():
    """BTC-Dominanz, Stablecoin-Flows, Fear/Greed Sentiment."""
    return {"cross_market": _bot_state.get("cross_market", {})}


@app.get("/api/derivatives")
def derivatives():
    """Funding-Rate, Liquidations-Cluster, Spot-Perp-Basis."""
    return {"derivatives": _bot_state.get("derivatives", {})}


@app.get("/api/regime_forecast")
def regime_forecast():
    """Regime-Übergangs-Wahrscheinlichkeiten (Markov)."""
    return {"regime_forecast": _bot_state.get("regime_forecast", {})}


@app.get("/api/opportunity_radar")
def opportunity_radar():
    """Per-Pair Opportunity Scores + beste Trading-Chance."""
    return {"opportunity_radar": _bot_state.get("opportunity_radar", {})}


@app.get("/api/features")
def feature_flags():
    """Aktuelle Feature-Flag Konfiguration."""
    from crypto_bot.config import features
    return {"features": features.get_all()}


# ── Round 9: Model Governance + Simulation + Stress + Allocator + Funding ────

@app.get("/api/model_governance")
def model_governance():
    """Entropie, Feature-Drift, Kalibrations-Drift — ML-Modell Gesundheit."""
    return {"model_governance": _bot_state.get("model_governance", {})}


@app.get("/api/regime_simulation")
def regime_simulation():
    """Monte Carlo Markov Regime-Simulation — Exposure-Empfehlung."""
    return {"regime_simulation": _bot_state.get("regime_simulation", {})}


@app.get("/api/stress_test")
def stress_test():
    """Flash Crash / Spread / Kaskaden Stress-Test Ergebnis."""
    return {"stress_test": _bot_state.get("stress_test", {})}


@app.get("/api/capital_allocation")
def capital_allocation():
    """Autonome Kapitalallokation — Signal-Tier + finaler Allokationsfaktor."""
    return {"capital_allocator": _bot_state.get("capital_allocator", {})}


@app.get("/api/funding_ts")
def funding_term_structure():
    """Funding Rate Term Structure — Contango/Backwardation + Carry-Signal."""
    return {"funding_ts": _bot_state.get("funding_ts", {})}


@app.get("/api/fear_greed")
def fear_greed():
    """Crypto Fear & Greed Index — aktueller Wert und Position-Faktor."""
    return {"fear_greed": _bot_state.get("fear_greed", {})}


@app.get("/api/news_sentiment")
def news_sentiment():
    """News Sentiment — aktuelles Sentiment aus RSS-Feeds + LLM-Analyse."""
    return {"news_sentiment": _bot_state.get("news_sentiment", {})}


@app.get("/api/log_level")
def get_log_level():
    """Aktuell gesetzter Log-Level (DEBUG/INFO/WARNING/ERROR)."""
    _level_file = Path(__file__).parent.parent / "data_store" / "log_level.txt"
    level = "INFO"
    if _level_file.exists():
        level = _level_file.read_text().strip().upper()
    return {"level": level}


@app.post("/api/control/log_level/{level}")
def set_log_level(level: str, _: None = Security(_check_api_key)):
    """Setzt Log-Level zur Laufzeit — wird vom Bot beim nächsten Loop-Zyklus übernommen."""
    import logging as _logging
    valid = {"DEBUG", "INFO", "WARNING", "ERROR"}
    level = level.upper()
    if level not in valid:
        raise HTTPException(400, f"Ungültig. Gültig: {sorted(valid)}")
    _level_file = Path(__file__).parent.parent / "data_store" / "log_level.txt"
    _level_file.parent.mkdir(parents=True, exist_ok=True)
    _level_file.write_text(level)
    # Auch im laufenden API-Prozess anwenden
    numeric = getattr(_logging, level)
    _logging.getLogger("trading_bot").setLevel(numeric)
    _logging.getLogger().setLevel(numeric)
    return {"status": "ok", "level": level, "message": f"LOG_LEVEL={level} gesetzt"}


# ── Exchange Management ───────────────────────────────────────────────────────

_EXCHANGES = {
    "binance":  "Binance Spot (Testnet / Live) — 100+ Paare, 0.1% Fee",
    "bybit":    "Bybit Spot & Futures (Testnet / Live) — niedrige Fees",
    "okx":      "OKX (Paper Demo / Live) — breites Angebot, EU-konform",
    "kraken":   "Kraken (Live only) — EU-reguliert, hohe Sicherheit",
    "coinbase": "Coinbase Advanced (Live only) — US-Markt, reguliert",
    "gateio":   "Gate.io (Live only) — breites Altcoin-Angebot",
    "kucoin":   "KuCoin (Live only) — niedrige Fees, viele Altcoins",
    "bitget":   "Bitget (Testnet / Live) — Futures-Fokus, Copy Trading",
    "htx":      "HTX / Huobi (Live only) — Asien-Markt",
    "mexc":     "MEXC (Live only) — günstigste Fees, 0% Maker",
}

_EXCHANGE_ENVS = {
    "binance":  ["testnet", "live"],
    "bybit":    ["testnet", "live"],
    "okx":      ["demo",    "live"],
    "kraken":   ["live"],
    "coinbase": ["live"],
    "gateio":   ["live"],
    "kucoin":   ["live"],
    "bitget":   ["testnet", "live"],
    "htx":      ["live"],
    "mexc":     ["live"],
}


class ExchangeCredentials(BaseModel):
    """Credentials für Exchange-Wechsel aus dem Dashboard (in-memory)."""
    env:        str = ""
    api_key:    str = ""
    api_secret: str = ""
    passphrase: str = ""   # OKX only


class AddExchangeCredentialsRequest(BaseModel):
    """Request-Body für POST /api/exchange/credentials (schreibt in .env)."""
    exchange:   str
    env:        str
    api_key:    str = ""
    api_secret: str = ""
    passphrase: str = ""   # OKX only


@app.get("/api/exchange")
def get_exchange_info():
    """Aktueller Exchange, verfügbare Exchanges und welche bereits konfiguriert sind."""
    from crypto_bot.config import settings as cfg
    from crypto_bot.execution.exchange_env_manager import get_configured

    current    = _bot_state.get("exchange", cfg.EXCHANGE)
    configured = get_configured()

    return {
        "current":    current,
        "configured": configured,
        "available": [
            {
                "name":        name,
                "description": desc,
                "active":      name == current,
                "envs":        _EXCHANGE_ENVS.get(name, ["live"]),
            }
            for name, desc in _EXCHANGES.items()
        ],
    }


@app.post("/api/exchange/{exchange_name}")
def set_exchange(exchange_name: str, creds: ExchangeCredentials = ExchangeCredentials(),
                 _: None = Security(_check_api_key)):
    """
    Wechselt den aktiven Exchange zur Laufzeit.

    Aktualisiert den Bot-State. Da das ML-Modell exchange-spezifisch ist,
    wird ein Bot-Neustart + Retraining empfohlen.
    """
    name = exchange_name.lower().strip()
    if name not in _EXCHANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannter Exchange '{name}'. Verfügbar: {list(_EXCHANGES.keys())}",
        )

    import crypto_bot.config.settings as cfg

    # .env aktualisieren
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        lines   = env_path.read_text().splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("EXCHANGE="):
                new_lines.append(f"EXCHANGE={name}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"EXCHANGE={name}")
        env_path.write_text("\n".join(new_lines) + "\n")
    else:
        with env_path.open("a") as f:
            f.write(f"\nEXCHANGE={name}\n")

    os.environ["EXCHANGE"] = name
    cfg.EXCHANGE = name
    _bot_state["exchange"]         = name
    _bot_state["exchange_changed"] = True

    return {
        "success":           True,
        "exchange":          name,
        "description":       _EXCHANGES[name],
        "message":           f"Exchange auf {name} gesetzt — Bot neu starten + Modell neu trainieren!",
        "retrain_required":  True,
    }


@app.post("/api/exchange/credentials")
def add_exchange_credentials(req: AddExchangeCredentialsRequest,
                              _: None = Security(_check_api_key)):
    """
    Schreibt neue Exchange-Credentials in .env.

    Gibt 409 zurück wenn für diesen Exchange+Env bereits ein Eintrag existiert.
    Credentials werden NICHT überschrieben — für Änderungen .env manuell editieren.
    """
    from crypto_bot.execution.exchange_env_manager import credentials_exist, write_credentials

    exchange = req.exchange.lower().strip()
    env      = req.env.lower().strip()

    if exchange not in _EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Unbekannter Exchange: {exchange}")

    existing = credentials_exist(exchange, env)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Existiert bereits: {existing}. Zum Ändern .env manuell editieren.",
        )

    try:
        write_credentials(exchange, env, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {
        "success":  True,
        "exchange": exchange,
        "env":      env,
        "message":  f"{_EXCHANGES[exchange]} ({env}) gespeichert.",
    }


# ── Pro Features: Execution Quality + Heartbeat + Extended Performance ────────

@app.get("/api/execution_quality")
def execution_quality(limit: int = 200):
    """
    Execution Quality — Slippage-Analyse (Signal-Preis vs. Fill-Preis).
    Zeigt wie gut die Ausführung ist und was Slippage kostet.
    Nur bei Live/Testnet sinnvoll (Paper-Modus hat kein echtes Slippage).
    """
    init_db()
    try:
        from crypto_bot.monitoring.logger import get_execution_quality_stats
        return get_execution_quality_stats(limit=limit)
    except Exception as e:
        return {"error": str(e), "avg_slippage_bps": 0.0, "recent": []}


@app.get("/api/heartbeat")
def heartbeat_status():
    """Dead Man's Switch Status — zeigt ob Bot noch lebt und wann letzter Ping war."""
    import json as _json

    # Immer zuerst heartbeat.json lesen — der Bot (anderer Container/Prozess)
    # schreibt die Datei, der Singleton im Dashboard-Prozess hat keine Pings.
    hb_file = Path(__file__).parent.parent / "data_store" / "heartbeat.json"
    if hb_file.exists():
        try:
            data = _json.loads(hb_file.read_text())
            ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            silence = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            return {
                "alive":           data.get("status") == "alive" and silence < 90,
                "last_ping":       ts.isoformat(),
                "silence_minutes": round(silence, 1),
                "max_silence_min": 90,
                "status":          data.get("status", "unknown"),
                "source":          "file",
            }
        except Exception:
            pass

    # Fallback: in-memory Singleton (nur wenn Bot im selben Prozess läuft)
    try:
        from crypto_bot.monitoring.heartbeat import get_heartbeat
        hb = get_heartbeat()
        status = hb.get_status()
        if status.get("last_ping") is not None:
            status["source"] = "singleton"
            return status
    except Exception:
        pass

    return {"alive": False, "last_ping": None, "silence_minutes": None, "source": "none"}


@app.get("/api/performance/extended")
def performance_extended():
    """
    Erweiterte Performance-Metriken inkl. Calmar, Omega, Rolling Sharpe,
    Drawdown-Dauer, Haltedauer, Win/Loss Streaks.
    Diese Metriken werden aus dem RiskManager-Summary gelesen (rm_summary in Bot-State).
    """
    init_db()
    rm_summary = _bot_state.get("rm_summary", {})
    db_summary = get_performance_summary()

    total    = db_summary.get("total_trades") or 0
    wins     = db_summary.get("wins")         or 0
    win_rate = round(wins / total * 100, 1) if total > 0 else 0.0

    return {
        # Basis-Metriken
        "total_trades":       total,
        "wins":               wins,
        "losses":             db_summary.get("losses") or 0,
        "win_rate":           win_rate,
        "total_pnl":          db_summary.get("total_pnl") or 0.0,
        "return_pct":         rm_summary.get("return_pct", 0.0),
        # Risk-Adjusted Returns
        "sharpe":             rm_summary.get("sharpe", 0.0),
        "sortino":            rm_summary.get("sortino", 0.0),
        "calmar":             rm_summary.get("calmar", 0.0),
        "omega":              rm_summary.get("omega", 0.0),
        "rolling_sharpe_20":  rm_summary.get("rolling_sharpe_20", 0.0),
        # Drawdown-Analyse
        "max_drawdown_pct":   rm_summary.get("max_drawdown_pct", 0.0),
        "avg_drawdown_trades": rm_summary.get("avg_drawdown_trades", 0.0),
        "max_drawdown_trades": rm_summary.get("max_drawdown_trades", 0),
        # Trade-Qualität
        "avg_win":            rm_summary.get("avg_win", 0.0),
        "avg_loss":           rm_summary.get("avg_loss", 0.0),
        "profit_factor":      rm_summary.get("profit_factor", 0.0),
        "expectancy":         rm_summary.get("expectancy", 0.0),
        "avg_hold_hours":     rm_summary.get("avg_hold_hours", 0.0),
        # Streak-Analyse
        "max_win_streak":     rm_summary.get("max_win_streak", 0),
        "max_loss_streak":    rm_summary.get("max_loss_streak", 0),
        # Kapital
        "initial_capital":    INITIAL_CAPITAL,
        "current_capital":    round(_bot_state.get("capital", INITIAL_CAPITAL), 2),
    }


@app.get("/api/live_state")
def live_state():
    """
    Live State Reconciliation Status — zeigt ob eine offene Position
    nach Bot-Neustart wiederhergestellt wurde.
    """
    _load_state_from_file()
    pos = _bot_state.get("position")
    reconciled = _bot_state.get("live_state_reconciled", False)
    return {
        "reconciled":     reconciled,
        "trading_mode":   _bot_state.get("trading_mode", TRADING_MODE),
        "has_position":   pos is not None,
        "position":       pos if isinstance(pos, dict) else None,
    }


@app.get("/api/benchmark")
def benchmark():
    """
    Buy & Hold Benchmark — vergleicht Bot-Rendite mit BTC Buy&Hold seit erstem Trade.

    Gibt zurück:
      - bot_return_pct:       Tatsächliche Bot-Rendite (Kapital-Delta)
      - buyhold_return_pct:   BTC Buy&Hold seit erstem Trade/Snapshot
      - alpha_pct:            Bot-Outperformance gegenüber Buy&Hold
      - start_price / current_price: BTC-Preis zum Vergleich
      - period_days:          Gemessener Zeitraum
    """
    init_db()
    try:
        from crypto_bot.monitoring.logger import _db
        from crypto_bot.data.fetcher import fetch_ohlcv
        import math

        # Ersten Trade oder Equity-Snapshot für Start-Zeitpunkt
        with _db() as conn:
            first_trade = conn.execute(
                "SELECT MIN(created_at) as ts FROM trades WHERE ai_source != 'backtest'"
            ).fetchone()
            first_snap = conn.execute(
                "SELECT capital, snapshot_date FROM performance_snapshots ORDER BY snapshot_date ASC LIMIT 1"
            ).fetchone()

        start_ts = None
        start_capital = INITIAL_CAPITAL
        if first_trade and first_trade["ts"]:
            start_ts = first_trade["ts"]
        elif first_snap and first_snap["snapshot_date"]:
            start_ts = first_snap["snapshot_date"]

        if start_ts is None:
            return {
                "status": "no_data",
                "message": "Noch keine Trades — Benchmark verfügbar sobald erster Trade abgeschlossen",
                "bot_return_pct": 0.0,
                "buyhold_return_pct": 0.0,
                "alpha_pct": 0.0,
            }

        # BTC-Preis-History für Vergleich laden (90 Tage reichen für die meisten Fälle)
        from crypto_bot.config.settings import SYMBOL, TIMEFRAME
        df = fetch_ohlcv(SYMBOL, "1d", days=400)

        # Startpreis: nächste verfügbare Candle nach erstem Trade
        start_date_str = start_ts[:10]  # "YYYY-MM-DD"
        df_reset = df.reset_index()
        ts_col = "timestamp" if "timestamp" in df_reset.columns else df_reset.columns[0]

        start_row = df_reset[df_reset[ts_col].astype(str) >= start_date_str]
        if start_row.empty:
            start_price = float(df.iloc[0]["close"])
        else:
            start_price = float(start_row.iloc[0]["close"])

        current_price = float(df.iloc[-1]["close"])
        buyhold_return = (current_price / start_price - 1) * 100

        # Bot-Rendite aus aktuellem Kapital
        current_capital = float(_bot_state.get("capital", INITIAL_CAPITAL))
        bot_return = (current_capital / start_capital - 1) * 100
        alpha = bot_return - buyhold_return

        # Zeitraum berechnen
        try:
            from datetime import datetime, timezone
            start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00").replace(" ", "T"))
            period_days = (datetime.now(timezone.utc) - start_dt).days
        except Exception:
            period_days = 0

        return {
            "status":             "ok",
            "symbol":             SYMBOL,
            "period_days":        period_days,
            "start_date":         start_date_str,
            "start_price":        round(start_price, 2),
            "current_price":      round(current_price, 2),
            "start_capital":      round(start_capital, 2),
            "current_capital":    round(current_capital, 2),
            "bot_return_pct":     round(bot_return, 2),
            "buyhold_return_pct": round(buyhold_return, 2),
            "alpha_pct":          round(alpha, 2),
            "outperforms":        alpha > 0,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "bot_return_pct": 0.0, "buyhold_return_pct": 0.0}


@app.get("/api/protection")
def protection_status():
    """
    Trade Cooldown + StoplossgGuard Status.
    Zeigt ob Trading gesperrt ist und warum.
    """
    rm_summary = _bot_state.get("rm_summary", {})
    return {
        "in_cooldown":             rm_summary.get("in_cooldown", False),
        "cooldown_remaining_min":  rm_summary.get("cooldown_remaining_min", 0.0),
        "cooldown_minutes":        rm_summary.get("cooldown_minutes", 60),
        "consecutive_losses":      rm_summary.get("consecutive_losses", 0),
        "stoploss_guard_active":   rm_summary.get("stoploss_guard_active", False),
        "max_consecutive_losses":  rm_summary.get("max_consecutive_losses", 3),
        "last_rejection":          _bot_state.get("last_rejection"),
    }


@app.post("/api/control/reset_protection")
def reset_protection(_: None = Security(_check_api_key)):
    """Setzt Cooldown und StoplossgGuard manuell zurück (nach manueller Prüfung)."""
    _bot_state["reset_protection_requested"] = True
    return {"status": "ok", "message": "Protection-Reset angefordert — wirkt beim nächsten Bot-Zyklus"}


# ── Strategy Marketplace ──────────────────────────────────────────────────────

@app.get("/api/marketplace/strategies")
def marketplace_list():
    """Alle verfügbaren Strategien mit Metadaten."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        registry = StrategyRegistry()
        return {"strategies": registry.list_all()}
    except Exception as e:
        return {"strategies": [], "error": str(e)}


@app.get("/api/marketplace/strategies/{name}")
def marketplace_get(name: str):
    """Einzelne Strategie-Details."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        registry = StrategyRegistry()
        meta = registry.get(name)
        if meta is None:
            raise HTTPException(404, f"Strategie '{name}' nicht gefunden")
        return meta.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


class StrategyMetaUpdate(BaseModel):
    name:        str = ""
    description: str = ""
    tags:        list = []
    risk_level:  str = "balanced"
    min_capital: float = 100.0
    params:      dict = {}


@app.post("/api/marketplace/strategies/{name}/meta")
def marketplace_update_meta(name: str, req: StrategyMetaUpdate,
                             _: None = Security(_check_api_key)):
    """Aktualisiert Metadaten einer Strategie (in .strategy.yaml)."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        registry = StrategyRegistry()
        ok = registry.save_meta(name, req.model_dump())
        if not ok:
            raise HTTPException(500, "YAML-Speichern fehlgeschlagen (PyYAML installiert?)")
        return {"status": "ok", "strategy": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/marketplace/strategies/{name}/export")
def marketplace_export(name: str, _: None = Security(_check_api_key)):
    """Exportiert eine Strategie als ZIP (Download-Pfad)."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        from fastapi.responses import FileResponse
        registry = StrategyRegistry()
        zip_path = registry.export(name)
        return FileResponse(zip_path, filename=f"{name}.strategy.zip",
                            media_type="application/zip")
    except FileNotFoundError:
        raise HTTPException(404, f"Strategie '{name}' nicht gefunden")
    except Exception as e:
        raise HTTPException(500, str(e))


class StrategyImportRequest(BaseModel):
    zip_path: str


@app.post("/api/marketplace/strategies/import")
def marketplace_import(req: StrategyImportRequest, _: None = Security(_check_api_key)):
    """Importiert eine Strategie aus einem lokalen ZIP-Pfad."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        registry = StrategyRegistry()
        module_name = registry.import_zip(req.zip_path)
        return {"status": "ok", "module_name": module_name}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/marketplace/performance")
def marketplace_performance():
    """Live-Performance aller aktiven Strategien aus dem Bot-State."""
    try:
        from crypto_bot.strategy.marketplace import StrategyRegistry
        registry = StrategyRegistry()
        return {"performance": registry.get_performance_summary()}
    except Exception as e:
        return {"performance": [], "error": str(e)}


# ── Hardware Benchmark ────────────────────────────────────────────────────────

@app.get("/api/benchmark/hardware")
def benchmark_hardware():
    """Gespeichertes Hardware-Profil (Ergebnis des letzten Benchmark-Laufs)."""
    try:
        from crypto_bot.benchmark.runner import load_profile, profile_age_hours
        profile = load_profile()
        if profile is None:
            return {"status": "not_run", "message": "Noch kein Benchmark durchgeführt — POST /api/benchmark/hardware/run"}
        return {
            "status":      "ok",
            "age_hours":   round(profile_age_hours() or 0, 1),
            "profile":     profile,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/benchmark/hardware/run")
def run_benchmark_hardware(_: None = Security(_check_api_key)):
    """Startet Hardware-Benchmark (dauert ~10 Sekunden). Speichert Ergebnis."""
    try:
        from crypto_bot.benchmark.runner import run_benchmark
        profile = run_benchmark(save=True, verbose=False)
        return {"status": "ok", "profile": profile}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Feature Management ────────────────────────────────────────────────────────

@app.get("/api/features/all")
def features_all():
    """Alle Feature-Flags mit Status + Metadaten (Label, Beschreibung, Kategorie, Level)."""
    from crypto_bot.config.features import get_all_with_meta
    return {"features": get_all_with_meta()}


class FeatureToggleRequest(BaseModel):
    enabled: bool
    persist: bool = True  # in .env schreiben


@app.post("/api/features/{name}")
def toggle_feature(name: str, req: FeatureToggleRequest, _: None = Security(_check_api_key)):
    """Aktiviert oder deaktiviert ein Feature-Flag zur Laufzeit."""
    from crypto_bot.config.features import set_flag, get_all
    name = name.upper()
    if name not in get_all():
        raise HTTPException(404, f"Feature '{name}' nicht gefunden")
    ok = set_flag(name, req.enabled, persist=req.persist)
    if not ok:
        raise HTTPException(500, "Feature konnte nicht gesetzt werden")
    return {
        "status":  "ok",
        "feature": name,
        "enabled": req.enabled,
        "persisted": req.persist,
    }


# ── Secret Provider Status ────────────────────────────────────────────────────

@app.get("/api/secrets/status")
def secrets_status():
    """Status aller Secret-Backends — welche verfügbar sind, welches aktiv ist."""
    try:
        from crypto_bot.config.secret_provider import all_backends_status, get_provider
        active = get_provider()
        return {
            "active_backend": active.name,
            "backends":       all_backends_status(),
        }
    except Exception as e:
        return {"active_backend": "unknown", "error": str(e), "backends": []}


# ── System Info ───────────────────────────────────────────────────────────────

@app.get("/api/system")
def system_info():
    """System-Informationen: Platform, Python, Docker-Stats, Disk-Nutzung."""
    import platform as _plat
    import shutil as _shutil
    result: dict = {
        "platform": _plat.system(),
        "machine":  _plat.machine(),
        "python":   _plat.python_version(),
    }
    # Disk-Nutzung
    try:
        data_dir = Path(__file__).parent.parent.parent / "data_store"
        total, used, free = _shutil.disk_usage(data_dir.parent)
        result["disk"] = {
            "total_gb": round(total / 1024**3, 1),
            "used_gb":  round(used  / 1024**3, 1),
            "free_gb":  round(free  / 1024**3, 1),
            "pct":      round(used / total * 100, 1),
        }
    except Exception:
        result["disk"] = {}
    # RAM
    try:
        import psutil
        vm = psutil.virtual_memory()
        result["ram"] = {
            "total_mb":     vm.total // (1024*1024),
            "available_mb": vm.available // (1024*1024),
            "pct":          vm.percent,
        }
    except Exception:
        result["ram"] = {}
    # Hardware-Profil Alter
    try:
        from crypto_bot.benchmark.runner import profile_age_hours
        result["benchmark_age_hours"] = profile_age_hours()
    except Exception:
        result["benchmark_age_hours"] = None

    return result


# ── Strategy Management ───────────────────────────────────────────────────────

_strategies_cache: dict = {}

@app.get("/api/strategies")
def list_strategies():
    """Alle verfügbaren Strategien — einmalig gecacht (Strategy-Klassen werden nur 1x instantiiert)."""
    global _strategies_cache
    if _strategies_cache:
        return _strategies_cache
    try:
        from crypto_bot.strategy.loader import list_strategies as _list
        _strategies_cache = {"strategies": _list()}
    except Exception as e:
        _strategies_cache = {"strategies": [], "error": str(e)}
    return _strategies_cache


@app.get("/api/strategies/active")
def active_strategy():
    """Aktuell geladene Strategie."""
    from crypto_bot.config.settings import STRATEGY, STRATEGY_PATH
    return {
        "strategy":      STRATEGY or "internal",
        "strategy_path": STRATEGY_PATH,
        "custom_active": bool(STRATEGY),
    }


class StrategySelectRequest(BaseModel):
    strategy: str
    strategy_path: str = ""
    persist: bool = True


@app.post("/api/strategies/select")
def select_strategy(req: StrategySelectRequest, _: None = Security(_check_api_key)):
    """Strategie wechseln (schreibt in .env, erfordert Bot-Restart)."""
    from crypto_bot.config.features import _write_flag_to_env
    try:
        from crypto_bot.strategy.loader import load_strategy
        load_strategy(req.strategy, req.strategy_path)  # validate first
    except Exception as e:
        raise HTTPException(400, f"Strategie nicht ladbar: {e}")

    if req.persist:
        _write_flag_to_env("STRATEGY", req.strategy)
        if req.strategy_path:
            _write_flag_to_env("STRATEGY_PATH", req.strategy_path)

    return {"status": "ok", "strategy": req.strategy, "restart_required": True}


# ── Hyperopt Loss Functions ───────────────────────────────────────────────────

_loss_functions_cache: dict = {}

@app.get("/api/hyperopt/loss_functions")
def hyperopt_loss_functions():
    """Alle verfügbaren Hyperopt-Loss-Funktionen — einmalig gecacht."""
    global _loss_functions_cache
    if _loss_functions_cache:
        return _loss_functions_cache
    from crypto_bot.optimization.loss_functions import list_loss_functions
    from crypto_bot.config.settings import HYPEROPT_LOSS
    _loss_functions_cache = {
        "active":    HYPEROPT_LOSS,
        "available": list_loss_functions(),
    }
    return _loss_functions_cache


class HyperoptLossRequest(BaseModel):
    loss_function: str
    persist: bool = True


@app.post("/api/hyperopt/loss_functions")
def set_hyperopt_loss(req: HyperoptLossRequest, _: None = Security(_check_api_key)):
    """Hyperopt-Loss-Funktion wechseln."""
    from crypto_bot.optimization.loss_functions import list_loss_functions
    valid = [f["name"] for f in list_loss_functions()]
    if req.loss_function not in valid:
        raise HTTPException(400, f"Unbekannte Loss-Funktion '{req.loss_function}'. Verfügbar: {valid}")
    if req.persist:
        from crypto_bot.config.features import _write_flag_to_env
        _write_flag_to_env("HYPEROPT_LOSS", req.loss_function)
    return {"status": "ok", "loss_function": req.loss_function}


# ── RPC / Alerting ────────────────────────────────────────────────────────────

@app.get("/api/rpc/status")
def rpc_status():
    """Status aller Alerting-Kanäle."""
    from crypto_bot.config.settings import (
        TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL, WEBHOOK_URL
    )
    from crypto_bot.config import features as feat
    return {
        "channels": {
            "telegram": {
                "configured": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
                "enabled":    bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
            },
            "discord": {
                "configured": bool(DISCORD_WEBHOOK_URL),
                "enabled":    feat.DISCORD_RPC and bool(DISCORD_WEBHOOK_URL),
                "feature":    "DISCORD_RPC",
            },
            "webhook": {
                "configured": bool(WEBHOOK_URL),
                "enabled":    feat.WEBHOOK_RPC and bool(WEBHOOK_URL),
                "feature":    "WEBHOOK_RPC",
                "url":        WEBHOOK_URL[:40] + "..." if len(WEBHOOK_URL) > 40 else WEBHOOK_URL,
            },
        }
    }


@app.post("/api/rpc/test")
def test_rpc(_: None = Security(_check_api_key)):
    """Testnachricht an alle konfigurierten Alerting-Kanäle senden."""
    try:
        from crypto_bot.rpc.manager import get_rpc
        results = get_rpc().test_all_channels()
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Backtest Report ───────────────────────────────────────────────────────────

@app.get("/api/backtest/last_report")
def backtest_last_report():
    """Letzter Backtest-Report aus dem State (wenn vorhanden)."""
    report = _bot_state.get("last_backtest_report")
    if not report:
        return {"status": "not_run", "message": "Noch kein Backtest durchgeführt"}
    return {"status": "ok", "report": report}


# ── ML Model Info ─────────────────────────────────────────────────────────────

_model_info_cache: dict = {}

@app.get("/api/model/info")
def model_info():
    """ML-Modell Informationen (Typ, F1, Features, Trainings-Datum) — einmalig gecacht."""
    global _model_info_cache
    if _model_info_cache:
        return _model_info_cache
    try:
        from crypto_bot.config.settings import ML_MODEL_PATH
        import joblib
        data = joblib.load(ML_MODEL_PATH)
        _model_info_cache = {
            "status":     "ok",
            "model_type": data.get("model_type", type(data.get("model")).__name__),
            "val_f1":     data.get("val_f1"),
            "trained_on": data.get("trained_on"),
            "n_features": len(data.get("features", [])),
            "features":   data.get("features", [])[:20],
        }
        del data  # Modell-Objekt sofort freigeben
        return _model_info_cache
    except Exception as e:
        return {"status": "not_found", "error": str(e)}


@app.get("/api/rate_limits")
def rate_limit_stats():
    """Exchange Rate-Limit Monitoring — Hits, Retries, letzter Fehler."""
    try:
        from crypto_bot.data.fetcher import get_rate_limit_stats
        return get_rate_limit_stats()
    except Exception as e:
        return {"hits": 0, "retries": 0, "last_hit": None, "last_error": str(e)}


@app.get("/api/tax/journal")
def tax_journal(year: int = 0):
    """FIFO Trade-Journal für DE/AT Steuer — realisierte Gewinne/Verluste."""
    try:
        from crypto_bot.reporting.tax_journal import get_tax_journal
        journal = get_tax_journal()
        journal.load_from_db()
        return journal.get_report(year=year if year > 0 else None)
    except Exception as e:
        return {"error": str(e), "trades_total": 0}


@app.get("/api/tax/export")
def tax_export(year: int = 0, fmt: str = "de"):
    """CSV-Export des FIFO Trade-Journals (fmt=de für ELSTER, fmt=at für Österreich)."""
    from fastapi.responses import Response
    try:
        from crypto_bot.reporting.tax_journal import get_tax_journal
        journal = get_tax_journal()
        journal.load_from_db()
        csv_str = journal.export_csv(path="", year=year if year > 0 else None, fmt=fmt)
        filename = f"steuerjournal_{year or 'all'}_{fmt}.csv"
        return Response(
            content=csv_str.encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/twap/status")
def twap_status():
    """TWAP Execution Status — ob TWAP verfügbar ist und ab welchem Betrag."""
    from crypto_bot.execution.twap import TWAPExecutor
    return {
        "available":       True,
        "min_usdt":        TWAPExecutor.MIN_USDT,
        "max_slices":      TWAPExecutor.MAX_SLICES,
        "description":     "Time-Weighted Average Price für Orders über $10k",
    }


@app.get("/api/signals/bus")
def signal_bus_status():
    """Signal Bus Status — letzte Signale im Bus."""
    try:
        from crypto_bot.signals.bus import get_bus
        bus     = get_bus("dashboard")
        signals = list(bus.consume(timeout=0, max_signals=20))
        return {
            "count":   len(signals),
            "signals": [s.to_dict() for s in signals],
        }
    except Exception as e:
        return {"count": 0, "signals": [], "error": str(e)}


@app.get("/api/walk_forward")
def walk_forward_result():
    """Letztes Walk-Forward Backtest Ergebnis aus bot_state."""
    return {"walk_forward": _bot_state.get("walk_forward", {})}


@app.post("/api/walk_forward/run")
def run_walk_forward_backtest(days: int = 720, windows: int = 6):
    """Walk-Forward Backtest starten (async — Ergebnis via /api/walk_forward)."""
    import threading
    def _run():
        try:
            from crypto_bot.backtest.walk_forward import run_walk_forward
            result = run_walk_forward(total_days=days, n_windows=windows, train_ratio=0.7)
            _bot_state["walk_forward"] = result or {}
        except Exception as e:
            _bot_state["walk_forward"] = {"error": str(e)}
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "days": days, "windows": windows}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.api:app", host="0.0.0.0", port=8000, reload=False)
