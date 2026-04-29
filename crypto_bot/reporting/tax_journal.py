"""
FIFO Trade-Journal für DE/AT Steuer.

Berechnet realisierte Gewinne/Verluste nach dem FIFO-Prinzip
(First In, First Out) — konform mit §20 EStG (DE) / §27 EStG (AT).

Features:
  - FIFO-Kostenbasis pro Symbol
  - Haltedauer-Tracking (Kurz- vs. Langfristig)
  - CSV-Export für ELSTER / BMF-Meldung (DE)
  - AT-Format (ebenfalls CSV)
  - API-Endpoint: GET /api/tax/journal

Nutzung:
    journal = TaxJournal()
    journal.add_buy("BTC/USDT", qty=0.1, price=50000, fee=5.0, date="2025-01-15")
    journal.add_sell("BTC/USDT", qty=0.1, price=60000, fee=6.0, date="2025-06-20")
    report = journal.get_report()
    journal.export_csv("steuer_2025.csv")
"""
from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

LONG_TERM_DAYS = 365   # DE: 1 Jahr Haltefrist für Steuerfreiheit (Privatperson)


@dataclass
class Lot:
    """Ein einzelnes Kaufpaket (FIFO-Lot)."""
    symbol:    str
    qty:       float
    price:     float
    fee:       float
    buy_date:  date
    remaining: float = 0.0

    def __post_init__(self):
        self.remaining = self.qty

    @property
    def cost_basis(self) -> float:
        return self.price * self.qty + self.fee

    @property
    def cost_per_unit(self) -> float:
        return (self.price + self.fee / self.qty) if self.qty > 0 else 0.0


@dataclass
class TaxableTrade:
    """Eine realisierte Steuerpflicht."""
    symbol:      str
    qty:         float
    buy_date:    date
    sell_date:   date
    buy_price:   float
    sell_price:  float
    buy_fee:     float
    sell_fee:    float
    gain_loss:   float          # positiv = Gewinn, negativ = Verlust
    holding_days: int
    long_term:   bool           # True = steuerfrei in DE (>1 Jahr)

    @property
    def net_proceeds(self) -> float:
        return self.sell_price * self.qty - self.sell_fee

    @property
    def cost_basis(self) -> float:
        return self.buy_price * self.qty + self.buy_fee


class TaxJournal:
    """FIFO-konformes Trade-Journal für DE/AT Steuer."""

    def __init__(self):
        self._lots:   dict[str, deque[Lot]] = defaultdict(deque)
        self._trades: list[TaxableTrade]    = []

    def add_buy(
        self,
        symbol: str,
        qty:    float,
        price:  float,
        fee:    float = 0.0,
        dt:     str | date | datetime = "",
    ) -> Lot:
        buy_date = _parse_date(dt)
        lot = Lot(symbol=symbol, qty=qty, price=price, fee=fee, buy_date=buy_date)
        self._lots[symbol].append(lot)
        log.debug(f"TaxJournal BUY: {qty} {symbol} @ {price} ({buy_date})")
        return lot

    def add_sell(
        self,
        symbol: str,
        qty:    float,
        price:  float,
        fee:    float = 0.0,
        dt:     str | date | datetime = "",
    ) -> list[TaxableTrade]:
        sell_date  = _parse_date(dt)
        remaining  = qty
        new_trades = []
        lots       = self._lots[symbol]

        if not lots:
            log.warning(f"TaxJournal: Verkauf ohne passenden Kauflot — {qty} {symbol}")
            return []

        while remaining > 1e-9 and lots:
            lot = lots[0]
            used = min(lot.remaining, remaining)

            fee_portion = fee * (used / qty)
            buy_fee_portion = lot.fee * (used / lot.qty) if lot.qty > 0 else 0.0

            proceeds   = price * used - fee_portion
            cost       = lot.price * used + buy_fee_portion
            gain_loss  = round(proceeds - cost, 4)
            hold_days  = (sell_date - lot.buy_date).days

            trade = TaxableTrade(
                symbol=symbol,
                qty=used,
                buy_date=lot.buy_date,
                sell_date=sell_date,
                buy_price=lot.price,
                sell_price=price,
                buy_fee=buy_fee_portion,
                sell_fee=fee_portion,
                gain_loss=gain_loss,
                holding_days=hold_days,
                long_term=hold_days >= LONG_TERM_DAYS,
            )
            self._trades.append(trade)
            new_trades.append(trade)

            lot.remaining -= used
            remaining     -= used
            if lot.remaining < 1e-9:
                lots.popleft()

        if remaining > 1e-9:
            log.warning(f"TaxJournal: {remaining} {symbol} verkauft ohne vollständigen Kauflot")

        return new_trades

    def get_report(self, year: Optional[int] = None) -> dict:
        trades = self._trades
        if year:
            trades = [t for t in trades if t.sell_date.year == year]

        taxable  = [t for t in trades if not t.long_term]
        exempt   = [t for t in trades if t.long_term]

        total_gain    = round(sum(t.gain_loss for t in taxable if t.gain_loss > 0), 2)
        total_loss    = round(sum(t.gain_loss for t in taxable if t.gain_loss < 0), 2)
        net_taxable   = round(sum(t.gain_loss for t in taxable), 2)
        net_exempt    = round(sum(t.gain_loss for t in exempt),  2)

        by_symbol: dict[str, dict] = {}
        for t in taxable:
            s = t.symbol
            if s not in by_symbol:
                by_symbol[s] = {"trades": 0, "gain": 0.0, "loss": 0.0, "net": 0.0}
            by_symbol[s]["trades"] += 1
            if t.gain_loss >= 0:
                by_symbol[s]["gain"] += t.gain_loss
            else:
                by_symbol[s]["loss"] += t.gain_loss
            by_symbol[s]["net"] = round(by_symbol[s]["gain"] + by_symbol[s]["loss"], 2)

        return {
            "year":           year or "all",
            "trades_total":   len(trades),
            "trades_taxable": len(taxable),
            "trades_exempt":  len(exempt),
            "total_gain":     total_gain,
            "total_loss":     total_loss,
            "net_taxable":    net_taxable,
            "net_exempt":     net_exempt,
            "by_symbol":      by_symbol,
            "trades":         [_trade_to_dict(t) for t in trades],
        }

    def export_csv(self, path: str | Path, year: Optional[int] = None, fmt: str = "de") -> str:
        """
        Exportiert als CSV.
        fmt="de" → ELSTER-kompatibles Format
        fmt="at" → Österreich BMF-Format
        Gibt CSV-String zurück (für API-Download).
        """
        report = self.get_report(year)
        trades = report["trades"]

        output = io.StringIO()
        if fmt == "at":
            fields = ["Kauf-Datum", "Verkauf-Datum", "Symbol", "Menge",
                      "Kaufpreis", "Verkaufspreis", "Kaufgebühr", "Verkaufsgebühr",
                      "Haltedauer (Tage)", "Gewinn/Verlust (€)", "Langfristig"]
        else:
            fields = ["Kaufdatum", "Verkaufsdatum", "Bezeichnung", "Menge",
                      "Kaufkurs", "Veräußerungspreis", "Kaufnebenkosten",
                      "Veräußerungskosten", "Haltedauer (Tage)", "Gewinn/Verlust",
                      "Steuerfrei (§23 EStG)"]

        writer = csv.DictWriter(output, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for t in trades:
            if fmt == "at":
                writer.writerow({
                    "Kauf-Datum":          t["buy_date"],
                    "Verkauf-Datum":       t["sell_date"],
                    "Symbol":              t["symbol"],
                    "Menge":               t["qty"],
                    "Kaufpreis":           t["buy_price"],
                    "Verkaufspreis":       t["sell_price"],
                    "Kaufgebühr":          t["buy_fee"],
                    "Verkaufsgebühr":      t["sell_fee"],
                    "Haltedauer (Tage)":   t["holding_days"],
                    "Gewinn/Verlust (€)":  t["gain_loss"],
                    "Langfristig":         "Ja" if t["long_term"] else "Nein",
                })
            else:
                writer.writerow({
                    "Kaufdatum":           t["buy_date"],
                    "Verkaufsdatum":       t["sell_date"],
                    "Bezeichnung":         t["symbol"],
                    "Menge":               t["qty"],
                    "Kaufkurs":            t["buy_price"],
                    "Veräußerungspreis":   t["sell_price"],
                    "Kaufnebenkosten":     t["buy_fee"],
                    "Veräußerungskosten":  t["sell_fee"],
                    "Haltedauer (Tage)":   t["holding_days"],
                    "Gewinn/Verlust":      t["gain_loss"],
                    "Steuerfrei (§23 EStG)": "Ja" if t["long_term"] else "Nein",
                })

        csv_str = output.getvalue()
        if path:
            Path(path).write_text(csv_str, encoding="utf-8-sig")
            log.info(f"TaxJournal: CSV exportiert nach {path}")
        return csv_str

    def load_from_db(self, db_path: str = "crypto_bot/logs/trades.db") -> int:
        """Lädt abgeschlossene Trades aus der SQLite-DB und befüllt das Journal."""
        import sqlite3
        loaded = 0
        try:
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM trades WHERE exit_price IS NOT NULL ORDER BY entry_time ASC"
            ).fetchall()
            con.close()
            for r in rows:
                symbol    = r["symbol"]
                qty       = float(r["quantity"] or 0)
                entry_p   = float(r["entry_price"] or 0)
                exit_p    = float(r["exit_price"] or 0)
                fee       = float(r.get("fee") or 0)
                entry_dt  = r["entry_time"] or ""
                exit_dt   = r["exit_time"]  or ""
                self.add_buy(symbol,  qty, entry_p, fee / 2, entry_dt)
                self.add_sell(symbol, qty, exit_p,  fee / 2, exit_dt)
                loaded += 1
        except Exception as e:
            log.warning(f"TaxJournal DB-Fehler: {e}")
        return loaded


# ── Singleton ──────────────────────────────────────────────────────────────────
_journal: Optional[TaxJournal] = None


def get_tax_journal() -> TaxJournal:
    global _journal
    if _journal is None:
        _journal = TaxJournal()
    return _journal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(dt) -> date:
    if isinstance(dt, datetime):
        return dt.date()
    if isinstance(dt, date):
        return dt
    if isinstance(dt, str) and dt:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt[:19], fmt).date()
            except ValueError:
                continue
    return date.today()


def _trade_to_dict(t: TaxableTrade) -> dict:
    return {
        "symbol":        t.symbol,
        "qty":           t.qty,
        "buy_date":      str(t.buy_date),
        "sell_date":     str(t.sell_date),
        "buy_price":     t.buy_price,
        "sell_price":    t.sell_price,
        "buy_fee":       round(t.buy_fee, 4),
        "sell_fee":      round(t.sell_fee, 4),
        "gain_loss":     t.gain_loss,
        "holding_days":  t.holding_days,
        "long_term":     t.long_term,
        "net_proceeds":  round(t.net_proceeds, 4),
        "cost_basis":    round(t.cost_basis, 4),
    }
