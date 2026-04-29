"""
Risk Parity Allocation — Inverse-Volatility Position Weighting.

Berechnet volatilitätsnormierte Gewichte über alle aktiven Forex-Pairs:
  w_i = (1 / vol_i) / Σ(1 / vol_j)

Ziel: Gleicher Risikobeitrag pro Instrument (gleiches ATR-Exposure).
Ohne Risk Parity dominieren hochvolatile Pairs (z.B. GBP/JPY) das Portfolio.

Verwendung in bot.py:
    rp_weights = compute_risk_parity_weights(df_cache)
    # rp_weights["EUR_USD"] = 0.18 → dieses Pair erhält 18% des Risikos
    # Normalisiert: Σ = 1.0, Durchschnitt = 1/N_pairs

    # Position Sizing:
    n = len(rp_weights)
    rp_factor = rp_weights.get(instrument, 1.0/n) * n   # = 1.0 im Durchschnitt
    adjusted_risk = mode.risk_per_trade * rp_factor
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")

ATR_PERIOD  = 14    # ATR-Lookback
MIN_CANDLES = 20    # Mindest-Candles für valide ATR
MIN_WEIGHT  = 0.05  # Mindestgewicht (5%) verhindert vollständiges Ignorieren


def _compute_atr_pct(df: pd.DataFrame) -> float:
    """Berechnet ATR als % des Close aus einem DataFrame."""
    try:
        closes = df["close"].astype(float)
        highs  = df["high"].astype(float)
        lows   = df["low"].astype(float)
        prev_c = closes.shift(1)

        tr  = pd.concat([
            highs - lows,
            (highs - prev_c).abs(),
            (lows  - prev_c).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=ATR_PERIOD, adjust=False).mean().iloc[-1]
        return float(atr) / (float(closes.iloc[-1]) + 1e-10)
    except Exception:
        return 0.001   # Fallback: 0.1%


def compute_risk_parity_weights(
    df_cache: Dict[str, pd.DataFrame],
) -> Dict[str, float]:
    """
    Berechnet inverse-volatility Gewichte für alle Instruments in df_cache.

    Parameters
    ----------
    df_cache: {instrument → DataFrame mit OHLC}

    Returns
    -------
    dict: {instrument → Gewicht (0.0–1.0), Summe = 1.0}
    """
    if not df_cache:
        return {}

    vols: Dict[str, float] = {}
    for instrument, df in df_cache.items():
        if len(df) < MIN_CANDLES:
            vols[instrument] = 0.001  # Fallback bei zu wenig Daten
        else:
            vols[instrument] = max(1e-6, _compute_atr_pct(df))

    # Inverse-Volatility Gewichte
    inv_vols = {instr: 1.0 / vol for instr, vol in vols.items()}
    total    = sum(inv_vols.values())

    if total <= 0:
        n = len(df_cache)
        return {instr: 1.0 / n for instr in df_cache}

    weights  = {instr: iv / total for instr, iv in inv_vols.items()}

    # Floor bei MIN_WEIGHT + Renormalisierung
    clamped = {instr: max(MIN_WEIGHT, w) for instr, w in weights.items()}
    ct      = sum(clamped.values())
    weights = {instr: round(w / ct, 4) for instr, w in clamped.items()}

    log.debug(
        f"Risk Parity Gewichte: "
        + ", ".join(f"{k}={v:.1%}" for k, v in sorted(weights.items(), key=lambda x: -x[1]))
    )
    return weights


def get_rp_sizing_factor(
    instrument: str,
    df_cache:   Dict[str, pd.DataFrame],
) -> float:
    """
    Gibt den Risk-Parity-Faktor für ein einzelnes Instrument zurück.
    Faktor = Gewicht × Anzahl_Instruments → Durchschnitt = 1.0

    So bleibt die Gesamtrisiko-Summe konstant, nur Umverteilung zwischen Pairs.

    Returns
    -------
    float: Faktor (typisch 0.3× bis 2.5×), 1.0 = Durchschnitt
    """
    if not df_cache:
        return 1.0
    weights = compute_risk_parity_weights(df_cache)
    n       = len(weights)
    w       = weights.get(instrument, 1.0 / n if n > 0 else 1.0)
    return round(w * n, 3)
