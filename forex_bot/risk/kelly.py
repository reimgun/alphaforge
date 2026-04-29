"""
Kelly Fraction Optimizer — optimale Positionsgröße via Kelly-Kriterium.

Verwendet Quarter-Kelly für Sicherheit:
  Full Kelly    = W - (1-W)/R  (theoretisch optimal, praktisch zu aggressiv)
  Quarter Kelly = Full Kelly × 0.25  (konservativ, empfohlen)

W = Win-Rate
R = Payoff-Ratio (AvgWin / |AvgLoss|)

Gibt Sizing-Faktor relativ zum Standard-Risiko (2%) zurück:
  Quarter Kelly 0.02  → Faktor 1.0×  (Standard)
  Quarter Kelly 0.04  → Faktor 2.0×  (doppeltes Risiko — nur bei starkem Edge)
  Quarter Kelly 0.01  → Faktor 0.5×  (halbes Risiko — schwacher Edge)
"""
from dataclasses import dataclass


@dataclass
class KellyResult:
    full_kelly:    float   # Theoretisch optimale Fraktion
    quarter_kelly: float   # Sichere Fraktion (empfohlen)
    win_rate:      float
    payoff_ratio:  float


class KellyOptimizer:
    """Berechnet optimale Positionsgröße via Kelly-Kriterium."""

    MIN_TRADES    = 10    # Mindest-Trades für valide Berechnung
    MAX_KELLY     = 0.25  # Absolutes Maximum (25% des Kapitals)
    STANDARD_RISK = 0.02  # Standard-Risiko (2%) für Faktor-Normalisierung

    def calculate(
        self,
        win_rate: float,
        avg_win:  float,
        avg_loss: float,
    ) -> KellyResult:
        """
        Berechnet Full Kelly und Quarter Kelly.

        Args:
            win_rate: Anteil gewonnener Trades (0.0–1.0)
            avg_win:  Durchschnittlicher Gewinn (positiv)
            avg_loss: Durchschnittlicher Verlust (negativ oder positiv — abs wird genommen)

        Returns:
            KellyResult mit beiden Fraktionen
        """
        avg_loss_abs = abs(avg_loss) if avg_loss != 0 else 0.001
        payoff_ratio = avg_win / avg_loss_abs if avg_loss_abs > 0 else 1.0

        # Kelly-Formel: f* = W - (1-W)/R
        full_kelly = win_rate - (1 - win_rate) / payoff_ratio

        # Negativer Kelly → kein Edge → kein Trade
        full_kelly = max(0.0, full_kelly)

        # Quarter Kelly + absolute Obergrenze
        quarter_kelly = min(full_kelly * 0.25, self.MAX_KELLY)

        return KellyResult(
            full_kelly    = round(full_kelly, 4),
            quarter_kelly = round(quarter_kelly, 4),
            win_rate      = round(win_rate, 4),
            payoff_ratio  = round(payoff_ratio, 4),
        )

    def get_sizing_factor(self, trades: list[dict]) -> float:
        """
        Gibt den Kelly-Sizing-Faktor relativ zum Standard-Risiko zurück.

        trades: Liste von {"pnl": float}
        Gibt 1.0 zurück wenn zu wenig Trades oder kein Edge.
        Bereich: 0.5× bis 2.0×
        """
        if len(trades) < self.MIN_TRADES:
            return 1.0

        pnls   = [t["pnl"] for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        if not wins or not losses:
            return 1.0

        win_rate = len(wins) / len(pnls)
        avg_win  = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))

        result = self.calculate(win_rate, avg_win, avg_loss)

        # Normalisierung: Quarter Kelly 0.02 → 1.0×
        factor = result.quarter_kelly / self.STANDARD_RISK if self.STANDARD_RISK > 0 else 1.0

        # Clamp: mindestens 0.5×, höchstens 2.0×
        return round(max(0.5, min(2.0, factor)), 2)
