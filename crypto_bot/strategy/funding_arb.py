"""
Funding Rate Arbitrage — Long Spot / Short Perpetual.

Strategie: Wenn die Funding Rate hoch ist, zahlen Long-Perpetual-Trader
Funding an Short-Trader. Wir kaufen Spot (ungehedgt gegenüber Spot-Risiko)
und shorten ein Perpetual mit gleichem Notional → Delta-neutral.

Position verdient:
  1. Funding-Zahlung jede 8 Stunden (bei positiver Funding-Rate)
  2. Basis-Konvergenz (Spot-Perp-Spread schließt sich)

Risiken:
  - Basis-Spread kann sich ausweiten (Liquidationsgefahr Perp-Short)
  - Funding-Rate kann sich umkehren
  - Exchange-Gebühren (2x Taker für Perp-Short)

Aktivierung:
    FEATURE_FUNDING_ARB=true
    FUNDING_ARB_MIN_RATE=0.0005   # 0.05% / 8h Mindest-Rate (Standard: 0.05%)
    FUNDING_ARB_MAX_POSITION=0.2  # max 20% des Kapitals (Standard: 10%)
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Konfiguration
MIN_RATE_DEFAULT    = float(os.getenv("FUNDING_ARB_MIN_RATE",    "0.0005"))   # 0.05%/8h
MAX_POS_PCT_DEFAULT = float(os.getenv("FUNDING_ARB_MAX_POSITION", "0.10"))    # 10% des Kapitals
ANNUALIZE_FACTOR    = 3 * 365   # 3 × 8h-Perioden pro Tag × 365 Tage


@dataclass
class FundingArbSignal:
    symbol:          str
    funding_rate:    float      # aktuell, pro 8h
    spot_price:      float
    perp_price:      float
    basis_pct:       float      # (perp - spot) / spot * 100
    annual_yield_pct: float     # funding_rate * ANNUALIZE_FACTOR * 100
    action:          str        # "ENTER", "EXIT", "HOLD"
    reason:          str        = ""
    recommended_usdt: float     = 0.0


class FundingArbStrategy:
    """
    Bewertet ob eine Funding-Arb-Position lohnt und gibt Einzel-Signale.

    Kompatibel mit Exchange-Instanzen die fetchFundingRate() unterstützen:
    Binance USDT-M Futures, Bybit, OKX, etc.
    """

    def __init__(
        self,
        exchange_spot,          # ccxt Spot-Exchange
        exchange_perp,          # ccxt Futures/Perp-Exchange (kann derselbe sein)
        symbol:      str,       # z.B. "BTC/USDT"
        perp_symbol: str = "",  # z.B. "BTC/USDT:USDT", leer = auto-detect
        min_rate:    float = MIN_RATE_DEFAULT,
        max_pos_pct: float = MAX_POS_PCT_DEFAULT,
    ):
        self.exchange_spot  = exchange_spot
        self.exchange_perp  = exchange_perp
        self.symbol         = symbol
        self.perp_symbol    = perp_symbol or self._detect_perp_symbol(symbol)
        self.min_rate       = min_rate
        self.max_pos_pct    = max_pos_pct
        self._position: Optional[dict] = None   # aktive Arb-Position

    def _detect_perp_symbol(self, symbol: str) -> str:
        base, quote = symbol.split("/")
        return f"{base}/{quote}:{quote}"   # Binance/Bybit USDT-M Format

    def evaluate(self, capital: float) -> FundingArbSignal:
        """Evaluiert ob eine Arb-Position geöffnet / gehalten / geschlossen werden soll."""
        try:
            spot_ticker = self.exchange_spot.fetch_ticker(self.symbol)
            spot_price  = float(spot_ticker["last"])
        except Exception as e:
            log.warning(f"FundingArb: Spot-Ticker Fehler: {e}")
            return FundingArbSignal(self.symbol, 0, 0, 0, 0, 0, "HOLD", f"Spot-Fehler: {e}")

        try:
            funding_info = self.exchange_perp.fetch_funding_rate(self.perp_symbol)
            funding_rate = float(funding_info.get("fundingRate", 0))
            perp_ticker  = self.exchange_perp.fetch_ticker(self.perp_symbol)
            perp_price   = float(perp_ticker["last"])
        except Exception as e:
            log.warning(f"FundingArb: Perp/Funding Fehler: {e}")
            return FundingArbSignal(self.symbol, 0, spot_price, spot_price, 0, 0, "HOLD", f"Perp-Fehler: {e}")

        basis_pct        = round((perp_price - spot_price) / spot_price * 100, 4)
        annual_yield_pct = round(funding_rate * ANNUALIZE_FACTOR * 100, 2)
        recommended_usdt = round(capital * self.max_pos_pct, 2)

        sig = FundingArbSignal(
            symbol=self.symbol,
            funding_rate=funding_rate,
            spot_price=spot_price,
            perp_price=perp_price,
            basis_pct=basis_pct,
            annual_yield_pct=annual_yield_pct,
            action="HOLD",
            recommended_usdt=recommended_usdt,
        )

        if self._position is None:
            if funding_rate >= self.min_rate:
                sig.action = "ENTER"
                sig.reason = (
                    f"Funding {funding_rate*100:.4f}%/8h "
                    f"= {annual_yield_pct:.1f}% p.a. > Mindest-Rate"
                )
                log.info(f"FundingArb ENTER: {sig.reason} | Basis: {basis_pct:+.3f}%")
            else:
                sig.reason = f"Funding {funding_rate*100:.4f}%/8h < Mindest-Rate {self.min_rate*100:.4f}%"
        else:
            entry_rate = self._position.get("funding_rate", 0)
            if funding_rate < 0:
                sig.action = "EXIT"
                sig.reason = "Negative Funding-Rate — Zinsvorteil umgekehrt"
                log.info(f"FundingArb EXIT: {sig.reason}")
            elif funding_rate < self.min_rate / 2:
                sig.action = "EXIT"
                sig.reason = f"Funding gesunken ({funding_rate*100:.4f}%/8h < halbe Mindest-Rate)"
                log.info(f"FundingArb EXIT: {sig.reason}")
            elif basis_pct < -0.5:
                sig.action = "EXIT"
                sig.reason = f"Basis-Spread negativ ({basis_pct:+.3f}%) — Konvergenz-Risiko"
                log.info(f"FundingArb EXIT: {sig.reason}")
            else:
                sig.reason = (
                    f"Position läuft | Funding: {funding_rate*100:.4f}%/8h | "
                    f"Basis: {basis_pct:+.3f}%"
                )

        return sig

    def open_position(self, sig: FundingArbSignal, dry_run: bool = True) -> dict:
        """Öffnet Spot-Long + Perp-Short (delta-neutral)."""
        usdt     = sig.recommended_usdt
        qty_spot = round(usdt / sig.spot_price, 6)
        qty_perp = round(usdt / sig.perp_price, 6)

        result = {
            "spot_order":  None,
            "perp_order":  None,
            "entry_rate":  sig.funding_rate,
            "funding_rate": sig.funding_rate,
            "spot_price":  sig.spot_price,
            "perp_price":  sig.perp_price,
        }

        if dry_run:
            log.info(
                f"FundingArb DRY-RUN OPEN: "
                f"Buy {qty_spot} {self.symbol} @ {sig.spot_price} | "
                f"Short {qty_perp} {self.perp_symbol} @ {sig.perp_price}"
            )
            result["spot_order"] = {"id": "dry_spot", "qty": qty_spot}
            result["perp_order"] = {"id": "dry_perp", "qty": qty_perp}
        else:
            try:
                result["spot_order"] = self.exchange_spot.create_market_buy_order(
                    self.symbol, qty_spot
                )
                result["perp_order"] = self.exchange_perp.create_market_sell_order(
                    self.perp_symbol, qty_perp
                )
            except Exception as e:
                log.error(f"FundingArb OPEN fehlgeschlagen: {e}")
                return result

        self._position = result
        return result

    def close_position(self, dry_run: bool = True) -> dict:
        """Schließt Spot-Long + Perp-Short."""
        if not self._position:
            return {"error": "Keine aktive Position"}

        if dry_run:
            log.info("FundingArb DRY-RUN CLOSE")
            self._position = None
            return {"status": "closed_dry_run"}

        try:
            spot_qty = float(
                (self._position.get("spot_order") or {}).get("qty", 0) or
                (self._position.get("spot_order") or {}).get("amount", 0)
            )
            perp_qty = float(
                (self._position.get("perp_order") or {}).get("qty", 0) or
                (self._position.get("perp_order") or {}).get("amount", 0)
            )
            result = {}
            if spot_qty > 0:
                result["spot_close"] = self.exchange_spot.create_market_sell_order(
                    self.symbol, spot_qty
                )
            if perp_qty > 0:
                result["perp_close"] = self.exchange_perp.create_market_buy_order(
                    self.perp_symbol, perp_qty
                )
            self._position = None
            return result
        except Exception as e:
            log.error(f"FundingArb CLOSE fehlgeschlagen: {e}")
            return {"error": str(e)}

    @property
    def has_position(self) -> bool:
        return self._position is not None


def get_annual_yield(funding_rate_per_8h: float) -> float:
    return round(funding_rate_per_8h * ANNUALIZE_FACTOR * 100, 2)
