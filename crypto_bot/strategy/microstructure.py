"""
Market Microstructure Intelligence — Gap 1–7 (Round 8).

  CVDTracker:               Cumulative Volume Delta (Buy vs Sell Pressure)
  OrderbookImbalanceProxy:  Bid/Ask Imbalanz aus Level-1 Ticker-Daten
  LiquidityWallDetector:    Volumen-Clustering an runden Preisleveln
  SpooofingProxy:           Wick-Anomalie-Erkennung (Large Wick → schnelle Reversal)
  MicrostructureSignals:    Convenience-Wrapper

Feature-Flag: FEATURE_MICROSTRUCTURE=true|false
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")


# ── CVD Tracker ───────────────────────────────────────────────────────────────

@dataclass
class CVDResult:
    cvd:            float    # Kumulative Netto-Kaufvolumen (positiv = Kaufdruck)
    cvd_ma:         float    # Gleitender Durchschnitt CVD
    cvd_trend:      str      # "BULLISH" | "BEARISH" | "NEUTRAL"
    buy_pct:        float    # Anteil Kauf-Volumen (0–1)
    pressure:       str      # "BUY_PRESSURE" | "SELL_PRESSURE" | "BALANCED"


class CVDTracker:
    """
    Schätzt Buy/Sell-Volumen via Tick-Regel (OHLCV-Näherung):
      - close > prev_close → Kauf-Volumen
      - close < prev_close → Verkauf-Volumen
      - close == prev_close → neutral (50/50)
    """
    CVD_MA_PERIOD = 20

    def compute(self, df: pd.DataFrame) -> CVDResult:
        try:
            closes  = df["close"]
            volumes = df["volume"]

            # Tick-Regel: Preisrichtung → Volumen-Attribution
            delta_close = closes.diff()
            buy_vol  = volumes.where(delta_close > 0,  volumes * 0.5)
            sell_vol = volumes.where(delta_close < 0,  volumes * 0.5)
            buy_vol  = buy_vol.fillna(volumes * 0.5)
            sell_vol = sell_vol.fillna(volumes * 0.5)

            cvd = float((buy_vol - sell_vol).rolling(self.CVD_MA_PERIOD).sum().iloc[-1])
            cvd_ma = float((buy_vol - sell_vol).rolling(self.CVD_MA_PERIOD * 2).mean().iloc[-1])

            # Absoluter Buy-Anteil (letzte 20 Kerzen)
            recent_buy   = float(buy_vol.tail(20).sum())
            recent_total = float(volumes.tail(20).sum())
            buy_pct = recent_buy / recent_total if recent_total > 0 else 0.5

            if cvd > abs(cvd_ma) * 0.1:
                trend = "BULLISH"
            elif cvd < -abs(cvd_ma) * 0.1:
                trend = "BEARISH"
            else:
                trend = "NEUTRAL"

            pressure = (
                "BUY_PRESSURE"  if buy_pct > 0.55 else
                "SELL_PRESSURE" if buy_pct < 0.45 else
                "BALANCED"
            )

            return CVDResult(
                cvd       = round(cvd, 2),
                cvd_ma    = round(cvd_ma, 2),
                cvd_trend = trend,
                buy_pct   = round(buy_pct, 3),
                pressure  = pressure,
            )
        except Exception as e:
            log.debug(f"CVDTracker Fehler: {e}")
            return CVDResult(0.0, 0.0, "NEUTRAL", 0.5, "BALANCED")


# ── Orderbook Imbalance Proxy ─────────────────────────────────────────────────

@dataclass
class ImbalanceResult:
    imbalance_ratio: float   # (bid_vol - ask_vol) / total  — positiv = Kaufdruck
    direction:       str     # "BID_HEAVY" | "ASK_HEAVY" | "BALANCED"
    strength:        str     # "STRONG" | "MODERATE" | "WEAK"


class OrderbookImbalanceProxy:
    """
    Schätzt Orderbook-Imbalanz aus OHLCV-Daten:
      Position des Close innerhalb der HL-Range = impliziter Bid/Ask-Druck.
      Close nahe High → Bid-Heavy (Käufer dominieren)
      Close nahe Low  → Ask-Heavy (Verkäufer dominieren)
    """
    STRONG_THRESHOLD   = 0.70   # Close > 70% der Range → stark bid-heavy
    MODERATE_THRESHOLD = 0.55

    def compute(self, df: pd.DataFrame) -> ImbalanceResult:
        try:
            high  = df["high"].tail(10)
            low   = df["low"].tail(10)
            close = df["close"].tail(10)

            hl_range = high - low
            # Position des Close: 0 = am Low, 1 = am High
            close_position = (close - low) / hl_range.replace(0, np.nan)
            avg_position   = float(close_position.mean())

            imbalance = (avg_position - 0.5) * 2   # Normalisiert: -1 bis +1

            direction = (
                "BID_HEAVY"  if avg_position > self.MODERATE_THRESHOLD else
                "ASK_HEAVY"  if avg_position < 1 - self.MODERATE_THRESHOLD else
                "BALANCED"
            )
            strength = (
                "STRONG"   if abs(avg_position - 0.5) > (self.STRONG_THRESHOLD - 0.5) else
                "MODERATE" if abs(avg_position - 0.5) > (self.MODERATE_THRESHOLD - 0.5) else
                "WEAK"
            )

            return ImbalanceResult(round(imbalance, 3), direction, strength)
        except Exception as e:
            log.debug(f"ImbalanceProxy Fehler: {e}")
            return ImbalanceResult(0.0, "BALANCED", "WEAK")


# ── Liquidity Wall Detector ───────────────────────────────────────────────────

@dataclass
class LiquidityWall:
    price_level:  float
    relative_vol: float   # Volumen dieser Kerze relativ zum Durchschnitt
    direction:    str     # "SUPPORT" | "RESISTANCE"


class LiquidityWallDetector:
    """
    Erkennt Liquidity Walls — Preislevels mit überdurchschnittlichem Volumen.
    Typisch für große Limit-Order-Cluster (Institutionelle Käufe/Verkäufe).
    """
    WALL_VOL_THRESHOLD = 2.5    # > 2.5× Durchschnittsvolumen = Liquidity Wall
    LOOKBACK           = 50

    def detect(self, df: pd.DataFrame) -> list[LiquidityWall]:
        try:
            recent = df.tail(self.LOOKBACK).copy()
            avg_vol = float(recent["volume"].mean())
            walls   = []

            for _, row in recent.iterrows():
                rel_vol = row["volume"] / avg_vol if avg_vol > 0 else 1.0
                if rel_vol >= self.WALL_VOL_THRESHOLD:
                    mid_price = (row["high"] + row["low"]) / 2
                    # Wall-Richtung: Kerze bullish → Support, bearish → Resistance
                    direction = "SUPPORT" if row["close"] >= row["open"] else "RESISTANCE"
                    walls.append(LiquidityWall(round(mid_price, 2), round(rel_vol, 2), direction))

            return sorted(walls, key=lambda w: w.relative_vol, reverse=True)[:3]
        except Exception as e:
            log.debug(f"LiquidityWallDetector Fehler: {e}")
            return []


# ── Spoofing Proxy ────────────────────────────────────────────────────────────

@dataclass
class SpoofingSignal:
    spoof_score:  float    # 0.0–1.0
    wick_ratio:   float    # Wick-Länge / Body-Länge
    is_suspicious: bool
    reason:        str


class SpoofingProxy:
    """
    Erkennt potenzielle Spoofing-Muster via Wick-Analyse:
      - Extrem langer Wick mit kleinem Body → möglicher Spoof
      - Wick > 3× Body-Größe + niedriges Volumen = verdächtig

    Kein echter Spoof-Beweis ohne Level-2 Daten — nur Proxy-Signal.
    """
    WICK_RATIO_THRESHOLD  = 3.0    # Wick > 3× Body
    LOW_VOL_THRESHOLD     = 0.5    # Volumen < 50% Durchschnitt

    def analyze(self, df: pd.DataFrame) -> SpoofingSignal:
        try:
            row      = df.iloc[-1]
            body     = abs(float(row["close"]) - float(row["open"]))
            wick_up  = float(row["high"])  - max(float(row["open"]), float(row["close"]))
            wick_dn  = min(float(row["open"]), float(row["close"])) - float(row["low"])
            max_wick = max(wick_up, wick_dn)

            wick_ratio = max_wick / body if body > 0 else 0.0

            vol_ratio = float(row["volume"]) / float(df["volume"].tail(20).mean()) \
                        if len(df) >= 20 else 1.0

            is_suspicious = (
                wick_ratio >= self.WICK_RATIO_THRESHOLD and
                vol_ratio  < self.LOW_VOL_THRESHOLD
            )

            spoof_score = min(1.0, max(0.0,
                (wick_ratio / self.WICK_RATIO_THRESHOLD) * 0.5 +
                (1 - vol_ratio) * 0.5
            )) if is_suspicious else 0.0

            reason = (
                f"Wick-Ratio {wick_ratio:.1f}× Body bei {vol_ratio:.0%} Volumen"
                if is_suspicious else "Kein Spoofing-Muster"
            )

            return SpoofingSignal(round(spoof_score, 3), round(wick_ratio, 2),
                                  is_suspicious, reason)
        except Exception as e:
            log.debug(f"SpoofingProxy Fehler: {e}")
            return SpoofingSignal(0.0, 0.0, False, "Fehler")


# ── Microstructure Signals (Wrapper) ─────────────────────────────────────────

@dataclass
class MicrostructureAnalysis:
    cvd:        CVDResult
    imbalance:  ImbalanceResult
    walls:      list[LiquidityWall]
    spoofing:   SpoofingSignal
    signal_bias: str       # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence:  float     # 0.0–1.0 (wie stark das Signal)


class MicrostructureSignals:
    """Wrapper — kombiniert alle Microstructure-Komponenten."""

    def __init__(self):
        self.cvd_tracker  = CVDTracker()
        self.imbalance    = OrderbookImbalanceProxy()
        self.wall_detector= LiquidityWallDetector()
        self.spoofing     = SpoofingProxy()

    def analyze(self, df: pd.DataFrame) -> MicrostructureAnalysis:
        cvd      = self.cvd_tracker.compute(df)
        imb      = self.imbalance.compute(df)
        walls    = self.wall_detector.detect(df)
        spoof    = self.spoofing.analyze(df)

        # Kombiniertes Signal
        bullish_score = 0.0
        bearish_score = 0.0

        if cvd.cvd_trend == "BULLISH":    bullish_score += 0.4
        elif cvd.cvd_trend == "BEARISH":  bearish_score += 0.4
        if imb.direction == "BID_HEAVY":  bullish_score += 0.3
        elif imb.direction == "ASK_HEAVY":bearish_score += 0.3
        if cvd.pressure == "BUY_PRESSURE":bullish_score += 0.3
        elif cvd.pressure == "SELL_PRESSURE": bearish_score += 0.3

        # Spoofing reduziert Konfidenz
        confidence = max(bullish_score, bearish_score) * (1 - spoof.spoof_score * 0.5)

        if bullish_score > bearish_score + 0.2:
            bias = "BULLISH"
        elif bearish_score > bullish_score + 0.2:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        return MicrostructureAnalysis(
            cvd         = cvd,
            imbalance   = imb,
            walls       = walls,
            spoofing    = spoof,
            signal_bias = bias,
            confidence  = round(confidence, 3),
        )


_ms_signals: MicrostructureSignals | None = None


def get_microstructure() -> MicrostructureSignals:
    global _ms_signals
    if _ms_signals is None:
        _ms_signals = MicrostructureSignals()
    return _ms_signals
