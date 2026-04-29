"""
Capital.com REST API Client.

Vollständiges Drop-In-Replacement für OandaClient.
Capital.com bietet Forex CFDs mit kostenlosem Demo-Account.

Docs: https://open-api.capital.com/

Authentifizierung:
  1. POST /session mit API-Key + E-Mail + Passwort
  2. CST + X-SECURITY-TOKEN aus Response-Headern extrahieren
  3. Beide Header bei jedem Request mitsenden
  Sitzung läuft nach 10 Minuten Inaktivität ab → Auto-Refresh.

Einrichtung:
  1. Account auf capital.com (oder demo.capital.com) anlegen
  2. API-Schlüssel: Mein Profil → API-Schlüssel generieren
  3. In forex_bot/.env:
       FOREX_BROKER=capital
       CAPITAL_API_KEY=dein-api-key
       CAPITAL_EMAIL=deine@email.com
       CAPITAL_PASSWORD=dein-passwort
       CAPITAL_ENV=demo    # demo | live

Capital.com REST API Client — drop-in replacement for OandaClient.
Provides Forex CFD trading with a free demo account.

Authentication:
  Session tokens (CST + X-SECURITY-TOKEN) are fetched automatically
  and refreshed on expiry.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

log = logging.getLogger("forex_bot")

_BASE = {
    "demo": "https://demo-api-capital.backend.gbksoft.com/api/v1",
    "live": "https://api-capital.backend.gbksoft.com/api/v1",
}

# Instrument-Mapping: OANDA-Format → Capital.com Epic
_EPIC = {
    "EUR_USD": "EURUSD", "GBP_USD": "GBPUSD", "USD_JPY": "USDJPY",
    "EUR_JPY": "EURJPY", "GBP_JPY": "GBPJPY", "EUR_GBP": "EURGBP",
    "AUD_USD": "AUDUSD", "USD_CAD": "USDCAD", "USD_CHF": "USDCHF",
    "NZD_USD": "NZDUSD", "EUR_CHF": "EURCHF", "AUD_JPY": "AUDJPY",
}

# Granularitäts-Mapping: OANDA → Capital.com
_GRAN = {
    "M1": "MINUTE", "M5": "MINUTE_5", "M15": "MINUTE_15",
    "M30": "MINUTE_30", "H1": "HOUR", "H4": "HOUR_4", "D": "DAY",
}

# Sitzungs-Refresh nach 9 Minuten (Capital.com Timeout: 10 Min.)
_SESSION_TTL = 540


class CapitalClient:
    """
    Capital.com API-Client — implementiert dasselbe Interface wie OandaClient.

    Alle Instruments werden intern von OANDA-Format (EUR_USD) in
    Capital.com-Epics (EURUSD) konvertiert.

    Positionen werden in Lots gemessen (1.0 = 100.000 Units Basiswährung).
    """

    def __init__(self, api_key: str, email: str, password: str,
                 environment: str = "demo"):
        self._base      = _BASE.get(environment, _BASE["demo"])
        self._api_key   = api_key
        self._email     = email
        self._password  = password
        self._cst:   str = ""
        self._token: str = ""
        self._session_ts: float = 0.0
        self._login()

    # ── Session Management ────────────────────────────────────────────────────

    def _login(self) -> None:
        """Erstellt neue Capital.com-Sitzung und speichert CST + X-SECURITY-TOKEN."""
        r = requests.post(
            f"{self._base}/session",
            headers={"X-CAP-API-KEY": self._api_key, "Content-Type": "application/json"},
            json={"identifier": self._email, "password": self._password,
                  "encryptedPassword": False},
            timeout=15,
        )
        r.raise_for_status()
        self._cst        = r.headers["CST"]
        self._token      = r.headers["X-SECURITY-TOKEN"]
        self._session_ts = time.time()
        log.info("Capital.com: Sitzung erstellt")

    def _refresh_if_needed(self) -> None:
        """Erneuert Sitzung wenn TTL überschritten."""
        if time.time() - self._session_ts > _SESSION_TTL:
            log.debug("Capital.com: Sitzung läuft ab — neu anmelden")
            self._login()

    @property
    def _headers(self) -> dict:
        self._refresh_if_needed()
        return {
            "X-CAP-API-KEY":     self._api_key,
            "CST":               self._cst,
            "X-SECURITY-TOKEN":  self._token,
            "Content-Type":      "application/json",
        }

    # ── HTTP Helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{self._base}{path}", headers=self._headers,
                         params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = requests.post(f"{self._base}{path}", headers=self._headers,
                          json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str, data: dict = None) -> dict:
        r = requests.delete(f"{self._base}{path}", headers=self._headers,
                            json=data or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Instrument-Konvertierung ──────────────────────────────────────────────

    @staticmethod
    def _epic(instrument: str) -> str:
        """OANDA-Instrument → Capital.com Epic (z.B. EUR_USD → EURUSD)."""
        return _EPIC.get(instrument, instrument.replace("_", ""))

    @staticmethod
    def _units_to_lots(units: int) -> float:
        """OANDA-Units → Capital.com Lots (100.000 Units = 1.0 Lot)."""
        return abs(units) / 100_000

    @staticmethod
    def _lots_to_units(lots: float, direction: str) -> int:
        """Capital.com Lots → OANDA-Units mit Vorzeichen."""
        u = int(lots * 100_000)
        return u if direction == "BUY" else -u

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Gibt Account-Zusammenfassung zurück."""
        return self._get("/accounts")

    def get_balance(self) -> float:
        """Aktueller Kontostand in der Account-Währung."""
        accounts = self._get("/accounts")
        for acc in accounts.get("accounts", []):
            if acc.get("preferred"):
                return float(acc["balance"]["balance"])
        # Fallback: erster Account
        accs = accounts.get("accounts", [])
        if accs:
            return float(accs[0]["balance"]["balance"])
        return 0.0

    # ── Marktdaten ────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, granularity: str = "H1",
                    count: int = 250) -> list:
        """
        Gibt OHLCV-Dicts zurück — kompatibel mit OandaClient.

        instrument:  OANDA-Format (EUR_USD)
        granularity: OANDA-Format (H1, M15, H4, D)
        """
        epic = self._epic(instrument)
        res  = _GRAN.get(granularity, "HOUR")
        data = self._get(f"/prices/{epic}", params={"resolution": res, "max": count})

        candles = []
        for p in data.get("prices", []):
            # Capital.com gibt bid/ask → Mid berechnen
            mid_o = (p["openPrice"]["bid"]  + p["openPrice"]["ask"])  / 2
            mid_h = (p["highPrice"]["bid"]  + p["highPrice"]["ask"])  / 2
            mid_l = (p["lowPrice"]["bid"]   + p["lowPrice"]["ask"])   / 2
            mid_c = (p["closePrice"]["bid"] + p["closePrice"]["ask"]) / 2
            candles.append({
                "time":   p["snapshotTime"],
                "open":   round(mid_o, 5),
                "high":   round(mid_h, 5),
                "low":    round(mid_l, 5),
                "close":  round(mid_c, 5),
                "volume": int(p.get("lastTradedVolume", 0)),
            })
        return candles

    def get_price(self, instrument: str) -> float:
        """Aktueller Mid-Price."""
        epic = self._epic(instrument)
        data = self._get(f"/markets/{epic}")
        snap = data.get("snapshot", {})
        bid  = float(snap.get("bid", 0))
        ask  = float(snap.get("offer", bid))
        return (bid + ask) / 2

    def get_spread_pips(self, instrument: str) -> float:
        """Aktueller Spread in Pips."""
        epic     = self._epic(instrument)
        data     = self._get(f"/markets/{epic}")
        snap     = data.get("snapshot", {})
        bid      = float(snap.get("bid", 0))
        ask      = float(snap.get("offer", bid))
        pip_size = 0.01 if "JPY" in instrument else 0.0001
        return round((ask - bid) / pip_size, 1)

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        instrument:  str,
        units:       int,
        stop_loss:   Optional[float] = None,
        take_profit: Optional[float] = None,
        comment:     str = "",
    ) -> dict:
        """
        Platziert Market-Order.

        units: positiv = BUY, negativ = SELL (OANDA-Konvention)
        """
        direction = "BUY" if units > 0 else "SELL"
        size      = self._units_to_lots(units)

        body: dict = {
            "epic":          self._epic(instrument),
            "direction":     direction,
            "size":          round(size, 2),
            "guaranteedStop": False,
            "forceOpen":     True,
        }
        if stop_loss:
            body["stopLevel"] = stop_loss
        if take_profit:
            body["profitLevel"] = take_profit

        result = self._post("/positions", body)
        log.info(f"Capital.com: {direction} {instrument} {size:.2f} lots → {result}")
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
        """
        Platziert Working Order (Limit-Order) — wird gecancelt nach gtd_seconds.

        Capital.com nennt Limit-Orders "Working Orders".
        """
        direction  = "BUY" if units > 0 else "SELL"
        size       = self._units_to_lots(units)
        expiry_utc = (datetime.now(timezone.utc) + timedelta(seconds=gtd_seconds))
        expiry_str = expiry_utc.strftime("%Y/%m/%d %H:%M:%S:%f")[:-3]

        body: dict = {
            "epic":          self._epic(instrument),
            "direction":     direction,
            "size":          round(size, 2),
            "level":         price,
            "type":          "LIMIT",
            "goodTillDate":  expiry_str,
            "guaranteedStop": False,
        }
        if stop_loss:
            body["stopLevel"] = stop_loss
        if take_profit:
            body["profitLevel"] = take_profit

        return self._post("/workingorders", body)

    def cancel_order(self, order_id: str) -> dict:
        """Storniert Working Order."""
        return self._delete(f"/workingorders/{order_id}")

    def close_trade(self, trade_id: str) -> dict:
        """Schließt offene Position."""
        return self._delete(f"/positions/{trade_id}")

    def modify_stop_loss(self, trade_id: str, stop_loss: float) -> dict:
        """Aktualisiert Stop-Loss einer offenen Position."""
        r = requests.put(
            f"{self._base}/positions/{trade_id}",
            headers=self._headers,
            json={"stopLevel": stop_loss},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ── Offene Positionen ─────────────────────────────────────────────────────

    def get_open_trades(self) -> list:
        """
        Gibt offene Positionen zurück — normalisiert auf OANDA-Format.

        Gibt list[dict] mit Feldern: id, instrument, currentUnits, price,
        unrealizedPL, stopLossOrder, takeProfitOrder
        """
        data   = self._get("/positions")
        result = []
        for pos in data.get("positions", []):
            epic   = pos.get("market", {}).get("epic", "")
            # Epic zurück zu OANDA-Format konvertieren
            oanda_instr = self._reverse_epic(epic)
            direction   = pos.get("position", {}).get("direction", "BUY")
            size_lots   = float(pos.get("position", {}).get("size", 0))
            units       = self._lots_to_units(size_lots, direction)
            result.append({
                "id":             pos.get("position", {}).get("dealId", ""),
                "instrument":     oanda_instr,
                "currentUnits":   str(units),
                "price":          pos.get("position", {}).get("openLevel", 0),
                "unrealizedPL":   pos.get("position", {}).get("upl", 0),
                "stopLossOrder":  {"price": pos.get("position", {}).get("stopLevel")},
                "takeProfitOrder":{"price": pos.get("position", {}).get("limitLevel")},
            })
        return result

    def get_closed_trades(self, count: int = 50) -> list:
        """Gibt abgeschlossene Positionen zurück."""
        data = self._get("/history/activity", params={"lastPeriod": 86400000})
        return data.get("activities", [])[:count]

    # ── Pip-Wert + Unit-Berechnung ────────────────────────────────────────────

    def pip_value_per_unit(self, instrument: str) -> float:
        """Pip-Wert in USD pro 1 Unit (OANDA-kompatibel)."""
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
        """Berechnet Units — identisch zu OandaClient."""
        pip_size    = 0.01 if "JPY" in instrument else 0.0001
        pips_risked = abs(entry - stop_loss) / pip_size
        if pips_risked < 0.1:
            return 0
        pv_per_unit = self.pip_value_per_unit(instrument)
        risk_amount = capital * risk_fraction
        units       = int(risk_amount / (pips_risked * pv_per_unit))
        return max(1_000, min(units, 100_000))

    @staticmethod
    def _reverse_epic(epic: str) -> str:
        """Capital.com Epic → OANDA-Format (EURUSD → EUR_USD)."""
        _rev = {v: k for k, v in _EPIC.items()}
        return _rev.get(epic, epic[:3] + "_" + epic[3:])
