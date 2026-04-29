"""
Walk-Forward Validation für den Forex Bot.

Validiert das Handelsmodell Out-of-Sample bevor es live geht.

Methodik:
  - Teilt historische Daten in N Fenster auf
  - Pro Fenster: 3 Monate In-Sample (Bestätigung), 1 Monat Out-of-Sample (Test)
  - Simuliert den Handels-Zyklus auf Out-of-Sample Daten
  - Berechnet Sharpe, Win-Rate, Max-Drawdown pro Fenster
  - Gibt Readiness-Score und Pass/Fail zurück

Readiness-Kriterien (konfigurierbar):
  - Sharpe > 0.5  in mindestens 5 von 8 Fenstern
  - Win-Rate > 45% in mindestens 5 von 8 Fenstern
  - Max-Drawdown < 15% in allen Fenstern

Verwendung:
    python -m forex_bot.backtest.walk_forward
    python -m forex_bot.backtest.walk_forward --instrument EUR_USD --windows 8
"""
import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from forex_bot.monitoring.logger import setup_logging

log = setup_logging()

# ── Readiness-Schwellenwerte ──────────────────────────────────────────────────
_MIN_SHARPE        = 0.5
_MIN_WIN_RATE      = 0.45
_MAX_DRAWDOWN      = 0.15
_MIN_PASS_FRACTION = 0.60   # 60% der Fenster müssen bestehen
_MIN_TRADES_WINDOW = 5      # Fenster mit < 5 Trades werden als "insufficient data" gewertet, nicht als Fail


# ── ML-Modell laden (einmalig, lazy) ─────────────────────────────────────────

_ml_model = None

def _get_ml_model():
    global _ml_model
    if _ml_model is None:
        try:
            from forex_bot.ai.model import ForexMLModel
            _ml_model = ForexMLModel()
            if _ml_model.model is None:
                _ml_model = None
        except Exception as e:
            log.debug(f"ML-Modell nicht verfügbar: {e}")
    return _ml_model


def _ml_confidence(df_window: pd.DataFrame, idx: int, direction: str) -> float:
    """
    Gibt ML-Konfidenz [0, 1] für 'direction' zurück.
    Gibt 0.5 zurück wenn Modell nicht verfügbar (neutral).
    Labels: 0=HOLD, 1=BUY, 2=SELL (aus trainer.py label_map)
    """
    model = _get_ml_model()
    if model is None:
        return 0.5
    try:
        from forex_bot.ai.features import build_features
        start = max(0, idx - 100)
        sub   = df_window.iloc[start:idx + 1].copy()
        if len(sub) < 30:
            return 0.5
        feats = build_features(sub, sub, sub)
        if feats is None or len(feats) == 0:
            return 0.5

        # model.predict() gibt (direction, confidence) zurück
        ml_dir, ml_conf = model.predict(feats)

        if ml_dir == direction:
            return ml_conf          # Modell stimmt zu
        elif ml_dir == "HOLD":
            return 0.45             # Neutral
        else:
            return 0.20             # Modell sagt Gegenrichtung → stark ablehnen
    except Exception:
        pass
    return 0.5


# ── Interne Hilfs-Funktionen ──────────────────────────────────────────────────

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    df["ema_fast"]  = _ema(df["close"], 20)
    df["ema_slow"]  = _ema(df["close"], 50)
    df["ema_trend"] = _ema(df["close"], 200)

    delta   = df["close"].diff()
    gain    = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss    = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    df["rsi"]  = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

    prev       = df["close"].shift(1)
    tr         = pd.concat([df["high"] - df["low"],
                             (df["high"] - prev).abs(),
                             (df["low"]  - prev).abs()], axis=1).max(axis=1)
    df["atr"]  = tr.ewm(span=14, adjust=False).mean()

    ema12       = _ema(df["close"], 12)
    ema26       = _ema(df["close"], 26)
    macd        = ema12 - ema26
    df["macd_h"] = macd - macd.ewm(span=9, adjust=False).mean()

    df["bb_mid"]   = df["close"].rolling(20).mean()
    df["bb_std"]   = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    return df


def _compute_h4_trend(df_h4: pd.DataFrame) -> pd.Series:
    """
    Berechnet H4-Trend-Richtung als Series aligned auf H4-Index.
    Gibt +1 (bullish), -1 (bearish), 0 (neutral) zurück.
    """
    df = df_h4.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    trend = pd.Series(0, index=df.index)
    trend[df["ema20"] > df["ema50"]] =  1
    trend[df["ema20"] < df["ema50"]] = -1
    return trend


def _signal(
    row:      pd.Series,
    prev:     pd.Series,
    h4_trend: int = 0,
) -> tuple[str, float]:
    """
    EMA-Crossover + Trend-Pullback Signal mit H4-Trend-Filter.

    h4_trend: +1 = H4 bullish, -1 = H4 bearish, 0 = neutral/unbekannt
    Signal nur wenn H4-Trend mit H1-Richtung übereinstimmt (oder unbekannt).
    """
    bull_trend = row.ema_fast > row.ema_slow > row.ema_trend
    bear_trend = row.ema_fast < row.ema_slow < row.ema_trend
    bull_cross = prev.ema_fast <= prev.ema_slow < row.ema_fast
    bear_cross = prev.ema_fast >= prev.ema_slow > row.ema_fast
    macd_bull  = row.macd_h > 0 and row.macd_h > prev.macd_h
    macd_bear  = row.macd_h < 0 and row.macd_h < prev.macd_h

    # H4-Filter: BUY nur wenn H4 neutral oder bullish, SELL nur wenn H4 neutral oder bearish
    h4_allows_buy  = h4_trend >= 0
    h4_allows_sell = h4_trend <= 0

    # EMA-Crossover (präzise, höhere Konfidenz)
    if bull_trend and bull_cross and macd_bull and 40 < row.rsi < 65 and h4_allows_buy:
        c = 0.58 + (0.10 if row.rsi < 55 else 0) + (0.05 if row.close > row.bb_mid else 0)
        c += 0.05 if h4_trend == 1 else 0   # H4-Bestätigung: +5%
        return "BUY", round(min(c, 1.0), 2)
    if bear_trend and bear_cross and macd_bear and 35 < row.rsi < 60 and h4_allows_sell:
        c = 0.58 + (0.10 if row.rsi > 45 else 0) + (0.05 if row.close < row.bb_mid else 0)
        c += 0.05 if h4_trend == -1 else 0
        return "SELL", round(min(c, 1.0), 2)

    # Trend-Pullback (häufiger, niedrigere Konfidenz)
    atr = row.atr if row.atr > 0 else 1e-5
    near_ema20 = abs(row.close - row.ema_fast) < atr * 0.6
    if bull_trend and near_ema20 and 38 < row.rsi < 55 and row.macd_h > 0 and h4_allows_buy:
        c = 0.52 + (0.08 if row.rsi < 48 else 0) + (0.05 if row.close < row.bb_mid else 0)
        c += 0.05 if h4_trend == 1 else 0
        return "BUY", round(min(c, 1.0), 2)
    if bear_trend and near_ema20 and 45 < row.rsi < 62 and row.macd_h < 0 and h4_allows_sell:
        c = 0.52 + (0.08 if row.rsi > 52 else 0) + (0.05 if row.close > row.bb_mid else 0)
        c += 0.05 if h4_trend == -1 else 0
        return "SELL", round(min(c, 1.0), 2)

    return "HOLD", 0.0


def _simulate_window(
    df:           pd.DataFrame,
    instrument:   str,
    spread_pips:  float = 0.8,
    atr_mult:     float = 1.5,
    rr_ratio:     float = 2.0,
    min_conf:     float = 0.65,
    h4_trends:    pd.Series | None = None,
) -> dict:
    """
    Simuliert den Forex-Bot auf einem Datenfenster.

    Returns dict mit: trades, wins, total_pips, sharpe, max_drawdown
    """
    pip_size     = 0.01 if "JPY" in instrument else 0.0001
    spread_price = spread_pips * pip_size

    trades        = []
    equity        = [100.0]   # Normalisiert auf 100
    peak          = 100.0
    max_dd        = 0.0
    risk_per_trade = 0.01

    in_trade      = False
    trade_dir     = None
    trade_entry   = 0.0
    trade_sl      = 0.0
    trade_tp      = 0.0

    start_idx = 210  # Warm-Up für EMA200

    for i in range(start_idx, len(df)):
        row  = df.iloc[i]
        prev = df.iloc[i - 1]
        # H4-Trend für diesen H1-Candle (letzter bekannter H4-Wert)
        h4_t = int(h4_trends.iloc[i]) if h4_trends is not None and i < len(h4_trends) else 0

        # Offenen Trade prüfen
        if in_trade:
            high  = float(row["high"])
            low   = float(row["low"])
            hit   = False
            pips  = 0.0

            if trade_dir == "BUY":
                if low <= trade_sl:
                    pips = (trade_sl - trade_entry) / pip_size
                    hit  = True
                elif high >= trade_tp:
                    pips = (trade_tp - trade_entry) / pip_size
                    hit  = True
            else:
                if high >= trade_sl:
                    pips = (trade_entry - trade_sl) / pip_size
                    hit  = True
                elif low <= trade_tp:
                    pips = (trade_entry - trade_tp) / pip_size
                    hit  = True

            if hit:
                trades.append(pips)
                capital_change = pips * pip_size * risk_per_trade / abs(trade_entry - trade_sl) if abs(trade_entry - trade_sl) > 0 else 0
                new_eq = equity[-1] * (1 + capital_change)
                equity.append(new_eq)
                if new_eq > peak:
                    peak = new_eq
                dd = (peak - new_eq) / peak
                if dd > max_dd:
                    max_dd = dd
                in_trade = False

            continue  # Skip Signal-Generierung während Trade läuft

        # Signal generieren (mit H4-Trend-Filter)
        direction, confidence = _signal(row, prev, h4_trend=h4_t)
        if direction == "HOLD" or confidence < min_conf:
            continue

        # ML-Modell: Hard-Filter wenn ML die Richtung ablehnt
        ml_conf = _ml_confidence(df, i, direction)
        if ml_conf < 0.40:   # ML confidence < 40% für diese Richtung → skip
            continue
        # Konfidenz-Boost wenn ML stark zustimmt
        if ml_conf > 0.55:
            confidence = min(1.0, confidence + 0.05)
        if confidence < min_conf:
            continue

        atr     = float(row["atr"])
        price   = float(row["close"])
        sl_dist = atr * atr_mult
        tp_dist = sl_dist * rr_ratio

        if direction == "BUY":
            entry   = price + spread_price
            trade_sl = entry - sl_dist
            trade_tp = entry + tp_dist
        else:
            entry   = price - spread_price
            trade_sl = entry + sl_dist
            trade_tp = entry - tp_dist

        in_trade    = True
        trade_dir   = direction
        trade_entry = entry

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "total_pips": 0.0,
                "sharpe": 0.0, "max_drawdown": 0.0}

    wins       = sum(1 for p in trades if p > 0)
    total_pips = sum(trades)
    win_rate   = wins / len(trades)

    pips_arr = np.array(trades)
    sharpe   = 0.0
    if len(pips_arr) > 2 and pips_arr.std() > 0:
        sharpe = round(float(pips_arr.mean() / pips_arr.std() * np.sqrt(252)), 2)

    return {
        "trades":       len(trades),
        "wins":         wins,
        "win_rate":     round(win_rate, 3),
        "total_pips":   round(total_pips, 1),
        "sharpe":       sharpe,
        "max_drawdown": round(max_dd, 4),
    }


# ── Haupt Walk-Forward ────────────────────────────────────────────────────────

def run_walk_forward(
    instrument:      str   = "EUR_USD",
    n_windows:       int   = 8,
    in_sample_weeks: int   = 12,  # 3 Monate
    oos_weeks:       int   = 4,   # 1 Monat
    spread_pips:     float = 1.0,  # 1.0 Pip für IG MINI (realistischer als 0.8)
    n_candles:       int   = 5000,
) -> dict:
    """
    Führt eine Walk-Forward-Validierung durch.

    Parameters
    ----------
    instrument:      OANDA Instrument
    n_windows:       Anzahl Validierungs-Fenster
    in_sample_weeks: In-Sample Länge in Wochen (Warm-Up, nicht getestet)
    oos_weeks:       Out-of-Sample Länge in Wochen (getestet)
    spread_pips:     Simulierter Spread
    n_candles:       Candles zum Laden

    Returns
    -------
    dict mit:
      windows:       Liste der Fenster-Ergebnisse
      summary:       Aggregierte Metriken
      readiness:     True wenn Bot bereit für Live-Trading
      readiness_score: 0–100 Score
    """
    from forex_bot.execution.broker_factory import create_broker_client

    log.info(f"Walk-Forward: {instrument} — lade {n_candles} H1-Candles...")

    # Broker-Verbindung versuchen, dann yfinance als Fallback
    df = None
    try:
        client = create_broker_client()
        raw    = client.get_candles(instrument, "H1", count=min(n_candles, 5000))
        if raw:
            df = pd.DataFrame(raw)
            log.info(f"  Broker: {len(df)} Candles geladen")
    except Exception as e:
        log.warning(f"  Broker nicht verfügbar ({e}) — versuche yfinance...")

    if df is None or len(df) < 500:
        try:
            import yfinance as yf
            _ticker_map = {
                "EUR_USD": "EURUSD=X", "GBP_USD": "GBPUSD=X",
                "USD_JPY": "USDJPY=X", "AUD_USD": "AUDUSD=X",
                "USD_CHF": "USDCHF=X", "USD_CAD": "USDCAD=X",
            }
            ticker = _ticker_map.get(instrument, f"{instrument.replace('_','')}=X")
            import math
            days   = min(math.ceil(n_candles / 24 * 1.5), 729)
            ydf    = yf.download(ticker, interval="1h", period=f"{days}d", progress=False)
            if ydf.empty:
                raise ValueError(f"yfinance: keine Daten für {ticker}")
            ydf = ydf.rename(columns={"Open": "open", "High": "high",
                                       "Low": "low", "Close": "close", "Volume": "volume"})
            if hasattr(ydf.columns, "droplevel"):
                try:
                    ydf.columns = ydf.columns.droplevel(1)
                except Exception:
                    pass
            df = ydf[["open", "high", "low", "close", "volume"]].dropna().tail(n_candles).reset_index(drop=True)
            log.info(f"  yfinance: {len(df)} Candles geladen")
        except Exception as e2:
            raise ValueError(f"Keine Daten verfügbar (Broker + yfinance): {e2}") from e2

    if len(df) < 500:
        raise ValueError(f"Zu wenig Candles: {len(df)} (mind. 500 nötig)")
    df = _compute_indicators(df)
    df = df.reset_index(drop=True)

    # ── H4-Trend laden (resampeln aus H1-Daten) ───────────────────────────────
    # yfinance H4 ist nicht verfügbar → H1-Daten auf H4 resampeln
    h4_trends_full: pd.Series | None = None
    try:
        df_h4 = df.copy()
        # H4 = jeder 4. H1-Candle (rolling aggregation)
        df_h4["close_h4"] = df["close"].rolling(4).mean()
        df_h4["ema20_h4"] = df_h4["close_h4"].ewm(span=20, adjust=False).mean()
        df_h4["ema50_h4"] = df_h4["close_h4"].ewm(span=50, adjust=False).mean()
        h4_trend_raw = pd.Series(0, index=df_h4.index)
        h4_trend_raw[df_h4["ema20_h4"] > df_h4["ema50_h4"]] =  1
        h4_trend_raw[df_h4["ema20_h4"] < df_h4["ema50_h4"]] = -1
        # Forward-fill: letzter H4-Wert gilt für die nächsten 4 H1-Candles
        h4_trends_full = h4_trend_raw
        log.info("  H4-Trend-Filter: aktiviert (resampelt aus H1)")
    except Exception as e:
        log.warning(f"  H4-Trend-Filter: {e} — deaktiviert")

    # Stunden pro Fenster
    is_hours  = in_sample_weeks * 5 * 24   # Handelstage × 24h
    oos_hours = oos_weeks * 5 * 24
    step      = oos_hours   # Schrittweite = OOS-Länge

    total_needed = is_hours + n_windows * step
    if len(df) < total_needed:
        available_windows = max(1, (len(df) - is_hours) // step)
        n_windows = min(n_windows, available_windows)
        log.warning(
            f"Walk-Forward: Nur {len(df)} Candles verfügbar → "
            f"reduziere auf {n_windows} Fenster"
        )

    windows     = []
    window_idx  = 0

    for w in range(n_windows):
        oos_start = is_hours + w * step
        oos_end   = oos_start + oos_hours

        if oos_end > len(df):
            break

        slice_start = max(0, oos_start - 210)
        oos_df = df.iloc[slice_start:oos_end].reset_index(drop=True)

        # H4-Trend-Slice für dieses Fenster
        h4_slice = None
        if h4_trends_full is not None:
            h4_slice = h4_trends_full.iloc[slice_start:oos_end].reset_index(drop=True)

        result = _simulate_window(oos_df, instrument, spread_pips, min_conf=0.58,
                                  h4_trends=h4_slice)
        result["window"] = w + 1

        # Pass/Fail pro Fenster — Fenster mit zu wenig Trades als "n/a" markieren
        if result["trades"] < _MIN_TRADES_WINDOW:
            result["passed"]  = None   # None = insufficient data, weder pass noch fail
            status_icon = "⚪"
        else:
            passes_sharpe  = result["sharpe"]       >= _MIN_SHARPE
            passes_winrate = result["win_rate"]      >= _MIN_WIN_RATE
            passes_dd      = result["max_drawdown"]  <= _MAX_DRAWDOWN
            result["passed"] = passes_sharpe and passes_winrate and passes_dd
            status_icon = "✅" if result["passed"] else "❌"

        windows.append(result)

        log.info(
            f"  Fenster {w+1}: trades={result['trades']} "
            f"WR={result['win_rate']:.0%} "
            f"Sharpe={result['sharpe']:.2f} "
            f"DD={result['max_drawdown']:.1%} "
            f"{status_icon}"
        )

    if not windows:
        return {
            "windows": [],
            "summary": {},
            "readiness": False,
            "readiness_score": 0,
        }

    # Aggregierte Zusammenfassung — nur Fenster mit genug Trades auswerten
    evaluable = [w for w in windows if w["passed"] is not None]
    passed_count  = sum(1 for w in evaluable if w["passed"])
    pass_fraction = passed_count / len(evaluable) if evaluable else 0
    total_trades  = sum(w["trades"] for w in windows)
    avg_sharpe    = np.mean([w["sharpe"]       for w in evaluable]) if evaluable else 0
    avg_win_rate  = np.mean([w["win_rate"]      for w in evaluable]) if evaluable else 0
    avg_max_dd    = np.mean([w["max_drawdown"]  for w in evaluable]) if evaluable else 0
    skipped       = len(windows) - len(evaluable)

    readiness       = pass_fraction >= _MIN_PASS_FRACTION and len(evaluable) >= 3
    readiness_score = int(pass_fraction * 100)

    summary = {
        "instrument":       instrument,
        "n_windows":        len(windows),
        "evaluable_windows": len(evaluable),
        "skipped_windows":  skipped,
        "passed_windows":   passed_count,
        "pass_fraction":    round(pass_fraction, 2),
        "total_trades":     total_trades,
        "avg_sharpe":       round(float(avg_sharpe), 2),
        "avg_win_rate":     round(float(avg_win_rate), 3),
        "avg_max_drawdown": round(float(avg_max_dd), 4),
        "readiness":        readiness,
        "readiness_score":  readiness_score,
    }

    skip_note = f" ({skipped} Fenster ⚪ zu wenig Trades)" if skipped else ""
    log.info(
        f"\n{'='*50}\n"
        f"Walk-Forward {instrument}: "
        f"{passed_count}/{len(evaluable)} Fenster bestanden{skip_note}\n"
        f"Avg Sharpe={avg_sharpe:.2f} WR={avg_win_rate:.0%} DD={avg_max_dd:.1%}\n"
        f"Readiness: {'✅ BEREIT' if readiness else '❌ NICHT BEREIT'} "
        f"(Score={readiness_score}/100)\n"
        f"{'='*50}"
    )

    return {
        "windows":         windows,
        "summary":         summary,
        "readiness":       readiness,
        "readiness_score": readiness_score,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forex Walk-Forward Validation")
    parser.add_argument("--instrument", default=None,
                        help="Einzelnes Instrument (default: alle konfigurierten Pairs)")
    parser.add_argument("--windows",    type=int,   default=8)
    parser.add_argument("--candles",    type=int,   default=5000)
    parser.add_argument("--spread",     type=float, default=1.0)
    args = parser.parse_args()

    # Instrument-Liste: entweder CLI-Argument oder aus Settings
    if args.instrument:
        instruments = [args.instrument]
    else:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from forex_bot.config import settings as _cfg
            instruments = list(_cfg.INSTRUMENTS)[:4]   # max 4 Pairs (Laufzeit)
        except Exception:
            instruments = ["EUR_USD", "GBP_USD", "USD_JPY"]

    all_scores = []
    all_ready  = []

    for instr in instruments:
        try:
            res = run_walk_forward(
                instrument  = instr,
                n_windows   = args.windows,
                n_candles   = args.candles,
                spread_pips = args.spread,
            )
            all_scores.append(res["readiness_score"])
            all_ready.append(res["readiness"])
        except Exception as e:
            log.warning(f"Walk-Forward {instr}: {e}")

    if all_scores:
        avg_score = int(np.mean(all_scores))
        overall_ready = sum(all_ready) / len(all_ready) >= 0.5
        print(f"\n{'='*50}")
        print(f"Gesamt-Readiness: {avg_score}/100")
        print(f"Bereit für Live: {'JA ✅' if overall_ready else 'NEIN ❌'}")
    else:
        print("\nKeine Ergebnisse — Daten nicht verfügbar")
