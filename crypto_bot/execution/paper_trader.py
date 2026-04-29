"""
Paper Trader — simuliert Orders inkl. Trailing Stop + SQLite Logging.

Gebühren-Simulation:
  Beide Seiten (Kauf + Verkauf) werden mit TRADING_FEE_PCT (Standard: 0.1%)
  belastet — identisch zu echten Binance Taker-Fees.
  Alle PnL-Angaben sind Netto (nach Gebühren).

Short-Selling:
  short() / cover() simulieren Short-Positionen lokal.
  Kein Futures-Account erforderlich im Paper-Modus.

State-Persistenz:
  save_state() / restore_state() schreiben/laden Kapital + offene Position
  in SQLite → überleben Container-Restarts.
"""
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from crypto_bot.risk.manager import RiskManager, Position
from crypto_bot.monitoring.logger import log_trade, log_event, save_paper_state, load_paper_state
from crypto_bot.monitoring import alerts
from crypto_bot.config.settings import SYMBOL, USE_TRAILING_STOP, TRADING_FEE_PCT, INITIAL_CAPITAL

console = Console()


class PaperTrader:
    def __init__(self, risk_manager: RiskManager):
        self.rm  = risk_manager
        self.log: list[dict] = []
        self._entry_time: str = ""
        self._entry_fee:  float = 0.0   # Kauf-Gebühr für spätere Netto-PnL-Berechnung

    def buy(
        self,
        price: float,
        reason: str = "",
        atr: float = 0.0,
        regime_factor: float = 1.0,
        explanation: str = "",
    ) -> Position | None:
        if self.rm.has_open_position():
            return None
        if self.rm.is_circuit_breaker_active():
            console.print("[bold red]CIRCUIT BREAKER — kein Trade[/bold red]")
            return None

        position = self.rm.open_position(SYMBOL, price, atr=atr, regime_factor=regime_factor)
        if position is None:
            log_event("BUY abgelehnt: Positionsgröße zu klein (stop_distance ≈ 0 oder kelly_factor ≈ 0)", "risk")
            return None
        self._entry_time = datetime.now(timezone.utc).isoformat()

        # ── Kauf-Gebühr abziehen ──────────────────────────────────────────────
        self._entry_fee   = round(price * position.quantity * TRADING_FEE_PCT, 4)
        self.rm.capital  -= self._entry_fee

        self.log.append({
            "time": self._entry_time, "action": "BUY", "price": price,
            "quantity": round(position.quantity, 6),
            "stop_loss": position.stop_loss, "take_profit": position.take_profit,
            "fee": self._entry_fee, "reason": reason,
        })

        sl_type = "ATR" if atr > 0 else "Fix"
        console.print(
            f"[bold green]BUY[/bold green] {position.quantity:.6f} BTC @ {price:.2f} "
            f"| SL({sl_type}): {position.stop_loss:.2f} | TP: {position.take_profit:.2f} "
            f"| Fee: {self._entry_fee:.2f} USDT | {reason}"
        )
        alerts.alert_trade_opened(price, position.quantity, position.stop_loss, position.take_profit, reason,
                                   explanation=explanation)
        self.save_state()
        return position

    def sell(self, price: float, reason: str = "", ai_source: str = "", explanation: str = "") -> dict:
        if not self.rm.has_open_position():
            return {}

        entry_price = self.rm.position.entry_price
        quantity    = self.rm.position.quantity
        trade = self.rm.close_position(price)   # Brutto-PnL, Kapital bereits aktualisiert
        trade["reason"] = reason

        # ── Verkauf-Gebühr abziehen, Netto-PnL berechnen ─────────────────────
        exit_fee          = round(price * quantity * TRADING_FEE_PCT, 4)
        self.rm.capital  -= exit_fee
        total_fee         = round(self._entry_fee + exit_fee, 4)
        net_pnl           = round(trade["pnl"] - total_fee, 2)
        trade["fee"]      = total_fee
        trade["pnl"]      = net_pnl                        # Netto-PnL
        trade["capital_after"] = round(self.rm.capital, 2) # nach Gebühr aktualisiert

        log_trade(
            symbol=SYMBOL, side="sell",
            entry_price=entry_price, exit_price=price,
            quantity=quantity, pnl=net_pnl,
            reason=reason, ai_source=ai_source,
            entry_time=self._entry_time,
            exit_time=datetime.now(timezone.utc).isoformat(),
        )
        self.log.append({"time": datetime.now(timezone.utc).isoformat(), "action": "SELL", **trade})

        color = "green" if net_pnl >= 0 else "red"
        console.print(
            f"[bold {color}]SELL[/bold {color}] @ {price:.2f} | "
            f"PnL: {net_pnl:+.2f} USDT ({trade['pnl_pct']:+.2f}%) | "
            f"Fee: {total_fee:.2f} USDT | Kapital: {trade['capital_after']:.2f} | {reason}"
        )
        alerts.alert_trade_closed(price, net_pnl, trade["pnl_pct"], reason, self.rm.capital,
                                   explanation=explanation)
        self.save_state()
        return trade

    def short(
        self,
        price: float,
        reason: str = "",
        atr: float = 0.0,
        regime_factor: float = 1.0,
        explanation: str = "",
    ) -> "Position | None":
        """Öffnet eine Short-Position (simuliert — kein Futures-Account nötig)."""
        if self.rm.has_open_position():
            return None
        if self.rm.is_circuit_breaker_active():
            console.print("[bold red]CIRCUIT BREAKER — kein Short-Trade[/bold red]")
            return None

        position = self.rm.open_position(SYMBOL, price, atr=atr, regime_factor=regime_factor, side="short")
        if position is None:
            log_event("SHORT abgelehnt: Positionsgröße zu klein", "risk")
            return None
        self._entry_time = datetime.now(timezone.utc).isoformat()

        self._entry_fee   = round(price * position.quantity * TRADING_FEE_PCT, 4)
        self.rm.capital  -= self._entry_fee

        self.log.append({
            "time": self._entry_time, "action": "SHORT", "price": price,
            "quantity": round(position.quantity, 6),
            "stop_loss": position.stop_loss, "take_profit": position.take_profit,
            "fee": self._entry_fee, "reason": reason,
        })

        sl_type = "ATR" if atr > 0 else "Fix"
        console.print(
            f"[bold magenta]SHORT[/bold magenta] {position.quantity:.6f} BTC @ {price:.2f} "
            f"| SL({sl_type}): {position.stop_loss:.2f} | TP: {position.take_profit:.2f} "
            f"| Fee: {self._entry_fee:.2f} USDT | {reason}"
        )
        alerts.alert_trade_opened(price, position.quantity, position.stop_loss, position.take_profit,
                                   f"SHORT: {reason}", explanation=explanation)
        self.save_state()
        return position

    def cover(self, price: float, reason: str = "", ai_source: str = "", explanation: str = "") -> dict:
        """Schließt eine Short-Position (Cover)."""
        if not self.rm.has_short_position():
            return {}

        entry_price = self.rm.position.entry_price
        quantity    = self.rm.position.quantity
        trade = self.rm.close_position(price)
        trade["reason"] = reason

        exit_fee          = round(price * quantity * TRADING_FEE_PCT, 4)
        self.rm.capital  -= exit_fee
        total_fee         = round(self._entry_fee + exit_fee, 4)
        net_pnl           = round(trade["pnl"] - total_fee, 2)
        trade["fee"]      = total_fee
        trade["pnl"]      = net_pnl
        trade["capital_after"] = round(self.rm.capital, 2)

        log_trade(
            symbol=SYMBOL, side="cover",
            entry_price=entry_price, exit_price=price,
            quantity=quantity, pnl=net_pnl,
            reason=reason, ai_source=ai_source,
            entry_time=self._entry_time,
            exit_time=datetime.now(timezone.utc).isoformat(),
        )
        self.log.append({"time": datetime.now(timezone.utc).isoformat(), "action": "COVER", **trade})

        color = "green" if net_pnl >= 0 else "red"
        console.print(
            f"[bold {color}]COVER[/bold {color}] @ {price:.2f} | "
            f"PnL: {net_pnl:+.2f} USDT ({trade['pnl_pct']:+.2f}%) | "
            f"Fee: {total_fee:.2f} USDT | Kapital: {trade['capital_after']:.2f} | {reason}"
        )
        alerts.alert_trade_closed(price, net_pnl, trade["pnl_pct"], f"COVER: {reason}", self.rm.capital,
                                   explanation=explanation)
        self.save_state()
        return trade

    def update_stops(self, current_price: float):
        """Aktualisiert Trailing Stop und prüft dann SL/TP."""
        if not self.rm.has_open_position():
            return

        if USE_TRAILING_STOP:
            new_stop = self.rm.update_trailing_stop(current_price)
            pos = self.rm.position
            if pos.side == "short":
                if new_stop < pos.entry_price * 1.001:
                    console.print(f"[dim]Trailing Stop (Short): {new_stop:.2f} (Tiefpunkt: {pos.highest_price:.2f})[/dim]")
            else:
                if new_stop > pos.entry_price * 0.999:
                    console.print(f"[dim]Trailing Stop: {new_stop:.2f} (Hochpunkt: {pos.highest_price:.2f})[/dim]")

        trigger = self.rm.check_stop_take(current_price)
        if trigger == "stop_loss":
            if self.rm.has_short_position():
                self.cover(current_price, reason="Stop-Loss (Short) ausgelöst")
            else:
                self.sell(current_price, reason="Stop-Loss ausgelöst")
        elif trigger == "take_profit":
            if self.rm.has_short_position():
                self.cover(current_price, reason="Take-Profit (Short) erreicht")
            else:
                self.sell(current_price, reason="Take-Profit erreicht")

    def save_state(self) -> None:
        """Persistiert Kapital und offene Position in SQLite."""
        pos_data = None
        if self.rm.position:
            pos_data = {
                "symbol":        self.rm.position.symbol,
                "entry_price":   self.rm.position.entry_price,
                "quantity":      self.rm.position.quantity,
                "stop_loss":     self.rm.position.stop_loss,
                "take_profit":   self.rm.position.take_profit,
                "highest_price": self.rm.position.highest_price,
                "side":          self.rm.position.side,
            }
        save_paper_state(
            capital         = self.rm.capital,
            initial_capital = INITIAL_CAPITAL,
            position_data   = pos_data,
            entry_time      = self._entry_time,
            entry_fee       = self._entry_fee,
        )

    def restore_state(self) -> bool:
        """
        Lädt gespeicherten State beim Start.
        Gibt True zurück wenn State erfolgreich wiederhergestellt wurde.
        """
        state = load_paper_state()
        if state is None:
            return False

        self.rm.capital = state["capital"]
        self._entry_time = state.get("entry_time", "")
        self._entry_fee  = state.get("entry_fee", 0.0)

        pos = state.get("position")
        if pos:
            from crypto_bot.risk.manager import Position
            self.rm.position = Position(
                symbol        = pos["symbol"],
                entry_price   = pos["entry_price"],
                quantity      = pos["quantity"],
                stop_loss     = pos["stop_loss"],
                take_profit   = pos["take_profit"],
                highest_price = pos.get("highest_price", pos["entry_price"]),
                side          = pos.get("side", "long"),
            )
            console.print(
                f"[dim]State wiederhergestellt: Kapital={self.rm.capital:.2f} USDT | "
                f"Position: {pos['side'].upper()} {pos['quantity']:.6f} BTC @ {pos['entry_price']:.2f}[/dim]"
            )
        else:
            console.print(f"[dim]State wiederhergestellt: Kapital={self.rm.capital:.2f} USDT | Keine offene Position[/dim]")
        return True

    def print_summary(self):
        summary = self.rm.summary()
        table   = Table(title="Paper Trading Ergebnis")
        table.add_column("Metrik", style="cyan")
        table.add_column("Wert",   style="white")

        table.add_row("Trades gesamt",    str(summary.get("trades", 0)))
        table.add_row("Gewinner",         str(summary.get("wins", 0)))
        table.add_row("Verlierer",        str(summary.get("losses", 0)))
        table.add_row("Win-Rate",         f"{summary.get('win_rate', 0)}%")
        table.add_row("Profit Factor",    str(summary.get("profit_factor", 0)))
        table.add_row("Sortino Ratio",    str(summary.get("sortino", 0)))
        table.add_row("Gesamt PnL",       f"{summary.get('total_pnl', 0):+.2f} USDT")
        table.add_row("Ø Gewinn",         f"{summary.get('avg_win', 0):+.2f} USDT")
        table.add_row("Ø Verlust",        f"{summary.get('avg_loss', 0):+.2f} USDT")
        table.add_row("Endkapital",       f"{summary.get('final_capital', 0):.2f} USDT")
        table.add_row("Rendite",          f"{summary.get('return_pct', 0):+.2f}%")
        console.print(table)
