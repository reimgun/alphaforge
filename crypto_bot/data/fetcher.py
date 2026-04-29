"""
Daten-Fetcher mit Retry-Logik, Daten-Validierung, Gap-Erkennung und lokalem Cache.

Cache:
  Historische OHLCV-Candles werden in data_store/ohlcv_cache/{SYMBOL}_{TF}.parquet
  gespeichert. Jeder Folge-Aufruf lädt nur die fehlenden neuen Candles nach
  (inkrementelles Update) — spart API-Calls und ermöglicht Training ohne
  Internetverbindung wenn Daten bereits vorhanden sind.
"""
import time
import ccxt
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crypto_bot.monitoring.logger import log
from crypto_bot.config.settings import EXCHANGE, API_KEY, API_SECRET, TRADING_MODE

MAX_RETRIES = 5
RETRY_BACKOFF = [1, 2, 4, 8, 16]  # Sekunden

# Maximale Cache-Tiefe: 800 Tage (mehr als ML_TRAIN_DAYS=730)
_CACHE_MAX_DAYS = 800

# Cache-Verzeichnis relativ zum Projekt-Root
_CACHE_DIR = Path(__file__).parent.parent / "data_store" / "ohlcv_cache"


# ── Exchange ──────────────────────────────────────────────────────────────────

def get_exchange() -> ccxt.Exchange:
    exchange_class = getattr(ccxt, EXCHANGE)
    params: dict = {"options": {"defaultType": "spot"}}
    if TRADING_MODE in ("live", "testnet") and API_KEY:
        params["apiKey"] = API_KEY
        params["secret"] = API_SECRET
    exchange = exchange_class(params)
    exchange.enableRateLimit = True
    if TRADING_MODE == "testnet":
        exchange.set_sandbox_mode(True)   # → testnet.binance.vision
    return exchange


_rate_limit_stats: dict = {
    "hits":       0,
    "last_hit":   None,
    "last_error": None,
    "retries":    0,
}


def get_rate_limit_stats() -> dict:
    return dict(_rate_limit_stats)


def _fetch_with_retry(fn, *args, **kwargs):
    """Führt eine Exchange-Funktion mit exponentiellem Backoff aus."""
    for attempt, wait in enumerate(RETRY_BACKOFF):
        try:
            return fn(*args, **kwargs)
        except ccxt.RateLimitExceeded:
            _rate_limit_stats["hits"]     += 1
            _rate_limit_stats["retries"]  += 1
            _rate_limit_stats["last_hit"]  = time.strftime("%Y-%m-%dT%H:%M:%S")
            log.warning(f"Rate-Limit — warte {wait}s (Versuch {attempt+1}/{MAX_RETRIES})")
            time.sleep(wait)
        except ccxt.NetworkError as e:
            _rate_limit_stats["retries"]   += 1
            _rate_limit_stats["last_error"] = str(e)
            log.warning(f"Netzwerk-Fehler: {e} — warte {wait}s")
            time.sleep(wait)
        except ccxt.ExchangeNotAvailable as e:
            _rate_limit_stats["retries"]   += 1
            _rate_limit_stats["last_error"] = str(e)
            log.warning(f"Exchange nicht verfügbar: {e} — warte {wait}s")
            time.sleep(wait)
        except ccxt.BaseError as e:
            log.error(f"Exchange-Fehler (kein Retry): {e}")
            raise
    raise RuntimeError(f"Alle {MAX_RETRIES} Versuche fehlgeschlagen")


def _validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Prüft Datenqualität und entfernt fehlerhafte Zeilen."""
    initial_len = len(df)

    # Negative oder Null-Preise entfernen
    df = df[(df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)]

    # Unmögliche OHLC-Verhältnisse entfernen (Low > High)
    df = df[df["low"] <= df["high"]]
    df = df[(df["open"] >= df["low"]) & (df["open"] <= df["high"])]
    df = df[(df["close"] >= df["low"]) & (df["close"] <= df["high"])]

    # Duplikate entfernen
    df = df[~df.index.duplicated(keep="first")]

    removed = initial_len - len(df)
    if removed > 0:
        log.warning(f"Daten-Validierung: {removed} fehlerhafte Zeilen entfernt")

    return df


# ── Cache-Hilfsfunktionen ─────────────────────────────────────────────────────

def _cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.upper().replace("/", "_").replace("-", "_")
    return _CACHE_DIR / f"{safe}_{timeframe}.parquet"


def _load_cache(symbol: str, timeframe: str) -> pd.DataFrame | None:
    """Lädt gecachte OHLCV-Daten. Gibt None zurück wenn Cache fehlt oder korrupt."""
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return None
        # Index muss timezone-aware DatetimeIndex sein
        if not isinstance(df.index, pd.DatetimeIndex):
            return None
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df
    except Exception as e:
        log.warning(f"Cache-Lese-Fehler ({path.name}): {e} — lade vollständig neu")
        return None


def _save_cache(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """Speichert OHLCV-Daten in den lokalen Cache."""
    path = _cache_path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path)
        log.debug(f"Cache gespeichert: {path.name} ({len(df)} Candles)")
    except Exception as e:
        log.warning(f"Cache-Schreib-Fehler ({path.name}): {e}")


def _fetch_raw(exchange: ccxt.Exchange, symbol: str, timeframe: str,
               since_dt: datetime) -> pd.DataFrame:
    """Holt OHLCV-Candles ab einem bestimmten Zeitpunkt (keine Cache-Logik)."""
    since = exchange.parse8601(since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    all_candles: list = []
    while True:
        batch = _fetch_with_retry(
            exchange.fetch_ohlcv, symbol, timeframe, since=since, limit=1000
        )
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df.astype(float)


# ── Haupt-Fetch-Funktion ──────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    days: int = 365,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Lädt OHLCV-Daten für `symbol` mit `timeframe` über `days` Tage.

    Mit use_cache=True (Standard):
      - Beim ersten Aufruf: vollständiger Download, Speicherung als Parquet
      - Bei Folge-Aufrufen: nur neue Candles seit letztem Cache-Eintrag laden
        → typisch < 10 Candles statt 17.500

    Mit use_cache=False:
      - Immer vollständiger API-Download (altes Verhalten)
    """
    exchange = get_exchange()

    if use_cache:
        cached = _load_cache(symbol, timeframe)
        if cached is not None:
            # Inkrementell: letzte 3 Candles immer neu laden damit
            # unvollständig gecachte Candles (z.B. beim ersten Start
            # mitten in einer laufenden Stunde) mit korrekten Schlusswerten
            # überschrieben werden. concat() mit keep="last" bevorzugt
            # frische API-Daten bei Duplikaten.
            last_cached_ts = cached.index[-1].to_pydatetime()
            since_dt = last_cached_ts - timedelta(hours=3)
            log.debug(f"Cache hit ({symbol} {timeframe}): {len(cached)} Candles, "
                      f"lade ab {since_dt.strftime('%Y-%m-%d %H:%M')} (-3h overlap)")
        else:
            # Kein Cache — vollständiger Download
            since_dt = datetime.now(timezone.utc) - timedelta(days=days)
            log.info(f"Kein Cache für {symbol} {timeframe} — lade {days} Tage von Binance")
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cached = None

    # Neue Candles von der API holen
    new_df = _fetch_raw(exchange, symbol, timeframe, since_dt)

    # Cache zusammenführen
    if use_cache:
        if cached is not None and not new_df.empty:
            df = pd.concat([cached, new_df])
            df = df[~df.index.duplicated(keep="last")]
            df.sort_index(inplace=True)
            log.debug(f"Cache aktualisiert: +{len(new_df)} neue Candles → {len(df)} gesamt")
        elif cached is not None:
            # Nichts Neues
            df = cached
        else:
            df = new_df

        # Cache auf maximale Tiefe trimmen
        if not df.empty:
            cutoff_cache = datetime.now(timezone.utc) - timedelta(days=_CACHE_MAX_DAYS)
            df = df[df.index >= cutoff_cache]
            _save_cache(df, symbol, timeframe)
    else:
        df = new_df

    if df.empty:
        raise RuntimeError(f"Keine Daten für {symbol}/{timeframe}")

    df = _validate_ohlcv(df)

    # Auf angeforderter Zeitraum trimmen
    cutoff_return = datetime.now(timezone.utc) - timedelta(days=days)
    df = df[df.index >= cutoff_return]

    if df.empty:
        raise RuntimeError(f"Keine Daten im angeforderten Zeitraum für {symbol}/{timeframe}")

    # Daten-Aktualität prüfen
    latest = df.index[-1]
    age_minutes = (datetime.now(timezone.utc) - latest.to_pydatetime()).total_seconds() / 60
    if age_minutes > 120:
        log.warning(f"Daten sind {age_minutes:.0f} Minuten alt — Exchange-Problem?")

    return df


def fetch_current_price(symbol: str) -> float:
    exchange = get_exchange()
    ticker = _fetch_with_retry(exchange.fetch_ticker, symbol)
    return float(ticker["last"])


# ── Funding Rate (Binance USDT-M Futures) ─────────────────────────────────────

_funding_cache: dict = {}   # {symbol: (rate, timestamp)}
_FUNDING_TTL = 3600         # 1h Cache


def fetch_funding_rate(symbol: str = "BTC/USDT") -> float:
    """
    Holt aktuellen Funding-Rate von Binance Perpetuals (USDT-M Futures).
    Positiv = Longs zahlen Shorts (Markt überhitzt, bullish).
    Negativ = Shorts zahlen Longs (Markt unter Druck, bearish).
    Gecacht für 1h. Gibt 0.0001 (neutraler Default) zurück bei Fehler.
    """
    global _funding_cache
    now = time.time()
    if symbol in _funding_cache:
        cached_rate, cached_ts = _funding_cache[symbol]
        if now - cached_ts < _FUNDING_TTL:
            return cached_rate
    try:
        exchange = ccxt.binance({
            "options": {"defaultType": "future"},
        })
        exchange.enableRateLimit = True
        funding = exchange.fetch_funding_rate(symbol.replace("/", ""))
        rate = float(funding.get("fundingRate", 0.0001))
        _funding_cache[symbol] = (rate, now)
        log.debug(f"Funding Rate {symbol}: {rate:.6f} ({rate*100:.4f}% per 8h)")
        return rate
    except Exception as e:
        log.debug(f"Funding Rate Fehler: {e} — nutze Default 0.0001")
        return 0.0001


# ── Order Book Tiefe (Imbalanz-Features) ─────────────────────────────────────

_orderbook_cache: dict = {}   # {symbol: (features_dict, timestamp)}
_ORDERBOOK_TTL = 30           # 30s Cache (OB ändert sich schnell)


def fetch_orderbook_features(symbol: str = "BTC/USDT") -> dict:
    """
    Holt Order Book und berechnet Imbalanz-Features für das ML-Modell.

    Returns dict mit:
      orderbook_imbalance    — Gesamt-Bid/Ask-Volumenverhältnis (-1 bis +1)
      orderbook_imbalance_5  — Top-5-Level Imbalanz
      bid_ask_spread_bps     — Spread in Basispunkten
    Gecacht für 30s. Gibt neutrale Werte bei Fehler zurück.
    """
    global _orderbook_cache
    now = time.time()
    if symbol in _orderbook_cache:
        cached_feat, cached_ts = _orderbook_cache[symbol]
        if now - cached_ts < _ORDERBOOK_TTL:
            return cached_feat

    _neutral = {"orderbook_imbalance": 0.0, "orderbook_imbalance_5": 0.0, "bid_ask_spread_bps": 0.0}
    try:
        exchange = get_exchange()
        ob = exchange.fetch_order_book(symbol, limit=20)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return _neutral

        bid_vol   = sum(s for _, s in bids)
        ask_vol   = sum(s for _, s in asks)
        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

        bid_5   = sum(s for _, s in bids[:5])
        ask_5   = sum(s for _, s in asks[:5])
        total_5 = bid_5 + ask_5
        imb_5   = (bid_5 - ask_5) / total_5 if total_5 > 0 else 0.0

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid      = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000 if mid > 0 else 0.0

        feat = {
            "orderbook_imbalance":   round(imbalance, 4),
            "orderbook_imbalance_5": round(imb_5, 4),
            "bid_ask_spread_bps":    round(spread_bps, 2),
        }
        _orderbook_cache[symbol] = (feat, now)
        log.debug(f"Orderbook {symbol}: imb={imbalance:+.3f} imb5={imb_5:+.3f} spread={spread_bps:.1f}bps")
        return feat
    except Exception as e:
        log.debug(f"Orderbook Fehler: {e}")
        return _neutral
