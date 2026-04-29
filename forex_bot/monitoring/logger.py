"""
Forex Bot — Logging & Trade-Persistenz.
"""
import logging
import sqlite3
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "data_store" / "trades.db"
LOG_PATH = Path(__file__).parent.parent / "logs" / "forex_bot.log"


def setup_logging(level: str = "INFO"):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level    = getattr(logging, level.upper(), logging.INFO),
        format   = fmt,
        handlers = [
            logging.StreamHandler(),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )
    return logging.getLogger("forex_bot")


def get_recent_trades(limit: int = 50) -> list:
    """Gibt letzte N abgeschlossene Trades als dict-Liste zurück."""
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_performance_summary() -> dict:
    """Berechnet Performance-Kennzahlen aus der Trade-DB."""
    trades = get_recent_trades(limit=9999)
    closed = [t for t in trades if t.get("status") == "closed"]
    if not closed:
        return {}

    wins      = [t for t in closed if (t.get("pnl_pips") or 0) > 0]
    total_pip = sum(t.get("pnl_pips", 0) for t in closed)
    total_usd = sum(t.get("pnl_usd", 0) for t in closed)

    return {
        "trades":     len(closed),
        "win_rate":   round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "total_pips": round(total_pip, 1),
        "total_pnl":  round(total_usd, 2),
    }
