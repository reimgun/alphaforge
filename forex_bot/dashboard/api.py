"""
Forex Bot — Dashboard REST API (FastAPI, Port 8001).

Endpunkte:
  GET  /api/status          Kapital, Modus, offene Trades
  GET  /api/trades          Letzte Trades aus DB
  GET  /api/performance     Win-Rate, Pips, PnL
  GET  /api/calendar        Heutige + morgige News-Events
  GET  /api/positions       Offene Positionen (live vom Broker)
  GET  /api/progress        Phase Progress (Paper→Testnet→Live)
  GET  /api/mode            Aktueller Risk Mode + Parameter
  POST /api/mode/{name}     Risk Mode ändern
  GET  /api/regime          Aktuelles Market Regime pro Instrument
  GET  /api/broker          Aktueller Broker + verfügbare Broker
  POST /api/broker/{name}   Broker wechseln (oanda|capital|ig|ibkr)
  GET  /health              Health-Check
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("forex_bot")
app = FastAPI(title="Forex Bot API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Shared state is set by bot.py
_bot_state: dict = {}
_risk_mode_callback: Optional[Callable] = None
_broker_callback: Optional[Callable] = None


def set_bot_state(state: dict):
    global _bot_state
    _bot_state = state


def set_risk_mode_callback(cb: Callable):
    """Register the callback that changes the live risk mode in bot.py."""
    global _risk_mode_callback
    _risk_mode_callback = cb


def set_broker_callback(cb: Callable):
    """Register the callback that swaps the live broker client in bot.py."""
    global _broker_callback
    _broker_callback = cb


# ── Existing Endpoints ────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    from forex_bot.config import settings as cfg
    return {
        "trading_mode":  cfg.TRADING_MODE,
        "oanda_env":     cfg.OANDA_ENV,
        "capital":       _bot_state.get("capital", cfg.INITIAL_CAPITAL),
        "daily_pnl":     _bot_state.get("daily_pnl", 0.0),
        "open_trades":   _bot_state.get("open_trades", 0),
        "paused":        _bot_state.get("paused", False),
        "running":       _bot_state.get("running", False),
        "instruments":   cfg.INSTRUMENTS,
        "last_cycle":    _bot_state.get("last_cycle"),
        "risk_mode":     _bot_state.get("risk_mode", cfg.RISK_MODE),
        "ml_model":      _bot_state.get("ml_model_info", {}),
        "broker":           _bot_state.get("broker", cfg.FOREX_BROKER),
        "data_warnings":    _bot_state.get("data_warnings", {}),
        "broker_connected": _bot_state.get("broker_connected", False),
        "broker_error":     _bot_state.get("broker_error", ""),
        "broker_env":       _bot_state.get("broker_env", ""),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/trades")
def get_trades(limit: int = 50):
    from forex_bot.monitoring.logger import get_recent_trades
    return {"trades": get_recent_trades(limit=limit)}


@app.get("/api/performance")
def get_performance():
    import statistics
    import numpy as np
    from forex_bot.monitoring.logger import get_recent_trades
    trades_raw = get_recent_trades(limit=9999)
    closed = [t for t in trades_raw if t.get("status") == "closed"]
    if not closed:
        return {"trades": 0}

    n         = len(closed)
    pnl_seq   = [float(t.get("pnl_usd",  0) or 0) for t in closed]
    pip_seq   = [float(t.get("pnl_pips", 0) or 0) for t in closed]
    wins_usd  = [p for p in pnl_seq if p > 0]
    losses_usd = [p for p in pnl_seq if p < 0]
    wins_pip  = [t for t in closed if (t.get("pnl_pips") or 0) > 0]
    total_pip = sum(pip_seq)
    total_usd = sum(pnl_seq)

    win_rate = round(len(wins_usd) / n * 100, 1) if n else 0.0

    # Sharpe (annualised, pip-based)
    sharpe = 0.0
    if len(pip_seq) > 2:
        try:
            mean_p = statistics.mean(pip_seq)
            std_p  = statistics.stdev(pip_seq)
            sharpe = round(mean_p / std_p * (252 ** 0.5) if std_p else 0, 2)
        except Exception:
            pass

    # Sortino (only downside deviation)
    sortino = 0.0
    if len(pip_seq) > 2:
        try:
            neg = [p for p in pip_seq if p < 0]
            if neg:
                mean_p  = statistics.mean(pip_seq)
                down_std = (sum(p ** 2 for p in neg) / len(pip_seq)) ** 0.5
                sortino  = round(mean_p / down_std * (252 ** 0.5) if down_std else 0, 2)
        except Exception:
            pass

    # Max Drawdown
    drawdown = 0.0
    try:
        arr  = np.array(pnl_seq, dtype=float)
        cum  = np.cumsum(arr)
        peak = np.maximum.accumulate(cum)
        dds  = (peak - cum) / (np.abs(peak) + 1e-10) * 100
        drawdown = round(float(dds.max()), 1)
    except Exception:
        pass

    # Profit Factor
    gross_win  = sum(wins_usd)
    gross_loss = abs(sum(losses_usd))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else 0.0

    # Avg win / loss
    avg_win  = round(sum(wins_usd)   / len(wins_usd),   2) if wins_usd  else 0.0
    avg_loss = round(sum(losses_usd) / len(losses_usd), 2) if losses_usd else 0.0

    instruments: dict = {}
    for t in closed:
        inst = t.get("instrument", "?")
        if inst not in instruments:
            instruments[inst] = {"trades": 0, "pips": 0.0, "wins": 0}
        instruments[inst]["trades"] += 1
        instruments[inst]["pips"]   += t.get("pnl_pips", 0) or 0
        if (t.get("pnl_pips") or 0) > 0:
            instruments[inst]["wins"] += 1

    return {
        "trades":        n,
        "win_rate":      win_rate,
        "total_pips":    round(total_pip, 1),
        "total_pnl":     round(total_usd, 2),
        "sharpe":        sharpe,
        "sortino":       sortino,
        "drawdown":      drawdown,
        "profit_factor": profit_factor,
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
        "instruments":   instruments,
    }


@app.get("/api/calendar")
def get_calendar(hours: int = 24):
    from forex_bot.calendar.economic_calendar import get_upcoming_events
    from forex_bot.config import settings as cfg
    events = get_upcoming_events(cfg.NEWS_CURRENCIES, hours=hours)
    return {
        "events": [
            {
                "time":     e["time"].isoformat(),
                "currency": e["currency"],
                "event":    e["event"],
                "impact":   e["impact"],
                "forecast": e.get("forecast", ""),
                "previous": e.get("previous", ""),
            }
            for e in events
        ]
    }


@app.get("/api/positions")
def get_positions():
    try:
        from forex_bot.execution.broker_factory import create_broker_client
        client = create_broker_client()
        trades = client.get_open_trades()
        return {"positions": trades}
    except Exception as e:
        return {"positions": [], "error": str(e)}


# ── New Endpoints (Features 2, 5, 7) ─────────────────────────────────────────

@app.get("/api/progress")
def get_progress():
    """Phase progress: Paper → Practice → Live."""
    try:
        from forex_bot.ai.phase_progress import get_forex_phase_progress
        from forex_bot.monitoring.logger import get_recent_trades
        import statistics

        trades_raw = get_recent_trades(limit=9999)
        closed     = [t for t in trades_raw if t.get("status") == "closed"]

        trades   = len(closed)
        win_rate = 0.0
        sharpe   = 0.0
        drawdown = 0.0

        first_trade_date = None
        if closed:
            wins     = [t for t in closed if (t.get("pnl_pips") or 0) > 0]
            win_rate = round(len(wins) / trades * 100, 1)
            pips_seq = [t.get("pnl_pips", 0) or 0 for t in closed]
            if len(pips_seq) > 2:
                try:
                    mean_p = statistics.mean(pips_seq)
                    std_p  = statistics.stdev(pips_seq)
                    sharpe = round(mean_p / std_p * (252 ** 0.5) if std_p else 0, 2)
                except Exception:
                    pass
            # Simple drawdown estimate from pips
            import numpy as np
            arr = np.array(pips_seq, dtype=float)
            cum = np.cumsum(arr)
            peak = np.maximum.accumulate(cum)
            dds  = (peak - cum) / (np.abs(peak) + 1e-10) * 100
            drawdown = round(float(dds.max()), 1)

            # First trade date for ETA calculation
            oldest = min(
                (t.get("entry_time") or t.get("created_at") or "" for t in closed),
                default=None,
            )
            if oldest:
                from datetime import datetime, timezone
                try:
                    first_trade_date = datetime.fromisoformat(
                        oldest.replace("Z", "+00:00")
                    )
                    if first_trade_date.tzinfo is None:
                        first_trade_date = first_trade_date.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

        ml_info  = _bot_state.get("ml_model_info", {})
        model_f1 = ml_info.get("val_f1", 0.0) if ml_info.get("loaded") else 0.0
        mode     = _bot_state.get("risk_mode", "balanced")

        progress = get_forex_phase_progress(
            trades=trades, sharpe=sharpe, win_rate=win_rate,
            drawdown=drawdown, model_f1=model_f1, mode=mode,
            first_trade_date=first_trade_date,
        )
        return progress.as_dict()

    except Exception as e:
        log.error(f"Progress endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mode")
def get_mode_info():
    """Return current risk mode and all its parameters."""
    from forex_bot.risk.risk_modes import get_mode, RISK_MODES
    from forex_bot.config import settings as cfg

    mode_name = _bot_state.get("risk_mode", cfg.RISK_MODE)
    mode      = get_mode(mode_name)

    return {
        "current_mode": mode.name,
        "params": {
            "risk_per_trade":       mode.risk_per_trade,
            "max_open_trades":      mode.max_open_trades,
            "min_confidence":       mode.min_confidence,
            "news_pause_min":       mode.news_pause_min,
            "spread_limit_pips":    mode.spread_limit_pips,
            "daily_loss_limit":     mode.daily_loss_limit,
            "session_strict":       mode.session_strict,
            "require_mtf":          mode.require_mtf,
            "consecutive_loss_stop": mode.consecutive_loss_stop,
            "atr_multiplier":       mode.atr_multiplier,
            "rr_ratio":             mode.rr_ratio,
        },
        "available_modes": list(RISK_MODES.keys()),
    }


@app.post("/api/mode/{mode_name}")
def set_mode(mode_name: str):
    """Change the active risk mode."""
    from forex_bot.risk.risk_modes import RISK_MODES, get_mode

    if mode_name.lower() not in RISK_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{mode_name}'. Available: {list(RISK_MODES.keys())}",
        )

    if _risk_mode_callback is not None:
        _risk_mode_callback(mode_name)
    else:
        # Just update state if callback not registered (e.g. standalone API)
        _bot_state["risk_mode"] = mode_name.lower()

    mode = get_mode(mode_name)
    return {
        "success": True,
        "mode":    mode.name,
        "message": f"Risk mode changed to {mode.name}",
    }


@app.get("/api/regime")
def get_regime():
    """Current market regime per instrument."""
    from forex_bot.config import settings as cfg
    regime_map = _bot_state.get("regime", {})

    return {
        "regime": regime_map,
        "instruments": cfg.INSTRUMENTS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "Regimes are updated each bot cycle (hourly).",
    }


@app.get("/api/macro")
def get_macro():
    """Current macro context: USD regime, VIX, risk regime, carry signals."""
    macro = _bot_state.get("macro", {})
    if macro:
        return macro
    # On-demand fetch if bot hasn't run a cycle yet
    try:
        from forex_bot.ai.macro_signals import get_macro_context
        return get_macro_context()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Macro data unavailable: {e}")


@app.get("/api/spreads")
def get_spreads():
    """Current rolling average spreads per instrument (from spread shock monitor)."""
    from forex_bot.execution.spread_monitor import spread_stats
    return {
        "spread_ema": _bot_state.get("spread_ema", spread_stats()),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }


_BROKERS = {
    "oanda":   "OANDA REST API v3 (practice / live)",
    "capital": "Capital.com REST API (CFD Demo/Live)",
    "ig":      "IG Group REST API (CFD Demo/Live)",
    "ibkr":    "Interactive Brokers via ib_insync (requires IB Gateway)",
}


class BrokerCredentials(BaseModel):
    """Optionale Credentials für den Broker-Wechsel aus dem Dashboard."""
    env:        str = ""   # demo | live | practice
    # OANDA
    api_key:    str = ""
    account_id: str = ""
    # Capital.com / IG
    email:      str = ""
    username:   str = ""
    password:   str = ""
    # IG extra
    ig_account_id: str = ""
    # IBKR
    host:       str = ""
    port:       int = 0
    client_id:  int = 0
    account:    str = ""


@app.get("/api/broker")
def get_broker():
    """Current broker, available brokers and which are already configured."""
    from forex_bot.config import settings as cfg
    from forex_bot.execution.env_manager import get_configured
    current    = _bot_state.get("broker", cfg.FOREX_BROKER)
    configured = get_configured()   # [{"broker": "capital", "env": "demo"}, ...]
    return {
        "current":    current,
        "configured": configured,
        "available":  [
            {"name": name, "description": desc, "active": name == current}
            for name, desc in _BROKERS.items()
        ],
    }


@app.post("/api/broker/{broker_name}")
def set_broker(broker_name: str, creds: BrokerCredentials = BrokerCredentials()):
    """
    Switch the active broker at runtime — optionally with new credentials.

    Credentials passed in the request body override the .env values for
    this session. They are NOT written back to the .env file.

    Raises 400 for unknown broker names.
    Raises 503 if the connection to the new broker fails.
    """
    name = broker_name.lower().strip()
    if name not in _BROKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown broker '{name}'. Available: {list(_BROKERS.keys())}",
        )

    # Build a credentials dict — only include non-empty values
    creds_dict = {"broker": name}
    for field, value in creds.model_dump().items():
        if value:
            creds_dict[field] = value
    # Normalize IG account_id field name
    if "ig_account_id" in creds_dict:
        creds_dict["account_id"] = creds_dict.pop("ig_account_id")

    if _broker_callback is not None:
        try:
            _broker_callback(name, creds_dict)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Broker switch failed: {e}")
    else:
        _bot_state["broker"] = name

    return {
        "success":     True,
        "broker":      name,
        "description": _BROKERS[name],
        "message":     f"Broker switched to {name}. Takes effect on next cycle.",
    }


class AddCredentialsRequest(BaseModel):
    broker:     str
    env:        str        # practice | live | demo
    api_key:    str = ""
    account_id: str = ""   # OANDA
    email:      str = ""   # Capital.com
    username:   str = ""   # IG
    password:   str = ""   # Capital.com / IG
    host:       str = ""   # IBKR
    port:       int = 0    # IBKR
    client_id:  int = 0    # IBKR
    account:    str = ""   # IBKR


@app.post("/api/broker/credentials")
def add_credentials(req: AddCredentialsRequest):
    """
    Schreibt neue Broker-Credentials in forex_bot/.env.

    Gibt 409 zurück wenn für diesen Broker+Env bereits ein Eintrag existiert.
    Credentials werden NICHT überschrieben — für Änderungen .env manuell editieren.
    """
    from forex_bot.execution.env_manager import credentials_exist, write_credentials

    broker = req.broker.lower().strip()
    env    = req.env.lower().strip()

    if broker not in _BROKERS:
        raise HTTPException(status_code=400, detail=f"Unbekannter Broker: {broker}")

    existing = credentials_exist(broker, env)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Existiert bereits: {existing}. Zum Ändern .env manuell editieren.",
        )

    try:
        write_credentials(broker, env, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log.info(f"Credentials gespeichert: {broker} ({env})")
    return {
        "success": True,
        "broker":  broker,
        "env":     env,
        "message": f"{_BROKERS[broker]} ({env}) gespeichert.",
    }


@app.post("/api/control/{action}")
def control(action: str):
    """Bot-Steuerung: pause | resume | stop"""
    action = action.lower()
    if action == "pause":
        _bot_state["paused"] = True
        log.info("Dashboard: Bot pausiert")
        return {"success": True, "message": "Bot pausiert"}
    elif action == "resume":
        _bot_state["paused"] = False
        log.info("Dashboard: Bot fortgesetzt")
        return {"success": True, "message": "Bot fortgesetzt"}
    elif action == "stop":
        _bot_state["running"] = False
        log.warning("Dashboard: Bot gestoppt")
        return {"success": True, "message": "Bot gestoppt"}
    else:
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")


@app.get("/api/logs")
def get_logs(lines: int = 200, level: str = ""):
    """Letzte N Zeilen aus forex_bot.log."""
    from pathlib import Path
    log_path = Path(__file__).parent.parent / "logs" / "forex_bot.log"
    if not log_path.exists():
        return {"lines": [], "path": str(log_path), "exists": False}
    try:
        text = log_path.read_text(errors="replace").splitlines()
        if level:
            text = [l for l in text if level.upper() in l]
        return {"lines": text[-lines:], "total": len(text), "exists": True}
    except Exception as e:
        return {"lines": [], "error": str(e), "exists": False}


@app.get("/api/log_level")
def get_log_level():
    root_logger = logging.getLogger()
    return {"level": logging.getLevelName(root_logger.level)}


@app.post("/api/log_level/{level}")
def set_log_level(level: str):
    level = level.upper()
    numeric = getattr(logging, level, None)
    if not isinstance(numeric, int):
        raise HTTPException(status_code=400, detail=f"Unbekannter Level: {level}")
    logging.getLogger().setLevel(numeric)
    logging.getLogger("forex_bot").setLevel(numeric)
    log.info(f"Log-Level auf {level} gesetzt")
    return {"status": "ok", "level": level}


@app.get("/api/candles")
def get_candles(instrument: str = "", granularity: str = "H1", limit: int = 150):
    """OHLCV candles for the requested (or first active) instrument."""
    try:
        from forex_bot.config import settings as cfg
        from forex_bot.execution.broker_factory import create_broker_client
        instr  = instrument or (cfg.INSTRUMENTS[0] if cfg.INSTRUMENTS else "EUR_USD")
        client = create_broker_client()
        raw    = client.get_candles(instr, granularity=granularity, count=limit)
        if not raw:
            raise ValueError("Keine Daten")
        return {"instrument": instr, "granularity": granularity, "candles": raw}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/heartbeat")
def get_heartbeat():
    """Bot liveness check based on last heartbeat timestamp."""
    last_hb = _bot_state.get("last_heartbeat") or _bot_state.get("last_cycle")
    if not last_hb:
        return {"alive": False, "silence_minutes": None, "last_ping": None}
    try:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        silence = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        alive = silence < 90  # 90 min = 1.5 Zyklen Toleranz
        return {"alive": alive, "silence_minutes": round(silence, 1), "last_ping": last_hb}
    except Exception:
        return {"alive": False, "silence_minutes": None, "last_ping": last_hb}


@app.get("/api/rejections")
def get_rejections(limit: int = 20):
    """Recent trade rejections tracked during bot cycles."""
    return {"rejections": _bot_state.get("recent_rejections", [])[:limit]}


@app.get("/api/signals")
def get_signals(limit: int = 20):
    """Recent accepted signals (passed all filters, trade attempted)."""
    return {"signals": _bot_state.get("recent_signals", [])[:limit]}


@app.get("/api/features")
def get_features():
    """Current boolean feature settings (readable + togglable at runtime)."""
    import os
    _FEATURES = [
        {"name": "SESSION_FILTER",   "env": "FOREX_SESSION_FILTER",   "default": "true",
         "label": "Session Filter",
         "desc":  "Nur während aktiver Trading-Sessions handeln (London / New York)"},
        {"name": "SESSION_QUALITY",  "env": "FOREX_SESSION_QUALITY",  "default": "true",
         "label": "Session Quality Filter",
         "desc":  "Nur Sessions mit guter Liquidität erlaubt (filtert schlechte Spread-Phasen)"},
        {"name": "MULTI_STRATEGY",   "env": "FOREX_MULTI_STRATEGY",   "default": "true",
         "label": "Multi-Strategy",
         "desc":  "Mehrere Strategien gleichzeitig evaluieren — wählt automatisch die beste"},
        {"name": "LEAN_MODE",        "env": "FOREX_LEAN_MODE",        "default": "false",
         "label": "Lean Mode",
         "desc":  "Minimaler Ressourcenverbrauch — deaktiviert LSTM, Monte Carlo (empfohlen für QNAP/NAS)"},
        {"name": "TELEGRAM_POLLING", "env": "FOREX_TELEGRAM_POLLING", "default": "false",
         "label": "Telegram Polling",
         "desc":  "Bot wartet aktiv auf Telegram-Befehle (polling statt webhook)"},
    ]
    result = []
    for f in _FEATURES:
        val = os.environ.get(f["env"], f["default"]).lower() == "true"
        result.append({
            "name":    f["name"],
            "env":     f["env"],
            "label":   f["label"],
            "desc":    f["desc"],
            "enabled": val,
        })
    return {"features": result}


@app.post("/api/features/{name}")
def set_feature(name: str, body: dict = {}):
    """Toggle a feature flag at runtime and persist to .env."""
    import os
    from pathlib import Path
    _ENV_MAP = {
        "SESSION_FILTER":   "FOREX_SESSION_FILTER",
        "SESSION_QUALITY":  "FOREX_SESSION_QUALITY",
        "MULTI_STRATEGY":   "FOREX_MULTI_STRATEGY",
        "LEAN_MODE":        "FOREX_LEAN_MODE",
        "TELEGRAM_POLLING": "FOREX_TELEGRAM_POLLING",
    }
    env_key = _ENV_MAP.get(name)
    if not env_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown feature: {name}")
    enabled = body.get("enabled", True)
    val_str = "true" if enabled else "false"

    # 1. In-memory
    os.environ[env_key] = val_str
    try:
        from forex_bot.config import settings as cfg
        if name == "SESSION_FILTER":    cfg.SESSION_FILTER          = enabled
        elif name == "SESSION_QUALITY": cfg.SESSION_QUALITY_FILTER  = enabled
        elif name == "MULTI_STRATEGY":  cfg.MULTI_STRATEGY          = enabled
        elif name == "LEAN_MODE":       cfg.LEAN_MODE               = enabled
        elif name == "TELEGRAM_POLLING": cfg.TELEGRAM_POLLING       = enabled
    except Exception:
        pass

    # 2. Persist to forex_bot/.env (same approach as crypto features.py)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{env_key}="):
                new_lines.append(f"{env_key}={val_str}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"{env_key}={val_str}")
        env_path.write_text("\n".join(new_lines) + "\n")

    return {"status": "ok", "name": name, "enabled": enabled, "persisted": env_path.exists()}


@app.get("/health")
def health():
    return {"status": "ok", "service": "forex-bot-api", "version": "2.3.0"}
