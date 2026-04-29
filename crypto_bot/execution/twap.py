"""
TWAP Execution — Time-Weighted Average Price für große Orders.

Teilt eine große Order in N gleichgroße Slices auf, die über
`duration_minutes` Minuten verteilt ausgeführt werden.
Empfohlen für Orders > $10k um Slippage zu minimieren.

Nutzung:
    twap = TWAPExecutor(exchange, symbol, "BUY", total_usdt=15000,
                        slices=10, duration_minutes=30)
    result = twap.execute()
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class TWAPResult:
    symbol:       str
    side:         str
    total_usdt:   float
    slices:       int
    filled_slices: int       = 0
    avg_price:    float      = 0.0
    total_qty:    float      = 0.0
    total_cost:   float      = 0.0
    orders:       list       = field(default_factory=list)
    errors:       list       = field(default_factory=list)
    success:      bool       = False

    @property
    def avg_slippage_bps(self) -> float:
        if not self.orders:
            return 0.0
        ref = self.orders[0].get("price", self.avg_price)
        if ref == 0:
            return 0.0
        return round((self.avg_price - ref) / ref * 10000, 2)


class TWAPExecutor:
    """Führt eine große Order als TWAP (Time-Weighted Average Price) aus."""

    MIN_USDT    = 5_000    # Unter diesem Wert TWAP unnötig
    MAX_SLICES  = 50
    MIN_SLICES  = 2

    def __init__(
        self,
        exchange,           # ccxt Exchange-Instanz
        symbol:   str,
        side:     str,      # "BUY" oder "SELL"
        total_usdt: float,
        slices:   int   = 10,
        duration_minutes: float = 30.0,
        dry_run:  bool  = False,
    ):
        if side.upper() not in ("BUY", "SELL"):
            raise ValueError(f"side muss BUY oder SELL sein, nicht {side!r}")
        if slices < self.MIN_SLICES:
            slices = self.MIN_SLICES
        if slices > self.MAX_SLICES:
            slices = self.MAX_SLICES

        self.exchange         = exchange
        self.symbol           = symbol
        self.side             = side.upper()
        self.total_usdt       = total_usdt
        self.slices           = slices
        self.interval_seconds = (duration_minutes * 60) / slices
        self.dry_run          = dry_run

    def execute(self) -> TWAPResult:
        result = TWAPResult(
            symbol=self.symbol,
            side=self.side,
            total_usdt=self.total_usdt,
            slices=self.slices,
        )
        slice_usdt = self.total_usdt / self.slices

        log.info(
            f"TWAP START: {self.side} {self.symbol} | "
            f"${self.total_usdt:,.0f} in {self.slices} Slices "
            f"à ${slice_usdt:,.0f} | Intervall: {self.interval_seconds:.0f}s"
        )

        for i in range(self.slices):
            try:
                ticker = self.exchange.fetch_ticker(self.symbol)
                price  = float(ticker["last"])
                qty    = round(slice_usdt / price, 6)

                if self.dry_run:
                    order = {
                        "id":     f"twap_dry_{i}",
                        "price":  price,
                        "amount": qty,
                        "cost":   slice_usdt,
                        "status": "dry_run",
                    }
                else:
                    if self.side == "BUY":
                        order = self.exchange.create_market_buy_order(self.symbol, qty)
                    else:
                        order = self.exchange.create_market_sell_order(self.symbol, qty)

                filled_price = float(order.get("average") or order.get("price") or price)
                filled_qty   = float(order.get("filled") or order.get("amount") or qty)

                result.orders.append({
                    "slice":  i + 1,
                    "price":  filled_price,
                    "qty":    filled_qty,
                    "cost":   round(filled_price * filled_qty, 2),
                    "id":     order.get("id", ""),
                })
                result.filled_slices += 1
                result.total_qty     += filled_qty
                result.total_cost    += filled_price * filled_qty

                log.info(
                    f"TWAP [{i+1}/{self.slices}]: {filled_qty:.6f} @ {filled_price:.2f} "
                    f"(${filled_price * filled_qty:,.2f})"
                )

            except Exception as e:
                err = f"Slice {i+1} fehlgeschlagen: {e}"
                result.errors.append(err)
                log.warning(f"TWAP {err}")

            if i < self.slices - 1:
                time.sleep(self.interval_seconds)

        if result.total_qty > 0:
            result.avg_price = round(result.total_cost / result.total_qty, 4)
            result.success   = result.filled_slices >= self.slices // 2

        log.info(
            f"TWAP ENDE: {result.filled_slices}/{self.slices} Slices | "
            f"Ø Preis: {result.avg_price:.4f} | "
            f"Gesamt: {result.total_qty:.6f} {self.symbol.split('/')[0]}"
        )
        return result


def should_use_twap(usdt_amount: float, threshold: float = 10_000.0) -> bool:
    return usdt_amount >= threshold
