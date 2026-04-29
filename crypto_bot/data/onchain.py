"""
On-Chain Data — kostenlose Public APIs ohne API-Key.

Quellen:
  - blockchain.info/charts: Hash-Rate, TX-Volumen, Mempool-Größe
  - CoinGecko (free tier): Market Cap, Circulating Supply, Exchange Volume

Kein API-Key erforderlich. Alle Werte werden 4h gecacht.
On-Chain-Metriken fließen als normalisierte Features in das ML-Modell ein
und liefern strukturelle Markt-Insights die rein technische Analyse fehlt:
  - Miner-Kapitulation (Hash-Rate-Einbruch → Sell-Pressure)
  - Netzwerk-Aktivität (TX-Volumen → Adoption / Sell)
  - MVRV-Proxy (Market Cap / Realized Cap Annäherung)
  - Mempool-Kongestion (Demand-Indikator)
"""
import time
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("trading_bot")

_CACHE_TTL = 4 * 3600   # 4h Cache — On-Chain ändert sich langsam
_HTTP_TIMEOUT = 10       # 10s Timeout pro Request


# ── HTTP Hilfsfunktion ────────────────────────────────────────────────────────

def _get_json(url: str) -> Optional[dict | list]:
    """Einfacher HTTP-GET ohne externe Abhängigkeiten (stdlib only)."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 TradingBot/1.0",
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.debug(f"HTTP GET Fehler ({url}): {e}")
        return None


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class OnChainMetrics:
    # Hash-Rate
    hash_rate_ghs:       float = 0.0    # Aktuelle Hash-Rate in GH/s
    hash_rate_trend:     float = 0.0    # Änderung vs 7-Tage-Mittel (-1 bis +1)
    miner_capitulation:  bool  = False  # True wenn Hash-Rate > 15% gefallen

    # Netzwerk-Aktivität
    tx_volume_usd:       float = 0.0    # Tägl. TX-Volumen in USD (Mrd)
    tx_volume_trend:     float = 0.0    # vs 7-Tage-Mittel (-1 bis +1)
    mempool_bytes:       float = 0.0    # Mempool-Größe in MB
    mempool_signal:      str   = "NEUTRAL"  # "HIGH_DEMAND"|"NEUTRAL"|"LOW_DEMAND"

    # MVRV-Proxy (vereinfacht)
    mvrv_proxy:          float = 1.0    # Market Cap / 200-Tage-MA-Cap Proxy
    mvrv_signal:         str   = "NEUTRAL"  # "OVERVALUED"|"NEUTRAL"|"UNDERVALUED"

    # Exchange-Volumen (CoinGecko)
    exchange_vol_24h_btc: float = 0.0   # Exchange-Volumen 24h in BTC
    vol_vs_mcap:          float = 0.0   # Volumen / Market-Cap Ratio

    # Gesamt-Signal
    signal:              str   = "NEUTRAL"  # "BULLISH"|"NEUTRAL"|"BEARISH"
    score:               float = 0.0        # -1 (bearish) bis +1 (bullish)
    source:              str   = "cache"


# ── Cache ─────────────────────────────────────────────────────────────────────

_metrics_cache: Optional[OnChainMetrics] = None
_cache_ts: float = 0.0


# ── Blockchain.info API ────────────────────────────────────────────────────────

def _fetch_blockchain_info_chart(chart: str, timespan: str = "2months") -> Optional[list]:
    """
    Holt Chart-Daten von blockchain.info.
    chart: z.B. 'hash-rate', 'estimated-transaction-volume-usd', 'mempool-size'
    Returns Liste von {'x': timestamp, 'y': value} oder None bei Fehler.
    """
    url = f"https://api.blockchain.info/charts/{chart}?timespan={timespan}&sampled=true&format=json&cors=true"
    data = _get_json(url)
    if data and isinstance(data, dict) and "values" in data:
        return data["values"]
    return None


def _get_hash_rate_metrics() -> tuple[float, float, bool]:
    """
    Gibt zurück: (aktuell_ghs, trend_7d, miner_capitulation)
    trend_7d: +1 = stark steigend, -1 = stark fallend
    """
    try:
        values = _fetch_blockchain_info_chart("hash-rate", timespan="1months")
        if not values or len(values) < 7:
            return 0.0, 0.0, False

        recent = [v["y"] for v in values[-7:]]
        current = recent[-1]
        ma7 = sum(recent) / len(recent)

        # Trend: Abweichung vom 7-Tage-Mittel
        trend = (current - ma7) / ma7 if ma7 > 0 else 0.0
        trend = max(-1.0, min(1.0, trend * 5))   # Normalisiert auf -1/+1

        # Miner-Kapitulation: Hash-Rate > 15% unter 7-Tage-MA
        capitulation = bool((ma7 - current) / ma7 > 0.15) if ma7 > 0 else False

        return float(current), float(trend), capitulation
    except Exception as e:
        log.debug(f"Hash-Rate Fehler: {e}")
        return 0.0, 0.0, False


def _get_tx_volume_metrics() -> tuple[float, float]:
    """
    Gibt zurück: (aktuell_usd_mrd, trend_7d)
    """
    try:
        values = _fetch_blockchain_info_chart("estimated-transaction-volume-usd", timespan="1months")
        if not values or len(values) < 7:
            return 0.0, 0.0

        recent = [v["y"] for v in values[-7:]]
        current = recent[-1] / 1e9   # USD → Mrd USD
        ma7 = sum(recent) / len(recent) / 1e9

        trend = (current - ma7) / ma7 if ma7 > 0 else 0.0
        trend = max(-1.0, min(1.0, trend * 3))

        return float(current), float(trend)
    except Exception as e:
        log.debug(f"TX-Volumen Fehler: {e}")
        return 0.0, 0.0


def _get_mempool_metrics() -> tuple[float, str]:
    """
    Gibt zurück: (mempool_mb, signal)
    """
    try:
        values = _fetch_blockchain_info_chart("mempool-size", timespan="2weeks")
        if not values:
            return 0.0, "NEUTRAL"

        current_mb = values[-1]["y"] / 1e6  # Bytes → MB

        # Signal: >200MB = hohe Nachfrage, <50MB = niedrige Nachfrage
        if current_mb > 200:
            signal = "HIGH_DEMAND"
        elif current_mb < 50:
            signal = "LOW_DEMAND"
        else:
            signal = "NEUTRAL"

        return float(current_mb), signal
    except Exception as e:
        log.debug(f"Mempool Fehler: {e}")
        return 0.0, "NEUTRAL"


# ── CoinGecko API ──────────────────────────────────────────────────────────────

def _get_coingecko_metrics() -> tuple[float, float, float]:
    """
    Gibt zurück: (mvrv_proxy, vol_24h_btc, vol_vs_mcap)
    mvrv_proxy: aktueller Preis / 200-Tage-MA Proxy (aus 200d Preisdaten)
    """
    try:
        url = ("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
               "?vs_currency=usd&days=200&interval=daily")
        data = _get_json(url)
        if not data or "prices" not in data:
            return 1.0, 0.0, 0.0

        prices = [p[1] for p in data["prices"]]
        if len(prices) < 30:
            return 1.0, 0.0, 0.0

        current_price = prices[-1]
        ma200 = sum(prices) / len(prices)

        # MVRV-Proxy: Preis vs langfristiger Mittelwert
        mvrv_proxy = current_price / ma200 if ma200 > 0 else 1.0

        # Volumen-Daten
        vols = data.get("total_volumes", [])
        vol_24h_usd = vols[-1][1] if vols else 0.0

        # Market Cap
        mcaps = data.get("market_caps", [])
        mcap = mcaps[-1][1] if mcaps else 1.0

        vol_vs_mcap = vol_24h_usd / mcap if mcap > 0 else 0.0

        # BTC-Volumen approximieren (Preis bekannt)
        vol_24h_btc = vol_24h_usd / current_price if current_price > 0 else 0.0

        return float(mvrv_proxy), float(vol_24h_btc), float(vol_vs_mcap)
    except Exception as e:
        log.debug(f"CoinGecko Fehler: {e}")
        return 1.0, 0.0, 0.0


# ── Gesamt-Score ──────────────────────────────────────────────────────────────

def _compute_signal(metrics: OnChainMetrics) -> tuple[str, float]:
    """
    Kombiniert alle On-Chain-Signale zu einem Score (-1 bis +1).
    """
    score = 0.0
    weight_total = 0.0

    # Hash-Rate-Trend (bullish = Miner vertrauen dem Preis)
    if metrics.hash_rate_trend != 0.0:
        score        += metrics.hash_rate_trend * 0.25
        weight_total += 0.25

    # Miner-Kapitulation (stark bearish)
    if metrics.miner_capitulation:
        score        -= 0.3
        weight_total += 0.3

    # TX-Volumen-Trend (hohe Aktivität = bullish)
    if metrics.tx_volume_trend != 0.0:
        score        += metrics.tx_volume_trend * 0.15
        weight_total += 0.15

    # Mempool
    if metrics.mempool_signal == "HIGH_DEMAND":
        score        += 0.1
        weight_total += 0.1
    elif metrics.mempool_signal == "LOW_DEMAND":
        score        -= 0.05
        weight_total += 0.05

    # MVRV-Proxy
    mvrv = metrics.mvrv_proxy
    if mvrv > 3.0:    # Stark überbewertet → bearish
        score        -= 0.2
        weight_total += 0.2
    elif mvrv > 2.0:  # Überbewertet
        score        -= 0.1
        weight_total += 0.1
    elif mvrv < 0.8:  # Unterbewertet → bullish
        score        += 0.2
        weight_total += 0.2
    elif mvrv < 1.0:
        score        += 0.1
        weight_total += 0.1

    # Normalisieren
    final_score = score / weight_total if weight_total > 0 else 0.0
    final_score = max(-1.0, min(1.0, final_score))

    if final_score > 0.2:
        signal = "BULLISH"
    elif final_score < -0.2:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    return signal, round(final_score, 3)


# ── Öffentliche API ───────────────────────────────────────────────────────────

def get_onchain_metrics(force_refresh: bool = False) -> OnChainMetrics:
    """
    Gibt On-Chain-Metriken zurück. Gecacht für 4h.
    Bei force_refresh=True wird der Cache ignoriert.
    """
    global _metrics_cache, _cache_ts

    if not force_refresh and _metrics_cache is not None:
        age = time.time() - _cache_ts
        if age < _CACHE_TTL:
            return _metrics_cache

    log.info("On-Chain Daten werden geladen (blockchain.info + CoinGecko)...")

    hash_rate, hash_trend, capitulation = _get_hash_rate_metrics()
    tx_vol, tx_trend                     = _get_tx_volume_metrics()
    mempool_mb, mempool_sig              = _get_mempool_metrics()
    mvrv_proxy, vol_btc, vol_vs_mcap     = _get_coingecko_metrics()

    # MVRV-Signal
    if mvrv_proxy > 2.5:
        mvrv_signal = "OVERVALUED"
    elif mvrv_proxy < 0.9:
        mvrv_signal = "UNDERVALUED"
    else:
        mvrv_signal = "NEUTRAL"

    metrics = OnChainMetrics(
        hash_rate_ghs        = hash_rate,
        hash_rate_trend      = hash_trend,
        miner_capitulation   = capitulation,
        tx_volume_usd        = tx_vol,
        tx_volume_trend      = tx_trend,
        mempool_bytes        = mempool_mb,
        mempool_signal       = mempool_sig,
        mvrv_proxy           = mvrv_proxy,
        mvrv_signal          = mvrv_signal,
        exchange_vol_24h_btc = vol_btc,
        vol_vs_mcap          = vol_vs_mcap,
        source               = "live",
    )

    metrics.signal, metrics.score = _compute_signal(metrics)

    _metrics_cache = metrics
    _cache_ts      = time.time()

    log.info(
        f"On-Chain: Signal={metrics.signal} Score={metrics.score:+.2f} | "
        f"HashTrend={metrics.hash_rate_trend:+.2f} "
        f"MVRV={metrics.mvrv_proxy:.2f}({metrics.mvrv_signal}) "
        f"Mempool={metrics.mempool_signal} "
        f"TxTrend={metrics.tx_volume_trend:+.2f}"
    )
    return metrics


def get_onchain_feature_dict() -> dict:
    """
    Gibt On-Chain-Metriken als Feature-Dictionary zurück (für ML-Features).
    Alle Werte sind normalisiert und ML-freundlich.
    """
    try:
        m = get_onchain_metrics()
        return {
            "onchain_hash_rate_trend":   m.hash_rate_trend,
            "onchain_miner_capitulation": 1.0 if m.miner_capitulation else 0.0,
            "onchain_tx_volume_trend":   m.tx_volume_trend,
            "onchain_mempool_high":      1.0 if m.mempool_signal == "HIGH_DEMAND" else 0.0,
            "onchain_mvrv_proxy":        min(m.mvrv_proxy, 5.0) / 5.0,   # Normalisiert 0-1
            "onchain_vol_vs_mcap":       min(m.vol_vs_mcap, 0.1) / 0.1,  # Normalisiert 0-1
            "onchain_score":             m.score,
        }
    except Exception as e:
        log.debug(f"On-Chain Feature-Dict Fehler: {e}")
        return {
            "onchain_hash_rate_trend":    0.0,
            "onchain_miner_capitulation": 0.0,
            "onchain_tx_volume_trend":    0.0,
            "onchain_mempool_high":       0.0,
            "onchain_mvrv_proxy":         0.5,
            "onchain_vol_vs_mcap":        0.0,
            "onchain_score":              0.0,
        }


# Singleton
_instance: Optional[object] = None


def get_onchain_data():
    """Singleton-Accessor für On-Chain Daten."""
    return OnChainDataProvider()


class OnChainDataProvider:
    """Wrapper-Klasse für konsistente API mit anderen Modulen."""

    def fetch(self) -> OnChainMetrics:
        return get_onchain_metrics()

    def get_features(self) -> dict:
        return get_onchain_feature_dict()
