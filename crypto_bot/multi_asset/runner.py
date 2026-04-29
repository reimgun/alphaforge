"""
Multi-Asset Runner — handelt gleichzeitig auf mehreren Paaren.

Aktivierung:
    FEATURE_MULTI_PAIR=true
    MULTI_PAIR_COUNT=3              # Anzahl Paare (auto-selektiert)
    MULTI_PAIR_SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT  # oder feste Liste

Architektur:
    - Jedes Pair bekommt einen eigenen RiskManager + PaperTrader/LiveTrader
    - Kapital wird gleichmäßig aufgeteilt (INITIAL_CAPITAL / num_pairs)
    - Paare werden sequentiell in jedem Zyklus abgearbeitet
    - Pair-Rotation: täglich wird select_pairs() neu ausgeführt + Paarliste aktualisiert
    - Portfolio-Level: gesamtes offenes Kapital wird überwacht

Verwendung (aus bot.py):
    from crypto_bot.multi_asset.runner import MultiAssetRunner
    runner = MultiAssetRunner(exchange, decision_engine)
    runner.run_cycle()   # in der Haupt-Schleife
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("trading_bot")


@dataclass
class PairState:
    """Zustand + Ressourcen für ein einzelnes Handelspaar."""
    symbol:      str
    capital:     float
    rm:          Any     # RiskManager
    trader:      Any     # PaperTrader | LiveTrader
    last_signal: str  = "HOLD"
    last_price:  float = 0.0
    pnl_total:   float = 0.0
    trades_today: int  = 0
    active:      bool  = True


class MultiAssetRunner:
    """
    Orchestriert Multi-Pair Trading.

    Lebenszyklus:
        runner = MultiAssetRunner(exchange, engine, trading_mode, initial_capital)
        runner.initialize_pairs()        # einmalig beim Start
        while running:
            runner.run_cycle(df_map)     # {symbol: DataFrame} → einmal pro Intervall
            runner.refresh_pairs_daily() # täglich Paare aktualisieren
    """

    def __init__(
        self,
        exchange,
        decision_engine,
        trading_mode:    str   = "paper",
        initial_capital: float = 5000.0,
        timeframe:       str   = "1h",
    ):
        from crypto_bot.config.settings import (
            MULTI_PAIR_SYMBOLS, MULTI_PAIR_COUNT, MULTI_PAIR_MIN_VOLUME, INITIAL_CAPITAL
        )
        self.exchange         = exchange
        self.engine           = decision_engine
        self.trading_mode     = trading_mode
        self.initial_capital  = initial_capital
        self.timeframe        = timeframe
        self.pair_count       = MULTI_PAIR_COUNT
        self.min_volume       = MULTI_PAIR_MIN_VOLUME
        self.fixed_symbols    = MULTI_PAIR_SYMBOLS  # leer → auto-selektion

        self.pairs: dict[str, PairState] = {}
        self._last_refresh     = datetime.min.replace(tzinfo=timezone.utc)
        self._refresh_interval = 86400   # 24h in Sekunden

    # ── Initialisierung ────────────────────────────────────────────────────────

    def initialize_pairs(self) -> list[str]:
        """Wählt Paare und initialisiert RiskManager + Trader. Gibt Symbol-Liste zurück."""
        symbols = self._select_symbols()
        if not symbols:
            symbols = ["BTC/USDT"]

        capital_per_pair = self.initial_capital / len(symbols)
        log.info(f"Multi-Asset: {len(symbols)} Paare | {capital_per_pair:.0f} USDT pro Pair")

        self.pairs = {}
        for sym in symbols:
            rm, trader = self._create_pair_instances(sym, capital_per_pair)
            self.pairs[sym] = PairState(
                symbol=sym, capital=capital_per_pair, rm=rm, trader=trader
            )
            log.info(f"  Pair initialisiert: {sym} | {capital_per_pair:.0f} USDT")

        self._last_refresh = datetime.now(timezone.utc)
        return symbols

    def _select_symbols(self) -> list[str]:
        """Gibt fixe Liste zurück oder führt auto-Selektion durch."""
        if self.fixed_symbols:
            log.info(f"Multi-Asset: Fixe Paare: {self.fixed_symbols}")
            return self.fixed_symbols

        try:
            from crypto_bot.strategy.pair_selector import select_pairs
            selection = select_pairs(
                exchange=self.exchange,
                max_pairs=self.pair_count,
                min_volume_usdt=self.min_volume,
            )
            symbols = selection.selected
            for ps in selection.scores[:self.pair_count]:
                log.info(f"  Pair-Score: {ps.symbol} = {ps.score:.3f} ({ps.reason})")
            return symbols
        except Exception as e:
            log.warning(f"Pair-Selektion fehlgeschlagen: {e} — Fallback auf BTC/ETH/SOL")
            return ["BTC/USDT", "ETH/USDT", "SOL/USDT"][:self.pair_count]

    def _create_pair_instances(self, symbol: str, capital: float):
        """Erstellt RiskManager + Trader für ein Pair."""
        from crypto_bot.config.settings import (
            MAX_DRAWDOWN_PCT, TRADE_COOLDOWN_MINUTES, MAX_CONSECUTIVE_LOSSES
        )
        from crypto_bot.risk.manager import RiskManager

        rm = RiskManager(
            initial_capital=capital,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            trade_cooldown_minutes=TRADE_COOLDOWN_MINUTES,
            max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
        )

        if self.trading_mode in ("paper", "testnet"):
            from crypto_bot.execution.paper_trader import PaperTrader
            trader = PaperTrader(initial_capital=capital, symbol=symbol)
        else:
            from crypto_bot.execution.live_trader import LiveTrader
            from crypto_bot.data.fetcher import get_exchange as _get_exc
            trader = LiveTrader(exchange=_get_exc(), symbol=symbol)

        return rm, trader

    # ── Trading-Zyklus ────────────────────────────────────────────────────────

    def run_cycle(self, df_map: dict) -> dict:
        """
        Führt einen Trading-Zyklus für alle aktiven Paare aus.

        Args:
            df_map: {symbol: DataFrame} — OHLCV-Daten je Pair

        Returns:
            Ergebnis-Dict: {symbol: {"signal": str, "price": float, "pnl": float}}
        """
        results = {}
        for symbol, state in self.pairs.items():
            if not state.active:
                continue
            df = df_map.get(symbol)
            if df is None or df.empty:
                log.debug(f"Multi-Asset: Keine Daten für {symbol}")
                continue

            try:
                result = self._run_symbol_cycle(symbol, state, df)
                results[symbol] = result
            except Exception as e:
                log.warning(f"Multi-Asset Fehler ({symbol}): {e}")
                results[symbol] = {"signal": "ERROR", "error": str(e)}

        return results

    def _run_symbol_cycle(self, symbol: str, state: PairState, df) -> dict:
        """Vollständiger Trading-Zyklus für ein einzelnes Pair."""
        from crypto_bot.config import features

        current_price = float(df["close"].iloc[-1])
        state.last_price = current_price

        # ── Bestehende Position prüfen ────────────────────────────────────────
        if hasattr(state.trader, "position") and state.trader.position:
            pos = state.trader.position
            unrealized = (current_price - pos.entry_price) / pos.entry_price * pos.size * pos.entry_price
            state.rm.update_unrealized_pnl(unrealized)

            # Stop-Loss prüfen
            if hasattr(state.trader, "check_stop_loss"):
                closed = state.trader.check_stop_loss(current_price)
                if closed:
                    pnl = getattr(closed, "pnl", 0.0)
                    state.pnl_total += pnl
                    state.rm.record_trade(pnl)
                    log.info(f"Multi-Asset {symbol}: Stop-Loss | PnL={pnl:+.2f}")
                    return {"signal": "SELL", "price": current_price, "pnl": pnl, "reason": "stop_loss"}

        # ── Entscheidungs-Engine ──────────────────────────────────────────────
        try:
            decision = self.engine.decide(df, symbol=symbol)
        except TypeError:
            decision = self.engine.decide(df)

        signal = decision.signal if hasattr(decision, "signal") else str(decision)
        state.last_signal = signal

        # ── Risk-Checks ───────────────────────────────────────────────────────
        if state.rm.is_in_cooldown() or state.rm.stoploss_guard_active():
            return {"signal": "BLOCKED", "price": current_price, "pnl": 0.0}

        # ── Order-Ausführung ──────────────────────────────────────────────────
        pnl = 0.0
        if signal == "BUY" and not self._has_open_position(state):
            size = self._calculate_position_size(state, df, current_price)
            if size > 0:
                state.trader.buy(current_price, size=size)
                state.trades_today += 1
                log.info(f"Multi-Asset {symbol}: BUY | Preis={current_price:.4f} | Size={size:.4f}")

        elif signal == "SELL" and self._has_open_position(state):
            closed = state.trader.sell(current_price)
            if closed:
                pnl = getattr(closed, "pnl", 0.0)
                state.pnl_total += pnl
                state.rm.record_trade(pnl)
                state.trades_today += 1
                log.info(f"Multi-Asset {symbol}: SELL | PnL={pnl:+.2f}")

        return {"signal": signal, "price": current_price, "pnl": pnl}

    def _has_open_position(self, state: PairState) -> bool:
        try:
            return bool(getattr(state.trader, "position", None))
        except Exception:
            return False

    def _calculate_position_size(self, state: PairState, df, price: float) -> float:
        """ATR-basierte Positions-Größe (% des Pair-Kapitals)."""
        try:
            from crypto_bot.risk.manager import calculate_atr_position_size
            return calculate_atr_position_size(df, price, state.rm.capital, risk_pct=0.01)
        except Exception:
            return state.rm.capital * 0.02 / price   # 2% Fallback

    # ── Pair-Rotation ─────────────────────────────────────────────────────────

    def refresh_pairs_daily(self) -> bool:
        """
        Aktualisiert Paarliste täglich. Gibt True zurück wenn Paare gewechselt wurden.
        Bestehende Positionen werden dabei respektiert (Pair bleibt bis Position geschlossen).
        """
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_refresh).total_seconds()
        if elapsed < self._refresh_interval:
            return False

        log.info("Multi-Asset: Tägliche Pair-Rotation ...")
        new_symbols = self._select_symbols()
        changed = False

        # Neue Paare hinzufügen
        capital_per_pair = self.initial_capital / max(len(new_symbols), 1)
        for sym in new_symbols:
            if sym not in self.pairs:
                rm, trader = self._create_pair_instances(sym, capital_per_pair)
                self.pairs[sym] = PairState(
                    symbol=sym, capital=capital_per_pair, rm=rm, trader=trader
                )
                log.info(f"  Neues Pair hinzugefügt: {sym}")
                changed = True

        # Alte Paare deaktivieren (wenn keine offene Position)
        for sym in list(self.pairs.keys()):
            if sym not in new_symbols:
                if not self._has_open_position(self.pairs[sym]):
                    del self.pairs[sym]
                    log.info(f"  Pair entfernt: {sym}")
                    changed = True
                else:
                    log.info(f"  Pair {sym} hat offene Position — bleibt aktiv bis zum Schließen")

        self._last_refresh = now
        return changed

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Gibt Portfolio-Status zurück (für Dashboard/API)."""
        total_capital = sum(s.rm.capital for s in self.pairs.values())
        total_pnl     = sum(s.pnl_total  for s in self.pairs.values())
        open_positions = sum(1 for s in self.pairs.values() if self._has_open_position(s))

        return {
            "active_pairs":   list(self.pairs.keys()),
            "total_capital":  round(total_capital, 2),
            "total_pnl":      round(total_pnl, 2),
            "open_positions": open_positions,
            "pairs": {
                sym: {
                    "capital":     round(s.rm.capital, 2),
                    "pnl":         round(s.pnl_total, 2),
                    "last_signal": s.last_signal,
                    "last_price":  s.last_price,
                    "has_position": self._has_open_position(s),
                }
                for sym, s in self.pairs.items()
            },
        }
