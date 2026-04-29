"""
Forex Risk Manager.

Pip-basiertes Position Sizing, Drawdown-Überwachung,
Circuit Breaker, Trade-Journal.

Feature 1: Daily Loss Limit + Consecutive Loss Stop.
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("forex_bot")

DB_PATH = Path(__file__).parent.parent / "data_store" / "trades.db"


# ── Trade-Dataclass ───────────────────────────────────────────────────────────

@dataclass
class ForexTrade:
    instrument:  str
    direction:   str       # "BUY" | "SELL"
    units:       int
    entry_price: float
    stop_loss:   float
    take_profit: float
    trade_id:    Optional[str] = None
    entry_time:  str            = ""
    exit_price:  Optional[float] = None
    exit_time:   Optional[str]   = None
    pnl_pips:        float           = 0.0
    pnl_usd:         float           = 0.0
    status:          str             = "open"   # open | closed
    reason:          str             = ""
    scaled_out:      bool            = False
    partial_pnl_usd: float           = 0.0


# ── Risk Manager ──────────────────────────────────────────────────────────────

class ForexRiskManager:
    def __init__(
        self,
        initial_capital: float,
        risk_per_trade:  float = 0.01,
        max_drawdown:    float = 0.15,
        max_open_trades: int   = 3,
    ):
        self.initial_capital  = initial_capital
        self.capital          = initial_capital
        self.risk_per_trade   = risk_per_trade
        self.max_drawdown     = max_drawdown
        self.max_open_trades  = max_open_trades
        self._peak_capital    = initial_capital
        self.trades: list[ForexTrade] = []
        # Feature 1: daily loss + consecutive loss tracking
        self.daily_loss_usd:     float = 0.0
        self.consecutive_losses: int   = 0
        self._daily_tracking_date: Optional[date] = None
        self._ensure_db()
        self._load_trades()

    # ── Position Sizing ───────────────────────────────────────────────────────

    def calculate_units(
        self,
        instrument:         str,
        entry:              float,
        stop_loss:          float,
        pip_value_per_unit: float,
    ) -> int:
        """
        Berechnet Units so dass max. risk_per_trade * capital verloren wird.

        Gibt 0 zurück wenn Sizing nicht möglich.
        """
        pip_size    = 0.01 if "JPY" in instrument else 0.0001
        pips_risked = abs(entry - stop_loss) / pip_size

        if pips_risked < 1 or pip_value_per_unit <= 0:
            log.warning(f"Sizing fehlgeschlagen: pips={pips_risked:.1f} pv={pip_value_per_unit}")
            return 0

        risk_amount = self.capital * self.risk_per_trade
        units       = int(risk_amount / (pips_risked * pip_value_per_unit))
        units       = (units // 1_000) * 1_000   # IG MINI: Schritte à 1.000 Units
        return max(1_000, min(units, 100_000))

    # ── Daily Loss / Consecutive Loss (Feature 1) ─────────────────────────────

    def daily_loss_limit_reached(self, limit_fraction: float) -> bool:
        """Returns True if today's realized losses >= limit_fraction * initial_capital."""
        self._auto_reset_daily()
        threshold = self.initial_capital * limit_fraction
        if self.daily_loss_usd >= threshold:
            log.warning(
                f"Daily loss limit reached: ${self.daily_loss_usd:.2f} >= "
                f"${threshold:.2f} ({limit_fraction*100:.1f}% of capital)"
            )
            return True
        return False

    def consecutive_loss_stop_reached(self, max_consec: int) -> bool:
        """Returns True if consecutive losing trades >= max_consec."""
        if self.consecutive_losses >= max_consec:
            log.warning(
                f"Consecutive loss stop reached: {self.consecutive_losses} losses in a row"
            )
            return True
        return False

    def reset_daily_tracking(self):
        """Reset daily loss tracking — call at UTC midnight."""
        log.info(
            f"Daily tracking reset. Yesterday's loss: ${self.daily_loss_usd:.2f}, "
            f"consecutive losses: {self.consecutive_losses}"
        )
        self.daily_loss_usd         = 0.0
        self._daily_tracking_date   = datetime.now(timezone.utc).date()

    def _auto_reset_daily(self):
        """Auto-reset if calendar date has changed since last tracking."""
        today = datetime.now(timezone.utc).date()
        if self._daily_tracking_date is None:
            self._daily_tracking_date = today
        elif today > self._daily_tracking_date:
            self.reset_daily_tracking()

    # ── Drawdown Recovery Mode (Feature 3) ───────────────────────────────────

    def current_drawdown_pct(self) -> float:
        """Return the current drawdown as a percentage of peak capital."""
        if self._peak_capital <= 0:
            return 0.0
        return (self._peak_capital - self.capital) / self._peak_capital * 100

    def drawdown_recovery_factor(self) -> float:
        """
        Position-size scaling factor based on current drawdown.

        > 10% DD → 0.25× (quarter size, last resort)
        >  5% DD → 0.50× (half size)
        ≤  5% DD → 1.00× (normal)

        Apply to risk_per_trade before calling calculate_units().
        Example:
            adjusted_risk = mode.risk_per_trade * rm.drawdown_recovery_factor()
        """
        dd = self.current_drawdown_pct()
        if dd > 10.0:
            return 0.25
        if dd > 5.0:
            return 0.50
        return 1.0

    # ── Guards ────────────────────────────────────────────────────────────────

    def circuit_breaker_active(self) -> bool:
        if self._peak_capital == 0:
            return False
        dd = (self._peak_capital - self.capital) / self._peak_capital
        if dd >= self.max_drawdown:
            log.warning(f"Circuit Breaker aktiv — Drawdown {dd*100:.1f}%")
            return True
        return False

    def open_trade_count(self) -> int:
        return sum(1 for t in self.trades if t.status == "open")

    def max_trades_reached(self) -> bool:
        return self.open_trade_count() >= self.max_open_trades

    def already_open(self, instrument: str) -> bool:
        return any(t.instrument == instrument and t.status == "open" for t in self.trades)

    # ── Trade-Verwaltung ──────────────────────────────────────────────────────

    def record_open(self, trade: ForexTrade):
        trade.entry_time = datetime.now(timezone.utc).isoformat()
        self.trades.append(trade)
        self._save_trade(trade)
        log.info(
            f"Trade OPEN: {trade.instrument} {trade.direction} "
            f"{trade.units} @ {trade.entry_price} SL={trade.stop_loss}"
        )

    def record_close(self, trade: ForexTrade, exit_price: float):
        pip_size         = 0.01 if "JPY" in trade.instrument else 0.0001
        trade.exit_price = exit_price
        trade.exit_time  = datetime.now(timezone.utc).isoformat()
        trade.status     = "closed"

        if trade.direction == "BUY":
            trade.pnl_pips = (exit_price - trade.entry_price) / pip_size
        else:
            trade.pnl_pips = (trade.entry_price - exit_price) / pip_size

        # PnL in USD (Näherung: pip_value ≈ pip_size * units für USD-Quote Pairs)
        trade.pnl_usd = trade.pnl_pips * pip_size * trade.units

        self.capital += trade.pnl_usd
        if self.capital > self._peak_capital:
            self._peak_capital = self.capital

        # Feature 1: update daily loss and consecutive loss counters
        self._auto_reset_daily()
        if trade.pnl_usd < 0:
            self.daily_loss_usd     += abs(trade.pnl_usd)
            self.consecutive_losses += 1
        else:
            # winning trade resets consecutive loss streak
            self.consecutive_losses = 0

        self._save_trade(trade)
        log.info(
            f"Trade CLOSED: {trade.instrument} "
            f"PnL {trade.pnl_pips:+.1f} Pips / ${trade.pnl_usd:+.2f}"
        )

    def get_open_trades(self) -> list[ForexTrade]:
        return [t for t in self.trades if t.status == "open"]

    # ── Statistiken ───────────────────────────────────────────────────────────

    def summary(self) -> dict:
        closed = [t for t in self.trades if t.status == "closed"]
        if not closed:
            return {
                "trades": 0, "win_rate": 0.0,
                "total_pips": 0.0, "total_pnl": 0.0,
                "capital": round(self.capital, 2),
                "drawdown_pct": 0.0,
            }

        wins      = [t for t in closed if t.pnl_pips > 0]
        total_pip = sum(t.pnl_pips for t in closed)
        total_pnl = sum(t.pnl_usd for t in closed)
        dd_pct    = (
            (self._peak_capital - self.capital) / self._peak_capital * 100
            if self._peak_capital else 0
        )

        # Sharpe (vereinfacht aus Pip-Sequenz)
        import statistics
        pips_seq = [t.pnl_pips for t in closed]
        sharpe   = 0.0
        if len(pips_seq) > 2:
            try:
                mean_p = statistics.mean(pips_seq)
                std_p  = statistics.stdev(pips_seq)
                sharpe = round(mean_p / std_p * (252 ** 0.5) if std_p else 0, 2)
            except Exception:
                pass

        return {
            "trades":       len(closed),
            "win_rate":     round(len(wins) / len(closed) * 100, 1),
            "total_pips":   round(total_pip, 1),
            "total_pnl":    round(total_pnl, 2),
            "capital":      round(self.capital, 2),
            "drawdown_pct": round(dd_pct, 2),
            "sharpe":       sharpe,
            "open_trades":  self.open_trade_count(),
        }

    # ── Persistenz ───────────────────────────────────────────────────────────

    def _ensure_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument  TEXT,
                    direction   TEXT,
                    units       INTEGER,
                    entry_price REAL,
                    stop_loss   REAL,
                    take_profit REAL,
                    trade_id    TEXT,
                    entry_time  TEXT,
                    exit_price  REAL,
                    exit_time   TEXT,
                    pnl_pips    REAL,
                    pnl_usd     REAL,
                    status      TEXT,
                    reason      TEXT
                )
            """)

    def _save_trade(self, t: ForexTrade):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                if t.status == "open" or not t.trade_id:
                    conn.execute("""
                        INSERT OR REPLACE INTO trades
                        (instrument,direction,units,entry_price,stop_loss,take_profit,
                         trade_id,entry_time,exit_price,exit_time,pnl_pips,pnl_usd,status,reason)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        t.instrument, t.direction, t.units, t.entry_price,
                        t.stop_loss, t.take_profit, t.trade_id, t.entry_time,
                        t.exit_price, t.exit_time, t.pnl_pips, t.pnl_usd,
                        t.status, t.reason,
                    ))
                else:
                    conn.execute("""
                        UPDATE trades SET exit_price=?,exit_time=?,pnl_pips=?,pnl_usd=?,status=?
                        WHERE trade_id=?
                    """, (t.exit_price, t.exit_time, t.pnl_pips, t.pnl_usd, t.status, t.trade_id))
        except Exception as e:
            log.error(f"DB-Fehler: {e}")

    def _load_trades(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
                cols = [
                    "id","instrument","direction","units","entry_price","stop_loss",
                    "take_profit","trade_id","entry_time","exit_price","exit_time",
                    "pnl_pips","pnl_usd","status","reason",
                ]
                for row in rows:
                    d = dict(zip(cols, row))
                    self.trades.append(ForexTrade(
                        instrument  = d["instrument"],
                        direction   = d["direction"],
                        units       = d["units"],
                        entry_price = d["entry_price"],
                        stop_loss   = d["stop_loss"],
                        take_profit = d["take_profit"],
                        trade_id    = d["trade_id"],
                        entry_time  = d["entry_time"] or "",
                        status      = "open",
                        reason      = d["reason"] or "",
                    ))
        except Exception as e:
            log.warning(f"Trades laden fehlgeschlagen: {e}")
