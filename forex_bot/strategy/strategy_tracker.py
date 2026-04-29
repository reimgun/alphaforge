"""
Strategy Performance Tracker.

Verfolgt pro Strategie: Win-Rate, Pips, PnL.
Gibt Confidence-Multiplikatoren zurück — schwache Strategien werden
abgeschwächt, gute Strategien bekommen einen Boost.

Spiegelt ai/strategy_tracker.py aus dem Crypto-Bot für Forex.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("forex_bot")

_SAVE_PATH = Path(__file__).parent.parent / "data_store" / "strategy_tracker.json"

_MIN_TRADES_FOR_SCORING = 8    # Mindest-Trades für Scoring
_UNDERPERFORM_PIPS      = -3.0  # Avg-Pips unter diesem Wert → schwache Strategie
_RECENT_WINDOW          = 20    # Sliding Window für Recent-Metriken


@dataclass
class StrategyStats:
    name:         str
    total_trades: int   = 0
    wins:         int   = 0
    total_pips:   float = 0.0
    recent_pips:  list  = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.5

    @property
    def avg_pips(self) -> float:
        return self.total_pips / self.total_trades if self.total_trades else 0.0

    @property
    def recent_avg_pips(self) -> float:
        return sum(self.recent_pips) / len(self.recent_pips) if self.recent_pips else 0.0

    def confidence_multiplier(self) -> float:
        """
        Confidence-Multiplikator basierend auf historischer Performance.

        ≥ 60% WR + avg_pips > 3 pips → 1.25× (hervorragend)
        ≥ 50% WR                     → 1.10× (gut)
        40–50% WR                    → 1.00× (neutral)
        30–40% WR                    → 0.85× (schwach)
        < 30% WR ODER avg < -3 Pips → 0.70× (schlecht)
        """
        if self.total_trades < _MIN_TRADES_FOR_SCORING:
            return 1.0  # Noch nicht genug Daten

        wr = self.win_rate
        ap = self.recent_avg_pips

        if wr >= 0.60 and ap > 3.0: return 1.25
        if wr >= 0.50:              return 1.10
        if wr >= 0.40:              return 1.00
        if wr >= 0.30:              return 0.85
        return 0.70

    def is_underperforming(self) -> bool:
        """True wenn Strategie konsistent schlecht abschneidet."""
        return (
            self.total_trades >= _MIN_TRADES_FOR_SCORING
            and self.recent_avg_pips < _UNDERPERFORM_PIPS
        )


class ForexStrategyTracker:
    """Verfolgt die Performance jeder Forex-Strategie."""

    def __init__(self):
        self._stats: dict[str, StrategyStats] = {
            "ema_crossover":  StrategyStats("ema_crossover"),
            "breakout":       StrategyStats("breakout"),
            "mean_reversion": StrategyStats("mean_reversion"),
        }
        self._load()

    def record_trade(self, strategy: str, pnl_pips: float, was_win: bool) -> None:
        """
        Registriert einen abgeschlossenen Trade für eine Strategie.

        Parameters
        ----------
        strategy:  Strategie-Name ("ema_crossover", "breakout", "mean_reversion")
        pnl_pips:  Realisierte Pips (positiv = Gewinn)
        was_win:   True wenn Trade profitabel war
        """
        if strategy not in self._stats:
            self._stats[strategy] = StrategyStats(strategy)

        s = self._stats[strategy]
        s.total_trades += 1
        s.total_pips   += pnl_pips
        if was_win:
            s.wins += 1

        s.recent_pips.append(pnl_pips)
        if len(s.recent_pips) > _RECENT_WINDOW:
            s.recent_pips.pop(0)

        mult = s.confidence_multiplier()
        log.info(
            f"StrategyTracker [{strategy}]: "
            f"trades={s.total_trades} WR={s.win_rate:.0%} "
            f"avg={s.avg_pips:.1f}pip recent={s.recent_avg_pips:.1f}pip "
            f"mult={mult:.2f}×"
        )

        if s.is_underperforming():
            log.warning(
                f"⚠️ [{strategy}] underperformt: "
                f"recent_avg={s.recent_avg_pips:.1f} Pips — mult={mult:.2f}×"
            )

        self._save()

    def get_multiplier(self, strategy: str) -> float:
        """Gibt den Confidence-Multiplikator für eine Strategie zurück."""
        s = self._stats.get(strategy)
        return s.confidence_multiplier() if s else 1.0

    def get_summary(self) -> dict:
        """Dashboard-Zusammenfassung aller Strategien."""
        return {
            name: {
                "trades":          s.total_trades,
                "win_rate":        round(s.win_rate * 100, 1),
                "avg_pips":        round(s.avg_pips, 1),
                "recent_avg_pips": round(s.recent_avg_pips, 1),
                "multiplier":      s.confidence_multiplier(),
                "underperforming": s.is_underperforming(),
            }
            for name, s in self._stats.items()
        }

    # ── Persistenz ────────────────────────────────────────────────────────────

    def _save(self):
        try:
            _SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                name: {
                    "total_trades": s.total_trades,
                    "wins":         s.wins,
                    "total_pips":   s.total_pips,
                    "recent_pips":  s.recent_pips,
                }
                for name, s in self._stats.items()
            }
            _SAVE_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.debug(f"StrategyTracker save failed: {e}")

    def _load(self):
        try:
            if not _SAVE_PATH.exists():
                return
            data = json.loads(_SAVE_PATH.read_text())
            for name, d in data.items():
                if name not in self._stats:
                    self._stats[name] = StrategyStats(name)
                s = self._stats[name]
                s.total_trades = d.get("total_trades", 0)
                s.wins         = d.get("wins", 0)
                s.total_pips   = d.get("total_pips", 0.0)
                s.recent_pips  = d.get("recent_pips", [])
        except Exception as e:
            log.debug(f"StrategyTracker load failed: {e}")
