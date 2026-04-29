"""
Forex Correlation Manager.

Tracks pairwise correlations between instruments and prevents over-exposure
when multiple correlated positions would move the portfolio in the same direction.

Positive correlation:  pairs tend to move together.
Negative correlation:  pairs tend to move in opposite directions.

If you are LONG EUR_USD and LONG GBP_USD (corr +0.85, same direction),
the effective exposure is approximately doubled — this module detects that.
"""

# ── Static correlation table ──────────────────────────────────────────────────
# Format: frozenset({A, B}) → correlation coefficient
# Values range from -1.0 (perfect inverse) to +1.0 (perfect co-movement).
# Extended with previously missing cross-pairs.

_CORRELATION_TABLE: dict[frozenset, float] = {
    # Majors
    frozenset({"EUR_USD", "GBP_USD"}): +0.85,
    frozenset({"EUR_USD", "USD_CHF"}): -0.90,
    frozenset({"EUR_USD", "USD_JPY"}): -0.75,
    frozenset({"GBP_USD", "USD_CHF"}): -0.80,
    frozenset({"GBP_USD", "USD_JPY"}): -0.65,
    frozenset({"USD_CHF", "USD_JPY"}): +0.70,
    frozenset({"EUR_USD", "AUD_USD"}): +0.70,
    frozenset({"GBP_USD", "AUD_USD"}): +0.65,
    # Cross-pairs (previously missing)
    frozenset({"EUR_USD", "EUR_CHF"}): +0.60,
    frozenset({"EUR_USD", "EUR_JPY"}): +0.75,
    frozenset({"GBP_USD", "GBP_JPY"}): +0.72,
    frozenset({"USD_JPY", "EUR_JPY"}): +0.80,
    frozenset({"USD_JPY", "GBP_JPY"}): +0.78,
    frozenset({"AUD_USD", "NZD_USD"}): +0.80,
    frozenset({"AUD_USD", "AUD_JPY"}): +0.65,
    frozenset({"USD_CAD", "USD_JPY"}): +0.30,
    frozenset({"EUR_USD", "NZD_USD"}): +0.60,
}


# ── Rolling Correlation Matrix (dynamisch) ────────────────────────────────────

from collections import deque
import math


class RollingCorrelationMatrix:
    """
    Berechnet rolling Pearson-Korrelationen aus Return-Zeitreihen.

    Aktualisiert wöchentlich (7 Tage Cache) um QNAP-CPU zu schonen.
    Fällt auf statische Tabelle zurück wenn zu wenig Daten vorhanden.

    Verwendung:
        rcm = RollingCorrelationMatrix(window=30)
        rcm.update("EUR_USD", close_price)
        rcm.update("GBP_USD", close_price)
        corr = rcm.get_correlation("EUR_USD", "GBP_USD")
    """

    WINDOW         = 30    # Korrelations-Fenster in Bars
    MIN_SAMPLES    = 15    # Mindest-Datenpunkte für Rolling-Korrelation
    CACHE_TTL_BARS = 168   # Wöchentliche Neuberechnung (~7 Tage × 24h)

    def __init__(self, window: int = 30):
        self._window    = window
        self._returns:  dict[str, deque] = {}   # instrument → deque[float]
        self._cache:    dict[frozenset, float] = {}
        self._bar_count = 0

    def update(self, instrument: str, close: float) -> None:
        """Aktualisiert die Return-Zeitreihe für ein Instrument."""
        if instrument not in self._returns:
            self._returns[instrument] = deque(maxlen=self._window + 1)
        self._returns[instrument].append(float(close))
        self._bar_count += 1

        # Cache-Invalidierung nach CACHE_TTL_BARS
        if self._bar_count % self.CACHE_TTL_BARS == 0:
            self._cache.clear()

    def _pearson(self, a: list[float], b: list[float]) -> float:
        """Pearson-Korrelation zwischen zwei gleich langen Listen."""
        n = len(a)
        if n < 2:
            return 0.0
        mean_a = sum(a) / n
        mean_b = sum(b) / n
        cov    = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
        std_a  = math.sqrt(sum((x - mean_a) ** 2 for x in a) / n)
        std_b  = math.sqrt(sum((x - mean_b) ** 2 for x in b) / n)
        if std_a < 1e-10 or std_b < 1e-10:
            return 0.0
        return round(cov / (n * std_a * std_b), 3)

    def _returns_from_deque(self, d: deque) -> list[float]:
        """Wandelt Preise in Log-Returns um."""
        prices = list(d)
        if len(prices) < 2:
            return []
        return [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]

    def get_correlation(self, a: str, b: str) -> float:
        """
        Gibt die rolling Korrelation zwischen zwei Instruments zurück.
        Fällt auf statische Tabelle zurück wenn zu wenig Daten.
        """
        if a == b:
            return 1.0

        key = frozenset({a, b})
        if key in self._cache:
            return self._cache[key]

        ret_a = self._returns_from_deque(self._returns.get(a, deque()))
        ret_b = self._returns_from_deque(self._returns.get(b, deque()))

        n = min(len(ret_a), len(ret_b))
        if n >= self.MIN_SAMPLES:
            corr = self._pearson(ret_a[-n:], ret_b[-n:])
            self._cache[key] = corr
            return corr

        # Fallback auf statische Tabelle
        return _CORRELATION_TABLE.get(key, 0.0)


# Globale Rolling-Korrelations-Instanz (wird von bot.py befüllt)
_rolling_matrix = RollingCorrelationMatrix(window=30)


def update_rolling_correlation(instrument: str, close_price: float) -> None:
    """Aktualisiert die Rolling Correlation Matrix mit einem neuen Close-Preis."""
    _rolling_matrix.update(instrument, close_price)


def get_correlation(a: str, b: str) -> float:
    """
    Gibt die Korrelation zwischen zwei Instruments zurück.

    Versucht zunächst Rolling-Korrelation (dynamisch),
    fällt auf statische Tabelle zurück wenn nicht genug Daten.
    """
    if a == b:
        return 1.0
    return _rolling_matrix.get_correlation(a, b)


def correlation_adjusted_exposure(
    open_trades: list,
    new_instrument: str,
    new_direction: str,
    risk_fraction: float,
) -> float:
    """
    Compute the total effective exposure fraction if a new trade is opened.

    For each existing open trade:
      - If same direction AND positive correlation  → adds corr * risk_fraction
        (they move together → amplified exposure)
      - If opposite direction OR negative correlation → subtracts |corr| * risk_fraction
        (partial hedge → reduced net exposure)

    The new trade itself always contributes +risk_fraction.

    Parameters
    ----------
    open_trades:    list of ForexTrade (must have .instrument, .direction attributes)
    new_instrument: e.g. "EUR_USD"
    new_direction:  "BUY" or "SELL"
    risk_fraction:  e.g. 0.01 (1% per trade)

    Returns
    -------
    float: total effective exposure as fraction of capital (can be > risk_fraction)
    """
    exposure = risk_fraction  # the new trade itself

    for trade in open_trades:
        if trade.status != "open":
            continue
        corr = get_correlation(new_instrument, trade.instrument)
        if corr == 0.0:
            # no known relationship — count it as independent, add full risk
            exposure += risk_fraction
            continue

        same_direction = (trade.direction == new_direction)

        if same_direction and corr > 0:
            # correlated in same direction → additive exposure
            exposure += corr * risk_fraction
        elif (not same_direction) and corr > 0:
            # correlated pair but opposite directions → partial hedge
            exposure -= corr * risk_fraction
        elif same_direction and corr < 0:
            # negatively correlated, same direction → effectively a partial hedge
            # (one leg will likely go up when the other goes down)
            exposure -= abs(corr) * risk_fraction
        else:
            # negatively correlated, opposite directions → additive exposure
            exposure += abs(corr) * risk_fraction

    return max(0.0, exposure)


def usd_concentration_blocked(
    open_trades:       list,
    new_instrument:    str,
    new_direction:     str,
    max_usd_fraction:  float = 0.60,
) -> tuple[bool, str]:
    """
    Block a trade if it would push USD directional concentration above the limit.

    "Directional USD exposure":
      BUY  USD_XXX → long USD
      SELL XXX_USD → long USD
      SELL USD_XXX → short USD
      BUY  XXX_USD → short USD

    Parameters
    ----------
    open_trades:       list of ForexTrade objects
    new_instrument:    e.g. "USD_JPY"
    new_direction:     "BUY" or "SELL"
    max_usd_fraction:  max fraction of portfolio in same USD direction (default 60%)

    Returns
    -------
    (blocked: bool, reason: str)
    """
    def _usd_side(instrument: str, direction: str) -> str:
        parts = instrument.split("_")
        if len(parts) != 2:
            return "NONE"
        base, quote = parts
        if base == "USD":
            return "LONG_USD"  if direction == "BUY"  else "SHORT_USD"
        if quote == "USD":
            return "SHORT_USD" if direction == "BUY"  else "LONG_USD"
        return "NONE"

    new_side = _usd_side(new_instrument, new_direction)
    if new_side == "NONE":
        return False, ""

    active = [t for t in open_trades if t.status == "open"]
    long_usd  = sum(1 for t in active if _usd_side(t.instrument, t.direction) == "LONG_USD")
    short_usd = sum(1 for t in active if _usd_side(t.instrument, t.direction) == "SHORT_USD")
    total     = len(active) + 1  # including the new trade

    count_after = (long_usd + 1) if new_side == "LONG_USD" else (short_usd + 1)
    fraction    = count_after / total

    if fraction > max_usd_fraction:
        return (
            True,
            f"USD {new_side} concentration {fraction*100:.0f}% > "
            f"limit {max_usd_fraction*100:.0f}% "
            f"({count_after}/{total} trades)",
        )
    return False, ""


def correlation_blocked(
    open_trades: list,
    new_instrument: str,
    new_direction: str,
    risk_fraction: float,
    max_exposure: float = 0.03,
) -> tuple[bool, str]:
    """
    Check whether opening a new trade would exceed the maximum allowed
    correlation-adjusted portfolio exposure.

    Parameters
    ----------
    open_trades:    list of ForexTrade objects
    new_instrument: instrument to be opened
    new_direction:  "BUY" or "SELL"
    risk_fraction:  per-trade risk fraction
    max_exposure:   maximum tolerated total effective exposure (default 3%)

    Returns
    -------
    (True, reason_str)  if the trade should be blocked
    (False, "")         if the trade is allowed
    """
    adjusted = correlation_adjusted_exposure(
        open_trades, new_instrument, new_direction, risk_fraction
    )

    if adjusted > max_exposure:
        correlated_pairs = []
        for trade in open_trades:
            if trade.status != "open":
                continue
            corr = get_correlation(new_instrument, trade.instrument)
            if abs(corr) >= 0.65:
                correlated_pairs.append(
                    f"{trade.instrument} {trade.direction} (corr={corr:+.2f})"
                )

        reason = (
            f"Correlation exposure {adjusted*100:.1f}% > limit {max_exposure*100:.1f}%. "
            f"Correlated open trades: {', '.join(correlated_pairs) or 'none'}"
        )
        return True, reason

    return False, ""
