"""
Interactive Brokers Client (via ib_insync).

Vollständiges Drop-In-Replacement für OandaClient.
IBKR ist der professionellste Retail-Broker — unterstützt Forex, Aktien,
Futures, Optionen in einem Account.

Voraussetzungen:
  pip install ib_insync
  IB Gateway oder TWS (Trader Workstation) muss laufen.

Ports:
  TWS Paper Trading:  7497
  TWS Live Trading:   7496
  IB Gateway Paper:   4002
  IB Gateway Live:    4001

Einrichtung:
  1. IB Gateway herunterladen: ibkr.com/trader-workstation
  2. API-Verbindungen erlauben: Edit → Global Configuration → API → Settings
     → "Enable ActiveX and Socket Clients" aktivieren
     → "Socket Port" prüfen (default 7497 für Paper)
  3. In forex_bot/.env:
       FOREX_BROKER=ibkr
       IBKR_HOST=127.0.0.1
       IBKR_PORT=7497      # 7497=TWS Paper, 7496=TWS Live, 4002=GW Paper, 4001=GW Live
       IBKR_CLIENT_ID=1
       IBKR_ACCOUNT=       # optional — leer = erster gefundener Account

Hinweis: IBKR erfordert eine laufende Desktop-Applikation (IB Gateway).
         Für Server-Betrieb: IB Gateway headless via Docker (ibc-docker).

Interactive Brokers client (via ib_insync) — drop-in replacement for OandaClient.
Professional-grade broker supporting Forex, stocks, futures and options in one account.

Requirements:
  pip install ib_insync
  IB Gateway or TWS must be running locally.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("forex_bot")

# Granularitäts-Mapping: OANDA → IBKR barSizeSetting
_GRAN: dict[str, str] = {
    "M1": "1 min", "M5": "5 mins", "M15": "15 mins",
    "M30": "30 mins", "H1": "1 hour", "H4": "4 hours", "D": "1 day",
}

# Duration-Mapping: Anzahl Candles → IBKR durationStr (Annäherung)
def _duration_str(granularity: str, count: int) -> str:
    """Schätzt IBKR durationStr aus Granularität + Anzahl."""
    hours_per_candle = {
        "M1": 1/60, "M5": 5/60, "M15": 15/60, "M30": 0.5,
        "H1": 1.0, "H4": 4.0, "D": 24.0,
    }
    h = hours_per_candle.get(granularity, 1.0) * count
    if h <= 24:
        return f"{max(1, int(h) + 1)} D"
    elif h <= 24 * 30:
        return f"{max(1, int(h / 24) + 1)} D"
    else:
        return f"{max(1, int(h / 24 / 7) + 1)} W"


class IBKRClient:
    """
    Interactive Brokers API-Client via ib_insync — implementiert dasselbe
    Interface wie OandaClient.

    Verbindet sich beim Start zu IB Gateway / TWS.
    Forex wird als CFD gehandelt (Forex-Kontrakt mit Commission).

    Wichtig: IB Gateway muss laufen bevor der Bot startet.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7497,
                 client_id: int = 1, account: str = ""):
        try:
            from ib_insync import IB, util
            util.logToConsole(logging.WARNING)
            self._ib      = IB()
            self._account = account
            self._ib.connect(host, port, clientId=client_id, timeout=20)

            if not self._account:
                accounts = self._ib.managedAccounts()
                self._account = accounts[0] if accounts else ""

            log.info(f"IBKR: Verbunden mit {host}:{port} (Account: {self._account})")
        except ImportError:
            raise ImportError(
                "ib_insync nicht installiert. Bitte: pip install ib_insync"
            )
        except Exception as e:
            raise ConnectionError(
                f"IBKR: Verbindung zu {host}:{port} fehlgeschlagen. "
                f"IB Gateway / TWS läuft? Fehler: {e}"
            )

    @staticmethod
    def _contract(instrument: str):
        """OANDA-Instrument → IBKR Forex-Kontrakt."""
        from ib_insync import Forex
        # EUR_USD → EURUSD (Forex-Pair ohne Underscore)
        pair = instrument.replace("_", "")
        return Forex(pair)

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Gibt Account-Zusammenfassung zurück."""
        summary = self._ib.accountSummary(self._account)
        result  = {}
        for item in summary:
            result[item.tag] = item.value
        return result

    def get_balance(self) -> float:
        """Aktueller Cash-Bestand (NetLiquidation)."""
        summary = self._ib.accountSummary(self._account)
        for item in summary:
            if item.tag == "CashBalance" and item.currency == "USD":
                return float(item.value)
        return 0.0

    # ── Marktdaten ────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, granularity: str = "H1",
                    count: int = 250) -> list:
        """
        Gibt OHLCV-Dicts zurück — kompatibel mit OandaClient.

        instrument:  OANDA-Format (EUR_USD)
        granularity: OANDA-Format (H1, M15, H4, D)
        """
        contract  = self._contract(instrument)
        bar_size  = _GRAN.get(granularity, "1 hour")
        duration  = _duration_str(granularity, count)

        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="MIDPOINT",
            useRTH=False,
            formatDate=1,
        )
        self._ib.sleep(0)  # Eventloop flushen

        candles = []
        for b in bars[-count:]:
            candles.append({
                "time":   str(b.date),
                "open":   float(b.open),
                "high":   float(b.high),
                "low":    float(b.low),
                "close":  float(b.close),
                "volume": int(b.volume) if b.volume > 0 else 0,
            })
        return candles

    def get_price(self, instrument: str) -> float:
        """Aktueller Mid-Price."""
        from ib_insync import util
        contract = self._contract(instrument)
        ticker   = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)
        mid = ticker.midpoint()
        if mid and mid > 0:
            return float(mid)
        # Fallback: letzter Schlusskurs
        candles = self.get_candles(instrument, "M1", 1)
        return float(candles[-1]["close"]) if candles else 0.0

    def get_spread_pips(self, instrument: str) -> float:
        """Aktueller Spread in Pips."""
        contract = self._contract(instrument)
        ticker   = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)
        bid = ticker.bid or 0.0
        ask = ticker.ask or 0.0
        if bid and ask:
            pip_size = 0.01 if "JPY" in instrument else 0.0001
            return round((ask - bid) / pip_size, 1)
        return 1.5  # Fallback-Spread

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        instrument:  str,
        units:       int,
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        comment:     str = "",
    ) -> dict:
        """Platziert Market-Order."""
        from ib_insync import MarketOrder, StopOrder, LimitOrder, BracketOrder

        contract  = self._contract(instrument)
        action    = "BUY" if units > 0 else "SELL"
        quantity  = abs(units)

        if stop_loss and take_profit:
            # Bracket Order: Entry + SL + TP in einem
            bracket = self._ib.bracketOrder(
                action, quantity,
                lmtPrice=None,  # Market Entry
                takeProfitPrice=take_profit,
                stopLossPrice=stop_loss,
            )
            trades = []
            for order in bracket:
                order.account = self._account
                trades.append(self._ib.placeOrder(contract, order))
            self._ib.sleep(1)
            trade = trades[0]
        else:
            order           = MarketOrder(action, quantity)
            order.account   = self._account
            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1)

        result = {
            "orderId":    str(trade.order.orderId),
            "status":     str(trade.orderStatus.status),
            "instrument": instrument,
            "units":      units,
        }
        log.info(f"IBKR: {action} {instrument} {quantity} units → {result}")
        return result

    def place_limit_order(
        self,
        instrument:  str,
        units:       int,
        price:       float,
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        gtd_seconds: int = 3600,
    ) -> dict:
        """Platziert GTD Limit-Order."""
        from ib_insync import LimitOrder

        contract = self._contract(instrument)
        action   = "BUY" if units > 0 else "SELL"
        quantity = abs(units)

        order             = LimitOrder(action, quantity, price)
        order.account     = self._account
        order.tif         = "GTD"
        expiry            = datetime.now(timezone.utc) + timedelta(seconds=gtd_seconds)
        order.goodTillDate = expiry.strftime("%Y%m%d %H:%M:%S")

        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1)
        return {"orderId": str(trade.order.orderId), "status": str(trade.orderStatus.status)}

    def cancel_order(self, order_id: str) -> dict:
        """Storniert offene Order."""
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == str(order_id):
                self._ib.cancelOrder(trade.order)
                self._ib.sleep(1)
                return {"cancelled": order_id}
        return {"error": f"Order {order_id} nicht gefunden"}

    def close_trade(self, trade_id: str) -> dict:
        """Schließt offene Position per Market-Order."""
        for pos in self._ib.positions(self._account):
            if str(pos.contract.conId) == str(trade_id) or \
               pos.contract.symbol in trade_id:
                action   = "SELL" if pos.position > 0 else "BUY"
                quantity = abs(int(pos.position))
                from ib_insync import MarketOrder
                order           = MarketOrder(action, quantity)
                order.account   = self._account
                trade = self._ib.placeOrder(pos.contract, order)
                self._ib.sleep(1)
                return {"closed": trade_id, "status": str(trade.orderStatus.status)}
        return {"error": f"Position {trade_id} nicht gefunden"}

    def modify_stop_loss(self, trade_id: str, stop_loss: float) -> dict:
        """
        Aktualisiert Stop-Loss.

        Bei IBKR muss der bestehende Stop-Order geändert werden.
        Diese Implementierung sucht nach einem passenden Stop-Order.
        """
        for trade in self._ib.openTrades():
            order = trade.order
            if (hasattr(order, "orderType") and
                order.orderType in ("STP", "STOP") and
                str(order.parentId) == str(trade_id)):
                order.auxPrice = stop_loss
                self._ib.placeOrder(trade.contract, order)
                self._ib.sleep(1)
                return {"modified": trade_id, "new_stop": stop_loss}
        return {"error": f"Stop-Order für {trade_id} nicht gefunden"}

    # ── Offene Positionen ─────────────────────────────────────────────────────

    def get_open_trades(self) -> list:
        """
        Gibt offene Positionen zurück — normalisiert auf OANDA-Format.
        """
        result = []
        for pos in self._ib.positions(self._account):
            if pos.position == 0:
                continue
            contract  = pos.contract
            symbol    = contract.symbol     # z.B. "EUR"
            currency  = contract.currency   # z.B. "USD"
            oanda_fmt = f"{symbol}_{currency}"

            result.append({
                "id":              str(contract.conId),
                "instrument":      oanda_fmt,
                "currentUnits":    str(int(pos.position)),
                "price":           float(pos.avgCost) if pos.avgCost else 0.0,
                "unrealizedPL":    0.0,   # via PnL-Subscription verfügbar
                "stopLossOrder":   {"price": None},
                "takeProfitOrder": {"price": None},
            })
        return result

    def get_closed_trades(self, count: int = 50) -> list:
        """Gibt abgeschlossene Trades aus der aktuellen Sitzung zurück."""
        fills = self._ib.fills()
        return [
            {
                "time":      str(f.time),
                "instrument": f"{f.contract.symbol}_{f.contract.currency}",
                "action":    f.execution.side,
                "quantity":  f.execution.shares,
                "price":     f.execution.price,
            }
            for f in fills[-count:]
        ]

    # ── Pip-Wert + Unit-Berechnung ────────────────────────────────────────────

    def pip_value_per_unit(self, instrument: str) -> float:
        pip_size  = 0.01 if "JPY" in instrument else 0.0001
        quote_ccy = instrument.split("_")[1]
        if quote_ccy == "USD":
            return pip_size
        try:
            price = self.get_price(instrument)
            return pip_size / price
        except Exception:
            return pip_size

    def calculate_units(self, instrument: str, entry: float, stop_loss: float,
                        capital: float, risk_fraction: float = 0.01) -> int:
        pip_size    = 0.01 if "JPY" in instrument else 0.0001
        pips_risked = abs(entry - stop_loss) / pip_size
        if pips_risked < 0.1:
            return 0
        pv_per_unit = self.pip_value_per_unit(instrument)
        risk_amount = capital * risk_fraction
        units       = int(risk_amount / (pips_risked * pv_per_unit))
        return max(1_000, min(units, 100_000))

    def disconnect(self) -> None:
        """Trennt Verbindung zu IB Gateway / TWS."""
        try:
            self._ib.disconnect()
        except Exception:
            pass
