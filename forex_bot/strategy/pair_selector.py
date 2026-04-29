"""
Pair Momentum Ranking & Capital Rotation — Tier 1.

Sortiert alle Instruments nach Signal-Stärke bevor der Bot iteriert.
Dadurch werden die stärksten 3 Setups gewählt, nicht die ersten in der
Konfigurationsliste — entscheidend wenn MAX_OPEN_TRADES < len(INSTRUMENTS).

Score-Faktoren (0.0–1.0):
  ADX Stärke     (35%): Trend-Stärke — ADX 50 = maximaler Score
  EMA Alignment  (30%): Perfekte EMA20/50/200 Ausrichtung
  RSI Momentum   (20%): Abstand RSI von 50 in Trend-Richtung
  EMA-Spread     (15%): Spreite EMA20−EMA50 relativ zu Preis

Session-Gewichtung: Score × session_quality_multiplier

Verwendung:
    ranked = rank_instruments(candles_map, regime_map, hour_utc=14)
    for instrument, score in ranked:
        ...   # bestes Setup zuerst
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("forex_bot")


# ── Technische Hilfsfunktionen ────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """ADX (Average Directional Index) aus OHLCV DataFrame."""
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


def score_instrument(
    df:         pd.DataFrame,
    instrument: str,
    regime:     str,
) -> float:
    """
    Berechnet den Momentum-Score für ein Instrument (0.0–1.0).

    SIDEWAYS / HIGH_VOLATILITY → stark reduzierter Score (Bot wählt Trend-Pairs zuerst).
    """
    try:
        closes = df["close"].astype(float)
        if len(closes) < 50:
            return 0.0

        price = float(closes.iloc[-1])
        if price <= 0:
            return 0.0

        # ── ADX Score (0–1) ──────────────────────────────────────────────────
        adx       = _compute_adx(df)
        adx_score = min(adx / 50.0, 1.0)   # ADX 50 → 1.0

        # ── EMA Alignment Score ───────────────────────────────────────────────
        ema20  = float(_ema(closes, 20).iloc[-1])
        ema50  = float(_ema(closes, 50).iloc[-1])
        ema200 = float(_ema(closes, 200).iloc[-1]) if len(df) >= 200 else ema50

        if regime == "TREND_UP":
            aligned = ema20 > ema50 > ema200
        elif regime == "TREND_DOWN":
            aligned = ema20 < ema50 < ema200
        else:
            aligned = False

        alignment_score = 0.85 if aligned else 0.25

        # ── RSI Momentum (Abstand von 50 in Trend-Richtung) ──────────────────
        try:
            delta    = closes.diff()
            gain     = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
            loss     = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
            rs       = gain / (loss + 1e-10)
            rsi_val  = float((100 - 100 / (1 + rs)).iloc[-1])

            if regime == "TREND_UP":
                rsi_score = min(max(rsi_val - 50, 0) / 20.0, 1.0)
            elif regime == "TREND_DOWN":
                rsi_score = min(max(50 - rsi_val, 0) / 20.0, 1.0)
            else:
                rsi_score = 0.15
        except Exception:
            rsi_score = 0.15

        # ── EMA-Spread als % des Preises ──────────────────────────────────────
        spread_pct   = abs(ema20 - ema50) / price
        spread_score = min(spread_pct / 0.003, 1.0)   # 0.3% → 1.0

        # ── Gewichtete Kombination ────────────────────────────────────────────
        score = (
            adx_score       * 0.35 +
            alignment_score * 0.30 +
            rsi_score       * 0.20 +
            spread_score    * 0.15
        )

        # Nicht-Trend-Regime: stark reduzieren (für Mean Reversion bleibt Restscore)
        if regime in ("SIDEWAYS", "HIGH_VOLATILITY"):
            score *= 0.20

        return round(max(0.0, min(1.0, score)), 4)

    except Exception as e:
        log.debug(f"score_instrument {instrument}: {e}")
        return 0.0


def rank_instruments(
    candles_map: dict,
    regime_map:  dict,
    hour_utc:    Optional[int] = None,
) -> list[tuple[str, float]]:
    """
    Bewertet alle Instruments und gibt eine nach Score sortierte Liste zurück.

    Parameters
    ----------
    candles_map : {instrument: list[dict]}  — OHLCV-Candle-Listen
    regime_map  : {instrument: str}         — vorberechnete Regimes
    hour_utc    : aktuelle UTC-Stunde (für Session-Gewichtung)

    Returns
    -------
    list[(instrument, score)] sortiert absteigend nach Score
    """
    from forex_bot.execution.session_quality import session_quality

    scores: list[tuple[str, float]] = []

    for instrument, candles in candles_map.items():
        if not candles:
            scores.append((instrument, 0.0))
            continue
        try:
            df = pd.DataFrame(candles)
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype(float)

            regime = regime_map.get(instrument, "SIDEWAYS")
            score  = score_instrument(df, instrument, regime)

            # Session-Qualität als Multiplikator einrechnen
            if hour_utc is not None:
                sess_mult, _ = session_quality(instrument, hour_utc)
                score = round(score * sess_mult, 4)

            scores.append((instrument, score))
        except Exception as e:
            log.debug(f"rank_instruments {instrument}: {e}")
            scores.append((instrument, 0.0))

    scores.sort(key=lambda x: x[1], reverse=True)

    log.info(
        "Pair Ranking: " +
        " > ".join(f"{i}={s:.3f}" for i, s in scores[:5])
    )
    return scores
