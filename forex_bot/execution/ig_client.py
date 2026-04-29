"""
IG Group REST API Client.

Vollständiges Drop-In-Replacement für OandaClient.
IG ist einer der größten CFD-Broker weltweit — reguliert in DE/AT/CH.

Docs: https://labs.ig.com/rest-trading-api-reference

Authentifizierung:
  1. POST /session mit API-Key im Header + Credentials im Body
  2. CST + X-SECURITY-TOKEN aus Response extrahieren
  3. Beide Header bei jedem Request mitsenden

Einrichtung:
  1. Demo-Account: ig.com → "Demo-Konto eröffnen"
  2. API-Zugang: ig.com → Mein Konto → API-Schlüssel
  3. In forex_bot/.env:
       FOREX_BROKER=ig
       IG_API_KEY=dein-api-key
       IG_USERNAME=dein-benutzername
       IG_PASSWORD=dein-passwort
       IG_ENV=demo    # demo | live
       IG_ACCOUNT_ID=  # optional — wenn mehrere Accounts

IG Group REST API Client — drop-in replacement for OandaClient.
IG is one of the world's largest CFD brokers, regulated in DE/AT/CH.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger("forex_bot")

_BASE = {
    "demo": "https://demo-api.ig.com/gateway/deal",
    "live": "https://api.ig.com/gateway/deal",
}

# Instrument-Mapping: OANDA-Format → IG Epic
_EPIC: dict[str, str] = {
    "EUR_USD": "CS.D.EURUSD.MINI.IP",
    "GBP_USD": "CS.D.GBPUSD.MINI.IP",
    "USD_JPY": "CS.D.USDJPY.MINI.IP",
    "EUR_JPY": "CS.D.EURJPY.MINI.IP",
    "GBP_JPY": "CS.D.GBPJPY.MINI.IP",
    "EUR_GBP": "CS.D.EURGBP.MINI.IP",
    "AUD_USD": "CS.D.AUDUSD.MINI.IP",
    "USD_CAD": "CS.D.USDCAD.MINI.IP",
    "USD_CHF": "CS.D.USDCHF.MINI.IP",
    "NZD_USD": "CS.D.NZDUSD.MINI.IP",
    "EUR_CHF": "CS.D.EURCHF.MINI.IP",
    "AUD_JPY": "CS.D.AUDJPY.MINI.IP",
}

# Granularitäts-Mapping: OANDA → IG
_GRAN: dict[str, str] = {
    "M1": "MINUTE", "M5": "MINUTE_5", "M15": "MINUTE_15",
    "M30": "MINUTE_30", "H1": "HOUR", "H4": "HOUR_4", "D": "DAY",
}

# Sitzungs-Refresh nach 5 Stunden (IG-Timeout: 6 Stunden)
_SESSION_TTL = 18_000


class IGClient:
    """
    IG Group API-Client — implementiert dasselbe Interface wie OandaClient.

    Instruments werden von OANDA-Format (EUR_USD) in IG-Epics
    (CS.D.EURUSD.MINI.IP) konvertiert. Größen werden in Lots gemessen.
    """

    def __init__(self, api_key: str, username: str, password: str,
                 environment: str = "demo", account_id: str = ""):
        self._base       = _BASE.get(environment, _BASE["demo"])
        self._api_key    = api_key
        self._username   = username
        self._password   = password
        self._account_id = account_id
        self._cst:   str = ""
        self._token: str = ""
        self._session_ts = 0.0
        self._login()

    # ── Session Management ────────────────────────────────────────────────────

    def _login(self) -> None:
        """Erstellt neue IG-Sitzung."""
        r = requests.post(
            f"{self._base}/session",
            headers={
                "X-IG-API-KEY":  self._api_key,
                "Content-Type":  "application/json",
                "VERSION":       "2",
            },
            json={"identifier": self._username, "password": self._password},
            timeout=15,
        )
        r.raise_for_status()
        self._cst        = r.headers["CST"]
        self._token      = r.headers["X-SECURITY-TOKEN"]
        self._session_ts = time.time()

        # Account-ID aus Response wenn nicht manuell gesetzt
        if not self._account_id:
            body = r.json()
            self._account_id = body.get("currentAccountId", "")

        log.info(f"IG: Sitzung erstellt (Account: {self._account_id})")

    def _refresh_if_needed(self) -> None:
        if time.time() - self._session_ts > _SESSION_TTL:
            log.debug("IG: Sitzung abgelaufen — neu anmelden")
            self._login()

    @property
    def _headers(self) -> dict:
        self._refresh_if_needed()
        return {
            "X-IG-API-KEY":      self._api_key,
            "CST":               self._cst,
            "X-SECURITY-TOKEN":  self._token,
            "Content-Type":      "application/json",
            "VERSION":           "1",
        }

    def _headers_v(self, version: str) -> dict:
        h = dict(self._headers)
        h["VERSION"] = version
        return h

    # ── HTTP Helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None, version: str = "1") -> dict:
        r = requests.get(f"{self._base}{path}", headers=self._headers_v(version),
                         params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict, version: str = "1") -> dict:
        r = requests.post(f"{self._base}{path}", headers=self._headers_v(version),
                          json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str, data: dict = None, version: str = "1") -> dict:
        h = dict(self._headers_v(version))
        h["_method"] = "DELETE"
        r = requests.post(f"{self._base}{path}", headers=h,
                          json=data or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Instrument-Konvertierung ──────────────────────────────────────────────

    @staticmethod
    def _epic(instrument: str) -> str:
        return _EPIC.get(instrument, f"CS.D.{instrument.replace('_', '')}.MINI.IP")

    @staticmethod
    def _price_scale(instrument: str) -> int:
        """IG MINI-Kontrakte quoten Preise skaliert: JPY-Paare ×100, alle anderen ×10000."""
        return 100 if "JPY" in instrument else 10_000

    @staticmethod
    def _units_to_lots(units: int) -> float:
        """OANDA-Units → IG-Lots (1 Mini-Lot = 10.000 Units)."""
        return abs(units) / 10_000

    @staticmethod
    def _lots_to_units(lots: float, direction: str) -> int:
        u = int(lots * 10_000)
        return u if direction == "BUY" else -u

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Gibt Account-Details zurück."""
        accounts = self._get("/accounts")
        for acc in accounts.get("accounts", []):
            if acc.get("accountId") == self._account_id:
                return acc
        accs = accounts.get("accounts", [])
        return accs[0] if accs else {}

    def get_balance(self) -> float:
        """Aktueller verfügbarer Kontostand."""
        acc = self.get_account()
        return float(acc.get("balance", {}).get("available", 0))

    # ── Marktdaten ────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, granularity: str = "H1",
                    count: int = 250) -> list:
        """
        Gibt OHLCV-Dicts zurück — kompatibel mit OandaClient.

        instrument:  OANDA-Format (EUR_USD)
        granularity: OANDA-Format (H1, M15, H4, D)
        """
        try:
            epic = self._epic(instrument)
            res  = _GRAN.get(granularity, "HOUR")
            data = self._get(
                f"/prices/{epic}",
                params={"resolution": res, "max": count, "pageSize": count},
                version="3",
            )

            candles = []
            for p in data.get("prices", []):
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
            if candles:
                return candles
            raise ValueError("IG: leere Preisantwort")

        except Exception as e:
            log.warning(f"IG get_candles {instrument} fehlgeschlagen ({e}) — yfinance Fallback")
            return self._yfinance_candles(instrument, granularity, count)

    _YF_MAP = {
        "EUR_USD": "EURUSD=X", "GBP_USD": "GBPUSD=X", "USD_JPY": "USDJPY=X",
        "EUR_JPY": "EURJPY=X", "GBP_JPY": "GBPJPY=X", "EUR_GBP": "EURGBP=X",
        "AUD_USD": "AUDUSD=X", "USD_CAD": "USDCAD=X", "USD_CHF": "USDCHF=X",
        "NZD_USD": "NZDUSD=X", "EUR_CHF": "EURCHF=X", "AUD_JPY": "AUDJPY=X",
    }
    _YF_INTERVAL = {"H1": "1h", "H4": "1h", "M15": "15m", "M5": "5m", "D": "1d"}

    def _yfinance_candles(self, instrument: str, granularity: str, count: int) -> list:
        import math
        import yfinance as yf
        ticker   = self._YF_MAP.get(instrument, f"{instrument.replace('_','')}=X")
        interval = self._YF_INTERVAL.get(granularity, "1h")
        days     = min(math.ceil(count / 24 * 1.5), 729) if "h" in interval else min(count + 10, 729)
        df = yf.download(ticker, interval=interval, period=f"{days}d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            raise ValueError(f"yfinance: keine Daten für {ticker}")
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                 "Close": "close", "Volume": "volume"})
        df = df.reset_index()
        time_col = next((c for c in df.columns if str(c).lower() in ("datetime", "date", "timestamp", "index")), None)
        if time_col:
            df = df.rename(columns={time_col: "time"})
            df["time"] = df["time"].astype(str)
        df = df[[c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]].dropna(
            subset=["open", "high", "low", "close"]
        ).tail(count).reset_index(drop=True)
        log.info(f"IG yfinance Fallback: {len(df)} Candles für {instrument} ({granularity})")
        return df.to_dict("records")

    def get_price(self, instrument: str) -> float:
        """Aktueller Mid-Price."""
        epic  = self._epic(instrument)
        data  = self._get(f"/markets/{epic}")
        snap  = data.get("snapshot", {})
        bid   = float(snap.get("bid", 0))
        ask   = float(snap.get("offer", bid))
        scale = self._price_scale(instrument)
        return (bid + ask) / 2 / scale

    def get_spread_pips(self, instrument: str) -> float:
        """Aktueller Spread in Pips."""
        epic     = self._epic(instrument)
        data     = self._get(f"/markets/{epic}")
        snap     = data.get("snapshot", {})
        bid      = float(snap.get("bid", 0))
        ask      = float(snap.get("offer", bid))
        scale    = self._price_scale(instrument)
        pip_size = 0.01 if "JPY" in instrument else 0.0001
        return round((ask - bid) / scale / pip_size, 1)

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
        direction = "BUY" if units > 0 else "SELL"
        size      = self._units_to_lots(units)
        price     = self.get_price(instrument)

        body: dict = {
            "epic":           self._epic(instrument),
            "direction":      direction,
            "size":           round(size, 2),
            "orderType":      "MARKET",
            "timeInForce":    "FILL_OR_KILL",
            "expiry":         "-",
            "guaranteedStop": False,
            "forceOpen":      True,
            "currencyCode":   "USD",
        }

        if stop_loss:
            # IG braucht Distanz in Pips, nicht absoluten Preis
            pip_size = 0.01 if "JPY" in instrument else 0.0001
            body["stopDistance"] = round(abs(price - stop_loss) / pip_size, 1)

        if take_profit:
            pip_size = 0.01 if "JPY" in instrument else 0.0001
            body["limitDistance"] = round(abs(price - take_profit) / pip_size, 1)

        result = self._post("/positions/otc", body, version="2")
        log.info(f"IG: {direction} {instrument} {size:.2f} lots → {result}")
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
        """Platziert Limit-Order."""
        direction  = "BUY" if units > 0 else "SELL"
        size       = self._units_to_lots(units)
        pip_size   = 0.01 if "JPY" in instrument else 0.0001

        body: dict = {
            "epic":           self._epic(instrument),
            "direction":      direction,
            "size":           round(size, 2),
            "level":          price,
            "type":           "LIMIT",
            "timeInForce":    "GOOD_TILL_CANCELLED",
            "expiry":         "-",
            "guaranteedStop": False,
            "forceOpen":      True,
            "currencyCode":   "USD",
        }

        if stop_loss:
            body["stopDistance"] = round(abs(price - stop_loss) / pip_size, 1)
        if take_profit:
            body["limitDistance"] = round(abs(price - take_profit) / pip_size, 1)

        return self._post("/workingorders/otc", body, version="2")

    def cancel_order(self, order_id: str) -> dict:
        """Storniert Working Order."""
        return self._delete(f"/workingorders/otc/{order_id}", version="2")

    def close_trade(self, trade_id: str) -> dict:
        """Schließt offene Position."""
        # IG braucht Size + Direction zum Schließen
        open_trades = self.get_open_trades()
        trade = next((t for t in open_trades if t["id"] == trade_id), None)
        if not trade:
            return {"error": f"Trade {trade_id} nicht gefunden"}

        units     = int(trade.get("currentUnits", 0))
        direction = "SELL" if units > 0 else "BUY"   # Gegenrichtung schließt
        size      = abs(self._units_to_lots(units))

        return self._delete(
            f"/positions/otc",
            data={
                "dealId":     trade_id,
                "direction":  direction,
                "size":       round(size, 2),
                "orderType":  "MARKET",
                "timeInForce": "FILL_OR_KILL",
                "expiry":     "-",
            },
            version="1",
        )

    def close_partial_trade(self, trade_id: str, units_to_close: int, direction: str) -> dict:
        """Schließt einen Teil einer offenen Position (Scale-Out)."""
        close_dir = "SELL" if direction == "BUY" else "BUY"
        size = round(abs(self._units_to_lots(units_to_close)), 2)
        return self._delete(
            "/positions/otc",
            data={
                "dealId":      trade_id,
                "direction":   close_dir,
                "size":        size,
                "orderType":   "MARKET",
                "timeInForce": "FILL_OR_KILL",
                "expiry":      "-",
            },
            version="1",
        )

    def get_pending_orders(self) -> list:
        """Gibt offene Working Orders zurück."""
        data = self._get("/workingorders/otc")
        return data.get("workingOrders", [])

    def modify_stop_loss(self, trade_id: str, stop_loss: float) -> dict:
        """Aktualisiert Stop-Loss einer offenen Position."""
        r = requests.put(
            f"{self._base}/positions/otc/{trade_id}",
            headers=self._headers_v("2"),
            json={"stopLevel": stop_loss, "trailingStop": False,
                  "limitedRiskPremium": None},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ── Offene Positionen ─────────────────────────────────────────────────────

    def get_open_trades(self) -> list:
        """
        Gibt offene Positionen zurück — normalisiert auf OANDA-Format.
        """
        data   = self._get("/positions/otc")
        result = []
        for pos in data.get("positions", []):
            market = pos.get("market", {})
            epic   = market.get("epic", "")
            deal   = pos.get("position", {})
            direction = deal.get("direction", "BUY")
            size_lots = float(deal.get("size", 0))
            units     = self._lots_to_units(size_lots, direction)

            # Epic zurück zu OANDA-Format
            _rev        = {v: k for k, v in _EPIC.items()}
            oanda_instr = _rev.get(epic, epic)

            result.append({
                "id":              deal.get("dealId", ""),
                "instrument":      oanda_instr,
                "currentUnits":    str(units),
                "price":           deal.get("openLevel", 0),
                "unrealizedPL":    deal.get("upl", 0),
                "stopLossOrder":   {"price": deal.get("stopLevel")},
                "takeProfitOrder": {"price": deal.get("limitLevel")},
            })
        return result

    def get_closed_trades(self, count: int = 50) -> list:
        """Gibt abgeschlossene Positionen zurück."""
        data = self._get("/history/activity/transactions",
                         params={"type": "TRADE", "maxSpanSeconds": 86400})
        return data.get("transactions", [])[:count]

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
