"""
OANDA REST API v3 Client.

Unterstützt Practice- und Live-Umgebung.
Verwendet direkt requests — keine externe SDK-Abhängigkeit.

Docs: https://developer.oanda.com/rest-live-v20/introduction/
"""
import logging
import requests
from typing import Optional

log = logging.getLogger("forex_bot")

_BASE = {
    "practice": "https://api-fxpractice.oanda.com/v3",
    "live":      "https://api-fxtrade.oanda.com/v3",
}


class OandaClient:
    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        self.account_id = account_id
        self._headers   = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        self._base = _BASE.get(environment, _BASE["practice"])

    # ── HTTP Helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{self._base}{path}", headers=self._headers, params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = requests.post(f"{self._base}{path}", headers=self._headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, data: dict = None) -> dict:
        r = requests.put(f"{self._base}{path}", headers=self._headers, json=data or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        return self._get(f"/accounts/{self.account_id}/summary")["account"]

    def get_balance(self) -> float:
        return float(self.get_account()["balance"])

    # ── Marktdaten ────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, granularity: str = "H1", count: int = 250) -> list:
        """
        Gibt Liste von OHLCV-Dicts zurück (nur abgeschlossene Candles).

        instrument:   "EUR_USD", "GBP_USD", "USD_JPY" etc.
        granularity:  M1, M5, M15, M30, H1, H4, D
        """
        data = self._get(
            f"/instruments/{instrument}/candles",
            params={"count": count, "granularity": granularity, "price": "M"},
        )
        candles = []
        for c in data.get("candles", []):
            if not c.get("complete", False):
                continue
            candles.append({
                "time":   c["time"],
                "open":   float(c["mid"]["o"]),
                "high":   float(c["mid"]["h"]),
                "low":    float(c["mid"]["l"]),
                "close":  float(c["mid"]["c"]),
                "volume": int(c.get("volume", 0)),
            })
        return candles

    def get_price(self, instrument: str) -> float:
        """Aktueller Mid-Price."""
        data = self._get(
            f"/accounts/{self.account_id}/pricing",
            params={"instruments": instrument},
        )
        p = data["prices"][0]
        return (float(p["asks"][0]["price"]) + float(p["bids"][0]["price"])) / 2

    def get_spread_pips(self, instrument: str) -> float:
        """Aktueller Spread in Pips."""
        data = self._get(
            f"/accounts/{self.account_id}/pricing",
            params={"instruments": instrument},
        )
        p        = data["prices"][0]
        ask      = float(p["asks"][0]["price"])
        bid      = float(p["bids"][0]["price"])
        pip_size = 0.01 if "JPY" in instrument else 0.0001
        return round((ask - bid) / pip_size, 1)

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        instrument:  str,
        units:       int,        # positiv = BUY, negativ = SELL
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        comment:     str = "",
    ) -> dict:
        order: dict = {
            "type":         "MARKET",
            "instrument":   instrument,
            "units":        str(units),
            "timeInForce":  "FOK",
            "positionFill": "DEFAULT",
        }
        if stop_loss:
            order["stopLossOnFill"]   = {"price": f"{stop_loss:.5f}"}
        if take_profit:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.5f}"}

        return self._post(f"/accounts/{self.account_id}/orders", {"order": order})

    def place_limit_order(
        self,
        instrument:  str,
        units:       int,        # positiv = BUY, negativ = SELL
        price:       float,      # Limit-Preis
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        gtd_seconds: int = 3600,  # Good-Till-Cancelled Dauer in Sekunden
    ) -> dict:
        """
        Platziert Limit-Order (Einstieg zu besserem Preis).

        Wird automatisch gecancelt nach gtd_seconds (default: 1 Stunde).
        """
        from datetime import datetime, timezone, timedelta
        gtd = (datetime.now(timezone.utc) + timedelta(seconds=gtd_seconds)).strftime(
            "%Y-%m-%dT%H:%M:%S.000000Z"
        )
        order: dict = {
            "type":         "LIMIT",
            "instrument":   instrument,
            "units":        str(units),
            "price":        f"{price:.5f}",
            "timeInForce":  "GTD",
            "gtdTime":      gtd,
            "positionFill": "DEFAULT",
        }
        if stop_loss:
            order["stopLossOnFill"]   = {"price": f"{stop_loss:.5f}"}
        if take_profit:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.5f}"}

        return self._post(f"/accounts/{self.account_id}/orders", {"order": order})

    def cancel_order(self, order_id: str) -> dict:
        """Storniert eine offene Order."""
        r = requests.put(
            f"{self._base}/accounts/{self.account_id}/orders/{order_id}/cancel",
            headers=self._headers,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def close_trade(self, trade_id: str) -> dict:
        return self._put(f"/accounts/{self.account_id}/trades/{trade_id}/close")

    def close_partial_trade(self, trade_id: str, units_to_close: int, direction: str) -> dict:
        """Schließt einen Teil einer offenen Position (Scale-Out)."""
        return self._put(
            f"/accounts/{self.account_id}/trades/{trade_id}/close",
            {"units": str(abs(units_to_close))},
        )

    def get_pending_orders(self) -> list:
        """Gibt offene Orders zurück."""
        return self._get(f"/accounts/{self.account_id}/pendingOrders").get("orders", [])

    def modify_stop_loss(self, trade_id: str, stop_loss: float) -> dict:
        return self._put(
            f"/accounts/{self.account_id}/trades/{trade_id}/orders",
            {"stopLoss": {"price": f"{stop_loss:.5f}"}},
        )

    # ── Offene Trades ─────────────────────────────────────────────────────────

    def get_open_trades(self) -> list:
        return self._get(f"/accounts/{self.account_id}/openTrades").get("trades", [])

    def get_closed_trades(self, count: int = 50) -> list:
        return self._get(
            f"/accounts/{self.account_id}/trades",
            params={"state": "CLOSED", "count": count},
        ).get("trades", [])

    # ── Pip-Wert ──────────────────────────────────────────────────────────────

    def pip_value_per_unit(self, instrument: str) -> float:
        """
        Pip-Wert in USD pro 1 Unit (kleinste Handelsgröße).

        Formel:
          Wenn Quote-Währung = USD: pip_value = pip_size
          Sonst:                    pip_value = pip_size / price
        """
        pip_size      = 0.01 if "JPY" in instrument else 0.0001
        quote_ccy     = instrument.split("_")[1]
        if quote_ccy == "USD":
            return pip_size
        # Konvertierung über aktuellen Kurs
        try:
            price = self.get_price(instrument)
            return pip_size / price
        except Exception:
            return pip_size  # Fallback

    def calculate_units(
        self,
        instrument:    str,
        entry:         float,
        stop_loss:     float,
        capital:       float,
        risk_fraction: float = 0.01,
    ) -> int:
        """
        Berechnet Einheitenzahl so, dass max. risk_fraction * capital riskiert wird.

        Gibt positiven Wert zurück — Vorzeichen (BUY/SELL) separat setzen.
        """
        pip_size    = 0.01 if "JPY" in instrument else 0.0001
        pips_risked = abs(entry - stop_loss) / pip_size
        if pips_risked < 0.1:
            return 0

        pv_per_unit = self.pip_value_per_unit(instrument)
        risk_amount = capital * risk_fraction
        units       = int(risk_amount / (pips_risked * pv_per_unit))
        return max(1_000, min(units, 100_000))   # 1k–100k Units (0.01–1.0 Lot)
