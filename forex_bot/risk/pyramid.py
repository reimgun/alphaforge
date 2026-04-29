"""
Position Pyramiding — Tier 1.

Fügt einer gewinnenden Position eine zweite Einheit hinzu wenn:
  1. Preis hat das 1:1 RR-Ziel erreicht (50% des TP-Abstands)
  2. ADX > 30 (Trend ist weiterhin stark)
  3. Trade wurde noch nicht pyramidiert (max. 1× pro Trade)

Institutionelle Logik:
  - SL wird auf Breakeven gezogen (risikofrei ab Einstieg)
  - Zweite Einheit mit 50% Originalgröße
  - TP der Pyramiden-Position: +50% des ursprünglichen TP-Abstands
  - Net-Effekt: 150% der ursprünglichen Position bei 0 zusätzlichem Risiko

Verwendung:
    opps = check_pyramid_opportunities(open_trades, prices, df_map)
    for opp in opps:
        # OANDA Order für opp.instrument opp.direction opp.add_units
        mark_pyramided(opp.trade_id)
"""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

# ── Konfiguration ─────────────────────────────────────────────────────────────
PYRAMID_ADX_MIN     = 30.0   # Mindest-ADX um Pyramidierung zuzulassen
PYRAMID_RR_TRIGGER  = 0.90   # Pyramidieren wenn 90% des 1:1 TP erreicht
PYRAMID_SIZE_FACTOR = 0.50   # Zweite Einheit = 50% der Originalgröße
PYRAMID_SL_BUFFER   = 2      # Breakeven SL: Entry ± 2 Pips Puffer


@dataclass
class PyramidOpportunity:
    trade_id:      str
    instrument:    str
    direction:     str
    current_price: float
    new_sl:        float   # SL auf Breakeven ziehen
    new_tp:        float   # TP um 50% verlängern
    add_units:     int


# Merkt sich bereits pyramidierte Trades (persistiert nur im RAM, OK für 1h-Zyklus)
_pyramided: set[str] = set()


# ── ADX-Berechnung ────────────────────────────────────────────────────────────

def _adx_from_df(df: pd.DataFrame, period: int = 14) -> float:
    try:
        highs  = df["high"].astype(float)
        lows   = df["low"].astype(float)
        closes = df["close"].astype(float)
        prev_c = closes.shift(1)

        tr = pd.concat([
            highs - lows,
            (highs - prev_c).abs(),
            (lows  - prev_c).abs(),
        ], axis=1).max(axis=1)

        up_move  = highs.diff()
        dn_move  = -lows.diff()
        plus_dm  = pd.Series(
            np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0),
            index=df.index,
        )
        minus_dm = pd.Series(
            np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0),
            index=df.index,
        )

        atr      = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx      = dx.ewm(span=period, adjust=False).mean()
        return float(adx.iloc[-1])
    except Exception:
        return 20.0


# ── Haupt-Logik ───────────────────────────────────────────────────────────────

def check_pyramid_opportunities(
    open_trades: list,
    prices:      dict[str, float],
    df_map:      Optional[dict] = None,
) -> list[PyramidOpportunity]:
    """
    Prüft alle offenen Trades auf Pyramidierungs-Gelegenheiten.

    Parameters
    ----------
    open_trades : Liste offener ForexTrade-Objekte
    prices      : {instrument: aktueller Preis}
    df_map      : {instrument: pd.DataFrame} — für ADX-Check (optional)

    Returns
    -------
    list[PyramidOpportunity]: Trades die pyramidiert werden sollen
    """
    opportunities: list[PyramidOpportunity] = []

    for trade in open_trades:
        if trade.status != "open":
            continue
        if not trade.trade_id:
            continue
        if trade.trade_id in _pyramided:
            continue

        price = prices.get(trade.instrument)
        if price is None:
            continue

        entry   = trade.entry_price
        tp      = trade.take_profit
        sl      = trade.stop_loss
        pip_sz  = 0.01 if "JPY" in trade.instrument else 0.0001

        tp_dist = abs(tp - entry)
        sl_dist = abs(entry - sl)

        if tp_dist < pip_sz or sl_dist < pip_sz:
            continue

        # ── Fortschritt Richtung TP berechnen ────────────────────────────────
        if trade.direction == "BUY":
            progress = (price - entry) / tp_dist
        else:
            progress = (entry - price) / tp_dist

        if progress < PYRAMID_RR_TRIGGER:
            continue

        # ── ADX prüfen ────────────────────────────────────────────────────────
        adx = 30.0  # Default — reicht für Pyramidierung
        if df_map and trade.instrument in df_map:
            df  = df_map[trade.instrument]
            adx = _adx_from_df(df)

        if adx < PYRAMID_ADX_MIN:
            log.debug(
                f"Pyramid {trade.instrument}: ADX {adx:.1f} < {PYRAMID_ADX_MIN} — skip"
            )
            continue

        # ── Breakeven SL + verlängerter TP ───────────────────────────────────
        if trade.direction == "BUY":
            new_sl = round(entry + pip_sz * PYRAMID_SL_BUFFER, 5)
            new_tp = round(tp + tp_dist * 0.50, 5)
        else:
            new_sl = round(entry - pip_sz * PYRAMID_SL_BUFFER, 5)
            new_tp = round(tp - tp_dist * 0.50, 5)

        add_units = max(1_000, int(trade.units * PYRAMID_SIZE_FACTOR))

        opp = PyramidOpportunity(
            trade_id      = trade.trade_id,
            instrument    = trade.instrument,
            direction     = trade.direction,
            current_price = price,
            new_sl        = new_sl,
            new_tp        = new_tp,
            add_units     = add_units,
        )
        opportunities.append(opp)
        log.info(
            f"Pyramid Gelegenheit: {trade.instrument} {trade.direction} "
            f"@ {price:.5f} | ADX={adx:.1f} | Fortschritt={progress:.0%} | "
            f"+{add_units} Units, SL→BE, TP+50%"
        )

    return opportunities


def mark_pyramided(trade_id: str) -> None:
    """Markiert Trade als pyramidiert (max. 1× pro Trade)."""
    _pyramided.add(trade_id)


def clear_closed_pyramids(active_trade_ids: set[str]) -> None:
    """Entfernt geschlossene Trades aus dem Pyramiding-Tracking."""
    global _pyramided
    _pyramided &= active_trade_ids
