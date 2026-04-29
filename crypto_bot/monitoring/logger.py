"""
SQLite Trade-Journal — persistentes Logging aller Trades, Signale und Events.
Überleben Bot-Neustarts und Crashes.
"""
import sqlite3
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from crypto_bot.config.settings import DB_PATH, LOG_DIR, LOG_LEVEL

# Filesystem-Logging
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "bot.log", maxBytes=50 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("trading_bot")

_db_initialized = False  # init_db() nur einmal loggen


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Concurrent reads
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Erstellt alle Tabellen falls nicht vorhanden. Loggt nur beim ersten Aufruf."""
    global _db_initialized
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL,
                entry_price REAL,
                exit_price  REAL,
                quantity    REAL,
                pnl         REAL,
                pnl_pct     REAL,
                reason      TEXT,
                ai_source   TEXT,
                confidence  REAL,
                entry_time  TEXT,
                exit_time   TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                signal      TEXT NOT NULL,
                price       REAL,
                ai_source   TEXT,
                confidence  REAL,
                reasoning   TEXT,
                acted_on    INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bot_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT NOT NULL,
                message     TEXT,
                severity    TEXT DEFAULT 'info',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS performance_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                capital         REAL,
                daily_pnl       REAL,
                total_pnl       REAL,
                open_position   INTEGER DEFAULT 0,
                snapshot_date   TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trade_rejections (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                signal      TEXT NOT NULL,
                price       REAL,
                reason      TEXT,
                source      TEXT,
                strategy    TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS paper_state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                capital         REAL NOT NULL,
                initial_capital REAL NOT NULL,
                position_json   TEXT,
                entry_time      TEXT,
                entry_fee       REAL DEFAULT 0,
                saved_at        TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS execution_quality (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                side         TEXT NOT NULL,
                signal_price REAL NOT NULL,
                fill_price   REAL NOT NULL,
                quantity     REAL NOT NULL,
                slippage_bps REAL NOT NULL,
                order_type   TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            );
        """)
    if not _db_initialized:
        log.info(f"Datenbank initialisiert: {DB_PATH}")
        _db_initialized = True


def save_paper_state(
    capital: float,
    initial_capital: float,
    position_data: "dict | None" = None,
    entry_time: str = "",
    entry_fee: float = 0.0,
) -> None:
    """Persistiert den Paper-Trading-State über Container-Restarts hinaus."""
    import json
    if not _db_initialized:
        init_db()
    pos_json = json.dumps(position_data) if position_data else None
    with _db() as conn:
        conn.execute(
            """INSERT INTO paper_state (id, capital, initial_capital, position_json, entry_time, entry_fee, saved_at)
               VALUES (1, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
                 capital         = excluded.capital,
                 initial_capital = excluded.initial_capital,
                 position_json   = excluded.position_json,
                 entry_time      = excluded.entry_time,
                 entry_fee       = excluded.entry_fee,
                 saved_at        = excluded.saved_at""",
            (round(capital, 6), round(initial_capital, 6), pos_json, entry_time, round(entry_fee, 6)),
        )


def load_paper_state() -> "dict | None":
    """
    Lädt gespeicherten Paper-State. Gibt None zurück wenn kein State vorhanden.
    Returns: {'capital': float, 'initial_capital': float, 'position': dict|None,
               'entry_time': str, 'entry_fee': float}
    """
    import json
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT capital, initial_capital, position_json, entry_time, entry_fee FROM paper_state WHERE id=1"
            ).fetchone()
        if row is None:
            return None
        pos = json.loads(row["position_json"]) if row["position_json"] else None
        return {
            "capital":         float(row["capital"]),
            "initial_capital": float(row["initial_capital"]),
            "position":        pos,
            "entry_time":      row["entry_time"] or "",
            "entry_fee":       float(row["entry_fee"]),
        }
    except Exception as e:
        log.warning(f"paper_state laden fehlgeschlagen: {e}")
        return None


def log_trade(
    symbol: str, side: str, entry_price: float, exit_price: float,
    quantity: float, pnl: float, reason: str = "",
    ai_source: str = "", confidence: float = 0.0,
    entry_time: str = "", exit_time: str = "",
):
    pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0
    with _db() as conn:
        conn.execute(
            """INSERT INTO trades
               (symbol, side, entry_price, exit_price, quantity, pnl, pnl_pct,
                reason, ai_source, confidence, entry_time, exit_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, side, entry_price, exit_price, quantity,
             round(pnl, 4), round(pnl_pct, 4),
             reason, ai_source, confidence, entry_time, exit_time),
        )
    log.info(f"TRADE {side} {symbol} | PnL: {pnl:+.2f} USDT ({pnl_pct:+.2f}%) | {reason}")


def log_signal(
    symbol: str, signal: str, price: float,
    ai_source: str = "", confidence: float = 0.0,
    reasoning: str = "", acted_on: bool = False,
):
    with _db() as conn:
        conn.execute(
            """INSERT INTO signals
               (symbol, signal, price, ai_source, confidence, reasoning, acted_on)
               VALUES (?,?,?,?,?,?,?)""",
            (symbol, signal, price, ai_source, confidence, reasoning, int(acted_on)),
        )


def log_event(message: str, event_type: str = "info", severity: str = "info"):
    with _db() as conn:
        conn.execute(
            "INSERT INTO bot_events (event_type, message, severity) VALUES (?,?,?)",
            (event_type, message, severity),
        )
    level = getattr(logging, severity.upper(), logging.INFO)
    log.log(level, f"[{event_type}] {message}")


def save_performance_snapshot(capital: float, daily_pnl: float, total_pnl: float, has_position: bool):
    today = datetime.now(timezone.utc).date().isoformat()
    with _db() as conn:
        conn.execute(
            """INSERT INTO performance_snapshots
               (capital, daily_pnl, total_pnl, open_position, snapshot_date)
               VALUES (?,?,?,?,?)""",
            (round(capital, 4), round(daily_pnl, 4), round(total_pnl, 4), int(has_position), today),
        )


def log_rejection(
    symbol: str, signal: str, price: float,
    reason: str, source: str = "", strategy: str = "",
):
    """Logt einen abgelehnten Trade (HOLD-Entscheidung) mit Begründung."""
    with _db() as conn:
        conn.execute(
            """INSERT INTO trade_rejections (symbol, signal, price, reason, source, strategy)
               VALUES (?,?,?,?,?,?)""",
            (symbol, signal, price, reason, source, strategy),
        )
    log.info(f"REJECTION {signal} {symbol} @ {price:.2f} | {source} | {reason}")


def get_recent_rejections(limit: int = 10) -> list[dict]:
    """Gibt die letzten abgelehnten Trades zurück."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_rejections ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_trades(limit: int = 20) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def export_trades_csv(path: str = "exports/trades.csv") -> str:
    """Exportiert alle Trades als CSV-Datei."""
    import csv
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    trades = get_recent_trades(limit=100_000)
    if not trades:
        log.warning("Keine Trades zum Exportieren")
        return path
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    log.info(f"Trades exportiert: {path} ({len(trades)} Trades)")
    return path


def export_performance_json(path: str = "exports/performance.json") -> str:
    """Exportiert Performance-Zusammenfassung als JSON."""
    import json
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "summary":   get_performance_summary(),
        "snapshots": _get_all_snapshots(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    log.info(f"Performance exportiert: {path}")
    return path


def _get_all_snapshots() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM performance_snapshots ORDER BY created_at DESC LIMIT 365"
        ).fetchall()
    return [dict(r) for r in rows]


def get_equity_curve() -> list[dict]:
    """Gibt Equity-Kurve als Liste von {date, capital} zurück."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT snapshot_date, capital FROM performance_snapshots ORDER BY snapshot_date"
        ).fetchall()
    return [dict(r) for r in rows]


def get_performance_summary() -> dict:
    with _db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                              AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
                ROUND(SUM(pnl), 2)                    AS total_pnl,
                ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2) AS avg_win,
                ROUND(AVG(CASE WHEN pnl < 0 THEN pnl END), 2) AS avg_loss
            FROM trades
        """).fetchone()
    return dict(row) if row else {}


def get_rolling_performance(days: int = 7) -> dict:
    """
    Berechnet Performance-Metriken für die letzten N Tage.

    Returns:
        dict mit trades, pnl, win_rate, avg_trade für den Zeitraum.
    """
    with _db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                      AS trades,
                ROUND(SUM(pnl), 2)                           AS pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)    AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END)    AS losses,
                ROUND(AVG(pnl), 2)                           AS avg_trade,
                ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2) AS avg_win,
                ROUND(AVG(CASE WHEN pnl < 0 THEN pnl END), 2) AS avg_loss
            FROM trades
            WHERE created_at >= datetime('now', ? || ' days')
        """, (f"-{days}",)).fetchone()

    result = dict(row) if row else {}
    trades = result.get("trades") or 0
    wins   = result.get("wins") or 0
    result["win_rate"] = round(wins / trades * 100, 1) if trades > 0 else 0.0
    result["period_days"] = days
    return result


def get_periodic_performance() -> dict:
    """Gibt Performance für 7d, 30d und gesamt zurück."""
    return {
        "7d":    get_rolling_performance(7),
        "30d":   get_rolling_performance(30),
        "total": get_performance_summary(),
    }


def get_weekly_monthly_pnl() -> dict:
    """Aggregiert tägliche PnL-Snapshots zu Wochen und Monaten."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT
                snapshot_date,
                daily_pnl
            FROM performance_snapshots
            ORDER BY snapshot_date
        """).fetchall()

    import re
    weekly: dict[str, float]  = {}
    monthly: dict[str, float] = {}

    for row in rows:
        date_str = row["snapshot_date"]
        pnl      = row["daily_pnl"] or 0.0
        if not date_str or len(date_str) < 10:
            continue

        # Woche: YYYY-WNN
        try:
            from datetime import date
            d      = date.fromisoformat(date_str[:10])
            week   = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
            month  = d.strftime("%Y-%m")
        except ValueError:
            continue

        weekly[week]   = round(weekly.get(week, 0.0) + pnl, 2)
        monthly[month] = round(monthly.get(month, 0.0) + pnl, 2)

    return {
        "weekly":  [{"period": k, "pnl": v} for k, v in sorted(weekly.items())],
        "monthly": [{"period": k, "pnl": v} for k, v in sorted(monthly.items())],
    }


# ── Execution Quality (P1) ────────────────────────────────────────────────────

def log_execution_quality(
    symbol: str, side: str,
    signal_price: float, fill_price: float,
    quantity: float, slippage_bps: float,
    order_type: str = "market",
) -> None:
    """Zeichnet Signal-Preis vs. Fill-Preis auf — für Slippage-Analyse."""
    with _db() as conn:
        conn.execute(
            """INSERT INTO execution_quality
               (symbol, side, signal_price, fill_price, quantity, slippage_bps, order_type)
               VALUES (?,?,?,?,?,?,?)""",
            (symbol, side, round(signal_price, 4), round(fill_price, 4),
             round(quantity, 8), round(slippage_bps, 3), order_type),
        )
    log.debug(
        f"Execution Quality {side}: signal={signal_price:.2f} fill={fill_price:.2f} "
        f"slippage={slippage_bps:+.1f}bps qty={quantity:.6f}"
    )


def get_execution_quality_stats(limit: int = 200) -> dict:
    """
    Berechnet Execution Quality Statistiken (Slippage-Analyse).

    Returns dict mit:
      - avg_slippage_bps: Durchschnittlicher Slippage über alle Trades
      - avg_buy_slippage_bps / avg_sell_slippage_bps: Getrennt nach Seite
      - fill_rate_pct: Anteil Limit Orders (slippage < 5bps)
      - worst_slippage_bps: Schlechtester Slippage
      - total_cost_usdt: Geschätzte Gesamtkosten durch Slippage
      - recent: Letzte N Einträge
    """
    with _db() as conn:
        # Gesamt-Statistik
        stats_row = conn.execute("""
            SELECT
                ROUND(AVG(slippage_bps), 2)                                     AS avg_slippage_bps,
                ROUND(AVG(CASE WHEN side='buy'  THEN slippage_bps END), 2)      AS avg_buy_slippage_bps,
                ROUND(AVG(CASE WHEN side='sell' THEN slippage_bps END), 2)      AS avg_sell_slippage_bps,
                ROUND(MAX(ABS(slippage_bps)), 2)                                AS worst_slippage_bps,
                COUNT(*)                                                         AS total_executions,
                SUM(CASE WHEN ABS(slippage_bps) < 5 THEN 1 ELSE 0 END)        AS tight_fills,
                ROUND(SUM(ABS(slippage_bps) / 10000.0 * fill_price * quantity), 4) AS total_cost_usdt
            FROM execution_quality
            LIMIT ?
        """, (limit,)).fetchone()

        recent_rows = conn.execute(
            """SELECT symbol, side, signal_price, fill_price, slippage_bps, order_type, created_at
               FROM execution_quality ORDER BY created_at DESC LIMIT 20"""
        ).fetchall()

    result = dict(stats_row) if stats_row else {}
    total = result.get("total_executions") or 0
    tight = result.get("tight_fills") or 0
    result["fill_rate_pct"] = round(tight / total * 100, 1) if total > 0 else 0.0
    result["recent"] = [dict(r) for r in recent_rows]
    return result
