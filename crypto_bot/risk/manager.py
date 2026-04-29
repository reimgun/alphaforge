"""
Risk Manager — ATR-basiertes Sizing + Trailing Stop + Drawdown Recovery.

Neu in Round 5:
  - drawdown_recovery_factor: reduziert Positionsgröße bei aktivem Drawdown
  - Kelly-Sizing-Faktor: extern setzbar via kelly_factor
  - Risk Personality Mode: conservative / balanced / aggressive (via RISK_MODE)
"""
import numpy as np
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from crypto_bot.config.settings import (
    RISK_PER_TRADE, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAX_DAILY_LOSS_PCT, INITIAL_CAPITAL,
    USE_ATR_SIZING, ATR_MULTIPLIER,
    USE_TRAILING_STOP, TRAILING_STOP_PCT,
    LEVERAGE, MAX_LEVERAGE,
    RISK_MODE, RISK_MODE_PARAMS,
    TRADE_COOLDOWN_MINUTES, MAX_CONSECUTIVE_LOSSES,
)


@dataclass
class Position:
    symbol:        str
    entry_price:   float
    quantity:      float
    stop_loss:     float
    take_profit:   float
    side:          str   = "long"
    highest_price: float = 0.0   # Für Trailing Stop

    @property
    def value(self) -> float:
        return self.entry_price * self.quantity

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price * 100


@dataclass
class RiskManager:
    capital:          float = INITIAL_CAPITAL
    position:         Position | None = None
    daily_loss:       float = 0.0
    daily_loss_date:  date  = field(default_factory=date.today)
    trades:           list  = field(default_factory=list)
    kelly_factor:     float = 1.0   # Wird extern vom Bot gesetzt (Kelly-Optimizer)
    # Startkapital dieser Instanz — korrekte Drawdown-Berechnung auch im Test
    _initial_capital:      float          = field(default=0.0,  repr=False)
    # Trade Cooldown — Pause nach Verlust-Trade
    _cooldown_until:       datetime | None = field(default=None, repr=False)
    # StoplossgGuard — blockiert Trading nach N konsekutiven Verlusten
    _consecutive_losses:   int             = field(default=0,    repr=False)

    def __post_init__(self):
        if self._initial_capital == 0.0:
            # Verwende INITIAL_CAPITAL aus settings (respektiert Test-Overrides)
            import crypto_bot.config.settings as _cfg
            self._initial_capital = getattr(_cfg, "INITIAL_CAPITAL", INITIAL_CAPITAL)

    # ── Trade Cooldown ────────────────────────────────────────────────────────

    def activate_cooldown(self, minutes: int | None = None) -> None:
        """Sperrt neues Trading für N Minuten nach einem Verlust-Trade."""
        mins = minutes if minutes is not None else TRADE_COOLDOWN_MINUTES
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=mins)

    def is_in_cooldown(self) -> bool:
        if self._cooldown_until is None:
            return False
        return datetime.now(timezone.utc) < self._cooldown_until

    def cooldown_remaining_minutes(self) -> float:
        if not self.is_in_cooldown():
            return 0.0
        return (self._cooldown_until - datetime.now(timezone.utc)).total_seconds() / 60

    def reset_cooldown(self) -> None:
        self._cooldown_until = None
        self._consecutive_losses = 0

    # ── StoplossgGuard ────────────────────────────────────────────────────────

    def is_stoploss_guard_active(self) -> bool:
        """True wenn zu viele konsekutive Verluste → kein neuer Trade erlaubt."""
        return self._consecutive_losses >= MAX_CONSECUTIVE_LOSSES

    @property
    def drawdown_recovery_factor(self) -> float:
        """
        Reduziert Positionsgröße basierend auf aktuellem Drawdown.
        Schützt Kapital in Verlustsituationen automatisch.

          Drawdown ≥ 15% → 0.25× (nur noch 25% der normalen Größe)
          Drawdown ≥ 10% → 0.50×
          Drawdown ≥  7% → 0.75×
          Drawdown  < 7% → 1.00× (normal)
        """
        base     = self._initial_capital if self._initial_capital > 0 else INITIAL_CAPITAL
        drawdown = (base - self.capital) / base if base > 0 else 0.0
        if drawdown >= 0.15:  return 0.25
        if drawdown >= 0.10:  return 0.50
        if drawdown >= 0.07:  return 0.75
        return 1.0

    @property
    def risk_mode_factor(self) -> float:
        """Risk-Personality-Faktor aus RISK_MODE (conservative/balanced/aggressive)."""
        import crypto_bot.config.settings as cfg
        mode   = getattr(cfg, "RISK_MODE", "balanced")
        params = getattr(cfg, "RISK_MODE_PARAMS", {})
        return params.get(mode, {}).get("risk_factor", 1.0)

    @property
    def effective_max_drawdown(self) -> float:
        """Dynamisches Drawdown-Limit basierend auf RISK_MODE."""
        import crypto_bot.config.settings as cfg
        mode   = getattr(cfg, "RISK_MODE", "balanced")
        params = getattr(cfg, "RISK_MODE_PARAMS", {})
        return params.get(mode, {}).get("drawdown_limit", 0.20)

    @property
    def effective_daily_loss_limit(self) -> float:
        """Dynamisches Tagesverlust-Limit basierend auf RISK_MODE."""
        import crypto_bot.config.settings as cfg
        mode   = getattr(cfg, "RISK_MODE", "balanced")
        params = getattr(cfg, "RISK_MODE_PARAMS", {})
        return params.get(mode, {}).get("daily_loss_limit", MAX_DAILY_LOSS_PCT)

    def _reset_daily_loss_if_new_day(self):
        today = date.today()
        if today != self.daily_loss_date:
            self.daily_loss      = 0.0
            self.daily_loss_date = today

    def is_circuit_breaker_active(self) -> bool:
        self._reset_daily_loss_if_new_day()
        return self.daily_loss >= self.capital * self.effective_daily_loss_limit

    def has_open_position(self) -> bool:
        return self.position is not None

    def has_long_position(self) -> bool:
        return self.position is not None and self.position.side == "long"

    def has_short_position(self) -> bool:
        return self.position is not None and self.position.side == "short"

    def open_position(
        self,
        symbol:      str,
        entry_price: float,
        atr:         float = 0.0,
        regime_factor: float = 1.0,
        side: str = "long",
    ) -> Position:
        """
        Öffnet Position mit ATR-basiertem oder fixem Stop-Loss.
        regime_factor: 0.5–1.0 je nach Marktregime (reduziert Größe bei Risiko)
        """
        if USE_ATR_SIZING and atr > 0:
            stop_distance = ATR_MULTIPLIER * atr
            if side == "short":
                stop_loss   = entry_price + stop_distance     # SL über Entry bei Short
                take_profit = entry_price - stop_distance * 2 # TP unter Entry bei Short
            else:
                stop_loss   = entry_price - stop_distance
                take_profit = entry_price + stop_distance * 2
        else:
            stop_distance = entry_price * STOP_LOSS_PCT
            if side == "short":
                stop_loss   = entry_price * (1 + STOP_LOSS_PCT)
                take_profit = entry_price * (1 - TAKE_PROFIT_PCT)
            else:
                stop_loss   = entry_price * (1 - STOP_LOSS_PCT)
                take_profit = entry_price * (1 + TAKE_PROFIT_PCT)

        # Position Sizing: kombinierter Faktor aus Regime + Drawdown Recovery + Kelly + Risk Mode
        effective_leverage = max(1, min(LEVERAGE, MAX_LEVERAGE))
        combined_factor = (
            regime_factor
            * self.drawdown_recovery_factor
            * self.kelly_factor
            * self.risk_mode_factor
        )
        risk_amount = self.capital * RISK_PER_TRADE * combined_factor * effective_leverage
        quantity    = risk_amount / stop_distance if stop_distance > 0 else 0
        # Kapital-Obergrenze: nie mehr als 95% × Leverage einsetzen
        max_qty     = (self.capital * 0.95 * effective_leverage) / entry_price
        quantity    = min(quantity, max_qty)

        # Mindest-Menge: kein Trade wenn Position zu klein um sinnvoll zu sein
        MIN_NOTIONAL = 1.0  # USDT — unter $1 kein Trade
        if quantity * entry_price < MIN_NOTIONAL:
            return None

        self.position = Position(
            symbol        = symbol,
            entry_price   = entry_price,
            quantity      = round(quantity, 8),
            stop_loss     = round(stop_loss, 2),
            take_profit   = round(take_profit, 2),
            highest_price = entry_price,
            side          = side,
        )
        return self.position

    def update_trailing_stop(self, current_price: float) -> float:
        """
        Aktualisiert den Trailing Stop falls aktiviert.
        Für Long: Stop steigt wenn Preis steigt.
        Für Short: Stop fällt wenn Preis fällt (lowest_price Tracking).
        Gibt den neuen Stop-Level zurück.
        """
        if not self.position or not USE_TRAILING_STOP:
            return self.position.stop_loss if self.position else 0.0

        if self.position.side == "short":
            # Short: Preis fällt → Stop fällt nach (via highest_price als lowest_price-Proxy)
            if current_price < self.position.highest_price:
                self.position.highest_price = current_price
                new_stop = current_price * (1 + TRAILING_STOP_PCT)
                if new_stop < self.position.stop_loss:
                    self.position.stop_loss = round(new_stop, 2)
        else:
            if current_price > self.position.highest_price:
                self.position.highest_price = current_price
                new_stop = current_price * (1 - TRAILING_STOP_PCT)
                if new_stop > self.position.stop_loss:
                    self.position.stop_loss = round(new_stop, 2)

        return self.position.stop_loss

    def check_stop_take(self, current_price: float) -> str | None:
        """Prüft ob Stop-Loss oder Take-Profit erreicht wurde (Long + Short)."""
        if not self.position:
            return None

        if self.position.side == "short":
            # Short: SL über Entry, TP unter Entry
            if current_price >= self.position.stop_loss:
                return "stop_loss"
            if current_price <= self.position.take_profit and not USE_TRAILING_STOP:
                return "take_profit"
        else:
            if current_price <= self.position.stop_loss:
                return "stop_loss"
            if current_price >= self.position.take_profit and not USE_TRAILING_STOP:
                return "take_profit"
        return None

    def close_position(self, exit_price: float) -> dict:
        if not self.position:
            return {}

        if self.position.side == "short":
            # Short P&L: profitiert wenn Preis fällt
            pnl     = (self.position.entry_price - exit_price) * self.position.quantity
            pnl_pct = (self.position.entry_price - exit_price) / self.position.entry_price * 100
        else:
            pnl     = (exit_price - self.position.entry_price) * self.position.quantity
            pnl_pct = (exit_price - self.position.entry_price) / self.position.entry_price * 100

        self.capital += pnl
        if pnl < 0:
            self.daily_loss += abs(pnl)
            self._consecutive_losses += 1
            self.activate_cooldown()  # Cooldown nach jedem Verlust-Trade
        else:
            self._consecutive_losses = 0  # Reset nach Gewinn

        trade = {
            "symbol":        self.position.symbol,
            "entry":         self.position.entry_price,
            "exit":          exit_price,
            "quantity":      self.position.quantity,
            "pnl":           round(pnl, 2),
            "pnl_pct":       round(pnl_pct, 2),
            "capital_after": round(self.capital, 2),
            "consecutive_losses": self._consecutive_losses,
        }
        self.trades.append(trade)
        self.position = None
        return trade

    def summary(self) -> dict:
        if not self.trades:
            return {"trades": 0}

        pnls   = [t["pnl"] for t in self.trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        base    = self._initial_capital if self._initial_capital > 0 else INITIAL_CAPITAL
        # Normalisierte Renditen pro Trade (relativ zum Startkapital)
        returns = [p / base for p in pnls] if base > 0 else pnls

        # Sharpe Ratio (trade-basiert, annualisiert auf ~252 Handelstage)
        std_returns  = float(np.std(returns)) if len(returns) > 1 else 0.0
        mean_returns = float(np.mean(returns))
        sharpe = round(mean_returns / std_returns * np.sqrt(252), 2) if std_returns > 0 else 0.0

        # Sortino Ratio (nur Downside-Volatilität)
        neg_returns  = [r for r in returns if r < 0]
        downside_std = float(np.std(neg_returns)) if neg_returns else 0.001
        sortino = round(mean_returns / downside_std * np.sqrt(252), 2) if downside_std > 0 else 0.0

        # Max Drawdown + Drawdown-Dauer (Anzahl Trades in Drawdown)
        peak          = base
        running       = INITIAL_CAPITAL
        max_dd_pct    = 0.0
        dd_start_idx  = None
        dd_durations  = []
        for idx, pnl in enumerate(pnls):
            running += pnl
            if running > peak:
                if dd_start_idx is not None:
                    dd_durations.append(idx - dd_start_idx)
                    dd_start_idx = None
                peak = running
            dd = (peak - running) / peak * 100 if peak > 0 else 0.0
            if dd > 0 and dd_start_idx is None:
                dd_start_idx = idx
            if dd > max_dd_pct:
                max_dd_pct = dd
        if dd_start_idx is not None:
            dd_durations.append(len(pnls) - dd_start_idx)

        avg_dd_duration = round(sum(dd_durations) / len(dd_durations), 1) if dd_durations else 0.0
        max_dd_duration = max(dd_durations) if dd_durations else 0

        # Calmar Ratio = Annualized Return / Max Drawdown
        total_return_pct = (self.capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        calmar = round(total_return_pct / max_dd_pct, 2) if max_dd_pct > 0 else 0.0

        # Omega Ratio (Schwelle = 0)
        gains  = sum(r for r in returns if r > 0)
        lossv  = abs(sum(r for r in returns if r < 0))
        omega  = round(gains / lossv, 2) if lossv > 0 else 0.0

        avg_win  = round(sum(wins)   / len(wins),   2) if wins   else 0.0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        win_rate = len(wins) / len(self.trades)

        # Expectancy = (WinRate × AvgWin) + (LossRate × AvgLoss)
        expectancy = round(win_rate * avg_win + (1 - win_rate) * avg_loss, 2)

        # Durchschnittliche Trade-Haltedauer (wenn entry_time/exit_time vorhanden)
        hold_durations = []
        for t in self.trades:
            try:
                from datetime import datetime
                entry = t.get("entry_time") or t.get("entry")
                exit_ = t.get("exit_time")  or t.get("exit")
                if entry and exit_ and isinstance(entry, str) and isinstance(exit_, str):
                    dt_e = datetime.fromisoformat(entry.replace("Z", "+00:00"))
                    dt_x = datetime.fromisoformat(exit_.replace("Z", "+00:00"))
                    hold_durations.append((dt_x - dt_e).total_seconds() / 3600)
            except Exception:
                pass
        avg_hold_hours = round(sum(hold_durations) / len(hold_durations), 1) if hold_durations else 0.0

        # Rolling Sharpe (letzte 20 Trades)
        rolling_returns = returns[-20:] if len(returns) >= 5 else returns
        r_std  = float(np.std(rolling_returns))  if len(rolling_returns) > 1 else 0.0
        r_mean = float(np.mean(rolling_returns))
        rolling_sharpe = round(r_mean / r_std * np.sqrt(252), 2) if r_std > 0 else 0.0

        # Win/Loss Streak
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        cur_win = 0
        cur_loss = 0
        for p in pnls:
            if p > 0:
                cur_win  += 1
                cur_loss  = 0
                max_win_streak = max(max_win_streak, cur_win)
            else:
                cur_loss += 1
                cur_win   = 0
                max_loss_streak = max(max_loss_streak, cur_loss)

        return {
            "trades":              len(self.trades),
            "wins":                len(wins),
            "losses":              len(losses),
            "win_rate":            round(win_rate * 100, 1),
            "total_pnl":           round(sum(pnls), 2),
            "avg_win":             avg_win,
            "avg_loss":            avg_loss,
            "profit_factor":       round(sum(wins) / abs(sum(losses)), 2) if losses else 0,
            "sharpe":              sharpe,
            "sortino":             sortino,
            "calmar":              calmar,
            "omega":               omega,
            "rolling_sharpe_20":   rolling_sharpe,
            "max_drawdown_pct":    round(max_dd_pct, 2),
            "avg_drawdown_trades": avg_dd_duration,
            "max_drawdown_trades": max_dd_duration,
            "avg_hold_hours":      avg_hold_hours,
            "max_win_streak":      max_win_streak,
            "max_loss_streak":     max_loss_streak,
            "expectancy":          expectancy,
            "final_capital":       round(self.capital, 2),
            "return_pct":          round((self.capital - base) / base * 100, 2),
            # Cooldown & Protection
            "in_cooldown":              self.is_in_cooldown(),
            "cooldown_remaining_min":   round(self.cooldown_remaining_minutes(), 1),
            "consecutive_losses":       self._consecutive_losses,
            "stoploss_guard_active":    self.is_stoploss_guard_active(),
            "max_consecutive_losses":   MAX_CONSECUTIVE_LOSSES,
            "cooldown_minutes":         TRADE_COOLDOWN_MINUTES,
        }
