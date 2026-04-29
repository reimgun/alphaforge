"""
Multi-Asset Pair Selector — Automatische Auswahl der besten USDT-Paare.

Scannt Binance nach Top-Paaren nach:
  - 24h Handelsvolumen (> min_volume_usdt)
  - ATR% (Volatilität) — ideal 1-5%
  - Trend-Qualität (ADX > 20 bevorzugt)
  - Korrelations-Filter (nicht zu stark korreliert mit anderen gewählten Paaren)

Gibt eine priorisierte Liste zurück.
"""
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger("trading_bot")

# Standard-Kandidaten wenn kein Scan möglich
DEFAULT_PAIRS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
]


@dataclass
class PairScore:
    symbol: str
    volume_24h: float       # in USDT
    atr_pct: float          # ATR als % des Preises
    adx: float              # Trend-Stärke
    score: float            # Gesamt-Score
    reason: str             # Warum gewählt


@dataclass
class PairSelection:
    selected: list[str]          # Gewählte Symbole
    scores: list[PairScore]      # Detail-Scores
    correlation_filtered: list[str] = field(default_factory=list)
    # Vollständige Korrelationsmatrix: {(sym_a, sym_b): pearson_r}
    correlation_matrix: dict = field(default_factory=dict)


def select_pairs(
    exchange=None,
    max_pairs: int = 3,
    min_volume_usdt: float = 50_000_000,   # 50M USDT/Tag
    min_atr_pct: float = 0.5,
    max_atr_pct: float = 8.0,
    max_correlation: float = 0.85,
) -> PairSelection:
    """
    Scannt Binance und wählt die besten USDT-Paare aus.

    Args:
        exchange:        CCXT Binance-Instanz (None → verwendet Default-Paare)
        max_pairs:       Maximale Anzahl gleichzeitiger Paare
        min_volume_usdt: Mindest-Tagesvolumen
        min_atr_pct:     Mindest-ATR% (zu wenig Volatilität = langweilig)
        max_atr_pct:     Maximal-ATR% (zu viel = zu riskant)
        max_correlation: Korrelations-Schwelle (Paare > threshold werden ausgeschlossen)

    Returns:
        PairSelection mit gewählten Symbolen und Detail-Scores
    """
    if exchange is None:
        log.info("Pair Selector: kein Exchange — Default-Paare verwenden")
        return PairSelection(
            selected=DEFAULT_PAIRS[:max_pairs],
            scores=[PairScore(s, 0, 0, 0, 0, "default") for s in DEFAULT_PAIRS[:max_pairs]],
        )

    try:
        tickers = exchange.fetch_tickers()
        candidates = _filter_candidates(tickers, min_volume_usdt)
        log.info(f"Pair Selector: {len(candidates)} Kandidaten nach Volumen-Filter")

        scores = _score_pairs(candidates, exchange, min_atr_pct, max_atr_pct)
        scores.sort(key=lambda x: x.score, reverse=True)

        # Korrelations-Filter + vollständige Matrix
        selected, filtered, corr_matrix = _apply_correlation_filter(
            scores, exchange, max_pairs, max_correlation
        )

        log.info(f"Pair Selector: {len(selected)} Paare gewählt: {selected}")
        return PairSelection(
            selected=selected,
            scores=scores,
            correlation_filtered=filtered,
            correlation_matrix=corr_matrix,
        )

    except Exception as e:
        log.warning(f"Pair Selector Fehler: {e} — Default-Paare verwenden")
        return PairSelection(
            selected=DEFAULT_PAIRS[:max_pairs],
            scores=[PairScore(s, 0, 0, 0, 0, f"fallback: {e}")
                    for s in DEFAULT_PAIRS[:max_pairs]],
        )


def _filter_candidates(tickers: dict, min_volume: float) -> list[dict]:
    """Filtert USDT-Paare nach Mindest-Volumen."""
    candidates = []
    for symbol, ticker in tickers.items():
        if not symbol.endswith("/USDT"):
            continue
        # Stablecoins, Leverage-Tokens und nicht-ASCII Symbole ausschließen
        base = symbol.split("/")[0]
        if not base.isascii() or not base.isalnum():
            continue
        if any(x in base for x in ["USDC", "BUSD", "DAI", "TUSD", "UP", "DOWN", "BULL", "BEAR"]):
            continue
        vol = float(ticker.get("quoteVolume") or ticker.get("baseVolume", 0) or 0)
        if vol >= min_volume:
            candidates.append({"symbol": symbol, "volume": vol, "ticker": ticker})
    return candidates


def _score_pairs(candidates: list[dict], exchange, min_atr: float, max_atr: float) -> list[PairScore]:
    """Berechnet Score für jeden Kandidaten basierend auf Volatilität und Trend."""
    scores = []
    for c in candidates[:30]:   # Top 30 by volume only
        try:
            ohlcv = exchange.fetch_ohlcv(c["symbol"], "1h", limit=50)
            df    = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])

            atr_pct = _calc_atr_pct(df)
            adx     = _calc_adx(df)
            vol     = c["volume"]

            # Score-Formel: Volumen (30%) + ATR-Qualität (40%) + ADX (30%)
            vol_score = min(np.log10(vol / 1e6) / 3, 1.0)   # Log-normalisiert
            atr_score = _atr_quality_score(atr_pct, min_atr, max_atr)
            adx_score = min(adx / 40, 1.0)

            total = vol_score * 0.3 + atr_score * 0.4 + adx_score * 0.3

            scores.append(PairScore(
                symbol     = c["symbol"],
                volume_24h = vol,
                atr_pct    = round(atr_pct, 2),
                adx        = round(adx, 1),
                score      = round(total, 3),
                reason     = f"Vol={vol/1e6:.0f}M ATR={atr_pct:.1f}% ADX={adx:.0f}",
            ))
        except Exception as e:
            log.debug(f"Score Fehler {c['symbol']}: {e}")

    return scores


def _apply_correlation_filter(
    scores: list[PairScore], exchange, max_pairs: int, max_corr: float
) -> tuple[list[str], list[str], dict]:
    """Schließt stark korrelierte Paare aus und gibt Korrelationsmatrix zurück."""
    selected = []
    filtered = []
    close_series = {}
    corr_matrix: dict = {}   # {(sym_a, sym_b): pearson_r}

    for ps in scores:
        if len(selected) >= max_pairs:
            break
        try:
            if exchange is not None and ps.score > 0:
                ohlcv = exchange.fetch_ohlcv(ps.symbol, "1h", limit=100)
                closes = pd.Series([c[4] for c in ohlcv])
                close_series[ps.symbol] = closes.pct_change().dropna()
        except Exception:
            pass

        # Korrelations-Check gegen bereits gewählte Paare
        too_correlated = False
        for sel in selected:
            if sel in close_series and ps.symbol in close_series:
                s1 = close_series[sel]
                s2 = close_series[ps.symbol]
                min_len = min(len(s1), len(s2))
                if min_len > 10:
                    corr = abs(float(np.corrcoef(s1.values[-min_len:],
                                                  s2.values[-min_len:])[0, 1]))
                    corr_matrix[(sel, ps.symbol)] = round(corr, 3)
                    if corr > max_corr:
                        too_correlated = True
                        filtered.append(ps.symbol)
                        log.debug(f"Korrelations-Filter: {ps.symbol} zu ähnlich zu {sel} (r={corr:.2f})")
                        break

        if not too_correlated:
            selected.append(ps.symbol)

    # Wenn nicht genug gefunden: mit Default auffüllen
    for default in DEFAULT_PAIRS:
        if len(selected) >= max_pairs:
            break
        if default not in selected:
            selected.append(default)

    # Korrelationsmatrix loggen (Self-Learning Mode — Trainings-Info)
    if corr_matrix:
        log.info("Korrelationsmatrix (Top-Paare):")
        for (a, b), r in sorted(corr_matrix.items(), key=lambda x: -x[1]):
            flag = " ← gefiltert" if r > max_corr else ""
            log.info(f"  {a} ↔ {b}: r={r:.2f}{flag}")

    return selected, filtered, corr_matrix


def _calc_atr_pct(df: pd.DataFrame) -> float:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    price = float(df["close"].iloc[-1])
    return (atr / price * 100) if price > 0 else 0.0


def _calc_adx(df: pd.DataFrame, period: int = 14) -> float:
    try:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        dm_plus  = (high - high.shift(1)).clip(lower=0)
        dm_minus = (low.shift(1) - low).clip(lower=0)
        dm_plus  = dm_plus.where(dm_plus > dm_minus, 0)
        dm_minus = dm_minus.where(dm_minus > dm_plus, 0)
        atr_s   = tr.ewm(span=period).mean()
        di_plus  = 100 * dm_plus.ewm(span=period).mean() / atr_s.replace(0, np.nan)
        di_minus = 100 * dm_minus.ewm(span=period).mean() / atr_s.replace(0, np.nan)
        dx = (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan) * 100
        return float(dx.ewm(span=period).mean().iloc[-1])
    except Exception:
        return 0.0


def _atr_quality_score(atr_pct: float, min_atr: float, max_atr: float) -> float:
    """Score 1.0 wenn ATR im Ideal-Bereich, fällt ab außerhalb."""
    ideal_min, ideal_max = min_atr * 1.5, max_atr * 0.6
    if ideal_min <= atr_pct <= ideal_max:
        return 1.0
    if atr_pct < min_atr or atr_pct > max_atr:
        return 0.0
    if atr_pct < ideal_min:
        return (atr_pct - min_atr) / (ideal_min - min_atr)
    return (max_atr - atr_pct) / (max_atr - ideal_max)
