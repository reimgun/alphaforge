"""
Trailing Take-Profit Manager — Dynamisches TP-Trailing bei starken Trends.

Problem:    Statischer TP entgeht dem Bot 2×–3× des ursprünglichen TP
            bei starken Trendbewegungen (ADX > 35).

Lösung:
  Phase 1 — Normal:     Statisches TP (wie bisher)
  Phase 2 — Trending:   Wenn ADX > 35 UND Profit > 50% von TP-Distanz:
                        → TP wird auf ATR-Trail umgestellt
  Phase 3 — Trail:      Jede neue Candle: Trail-TP = Highest High - 1.5×ATR (BUY)
                                          Trail-TP = Lowest Low  + 1.5×ATR (SELL)

SL-Breakeven:
  Wenn Profit > 50% der ursprünglichen TP-Distanz → SL auf Breakeven setzen.
  Danach: SL folgt dem Trail-TP mit fixem Abstand.

Integration in bot.py (_update_trailing_stop bereits vorhanden):
  TrailingTPManager.update() wird pro Zyklus pro offenem Trade aufgerufen.

Usage:
    from forex_bot.risk.trailing_tp import TrailingTPManager
    mgr = TrailingTPManager()
    update = mgr.update(trade, df_current)
    if update.new_tp:
        client.modify_take_profit(trade.trade_id, update.new_tp)
    if update.new_sl:
        client.modify_stop_loss(trade.trade_id, update.new_sl)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

# Konfiguration
ADX_THRESHOLD       = 35.0   # Mindest-ADX für Trail-Aktivierung
TRAIL_ATR_MULT      = 1.5    # Trail-Abstand = 1.5 × ATR
BREAKEVEN_TRIGGER   = 0.50   # Profit > 50% von TP-Distanz → SL auf Breakeven
ATR_PERIOD          = 14


@dataclass
class TPUpdate:
    new_tp:        float | None   # Neues Take-Profit Level (None = keine Änderung)
    new_sl:        float | None   # Neues Stop-Loss Level (None = keine Änderung)
    mode:          str            # "static" | "trailing" | "breakeven"
    reason:        str
    trail_distance: float = 0.0  # Aktueller Trail-Abstand in Pips


def _compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Berechnet ADX aus OHLC DataFrame."""
    try:
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)

        dm_up   = high.diff()
        dm_down = -low.diff()
        dm_plus  = dm_up.where((dm_up > dm_down) & (dm_up > 0), 0.0)
        dm_minus = dm_down.where((dm_down > dm_up) & (dm_down > 0), 0.0)

        prev_c = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_c).abs(),
            (low  - prev_c).abs(),
        ], axis=1).max(axis=1)

        atr14   = tr.ewm(span=period, adjust=False).mean()
        di_plus  = 100 * dm_plus.ewm(span=period, adjust=False).mean()  / (atr14 + 1e-10)
        di_minus = 100 * dm_minus.ewm(span=period, adjust=False).mean() / (atr14 + 1e-10)

        dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus + 1e-10)
        adx = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
        return round(adx, 2)
    except Exception:
        return 0.0


def _compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Aktueller ATR-Wert."""
    try:
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_c = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_c).abs(),
            (low  - prev_c).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
    except Exception:
        return 0.0


class TrailingTPManager:
    """
    Verwaltet dynamisches TP-Trailing pro Trade.

    State wird in-memory gehalten (Trade-ID → State).
    Bei Bot-Restart zurückgesetzt → erneute Aktivierung beim nächsten Zyklus.
    """

    def __init__(self):
        self._states: dict[str, dict] = {}

    def update(
        self,
        trade:      Any,   # ForexTrade mit .trade_id, .direction, .entry_price, .stop_loss, .take_profit
        df:         pd.DataFrame,
    ) -> TPUpdate:
        """
        Berechnet neue TP/SL-Level für einen offenen Trade.

        Parameters
        ----------
        trade: Offener Trade (ForexTrade)
        df:    Aktuelle H1 OHLC DataFrame (mind. 20 Candles)

        Returns
        -------
        TPUpdate mit optionalen neuen Levels
        """
        if len(df) < ATR_PERIOD + 5:
            return TPUpdate(new_tp=None, new_sl=None, mode="static", reason="Zu wenig Candles")

        trade_id     = getattr(trade, "trade_id", str(id(trade)))
        direction    = getattr(trade, "direction", "BUY")
        entry_price  = float(getattr(trade, "entry_price", 0.0))
        orig_sl      = float(getattr(trade, "stop_loss", 0.0))
        orig_tp      = float(getattr(trade, "take_profit", 0.0))
        instrument   = getattr(trade, "instrument", "")
        pip          = 0.01 if "JPY" in instrument else 0.0001

        current_price = float(df["close"].iloc[-1])
        atr           = _compute_atr(df)
        adx           = _compute_adx(df)

        # State initialisieren
        if trade_id not in self._states:
            self._states[trade_id] = {
                "mode":            "static",
                "best_price":      current_price,
                "breakeven_set":   False,
                "trail_tp":        orig_tp,
            }

        state = self._states[trade_id]
        state["best_price"] = (
            max(state["best_price"], current_price) if direction == "BUY"
            else min(state["best_price"], current_price)
        )

        # Profit berechnen
        if direction == "BUY":
            current_profit = current_price - entry_price
            tp_distance    = orig_tp - entry_price
        else:
            current_profit = entry_price - current_price
            tp_distance    = entry_price - orig_tp

        profit_ratio = current_profit / tp_distance if tp_distance > 0 else 0.0
        trail_distance = atr * TRAIL_ATR_MULT

        new_sl: float | None = None
        new_tp: float | None = None

        # ── Breakeven SL ──────────────────────────────────────────────────────
        if profit_ratio >= BREAKEVEN_TRIGGER and not state["breakeven_set"]:
            if direction == "BUY":
                be_sl = round(entry_price + pip * 2, 5)   # 2 Pips über Breakeven
                if be_sl > orig_sl:
                    new_sl = be_sl
                    state["breakeven_set"] = True
                    log.info(
                        f"TrailingTP [{instrument}]: SL → Breakeven "
                        f"{be_sl:.5f} (Profit {profit_ratio:.0%})"
                    )
            else:
                be_sl = round(entry_price - pip * 2, 5)
                if be_sl < orig_sl:
                    new_sl = be_sl
                    state["breakeven_set"] = True
                    log.info(
                        f"TrailingTP [{instrument}]: SL → Breakeven "
                        f"{be_sl:.5f} (Profit {profit_ratio:.0%})"
                    )

        # ── Trail-TP aktivieren (ADX > Schwelle + ausreichend im Profit) ──────
        if adx >= ADX_THRESHOLD and profit_ratio >= BREAKEVEN_TRIGGER:
            state["mode"] = "trailing"

        if state["mode"] == "trailing":
            if direction == "BUY":
                # Trail: Highest-High minus ATR-Trail
                recent_high = float(df["high"].tail(5).max())
                trail_tp    = round(recent_high + trail_distance * 0.5, 5)
                # Trail-TP nur erhöhen (nie senken)
                if trail_tp > state["trail_tp"] and trail_tp > orig_tp:
                    state["trail_tp"] = trail_tp
                    new_tp = trail_tp
                    log.info(
                        f"TrailingTP [{instrument}] BUY: Trail-TP → {trail_tp:.5f} "
                        f"(ADX={adx:.1f}, Profit={profit_ratio:.0%})"
                    )
                    # SL mitziehen: Trail-TP - 2×ATR
                    if state["breakeven_set"]:
                        trail_sl = round(trail_tp - trail_distance * 2, 5)
                        if trail_sl > (new_sl or orig_sl):
                            new_sl = trail_sl

            else:  # SELL
                recent_low = float(df["low"].tail(5).min())
                trail_tp   = round(recent_low - trail_distance * 0.5, 5)
                if trail_tp < state["trail_tp"] and trail_tp < orig_tp:
                    state["trail_tp"] = trail_tp
                    new_tp = trail_tp
                    log.info(
                        f"TrailingTP [{instrument}] SELL: Trail-TP → {trail_tp:.5f} "
                        f"(ADX={adx:.1f}, Profit={profit_ratio:.0%})"
                    )
                    if state["breakeven_set"]:
                        trail_sl = round(trail_tp + trail_distance * 2, 5)
                        if trail_sl < (new_sl or orig_sl):
                            new_sl = trail_sl

        mode_str = state["mode"]
        trail_pips = trail_distance / pip if atr > 0 else 0.0

        if new_tp or new_sl:
            return TPUpdate(
                new_tp=new_tp, new_sl=new_sl,
                mode=mode_str,
                reason=f"ADX={adx:.1f} | Profit={profit_ratio:.0%} | Trail={trail_pips:.1f}Pips",
                trail_distance=trail_pips,
            )

        return TPUpdate(
            new_tp=None, new_sl=None,
            mode=mode_str,
            reason=f"Keine Anpassung (ADX={adx:.1f}, Profit={profit_ratio:.0%})",
            trail_distance=trail_pips,
        )

    def cleanup(self, closed_trade_ids: list[str]) -> None:
        """Bereinigt State für geschlossene Trades."""
        for tid in closed_trade_ids:
            self._states.pop(tid, None)
