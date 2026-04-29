"""
Forex Risk Modes — Conservative / Balanced / Aggressive.

Each mode bundles all risk-related parameters so the bot can switch
personality with a single env-var (FOREX_RISK_MODE).
"""
from dataclasses import dataclass


@dataclass
class RiskMode:
    name: str
    risk_per_trade: float       # fraction of capital risked per trade
    max_open_trades: int        # max simultaneous open positions
    min_confidence: float       # minimum signal confidence required
    news_pause_min: int         # minutes to pause around high-impact news
    spread_limit_pips: float    # max allowed spread in pips
    daily_loss_limit: float     # fraction of initial capital (daily loss stop)
    session_strict: bool        # True = only London/NY overlap (13-15 UTC)
    require_mtf: bool           # True = require H4+D1 multi-timeframe confirmation
    consecutive_loss_stop: int  # stop after N consecutive losses
    atr_multiplier: float       # ATR multiplier for stop-loss distance
    rr_ratio: float             # reward:risk ratio for take-profit
    allow_pyramiding: bool      # True = scale into winning trades


RISK_MODES: dict[str, RiskMode] = {
    "conservative": RiskMode(
        name="conservative",
        risk_per_trade=0.005,
        max_open_trades=1,
        min_confidence=0.72,
        news_pause_min=60,
        spread_limit_pips=1.5,
        daily_loss_limit=0.01,
        session_strict=True,
        require_mtf=True,
        consecutive_loss_stop=2,
        atr_multiplier=2.0,
        rr_ratio=2.5,
        allow_pyramiding=False,
    ),
    "balanced": RiskMode(
        name="balanced",
        risk_per_trade=0.01,
        max_open_trades=3,
        min_confidence=0.58,
        news_pause_min=30,
        spread_limit_pips=3.0,
        daily_loss_limit=0.02,
        session_strict=False,
        require_mtf=True,
        consecutive_loss_stop=3,
        atr_multiplier=1.5,
        rr_ratio=2.0,
        allow_pyramiding=True,
    ),
    "aggressive": RiskMode(
        name="aggressive",
        risk_per_trade=0.02,
        max_open_trades=5,
        min_confidence=0.50,
        news_pause_min=15,
        spread_limit_pips=5.0,
        daily_loss_limit=0.04,
        session_strict=False,
        require_mtf=False,
        consecutive_loss_stop=4,
        atr_multiplier=1.5,
        rr_ratio=1.5,
        allow_pyramiding=True,
    ),
}


def get_mode(name: str) -> RiskMode:
    """Return the RiskMode for the given name (case-insensitive). Defaults to 'balanced'."""
    return RISK_MODES.get(name.lower(), RISK_MODES["balanced"])
