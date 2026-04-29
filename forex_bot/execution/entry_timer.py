"""
Entry Timer — M5/M15 Pullback-basiertes Entry-Timing.

Problem:    H1-Close als Entry → 5–15 Pip Slippage durch ungenaue Entries.
Lösung:     H1-Signal generieren → M15/M5 Pullback auf EMA20 abwarten
            → präziserer Einstieg, engerer SL, besseres RR.

Ablauf:
  1. H1-Signal: BUY bei bullishem Regime
  2. Entry-Timer holt M15-Candles (letzte 30)
  3. Sucht Pullback: Close nähert sich EMA20 von oben (BUY) oder unten (SELL)
  4. Wenn Pullback innerhalb PULLBACK_PIPS_TOLERANCE → Entry-Preis refinieren
  5. Stop-Loss auf letztes M15-Low (BUY) / M15-High (SELL) setzen → enger

Modes:
  IMMEDIATE:   Kein Warten, sofort zum H1-Preis (Fallback)
  PULLBACK:    Warte auf M15-EMA20-Pullback
  LIMIT:       Setze Limit-Order auf Pullback-Level (asynchron)

Wenn kein Pullback innerhalb MAX_WAIT_CANDLES M15-Candles → IMMEDIATE fallback.

Usage:
    from forex_bot.execution.entry_timer import get_refined_entry
    result = get_refined_entry(client, instrument, direction, h1_signal)
    if result.should_use:
        entry = result.entry_price
        sl    = result.stop_loss
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

log = logging.getLogger("forex_bot")

# Konfiguration
PULLBACK_TIMEFRAME      = "M15"
PULLBACK_CANDLES        = 30          # Letzte 30 M15-Candles prüfen
EMA_PERIOD              = 20
PULLBACK_PIPS_TOLERANCE = 5.0        # Max Abstand von EMA20 für Pullback
MAX_WAIT_CANDLES        = 3          # Nach N Candles ohne Pullback → IMMEDIATE
SL_BUFFER_PIPS          = 2.0        # Buffer über/unter M15-Wick


@dataclass
class EntryResult:
    entry_price:  float
    stop_loss:    float
    mode:         str    # "pullback" | "immediate"
    improvement:  float  # Verbesserung in Pips vs. H1-Entry
    reason:       str


def _pip_size(instrument: str) -> float:
    return 0.01 if "JPY" in instrument else 0.0001


def _pips(diff: float, instrument: str) -> float:
    return diff / _pip_size(instrument)


def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def get_refined_entry(
    client:          object,   # OandaClient
    instrument:      str,
    direction:       str,      # "BUY" | "SELL"
    h1_entry:        float,
    h1_stop_loss:    float,
) -> EntryResult:
    """
    Verfeinert Entry auf Basis von M15-Pullback-Analyse.

    Parameters
    ----------
    client:       OandaClient-Instanz
    instrument:   z.B. "EUR_USD"
    direction:    "BUY" | "SELL"
    h1_entry:     Vorberechneter H1-Entry-Preis
    h1_stop_loss: Vorberechneter H1-Stop-Loss

    Returns
    -------
    EntryResult — nutze entry_price + stop_loss für Order
    """
    pip = _pip_size(instrument)

    try:
        candles = client.get_candles(instrument, PULLBACK_TIMEFRAME, count=PULLBACK_CANDLES)
        if len(candles) < EMA_PERIOD + 5:
            return EntryResult(
                entry_price=h1_entry, stop_loss=h1_stop_loss,
                mode="immediate", improvement=0.0,
                reason="Zu wenig M15-Candles",
            )

        df = pd.DataFrame(candles)
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)

        closes = df["close"]
        highs  = df["high"]
        lows   = df["low"]
        ema20  = _compute_ema(closes, EMA_PERIOD)

        last_close = float(closes.iloc[-1])
        last_ema   = float(ema20.iloc[-1])
        last_low   = float(lows.iloc[-1])
        last_high  = float(highs.iloc[-1])

        dist_pips  = _pips(abs(last_close - last_ema), instrument)

        if direction == "BUY":
            # Pullback: Kurs nähert sich EMA20 von oben
            pullback_ok = (
                last_close >= last_ema and          # Close noch über EMA
                dist_pips <= PULLBACK_PIPS_TOLERANCE  # Nah genug am EMA
            )
            if pullback_ok:
                # Entry nahe EMA20, leicht darüber
                refined_entry = round(last_ema + pip * 1.0, 5)
                # SL: Unter letztem M15-Low + Buffer
                refined_sl = round(last_low - pip * SL_BUFFER_PIPS, 5)

                improvement = _pips(h1_entry - refined_entry, instrument)
                log.info(
                    f"{instrument}: M15 Pullback Entry — "
                    f"EMA20={last_ema:.5f} | "
                    f"refined={refined_entry:.5f} vs H1={h1_entry:.5f} "
                    f"({improvement:+.1f} Pips)"
                )
                return EntryResult(
                    entry_price=refined_entry,
                    stop_loss=max(refined_sl, h1_stop_loss),  # Nie weiter als H1-SL
                    mode="pullback",
                    improvement=improvement,
                    reason=f"M15 Pullback zu EMA20 ({dist_pips:.1f} Pip Abstand)",
                )

        elif direction == "SELL":
            # Pullback: Kurs nähert sich EMA20 von unten
            pullback_ok = (
                last_close <= last_ema and
                dist_pips <= PULLBACK_PIPS_TOLERANCE
            )
            if pullback_ok:
                refined_entry = round(last_ema - pip * 1.0, 5)
                refined_sl    = round(last_high + pip * SL_BUFFER_PIPS, 5)

                improvement = _pips(refined_entry - h1_entry, instrument)
                log.info(
                    f"{instrument}: M15 Pullback Entry (SELL) — "
                    f"EMA20={last_ema:.5f} | "
                    f"refined={refined_entry:.5f} ({improvement:+.1f} Pips)"
                )
                return EntryResult(
                    entry_price=refined_entry,
                    stop_loss=min(refined_sl, h1_stop_loss),
                    mode="pullback",
                    improvement=improvement,
                    reason=f"M15 Pullback zu EMA20 ({dist_pips:.1f} Pip Abstand)",
                )

        # Kein Pullback gefunden → sofortiger Einstieg
        log.debug(
            f"{instrument}: Kein M15-Pullback (dist={dist_pips:.1f} Pips) → IMMEDIATE"
        )
        return EntryResult(
            entry_price=h1_entry, stop_loss=h1_stop_loss,
            mode="immediate", improvement=0.0,
            reason=f"Kein Pullback (EMA-Abstand {dist_pips:.1f} Pips > Toleranz {PULLBACK_PIPS_TOLERANCE})",
        )

    except Exception as e:
        log.debug(f"Entry Timer [{instrument}]: {e}")
        return EntryResult(
            entry_price=h1_entry, stop_loss=h1_stop_loss,
            mode="immediate", improvement=0.0,
            reason=f"Entry Timer Fehler: {e}",
        )
