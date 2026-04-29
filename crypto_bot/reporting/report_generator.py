"""
PDF Report Generator — Gaps 20–23.

  Gap 20 — Performance Report:       Vollständiger PDF-Bericht (fpdf2)
  Gap 21 — Strategy Attribution:     PnL-Beitrag pro Strategie
  Gap 22 — Alpha/Beta Decomposition: Jensen's Alpha + Beta vs BTC (Buy&Hold)
  Gap 23 — Regime Exposure Analysis: Zeit im Markt pro Regime

Verwendung:
    from crypto_bot.reporting.report_generator import ReportGenerator
    rg = ReportGenerator()
    rg.generate(trades, capital, symbol, output_path)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("trading_bot")

# Optionale Abhängigkeit: fpdf2
try:
    from fpdf import FPDF
    _FPDF_AVAILABLE = True
except ImportError:
    _FPDF_AVAILABLE = False
    log.debug("fpdf2 nicht installiert — PDF-Reports deaktiviert. pip install fpdf2")


@dataclass
class StrategyAttribution:
    strategy:      str
    n_trades:      int
    total_pnl:     float
    win_rate:      float
    avg_pnl:       float


@dataclass
class AlphaBetaResult:
    alpha:    float   # Jensen's Alpha (annualisiert)
    beta:     float   # Markt-Beta
    r_squared: float  # Fit-Qualität


@dataclass
class RegimeExposure:
    regime:      str
    hours_held:  float
    pnl:         float
    win_rate:    float


class ReportGenerator:
    """
    Erstellt institutionelle PDF-Performance-Reports.

    Abschnitte:
      1. Executive Summary (Kapital, PnL, Sharpe, Win-Rate)
      2. Strategy Attribution (PnL pro Strategie)
      3. Alpha/Beta Decomposition (vs BTC Buy&Hold)
      4. Regime Exposure Analysis (Zeit + Performance pro Regime)
      5. Trade-Liste (letzte 20 Trades)
    """

    PAGE_MARGIN = 15
    TITLE_FONT_SIZE = 16
    HEADER_FONT_SIZE = 12
    BODY_FONT_SIZE = 10
    SMALL_FONT_SIZE = 8

    def generate(
        self,
        trades:       list[dict],
        capital:      float,
        initial_cap:  float,
        symbol:       str = "BTC/USDT",
        output_path:  Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Generiert vollständigen PDF-Report.

        Args:
            trades:      Liste von Trade-Dicts (aus SQLite)
            capital:     Aktuelles Kapital
            initial_cap: Startkapital
            symbol:      Handelspaar
            output_path: Ausgabepfad (None = auto-generiert)

        Returns:
            Pfad zur generierten PDF, oder None wenn fpdf2 nicht verfügbar
        """
        if not _FPDF_AVAILABLE:
            log.warning("fpdf2 nicht installiert — Report übersprungen")
            return None

        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path("reports") / f"trading_report_{ts}.pdf"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Daten berechnen
        summary    = self._calc_summary(trades, capital, initial_cap)
        attribution = self._calc_attribution(trades)
        ab         = self._calc_alpha_beta(trades, initial_cap)
        regime_exp = self._calc_regime_exposure(trades)

        # PDF erstellen
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=self.PAGE_MARGIN)

        self._add_header(pdf, symbol)
        self._add_summary_section(pdf, summary, capital, initial_cap)
        self._add_attribution_section(pdf, attribution)
        self._add_alpha_beta_section(pdf, ab)
        self._add_regime_section(pdf, regime_exp)
        self._add_trade_list(pdf, trades[-20:] if len(trades) > 20 else trades)

        pdf.output(str(output_path))
        log.info(f"PDF-Report erstellt: {output_path}")
        return output_path

    # ── Daten-Berechnung ──────────────────────────────────────────────────────

    def _calc_summary(
        self, trades: list[dict], capital: float, initial_cap: float
    ) -> dict:
        if not trades:
            return {"n_trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
                    "sharpe": 0.0, "max_dd": 0.0}

        pnls     = [t.get("pnl", 0.0) for t in trades if t.get("pnl") is not None]
        wins     = [p for p in pnls if p > 0]
        total    = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0.0

        # Sharpe (annualisiert, 1h Perioden → ×√8760)
        if len(pnls) > 1:
            returns = np.array(pnls) / initial_cap
            sharpe  = float(np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(8760))
        else:
            sharpe = 0.0

        # Max Drawdown
        running = initial_cap
        peak    = initial_cap
        max_dd  = 0.0
        for p in pnls:
            running += p
            peak     = max(peak, running)
            dd       = (peak - running) / peak
            max_dd   = max(max_dd, dd)

        return {
            "n_trades":  len(pnls),
            "win_rate":  round(win_rate * 100, 1),
            "total_pnl": round(total, 2),
            "sharpe":    round(sharpe, 2),
            "max_dd":    round(max_dd * 100, 1),
        }

    @staticmethod
    def _calc_attribution(trades: list[dict]) -> list[StrategyAttribution]:
        from collections import defaultdict
        strategy_trades: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            strat = t.get("ai_source") or t.get("strategy") or "unknown"
            pnl   = t.get("pnl")
            if pnl is not None:
                strategy_trades[strat].append(float(pnl))

        result = []
        for strat, pnls in strategy_trades.items():
            wins = [p for p in pnls if p > 0]
            result.append(StrategyAttribution(
                strategy  = strat,
                n_trades  = len(pnls),
                total_pnl = round(sum(pnls), 2),
                win_rate  = round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
                avg_pnl   = round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
            ))
        return sorted(result, key=lambda x: x.total_pnl, reverse=True)

    @staticmethod
    def _calc_alpha_beta(trades: list[dict], initial_cap: float) -> AlphaBetaResult:
        """Berechnet Jensen's Alpha + Beta vs BTC Buy&Hold."""
        pnls = [t.get("pnl", 0.0) for t in trades if t.get("pnl") is not None]
        if len(pnls) < 5:
            return AlphaBetaResult(0.0, 1.0, 0.0)

        # Bot-Returns
        bot_returns = np.array(pnls) / initial_cap

        # BTC Buy&Hold approximiert via Preisänderungen (aus Trade-Preisen)
        prices = [t.get("price", 0.0) for t in trades if t.get("price", 0.0) > 0]
        if len(prices) >= 2:
            mkt_returns = np.array([
                (prices[i] - prices[i-1]) / prices[i-1]
                for i in range(1, len(prices))
            ])
            # Auf gleiche Länge kürzen
            n = min(len(bot_returns), len(mkt_returns))
            b = bot_returns[-n:]
            m = mkt_returns[-n:]

            try:
                beta      = float(np.cov(b, m)[0, 1] / (np.var(m) + 1e-10))
                rf        = 0.0001   # Risk-free: ~0.01%/Trade
                alpha     = float(np.mean(b) - rf - beta * (np.mean(m) - rf))
                # Annualisieren (8760 Trade-Perioden pro Jahr bei 1h)
                alpha_ann = float(alpha * 8760)
                r2 = float(np.corrcoef(b, m)[0, 1] ** 2) if len(b) >= 3 else 0.0
                return AlphaBetaResult(round(alpha_ann, 4), round(beta, 3), round(r2, 3))
            except Exception:
                pass

        return AlphaBetaResult(0.0, 1.0, 0.0)

    @staticmethod
    def _calc_regime_exposure(trades: list[dict]) -> list[RegimeExposure]:
        from collections import defaultdict
        regime_data: dict[str, list] = defaultdict(list)
        for t in trades:
            r = t.get("regime") or "UNKNOWN"
            p = t.get("pnl")
            if p is not None:
                regime_data[r].append(float(p))

        result = []
        for regime, pnls in regime_data.items():
            wins = [p for p in pnls if p > 0]
            result.append(RegimeExposure(
                regime     = regime,
                hours_held = len(pnls),
                pnl        = round(sum(pnls), 2),
                win_rate   = round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            ))
        return sorted(result, key=lambda x: x.hours_held, reverse=True)

    # ── PDF-Rendering ─────────────────────────────────────────────────────────

    def _add_header(self, pdf: "FPDF", symbol: str) -> None:
        pdf.set_font("Helvetica", "B", self.TITLE_FONT_SIZE)
        pdf.cell(0, 10, f"Trading Performance Report — {symbol}", ln=True, align="C")
        pdf.set_font("Helvetica", "", self.SMALL_FONT_SIZE)
        pdf.cell(0, 6, f"Erstellt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align="C")
        pdf.ln(8)

    def _add_summary_section(
        self, pdf: "FPDF", summary: dict, capital: float, initial_cap: float
    ) -> None:
        self._section_title(pdf, "1. Executive Summary")
        pnl_total = capital - initial_cap
        pnl_pct   = pnl_total / initial_cap * 100

        rows = [
            ("Startkapital",         f"{initial_cap:,.2f} USDT"),
            ("Aktuelles Kapital",    f"{capital:,.2f} USDT"),
            ("Gesamt PnL",           f"{pnl_total:+,.2f} USDT ({pnl_pct:+.1f}%)"),
            ("Anzahl Trades",        str(summary["n_trades"])),
            ("Win-Rate",             f"{summary['win_rate']:.1f}%"),
            ("Sharpe Ratio",         f"{summary['sharpe']:.2f}"),
            ("Max Drawdown",         f"{summary['max_dd']:.1f}%"),
        ]
        self._render_table(pdf, rows)
        pdf.ln(6)

    def _add_attribution_section(self, pdf: "FPDF", attrs: list[StrategyAttribution]) -> None:
        self._section_title(pdf, "2. Strategy Attribution")
        if not attrs:
            pdf.set_font("Helvetica", "", self.BODY_FONT_SIZE)
            pdf.cell(0, 6, "Keine Trade-Daten verfügbar.", ln=True)
            pdf.ln(4)
            return

        headers = ["Strategie", "Trades", "PnL", "Win-Rate", "Ø PnL"]
        col_w   = [60, 20, 35, 30, 35]
        self._table_header(pdf, headers, col_w)
        pdf.set_font("Helvetica", "", self.SMALL_FONT_SIZE)
        for a in attrs[:10]:
            row = [
                a.strategy[:25], str(a.n_trades),
                f"{a.total_pnl:+.2f}", f"{a.win_rate:.0f}%", f"{a.avg_pnl:+.2f}",
            ]
            self._table_row(pdf, row, col_w)
        pdf.ln(6)

    def _add_alpha_beta_section(self, pdf: "FPDF", ab: AlphaBetaResult) -> None:
        self._section_title(pdf, "3. Alpha/Beta Decomposition")
        rows = [
            ("Jensen's Alpha (ann.)", f"{ab.alpha:+.2%}"),
            ("Beta (vs BTC)",         f"{ab.beta:.3f}"),
            ("R²",                    f"{ab.r_squared:.3f}"),
        ]
        self._render_table(pdf, rows)
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", self.SMALL_FONT_SIZE)
        alpha_text = (
            "Positive Alpha: Bot generiert Überrendite vs BTC Buy&Hold."
            if ab.alpha > 0
            else "Negative Alpha: Bot underperformt vs BTC Buy&Hold."
        )
        pdf.cell(0, 5, alpha_text, ln=True)
        pdf.ln(4)

    def _add_regime_section(self, pdf: "FPDF", exposures: list[RegimeExposure]) -> None:
        self._section_title(pdf, "4. Regime Exposure Analysis")
        if not exposures:
            pdf.set_font("Helvetica", "", self.BODY_FONT_SIZE)
            pdf.cell(0, 6, "Keine Regime-Daten verfügbar.", ln=True)
            pdf.ln(4)
            return

        headers = ["Regime", "Trades", "PnL", "Win-Rate"]
        col_w   = [60, 25, 40, 35]
        self._table_header(pdf, headers, col_w)
        pdf.set_font("Helvetica", "", self.SMALL_FONT_SIZE)
        for e in exposures:
            row = [
                e.regime, str(int(e.hours_held)),
                f"{e.pnl:+.2f}", f"{e.win_rate:.0f}%",
            ]
            self._table_row(pdf, row, col_w)
        pdf.ln(6)

    def _add_trade_list(self, pdf: "FPDF", trades: list[dict]) -> None:
        self._section_title(pdf, "5. Letzte Trades")
        if not trades:
            pdf.set_font("Helvetica", "", self.BODY_FONT_SIZE)
            pdf.cell(0, 6, "Keine Trades.", ln=True)
            return

        headers = ["Datum", "Signal", "Preis", "PnL", "Quelle"]
        col_w   = [40, 20, 30, 25, 45]
        self._table_header(pdf, headers, col_w)
        pdf.set_font("Helvetica", "", self.SMALL_FONT_SIZE)
        for t in reversed(trades):
            ts   = str(t.get("created_at", ""))[:16]
            sig  = str(t.get("signal", ""))
            px   = f"{float(t.get('price', 0)):.0f}"
            pnl  = f"{float(t.get('pnl') or 0):+.2f}" if t.get("pnl") else "-"
            src  = str(t.get("ai_source", ""))[:20]
            self._table_row(pdf, [ts, sig, px, pnl, src], col_w)

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    def _section_title(self, pdf: "FPDF", title: str) -> None:
        pdf.set_font("Helvetica", "B", self.HEADER_FONT_SIZE)
        pdf.cell(0, 8, title, ln=True)
        pdf.ln(2)

    def _render_table(self, pdf: "FPDF", rows: list[tuple[str, str]]) -> None:
        pdf.set_font("Helvetica", "", self.BODY_FONT_SIZE)
        for label, value in rows:
            pdf.cell(80, 6, label + ":", border=0)
            pdf.cell(0,  6, value, border=0, ln=True)

    def _table_header(self, pdf: "FPDF", headers: list[str], col_widths: list[int]) -> None:
        pdf.set_font("Helvetica", "B", self.SMALL_FONT_SIZE)
        pdf.set_fill_color(200, 200, 200)
        for h, w in zip(headers, col_widths):
            pdf.cell(w, 6, h, border=1, fill=True)
        pdf.ln()

    @staticmethod
    def _table_row(pdf: "FPDF", cells: list[str], col_widths: list[int]) -> None:
        for val, w in zip(cells, col_widths):
            pdf.cell(w, 5, str(val), border=1)
        pdf.ln()


_report_generator: ReportGenerator | None = None


def get_report_generator() -> ReportGenerator:
    global _report_generator
    if _report_generator is None:
        _report_generator = ReportGenerator()
    return _report_generator
