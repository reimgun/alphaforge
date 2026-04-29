"""
Live Trader — echte Orders mit:
- Limit Orders (weniger Slippage) mit Market-Fallback
- Bracket Orders: OCO (SL + TP atomar) mit Fallback auf separate SL-Order (P1)
- Order-Reconciliation (Status-Prüfung)
- Stop-Loss-Verifizierung
- Trailing Stop-Update
- Live State Reconciliation nach Crash/Restart (P0)
- Execution Quality Tracking (Signal-Preis vs. Fill-Preis) (P1)
"""
import time
import ccxt
from datetime import datetime, timezone
from rich.console import Console
from crypto_bot.risk.manager import RiskManager, Position
from crypto_bot.data.fetcher import get_exchange, _fetch_with_retry
from crypto_bot.monitoring.logger import log, log_trade, log_event, log_execution_quality
from crypto_bot.monitoring import alerts
from crypto_bot.config.settings import (
    SYMBOL, API_KEY,
    USE_LIMIT_ORDERS, LIMIT_ORDER_OFFSET, LIMIT_ORDER_TIMEOUT,
    USE_TRAILING_STOP, STOP_LOSS_PCT,
)

console  = Console()
POLL_INT = 2  # Sekunden zwischen Order-Status-Checks

# Minimum BTC-Wert in USD damit eine Position als "offen" gilt
_MIN_POSITION_USD = 10.0


class LiveTrader:
    def __init__(self, risk_manager: RiskManager):
        if not API_KEY:
            raise ValueError("API_KEY fehlt in .env Datei!")
        self.rm                       = risk_manager
        self.exchange                 = get_exchange()
        self._sl_order_id: str | None = None
        self._tp_order_id: str | None = None
        self._entry_time: str         = ""
        self._reconciled: bool        = False  # True nach erfolgreichem restore_live_state()

    # ── Live State Reconciliation (P0) ───────────────────────────────────────
    def restore_live_state(self) -> bool:
        """
        Reconciliert Bot-State mit Exchange nach Crash/Restart.

        Ablauf:
          1. BTC-Balance prüfen (Spot: haben wir BTC?)
          2. Letzten unkgeschlossenen BUY-Trade in DB suchen (Entry-Preis)
          3. Offene Stop-Loss-Orders auf Exchange suchen (Stop-Preis)
          4. Position im RiskManager rekonstruieren

        Gibt True zurück wenn eine offene Position wiederhergestellt wurde.
        """
        try:
            balance      = _fetch_with_retry(self.exchange.fetch_balance)
            btc_total    = float(balance.get("BTC", {}).get("total", 0.0))
            ticker       = _fetch_with_retry(self.exchange.fetch_ticker, SYMBOL)
            current_price = float(ticker["last"])
            btc_value_usd = btc_total * current_price

            if btc_value_usd < _MIN_POSITION_USD:
                log.info(f"Live State Check: keine offene BTC-Position "
                         f"({btc_total:.6f} BTC = ${btc_value_usd:.2f})")
                self._reconciled = True
                return False

            # ── Entry-Preis aus DB-History ─────────────────────────────────
            entry_price, entry_time = self._find_unclosed_entry_in_db()
            if entry_price is None:
                log.warning(
                    f"Live State: {btc_total:.6f} BTC (${btc_value_usd:.2f}) gefunden "
                    f"aber kein offener DB-Trade — nutze aktuellen Preis als Fallback"
                )
                entry_price = current_price
                entry_time  = datetime.now(timezone.utc).isoformat()

            # ── Stop-Loss aus offenen Orders ───────────────────────────────
            stop_price = self._find_open_sl_order()
            if stop_price is None:
                stop_price = round(current_price * (1 - STOP_LOSS_PCT), 2)
                log.warning(
                    f"Live State: kein SL-Order auf Exchange — "
                    f"platziere neuen SL @ {stop_price:.2f} ({STOP_LOSS_PCT*100:.1f}% unter aktuellem Preis)"
                )
                # SL-Order direkt auf Exchange platzieren um Position zu schützen
                sl_order = self._place_stop_loss(stop_price, btc_total)
                if sl_order:
                    self._sl_order_id = sl_order.get("id")
                    log.info(f"Live State: SL-Order platziert @ {stop_price:.2f} (ID: {self._sl_order_id})")
                    alerts.alert_error(f"⚠️ SL-Order nach Neustart neu platziert @ {stop_price:.2f}")
                else:
                    log.error("Live State: SL-Order konnte nicht platziert werden — Position ungeschützt!")
                    alerts.alert_error("🚨 KRITISCH: SL-Order nach Neustart fehlgeschlagen — Position UNGESCHÜTZT!")
            else:
                log.info(f"Live State: SL-Order gefunden @ {stop_price:.2f}")

            # ── Position im RiskManager setzen ────────────────────────────
            stop_distance = abs(entry_price - stop_price)
            take_profit   = round(entry_price + stop_distance * 2, 2)

            position = Position(
                symbol        = SYMBOL,
                entry_price   = entry_price,
                quantity      = round(btc_total, 8),
                stop_loss     = stop_price,
                take_profit   = take_profit,
                side          = "long",
                highest_price = max(entry_price, current_price),
            )
            self.rm.position  = position
            self._entry_time  = entry_time
            self._reconciled  = True

            unrealized_pnl = (current_price - entry_price) * btc_total
            console.print(
                f"[bold yellow]Live State wiederhergestellt:[/bold yellow] "
                f"{btc_total:.6f} BTC @ Entry {entry_price:.2f} USDT | "
                f"SL: {stop_price:.2f} | uPnL: {unrealized_pnl:+.2f} USDT"
            )
            log_event(
                f"Live State reconciled: {btc_total:.6f} BTC @ {entry_price:.2f} "
                f"| SL {stop_price:.2f} | uPnL {unrealized_pnl:+.2f}",
                "startup",
            )
            alerts.alert_error(
                f"⚠️ Bot-Neustart mit offener Position! "
                f"{btc_total:.6f} BTC @ Entry {entry_price:.2f} USDT | SL: {stop_price:.2f}"
            )
            return True

        except Exception as e:
            log.error(f"Live State Reconciliation fehlgeschlagen: {e}")
            self._reconciled = False
            return False

    def _find_unclosed_entry_in_db(self) -> tuple[float | None, str]:
        """
        Sucht letzten BUY-Trade in DB der noch keinen entsprechenden SELL hat.
        Gibt (entry_price, entry_time) zurück oder (None, "") wenn nicht gefunden.
        """
        try:
            from crypto_bot.monitoring.logger import _db
            with _db() as conn:
                # Letzter BUY
                buy_row = conn.execute(
                    """SELECT id, entry_price, entry_time, created_at
                       FROM trades
                       WHERE symbol = ? AND side = 'buy'
                         AND ai_source != 'backtest'
                       ORDER BY created_at DESC LIMIT 1""",
                    (SYMBOL,),
                ).fetchone()
                if buy_row is None:
                    return None, ""

                # Gibt es einen SELL nach diesem BUY?
                sell_row = conn.execute(
                    """SELECT id FROM trades
                       WHERE symbol = ? AND side = 'sell'
                         AND created_at > ?
                       LIMIT 1""",
                    (SYMBOL, buy_row["created_at"]),
                ).fetchone()

                if sell_row is not None:
                    return None, ""  # BUY war bereits geschlossen

                return float(buy_row["entry_price"]), buy_row["entry_time"] or ""
        except Exception as e:
            log.warning(f"DB-Lookup für unclosed entry fehlgeschlagen: {e}")
            return None, ""

    def _find_open_sl_order(self) -> float | None:
        """
        Sucht offene Stop-Loss Sell-Order auf der Exchange.
        Gibt den Stop-Preis zurück oder None wenn nicht gefunden.
        """
        try:
            open_orders = _fetch_with_retry(self.exchange.fetch_open_orders, SYMBOL)
            for order in open_orders:
                order_type = (order.get("type") or "").lower()
                if order_type in ("stop_market", "stop_limit", "stop") and \
                   order.get("side") == "sell":
                    stop_price = order.get("stopPrice") or order.get("price")
                    if stop_price:
                        self._sl_order_id = order.get("id")
                        return float(stop_price)
            return None
        except Exception as e:
            log.warning(f"Open Orders abrufen fehlgeschlagen: {e}")
            return None

    # ── BUY ──────────────────────────────────────────────────────────────────
    def buy(
        self,
        price: float,
        reason: str = "",
        atr: float = 0.0,
        regime_factor: float = 1.0,
        explanation: str = "",
    ) -> Position | None:
        if self.rm.has_open_position() or self.rm.is_circuit_breaker_active():
            return None

        position = self.rm.open_position(SYMBOL, price, atr=atr, regime_factor=regime_factor)
        if position is None:
            log_event("LIVE BUY abgelehnt: Positionsgröße zu klein", "risk")
            return None

        signal_price = price  # für Execution Quality Tracking

        try:
            order = self._place_order("buy", position.quantity, price)
            if not order:
                self.rm.position = None
                return None

            filled_price, filled_qty = self._wait_for_fill(order["id"], "buy")
            if filled_qty == 0.0:
                try:
                    _fetch_with_retry(self.exchange.cancel_order, order["id"], SYMBOL)
                except Exception:
                    pass
                self.rm.position = None
                log_event("BUY abgelehnt: Order-Timeout (keine Füllung)", "order_error", "warning")
                return None
            if filled_qty < position.quantity * 0.9:
                log_event(f"Partial Fill: {filled_qty:.6f}/{position.quantity:.6f}", "partial_fill", "warning")

            # ── Bracket: OCO (SL + TP atomar) mit Fallback auf SL-only ─────────
            bracket_ok = self._place_bracket_orders(
                position.stop_loss, position.take_profit, filled_qty
            )
            if not bracket_ok:
                alerts.alert_error("Stop-Loss Order fehlgeschlagen — Position ungeschützt! Manuell prüfen!")

            self._entry_time = datetime.now(timezone.utc).isoformat()

            # ── Execution Quality aufzeichnen (P1) ─────────────────────────────
            slippage_bps = round((filled_price - signal_price) / signal_price * 10000, 2)
            log_execution_quality(
                symbol=SYMBOL, side="buy",
                signal_price=signal_price, fill_price=filled_price,
                quantity=filled_qty, slippage_bps=slippage_bps,
                order_type="limit" if USE_LIMIT_ORDERS else "market",
            )
            if abs(slippage_bps) > 20:
                log.warning(f"Hoher Slippage beim BUY: {slippage_bps:+.1f} bps")

            alerts.alert_trade_opened(
                filled_price, filled_qty, position.stop_loss, position.take_profit,
                reason, explanation=explanation,
            )
            console.print(
                f"[bold green]LIVE BUY[/bold green] {filled_qty:.6f} BTC @ {filled_price:.2f} "
                f"| SL: {position.stop_loss:.2f} | TP: {position.take_profit:.2f} "
                f"| Slippage: {slippage_bps:+.1f}bps | Order: {order['id']}"
            )
            return position

        except ccxt.BaseError as e:
            log_event(f"BUY Fehler: {e}", "order_error", "error")
            self.rm.position = None
            return None

    # ── SELL ─────────────────────────────────────────────────────────────────
    def sell(self, price: float, reason: str = "", ai_source: str = "", explanation: str = "") -> dict:
        if not self.rm.has_open_position():
            return {}

        entry_price  = self.rm.position.entry_price
        quantity     = self.rm.position.quantity
        signal_price = price  # für Execution Quality

        try:
            self._cancel_bracket_orders()
            order = self._place_order("sell", quantity, price)
            if not order:
                return {}

            filled_price, _ = self._wait_for_fill(order["id"], "sell")
            trade = self.rm.close_position(filled_price)
            trade["reason"] = reason

            log_trade(
                symbol=SYMBOL, side="sell",
                entry_price=entry_price, exit_price=filled_price,
                quantity=quantity, pnl=trade["pnl"],
                reason=reason, ai_source=ai_source,
                entry_time=self._entry_time,
                exit_time=datetime.now(timezone.utc).isoformat(),
            )

            # ── Execution Quality aufzeichnen (P1) ─────────────────────────
            slippage_bps = round((signal_price - filled_price) / signal_price * 10000, 2)
            log_execution_quality(
                symbol=SYMBOL, side="sell",
                signal_price=signal_price, fill_price=filled_price,
                quantity=quantity, slippage_bps=slippage_bps,
                order_type="limit" if USE_LIMIT_ORDERS else "market",
            )

            alerts.alert_trade_closed(
                filled_price, trade["pnl"], trade["pnl_pct"], reason, self.rm.capital,
                explanation=explanation,
            )
            color = "green" if trade["pnl"] >= 0 else "red"
            console.print(
                f"[bold {color}]LIVE SELL[/bold {color}] @ {filled_price:.2f} | "
                f"PnL: {trade['pnl']:+.2f} USDT ({trade['pnl_pct']:+.2f}%) | "
                f"Slippage: {slippage_bps:+.1f}bps"
            )
            return trade

        except ccxt.BaseError as e:
            log_event(f"SELL Fehler: {e}", "order_error", "error")
            alerts.alert_error(f"SELL fehlgeschlagen: {e}")
            return {}

    def update_stops(self, current_price: float):
        """Trailing Stop aktualisieren + SL auf Exchange anpassen."""
        if not self.rm.has_open_position() or not USE_TRAILING_STOP:
            return

        old_stop = self.rm.position.stop_loss
        new_stop = self.rm.update_trailing_stop(current_price)

        if new_stop > old_stop * 1.001:  # Stop hat sich signifikant bewegt
            # Nur SL canceln + neu setzen, TP-Order bleibt
            if self._sl_order_id:
                try:
                    _fetch_with_retry(self.exchange.cancel_order, self._sl_order_id, SYMBOL)
                except Exception:
                    pass
                self._sl_order_id = None
            sl_order = self._place_stop_loss(new_stop, self.rm.position.quantity)
            if sl_order:
                self._sl_order_id = sl_order["id"]
                log.info(f"Trailing Stop aktualisiert: {old_stop:.2f} → {new_stop:.2f}")

        # Prüfen ob SL ausgelöst wurde
        trigger = self.rm.check_stop_take(current_price)
        if trigger:
            self.sell(current_price, reason=f"{trigger} ausgelöst")

    # ── Bracket Orders: OCO (SL + TP atomar) (P1) ────────────────────────────
    def _place_bracket_orders(
        self, stop_price: float, take_profit_price: float, quantity: float
    ) -> bool:
        """
        Platziert SL + TP als atomares OCO-Paar auf Binance.
        OCO = One-Cancels-Other: wenn SL ausgelöst wird, wird TP gecancelt und umgekehrt.

        Fallback-Kaskade:
          1. OCO (atomar, ideal)
          2. Separate stop_market SL + limit TP (zwei unabhängige Orders)
          3. Nur stop_market SL (Mindestschutz)

        Gibt True zurück wenn mindestens der Stop-Loss erfolgreich platziert wurde.
        """
        qty = round(quantity, 6)

        # ── Versuch 1: OCO (atomar) ────────────────────────────────────────
        try:
            oco = _fetch_with_retry(
                self.exchange.create_order,
                SYMBOL, "oco", "sell", qty,
                round(take_profit_price, 2),
                {
                    "stopPrice":             round(stop_price, 2),
                    "stopLimitPrice":        round(stop_price * 0.999, 2),
                    "stopLimitTimeInForce":  "GTC",
                },
            )
            # OCO gibt eine Liste von Orders zurück — IDs speichern
            if isinstance(oco, dict) and "orders" in oco:
                self._sl_order_id  = oco["orders"][0].get("orderId") or oco["orders"][0].get("id")
                self._tp_order_id  = oco["orders"][1].get("orderId") or oco["orders"][1].get("id")
            elif isinstance(oco, dict):
                self._sl_order_id = oco.get("id")
                self._tp_order_id = None
            log.info(
                f"Bracket OCO platziert: SL {stop_price:.2f} | TP {take_profit_price:.2f}"
            )
            return True
        except ccxt.BaseError as e:
            log.warning(f"OCO fehlgeschlagen ({e}) — Fallback auf separate Orders")

        # ── Versuch 2: Separate SL + TP Orders ────────────────────────────
        sl_ok = False
        tp_ok = False

        sl_order = self._place_stop_loss(stop_price, qty)
        if sl_order:
            self._sl_order_id = sl_order["id"]
            sl_ok = True
        else:
            log.error("Stop-Loss Order fehlgeschlagen!")

        try:
            tp_order = _fetch_with_retry(
                self.exchange.create_order,
                SYMBOL, "limit", "sell", qty,
                round(take_profit_price, 2),
                {"timeInForce": "GTC"},
            )
            if tp_order:
                self._tp_order_id = tp_order["id"]
                tp_ok = True
                log.info(f"TP Limit Order platziert @ {take_profit_price:.2f}")
        except ccxt.BaseError as e:
            log.warning(f"TP Order fehlgeschlagen: {e}")

        if sl_ok:
            log.info(
                f"Bracket (separate): SL @ {stop_price:.2f} {'| TP @ ' + str(take_profit_price) if tp_ok else '(TP fehlt)'}"
            )
        return sl_ok

    def _cancel_bracket_orders(self):
        """Cancelt SL und TP Orders vor einem manuellen SELL."""
        for attr, name in [("_sl_order_id", "SL"), ("_tp_order_id", "TP")]:
            oid = getattr(self, attr, None)
            if oid:
                try:
                    _fetch_with_retry(self.exchange.cancel_order, oid, SYMBOL)
                    log.debug(f"{name}-Order {oid} gecancelt")
                except Exception:
                    pass
                setattr(self, attr, None)

    # ── Private Helpers ───────────────────────────────────────────────────────
    def _place_order(self, side: str, quantity: float, price: float) -> dict | None:
        """Versucht Limit Order, fällt auf Market zurück wenn nicht gefüllt."""
        qty = round(quantity, 6)

        if USE_LIMIT_ORDERS:
            limit_price = price * (1 + LIMIT_ORDER_OFFSET) if side == "buy" \
                     else price * (1 - LIMIT_ORDER_OFFSET)
            try:
                order = _fetch_with_retry(
                    self.exchange.create_order, SYMBOL, "limit", side, qty,
                    round(limit_price, 2),
                )
                filled_price, filled_qty = self._wait_for_fill(order["id"], side, timeout=LIMIT_ORDER_TIMEOUT)
                if filled_qty >= qty * 0.9:
                    return order
                # Nicht gefüllt → canceln und Market-Fallback
                try:
                    _fetch_with_retry(self.exchange.cancel_order, order["id"], SYMBOL)
                except Exception:
                    pass
                log.info(f"Limit Order nicht gefüllt — Market-Fallback")
            except ccxt.BaseError as e:
                log.warning(f"Limit Order Fehler: {e} — Market-Fallback")

        # Market Order Fallback
        return _fetch_with_retry(self.exchange.create_order, SYMBOL, "market", side, qty)

    def _wait_for_fill(self, order_id: str, side: str, timeout: int = 30) -> tuple[float, float]:
        elapsed = 0
        while elapsed < timeout:
            try:
                order = _fetch_with_retry(self.exchange.fetch_order, order_id, SYMBOL)
                if order.get("status") == "closed":
                    return (float(order.get("average") or order.get("price") or 0),
                            float(order.get("filled", 0)))
                if order.get("status") == "canceled":
                    raise RuntimeError(f"Order {order_id} gecancelt")
            except Exception as e:
                log.warning(f"Order-Status: {e}")
            time.sleep(POLL_INT)
            elapsed += POLL_INT
        return self._get_current_price(), 0.0

    def _place_stop_loss(self, stop_price: float, quantity: float) -> dict | None:
        try:
            return _fetch_with_retry(
                self.exchange.create_order, SYMBOL, "stop_market", "sell",
                round(quantity, 6),
                params={"stopPrice": round(stop_price, 2), "reduceOnly": True},
            )
        except ccxt.BaseError as e:
            log.error(f"Stop-Loss-Order Fehler: {e}")
            return None

    def _get_current_price(self) -> float:
        try:
            return float(_fetch_with_retry(self.exchange.fetch_ticker, SYMBOL)["last"])
        except Exception:
            return 0.0
