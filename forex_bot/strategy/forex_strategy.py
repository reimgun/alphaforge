"""
Forex-Strategie: EMA-Crossover + MACD + RSI.

Signal-Logik:
  BUY  wenn EMA20 > EMA50 > EMA200 (Aufwärtstrend)
         + EMA20 kreuzt EMA50 von unten
         + MACD-Histogramm positiv und steigend
         + RSI zwischen 40–65 (nicht überkauft)

  SELL umgekehrt.

  Kein Trade bei:
    - Aktiven High-Impact News (±30 Min.)
    - Außerhalb Trading-Session
    - Spread > 3 Pips
"""
import logging
from dataclasses import dataclass

import pandas as pd

log = logging.getLogger("forex_bot")


@dataclass
class ForexSignal:
    instrument:  str
    direction:   str       # "BUY" | "SELL" | "HOLD"
    entry_price: float
    stop_loss:   float
    take_profit: float
    atr:         float
    pips_sl:     float     # Pip-Abstand bis SL
    confidence:  float     # 0.0–1.0
    reason:      str


def compute_indicators(candles: list) -> pd.DataFrame:
    df = pd.DataFrame(candles).copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    # ── EMAs ──────────────────────────────────────────────────────────────────
    df["ema_fast"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["ema_slow"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema_trend"] = df["close"].ewm(span=200, adjust=False).mean()

    # ── RSI ───────────────────────────────────────────────────────────────────
    delta  = df["close"].diff()
    gain   = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

    # ── ATR ───────────────────────────────────────────────────────────────────
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = df["tr"].ewm(span=14, adjust=False).mean()

    # ── MACD ──────────────────────────────────────────────────────────────────
    ema12          = df["close"].ewm(span=12, adjust=False).mean()
    ema26          = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]     = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_h"]   = df["macd"] - df["macd_sig"]

    # ── Bollinger Bänder ──────────────────────────────────────────────────────
    df["bb_mid"]   = df["close"].rolling(20).mean()
    df["bb_std"]   = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    return df


def generate_signal(
    candles:        list,
    instrument:     str,
    atr_multiplier: float = 1.5,
    rr_ratio:       float = 2.0,
) -> ForexSignal:
    if len(candles) < 210:
        return ForexSignal(instrument, "HOLD", 0, 0, 0, 0, 0, 0.0, "Zu wenig Daten")

    df   = compute_indicators(candles)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price    = float(last["close"])
    atr      = float(last["atr"])
    pip_size = 0.01 if "JPY" in instrument else 0.0001

    # ── Trend ─────────────────────────────────────────────────────────────────
    bull_trend = (last["ema_fast"] > last["ema_slow"] > last["ema_trend"])
    bear_trend = (last["ema_fast"] < last["ema_slow"] < last["ema_trend"])

    # ── Crossover (EMA20 kreuzt EMA50) ────────────────────────────────────────
    bull_cross = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    bear_cross = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    # ── MACD Bestätigung ──────────────────────────────────────────────────────
    macd_bull = (last["macd_h"] > 0) and (last["macd_h"] > prev["macd_h"])
    macd_bear = (last["macd_h"] < 0) and (last["macd_h"] < prev["macd_h"])

    # ── RSI Filter ────────────────────────────────────────────────────────────
    rsi_buy_ok  = 40 < last["rsi"] < 65
    rsi_sell_ok = 35 < last["rsi"] < 60

    # ── Trend Pullback: kaufe/verkaufe Rücksetzer im bestehenden Trend ───────
    # Feuert viel öfter als der Crossover (der nur beim exakten Kreuzungs-Candle aktiv wird).
    # Logik: Trend klar ausgerichtet + Preis testet EMA20 als Support/Resistance + RSI-Dip
    price_near_ema20 = abs(price - float(last["ema_fast"])) < atr * 0.6
    bull_pullback = (
        bull_trend and price_near_ema20 and
        38 < last["rsi"] < 55 and last["macd_h"] > 0
    )
    bear_pullback = (
        bear_trend and price_near_ema20 and
        45 < last["rsi"] < 62 and last["macd_h"] < 0
    )

    # ── Signal berechnen ──────────────────────────────────────────────────────
    direction  = "HOLD"
    confidence = 0.0
    reason     = "Kein Signal"

    if bull_trend and bull_cross and macd_bull and rsi_buy_ok:
        direction  = "BUY"
        confidence = 0.58
        if last["rsi"] < 55:                         confidence += 0.10
        if last["macd_h"] > prev["macd_h"] * 1.5:   confidence += 0.05
        if price > last["bb_mid"]:                   confidence += 0.05
        reason = (
            f"EMA Crossover ↑ | Trend aufwärts | "
            f"RSI {last['rsi']:.0f} | MACD bullish"
        )

    elif bull_pullback and not bull_cross:
        direction  = "BUY"
        confidence = 0.52
        if last["rsi"] < 48:            confidence += 0.08
        if last["macd_h"] > 0:          confidence += 0.05
        if price < last["bb_mid"]:      confidence += 0.05
        reason = (
            f"Trend Pullback ↑ | EMA20-Test | "
            f"RSI {last['rsi']:.0f} | MACD positiv"
        )

    elif bear_trend and bear_cross and macd_bear and rsi_sell_ok:
        direction  = "SELL"
        confidence = 0.58
        if last["rsi"] > 45:        confidence += 0.10
        if price < last["bb_mid"]:  confidence += 0.05
        reason = (
            f"EMA Crossover ↓ | Trend abwärts | "
            f"RSI {last['rsi']:.0f} | MACD bearish"
        )

    elif bear_pullback and not bear_cross:
        direction  = "SELL"
        confidence = 0.52
        if last["rsi"] > 52:            confidence += 0.08
        if last["macd_h"] < 0:          confidence += 0.05
        if price > last["bb_mid"]:      confidence += 0.05
        reason = (
            f"Trend Pullback ↓ | EMA20-Test | "
            f"RSI {last['rsi']:.0f} | MACD negativ"
        )

    sl_dist = atr * atr_multiplier
    tp_dist = sl_dist * rr_ratio

    if direction == "BUY":
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        sl = price + sl_dist
        tp = price - tp_dist

    pips_sl = round(sl_dist / pip_size, 1)

    log.debug(
        f"{instrument} Signal: {direction} | conf={confidence:.2f} | "
        f"SL={pips_sl:.1f}pip | {reason}"
    )

    return ForexSignal(
        instrument  = instrument,
        direction   = direction,
        entry_price = round(price, 5),
        stop_loss   = round(sl, 5),
        take_profit = round(tp, 5),
        atr         = round(atr, 5),
        pips_sl     = pips_sl,
        confidence  = round(min(confidence, 1.0), 2),
        reason      = reason,
    )
