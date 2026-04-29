"""
Alpaca Markets Client — Equities + Crypto in einem Account.

Unterstützt:
  - US-Aktien (NYSE, NASDAQ) — Paper + Live
  - Crypto (BTC, ETH, ...) — Paper + Live
  - Forex (via Alpaca Forex API) — experimentell

Voraussetzungen:
  pip install alpaca-py

Konfiguration (.env):
  FOREX_BROKER=alpaca
  ALPACA_API_KEY=...
  ALPACA_API_SECRET=...
  ALPACA_ENV=paper    # paper | live

Paper Trading URL:  https://paper-api.alpaca.markets
Live Trading URL:   https://api.alpaca.markets

Besonderheit: Alpaca ist der einzige Broker der Aktien + Crypto
in einem Account vereint — kein IBKR-Desktop nötig, reine REST API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("forex_bot")

_BASE_PAPER = "https://paper-api.alpaca.markets"
_BASE_LIVE  = "https://api.alpaca.markets"
_BASE_DATA  = "https://data.alpaca.markets"

# Granularitäts-Mapping: OANDA-Format → Alpaca TimeFrame
_GRAN = {
    "M1":  "1Min",  "M5":  "5Min",  "M15": "15Min",
    "M30": "30Min", "H1":  "1Hour", "H4":  "4Hour",
    "D":   "1Day",
}

# Instrument-Mapping: OANDA EUR_USD → Alpaca EUR/USD
def _to_alpaca_symbol(instrument: str) -> str:
    """EUR_USD → EUR/USD für Forex-Paare, sonst unverändert (AAPL, BTC/USD)."""
    if "_" in instrument and len(instrument) == 7:
        base, quote = instrument.split("_")
        return f"{base}/{quote}"
    return instrument


class AlpacaClient:
    """
    Alpaca Markets Client — implementiert dasselbe Interface wie OandaClient.

    Unterstützt Aktien, ETFs und Crypto über eine einheitliche REST API.
    Kein Desktop-Client nötig (im Gegensatz zu IBKR).
    """

    def __init__(self, api_key: str, api_secret: str, environment: str = "paper"):
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
        except ImportError:
            raise ImportError(
                "alpaca-py nicht installiert. Bitte: pip install alpaca-py"
            )

        self._env        = environment.lower()
        self._api_key    = api_key
        self._api_secret = api_secret
        self._paper      = self._env == "paper"

        self._trading = TradingClient(api_key, api_secret, paper=self._paper)
        self._stock_data  = StockHistoricalDataClient(api_key, api_secret)
        self._crypto_data = CryptoHistoricalDataClient(api_key, api_secret)

        account = self._trading.get_account()
        log.info(f"Alpaca: Verbunden ({self._env}) | Account: {account.id} | "
                 f"Buying Power: ${float(account.buying_power):,.2f}")

    @staticmethod
    def _is_crypto(instrument: str) -> bool:
        crypto_bases = {"BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "LTC", "LINK", "AVAX", "DOT"}
        base = instrument.split("/")[0].split("_")[0].upper()
        return base in crypto_bases

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        acc = self._trading.get_account()
        return {
            "id":            str(acc.id),
            "status":        str(acc.status),
            "currency":      "USD",
            "buying_power":  float(acc.buying_power),
            "equity":        float(acc.equity),
            "cash":          float(acc.cash),
            "environment":   self._env,
        }

    def get_balance(self) -> float:
        return float(self._trading.get_account().equity)

    # ── Marktdaten ────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, granularity: str = "H1",
                    count: int = 250) -> list:
        """OHLCV-Daten — kompatibel mit OandaClient-Interface."""
        from datetime import timezone as _tz
        symbol   = _to_alpaca_symbol(instrument)
        timeframe = _GRAN.get(granularity, "1Hour")
        end   = datetime.now(_tz.utc)
        # Zeitraum schätzen
        hours = {"1Min": 1/60, "5Min": 5/60, "15Min": 15/60, "30Min": 0.5,
                 "1Hour": 1, "4Hour": 4, "1Day": 24}.get(timeframe, 1) * count
        start = end - timedelta(hours=hours * 1.5)

        try:
            if self._is_crypto(instrument):
                from alpaca.data.requests import CryptoBarsRequest
                from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
                tf = self._parse_timeframe(timeframe)
                req  = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf,
                                         start=start, end=end, limit=count)
                bars = self._crypto_data.get_crypto_bars(req)
            else:
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                tf = self._parse_timeframe(timeframe)
                req  = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf,
                                        start=start, end=end, limit=count)
                bars = self._stock_data.get_stock_bars(req)

            result = []
            bar_list = bars[symbol] if hasattr(bars, "__getitem__") else list(bars)
            for b in bar_list[-count:]:
                result.append({
                    "time":   b.timestamp.isoformat(),
                    "open":   float(b.open),
                    "high":   float(b.high),
                    "low":    float(b.low),
                    "close":  float(b.close),
                    "volume": float(b.volume),
                })
            return result
        except Exception as e:
            log.warning(f"Alpaca get_candles {symbol} fehlgeschlagen: {e}")
            return []

    @staticmethod
    def _parse_timeframe(tf: str):
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        mapping = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "30Min": TimeFrame(30, TimeFrameUnit.Minute),
            "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
            "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
        }
        return mapping.get(tf, TimeFrame(1, TimeFrameUnit.Hour))

    def get_price(self, instrument: str) -> float:
        """Aktueller Preis."""
        candles = self.get_candles(instrument, "M1", count=1)
        return candles[-1]["close"] if candles else 0.0

    def get_spread_pips(self, instrument: str) -> float:
        """Alpaca hat keinen Spread im klassischen Sinne — gibt Schätzwert zurück."""
        return 0.5  # Alpaca: feste Commission statt Spread

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_market_order(self, instrument: str, units: float,
                           side: str = "buy") -> dict:
        """Market Order platzieren."""
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        symbol   = _to_alpaca_symbol(instrument)
        alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        # Crypto: qty-basiert; Aktien: notional oder qty
        req = MarketOrderRequest(
            symbol      = symbol,
            qty         = abs(units),
            side        = alpaca_side,
            time_in_force = TimeInForce.GTC,
        )
        try:
            order = self._trading.submit_order(req)
            log.info(f"Alpaca Market Order: {side.upper()} {units} {symbol} | ID={order.id}")
            return {
                "id":         str(order.id),
                "status":     str(order.status),
                "instrument": instrument,
                "units":      units,
                "side":       side,
            }
        except Exception as e:
            log.error(f"Alpaca place_market_order fehlgeschlagen: {e}")
            return {"error": str(e)}

    def place_limit_order(self, instrument: str, units: float,
                          price: float, side: str = "buy") -> dict:
        """Limit Order platzieren."""
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        symbol = _to_alpaca_symbol(instrument)
        alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        req = LimitOrderRequest(
            symbol        = symbol,
            qty           = abs(units),
            limit_price   = price,
            side          = alpaca_side,
            time_in_force = TimeInForce.GTC,
        )
        try:
            order = self._trading.submit_order(req)
            return {"id": str(order.id), "status": str(order.status), "price": price}
        except Exception as e:
            log.error(f"Alpaca place_limit_order fehlgeschlagen: {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._trading.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            log.warning(f"Alpaca cancel_order {order_id}: {e}")
            return False

    def close_trade(self, trade_id: str, units: Optional[float] = None) -> dict:
        """Position schließen (trade_id = Symbol bei Alpaca)."""
        symbol = _to_alpaca_symbol(trade_id)
        try:
            if units:
                result = self._trading.close_position(symbol, qty=str(abs(units)))
            else:
                result = self._trading.close_position(symbol)
            return {"status": "closed", "id": str(result.id) if hasattr(result, "id") else "ok"}
        except Exception as e:
            log.error(f"Alpaca close_trade {symbol}: {e}")
            return {"error": str(e)}

    def modify_stop_loss(self, trade_id: str, stop_price: float) -> bool:
        """Stop-Loss via Stop-Order (Alpaca hat kein natives SL auf Positions)."""
        try:
            from alpaca.trading.requests import StopOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            # Bestehende SL-Orders für dieses Symbol canceln
            orders = self._trading.get_orders()
            symbol = _to_alpaca_symbol(trade_id)
            for o in orders:
                if str(o.symbol) == symbol and str(o.type) in ("stop", "stop_limit"):
                    self._trading.cancel_order_by_id(str(o.id))
            # Neue Stop-Order
            pos = self._trading.get_open_position(symbol)
            qty = abs(float(pos.qty))
            side = OrderSide.SELL if float(pos.qty) > 0 else OrderSide.BUY
            req = StopOrderRequest(symbol=symbol, qty=qty, stop_price=stop_price,
                                   side=side, time_in_force=TimeInForce.GTC)
            self._trading.submit_order(req)
            return True
        except Exception as e:
            log.warning(f"Alpaca modify_stop_loss: {e}")
            return False

    def get_open_trades(self) -> list:
        """Offene Positionen als Trade-Liste."""
        try:
            positions = self._trading.get_all_positions()
            trades = []
            for p in positions:
                trades.append({
                    "id":          str(p.symbol),
                    "instrument":  str(p.symbol),
                    "units":       float(p.qty),
                    "price":       float(p.avg_entry_price),
                    "unrealized_pl": float(p.unrealized_pl),
                    "side":        "buy" if float(p.qty) > 0 else "sell",
                })
            return trades
        except Exception as e:
            log.error(f"Alpaca get_open_trades: {e}")
            return []

    def get_closed_trades(self, instrument: str = "", count: int = 50) -> list:
        """Letzte abgeschlossene Orders."""
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            req    = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=count)
            orders = self._trading.get_orders(filter=req)
            trades = []
            for o in orders:
                if instrument and _to_alpaca_symbol(instrument) != str(o.symbol):
                    continue
                trades.append({
                    "id":         str(o.id),
                    "instrument": str(o.symbol),
                    "units":      float(o.qty or 0),
                    "price":      float(o.filled_avg_price or 0),
                    "side":       str(o.side),
                    "time":       str(o.filled_at or o.created_at),
                })
            return trades
        except Exception as e:
            log.error(f"Alpaca get_closed_trades: {e}")
            return []

    def pip_value_per_unit(self, instrument: str) -> float:
        """Alpaca: Punkt-Wert (Aktien = $1, Crypto variiert)."""
        return 1.0

    def calculate_units(self, instrument: str, risk_usd: float,
                        stop_pips: float) -> float:
        """Position-Size: risk_usd / (stop_pips * pip_value)."""
        price = self.get_price(instrument)
        if not price or not stop_pips:
            return 0.0
        stop_usd = stop_pips * price / 100  # stop_pips als %-Wert
        if stop_usd <= 0:
            return 0.0
        units = risk_usd / stop_usd
        # Runde auf ganze Aktien / 2 Dezimalstellen für Crypto
        if self._is_crypto(instrument):
            return round(units, 4)
        return max(1.0, round(units))
