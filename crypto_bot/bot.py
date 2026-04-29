"""
Haupt-Bot — vollständig integriert.
Verwendung:
  python bot.py           — Bot starten (liest .env)
  python bot.py --check   — System-Check, kein Trading
  python bot.py --paper   — Paper-Modus erzwingen
  python bot.py --live    — Live-Modus erzwingen
"""
import sys
import time
import argparse
import platform
import signal as signal_module
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent

import os  # noqa: E402 — muss vor config-imports stehen (für --paper/--live)
from crypto_bot.data.fetcher import fetch_ohlcv, fetch_current_price, fetch_funding_rate, fetch_orderbook_features
from crypto_bot.data.ws_streamer import BinanceWSStreamer
from crypto_bot.data.onchain import get_onchain_feature_dict
from crypto_bot.ai.decision_engine import DecisionEngine
from crypto_bot.ai.retrainer import AutoRetrainer
from crypto_bot.ai.confidence_monitor import try_auto_transition
from crypto_bot.risk.manager import RiskManager
from crypto_bot.execution.paper_trader import PaperTrader
from crypto_bot.execution.live_trader import LiveTrader
from crypto_bot.monitoring.logger import init_db, log, log_signal, log_event, save_performance_snapshot, log_rejection
from crypto_bot.monitoring import alerts
from crypto_bot.monitoring.heartbeat import get_heartbeat
from crypto_bot.monitoring.telegram_dashboard import TelegramDashboard
from crypto_bot.config.settings import (
    SYMBOL, TIMEFRAME, TRADING_MODE, INITIAL_CAPITAL,
    AI_MODE, MAX_DRAWDOWN_PCT, ALLOW_SHORT,
)
from crypto_bot.config import features as features  # Feature-Flag System

console   = Console()
_running  = True
_bot_state: dict = {
    "capital":              INITIAL_CAPITAL,
    "daily_pnl":            0.0,
    "position":             None,
    "unrealized_pnl":       0.0,
    "running":              True,
    "stop_requested":       False,
    "paused":               False,
    "start_requested":      False,
    "training_mode":        False,
    "volatility_regime":    "UNKNOWN",
    "risk_mode":            "balanced",
    "last_rejection":       None,
    "drift_status":         None,
    "strategy_performance": {},
    "last_explanation":     None,   # TradeExplanation narrative
    "scanner_results":      {},     # Letzter Pair-Scanner Run
}


def _signal_handler(sig, frame):
    global _running
    console.print("\n[bold yellow]Shutdown — Bot wird sauber beendet...[/bold yellow]")
    log_event("Shutdown-Signal empfangen", "shutdown")
    _running = False


def _auto_train_if_needed() -> None:
    """
    Startet automatisch das ML-Training wenn kein Modell vorhanden ist.
    Wird einmalig beim Bot-Start aufgerufen (GAP 1 — Self-Learning Mode).
    """
    if AI_MODE not in ("ml", "combined"):
        return

    model_path = Path(BASE_DIR) / "ai" / "model.joblib"
    if model_path.exists():
        return   # Modell vorhanden — kein Auto-Training nötig

    console.print(Panel(
        "Kein ML-Modell gefunden.\n"
        "Starte automatisches Training — dies dauert 3-5 Minuten...\n"
        "Der Bot beginnt danach automatisch mit dem Trading.",
        title="🎓 Training Mode",
        style="bold yellow",
    ))
    log_event("Auto-Training gestartet (kein Modell vorhanden)", "training")
    _bot_state["training_mode"] = True

    try:
        from crypto_bot.ai.trainer import train
        train()
        log_event("Auto-Training erfolgreich abgeschlossen", "training")
        console.print("[bold green]Training abgeschlossen — Bot startet jetzt...[/bold green]")
    except Exception as e:
        log_event(f"Auto-Training fehlgeschlagen: {e}", "training", "error")
        console.print(f"[bold red]Training fehlgeschlagen: {e}[/bold red]")
        console.print("[yellow]Fallback: AI_MODE wird auf 'rules' gesetzt[/yellow]")
        os.environ["AI_MODE"] = "rules"
        import crypto_bot.config.settings as cfg
        cfg.AI_MODE = "rules"
    finally:
        _bot_state["training_mode"] = False


def _get_trader(rm: RiskManager):
    if TRADING_MODE == "live":
        console.print("[bold red]LIVE MODUS — echtes Geld![/bold red]")
        return LiveTrader(rm)
    if TRADING_MODE == "testnet":
        console.print("[bold yellow]TESTNET MODUS — Binance Testnet (virtuelles Geld, echte API)[/bold yellow]")
        return LiveTrader(rm)   # LiveTrader nutzt get_exchange() → sandbox_mode=True
    console.print("[bold cyan]PAPER MODUS — lokale Simulation mit Gebühren-Simulation[/bold cyan]")
    return PaperTrader(rm)


def run():
    global _running

    init_db()
    signal_module.signal(signal_module.SIGINT,  _signal_handler)
    signal_module.signal(signal_module.SIGTERM, _signal_handler)

    console.print(Panel(
        f"Symbol: {SYMBOL} | Timeframe: {TIMEFRAME}\n"
        f"Modus:  {TRADING_MODE.upper()} | AI: {AI_MODE.upper()}\n"
        f"Kapital: {INITIAL_CAPITAL:.2f} USDT",
        title="BTC/USDT AI Trading Bot",
        style="bold blue",
    ))

    # ── Auto-Training beim ersten Start ─────────────────────────────────────
    _auto_train_if_needed()

    rm        = RiskManager(capital=INITIAL_CAPITAL)
    trader    = _get_trader(rm)

    # Exchange-Verbindungsstatus setzen
    if isinstance(trader, LiveTrader):
        try:
            from crypto_bot.data.fetcher import get_exchange
            _ex = get_exchange()
            _ex.fetch_ticker(SYMBOL)
            _bot_state["exchange_connected"] = True
            _bot_state["exchange_error"]     = ""
            _bot_state["exchange"]           = getattr(_ex, "id", "binance")
        except Exception as _ce:
            _bot_state["exchange_connected"] = False
            _bot_state["exchange_error"]     = str(_ce)
            _bot_state["exchange"]           = "binance"
    else:
        _bot_state["exchange_connected"] = None  # Paper — kein Login nötig
        _bot_state["exchange"]           = "binance"

    # ── State wiederherstellen (Paper-Modus: Kapital + Position über Restarts) ─
    if TRADING_MODE == "paper" and isinstance(trader, PaperTrader):
        if trader.restore_state():
            # Kapital aus persistiertem State übernehmen
            _bot_state["capital"] = trader.rm.capital
            log_event(
                f"Paper-State wiederhergestellt: Kapital={trader.rm.capital:.2f} USDT"
                + (f" | Position={trader.rm.position.side.upper()}" if trader.rm.position else ""),
                "startup",
            )

    # ── Live State Reconciliation (P0) — Position nach Crash/Restart wiederherstellen ─
    # Kritisch: verhindert doppeltes Kaufen oder unbekannte offene Positionen
    elif TRADING_MODE in ("live", "testnet") and isinstance(trader, LiveTrader):
        try:
            restored = trader.restore_live_state()
            if restored and rm.position:
                _bot_state["capital"]  = rm.capital
                _bot_state["position"] = rm.position
                console.print(
                    f"[bold yellow]⚠ Live State: offene {rm.position.side.upper()}-Position "
                    f"aus letzter Session erkannt ({rm.position.quantity:.6f} BTC)[/bold yellow]"
                )
        except Exception as _e:
            log_event(f"Live State Reconciliation fehlgeschlagen: {_e}", "startup", "error")
            console.print(f"[bold red]Live State Reconciliation fehlgeschlagen: {_e}[/bold red]")

    engine    = DecisionEngine()
    retrainer = AutoRetrainer()
    dashboard = TelegramDashboard(_bot_state)
    dashboard.start()

    # Round 5: Strategy Tracker + Kelly Optimizer
    from crypto_bot.ai.strategy_tracker import StrategyTracker
    from crypto_bot.risk.kelly import KellyOptimizer
    strategy_tracker = StrategyTracker()
    kelly_optimizer  = KellyOptimizer()
    _active_strategy_name: str = "unknown"

    # Round 6: Online Learning + Tail Risk + Portfolio Optimizer
    if features.ONLINE_LEARNING:
        from crypto_bot.ai.online_learner import OnlineLearningPipeline
        online_learner = OnlineLearningPipeline()
    else:
        online_learner = None

    # RL Agent (Q-Learning als zweite Signal-Quelle)
    _rl_agent = None
    if features.RL_AGENT:
        try:
            from crypto_bot.ai.rl_agent import QLearningAgent, BaseRLAgent
            _rl_agent = QLearningAgent()
            rl_path = Path(__file__).parent / "ai" / "rl_agent.pkl"
            if rl_path.exists():
                _rl_agent.load(rl_path)
            log.info("RL Agent geladen")
        except Exception as e:
            log.warning(f"RL Agent nicht verfügbar: {e}")
            _rl_agent = None

    # Signal Bus (Multi-Bot Kommunikation)
    _signal_bus = None
    if features.SIGNAL_BUS:
        try:
            from crypto_bot.signals.bus import get_bus
            _signal_bus = get_bus("crypto_bot")
            log.info("Signal Bus aktiv")
        except Exception as e:
            log.warning(f"Signal Bus nicht verfügbar: {e}")

    # Tax Journal (FIFO, lädt bei Start aus DB)
    if features.TAX_JOURNAL:
        try:
            from crypto_bot.reporting.tax_journal import get_tax_journal
            _tax_journal = get_tax_journal()
            loaded = _tax_journal.load_from_db()
            log.info(f"Tax Journal: {loaded} Trades geladen")
        except Exception as e:
            log.warning(f"Tax Journal nicht verfügbar: {e}")

    if features.TAIL_RISK:
        from crypto_bot.risk.black_swan import get_tail_risk_manager
        tail_risk_mgr = get_tail_risk_manager()
    else:
        tail_risk_mgr = None

    if features.PORTFOLIO_OPTIMIZER:
        from crypto_bot.ai.portfolio_optimizer import get_allocator
        portfolio_alloc = get_allocator()
    else:
        portfolio_alloc = None

    _auto_risk_downgraded: bool = False   # Flag: auto-switch war aktiv

    # Wire StrategyTracker into DecisionEngine for confidence multiplier
    if features.STRATEGY_TRACKER:
        engine.set_strategy_tracker(strategy_tracker)

    # ── Round 8: Advanced Features ────────────────────────────────────────────
    if features.MICROSTRUCTURE:
        from crypto_bot.strategy.microstructure import get_microstructure
        _microstructure = get_microstructure()
    else:
        _microstructure = None

    if features.DERIVATIVES_SIGNALS:
        from crypto_bot.strategy.derivatives import get_derivatives
        _derivatives = get_derivatives()
    else:
        _derivatives = None

    if features.CROSS_MARKET:
        from crypto_bot.ai.cross_market import get_cross_market
        _cross_market = get_cross_market()
    else:
        _cross_market = None

    if features.REGIME_FORECASTER:
        from crypto_bot.ai.regime_forecaster import get_regime_forecaster
        _regime_forecaster = get_regime_forecaster()
        _last_regime_for_forecaster: str | None = None
    else:
        _regime_forecaster = None
        _last_regime_for_forecaster = None

    if features.GROWTH_OPTIMIZER:
        from crypto_bot.risk.growth_optimizer import get_growth_optimizer
        _growth_optimizer = get_growth_optimizer()
    else:
        _growth_optimizer = None

    if features.VENUE_OPTIMIZER:
        from crypto_bot.execution.venue_optimizer import get_venue_optimizer
        _venue_optimizer = get_venue_optimizer()
    else:
        _venue_optimizer = None

    if features.RESILIENCE:
        from crypto_bot.monitoring.resilience import get_resilience
        _resilience = get_resilience(primary="binance")
    else:
        _resilience = None

    if features.STRATEGY_LIFECYCLE:
        from crypto_bot.ai.strategy_lifecycle import get_lifecycle_manager
        _lifecycle_mgr = get_lifecycle_manager()
    else:
        _lifecycle_mgr = None

    if features.OPPORTUNITY_RADAR:
        from dashboard.opportunity_radar import get_opportunity_radar
        _opp_radar = get_opportunity_radar()
    else:
        _opp_radar = None

    # ── Round 9: Model Governance + Simulation + Stress + Allocator + Funding ──
    if features.MODEL_GOVERNANCE:
        from crypto_bot.ai.model_governance import get_model_governance
        _model_governance = get_model_governance()
    else:
        _model_governance = None

    if features.REGIME_SIMULATION:
        from crypto_bot.ai.regime_simulation import get_regime_simulation
        _regime_simulation = get_regime_simulation()
    else:
        _regime_simulation = None

    if features.STRESS_TESTER:
        from crypto_bot.risk.stress_tester import get_stress_tester
        _stress_tester = get_stress_tester()
    else:
        _stress_tester = None

    if features.CAPITAL_ALLOCATOR:
        from crypto_bot.risk.capital_allocator import get_capital_allocator
        _capital_allocator = get_capital_allocator()
    else:
        _capital_allocator = None

    if features.FUNDING_TERM_STRUCTURE:
        from crypto_bot.strategy.funding_term_structure import get_funding_term_structure
        _funding_ts = get_funding_term_structure()
    else:
        _funding_ts = None

    # ── Round 10: Fear & Greed + News Sentiment ───────────────────────────────
    if features.FEAR_GREED:
        from crypto_bot.strategy.fear_greed import get_fear_greed
        _fear_greed = get_fear_greed()
    else:
        _fear_greed = None

    if features.NEWS_SENTIMENT:
        from crypto_bot.ai.news_sentiment import get_news_sentiment
        _news_sentiment = get_news_sentiment()
    else:
        _news_sentiment = None

    # ── Round 11: Global Exposure Controller ──────────────────────────────────
    if features.GLOBAL_EXPOSURE:
        from crypto_bot.risk.global_exposure_controller import get_exposure_controller
        _exposure_ctrl = get_exposure_controller()
        dashboard.register_exposure_controller(_exposure_ctrl)
    else:
        _exposure_ctrl = None

    # ── Multi-Asset Runner (FEATURE_MULTI_PAIR=true) ─────────────────────────
    _multi_runner = None
    if features.MULTI_PAIR:
        try:
            from crypto_bot.multi_asset.runner import MultiAssetRunner
            from crypto_bot.data.fetcher import get_exchange as _get_exc_ma
            _ma_exchange = None
            try:
                _ma_exchange = _get_exc_ma()
            except Exception as _mae:
                log.debug(f"Multi-Asset Exchange-Init: {_mae}")
            _multi_runner = MultiAssetRunner(
                exchange=_ma_exchange,
                decision_engine=engine,
                trading_mode=TRADING_MODE,
                initial_capital=INITIAL_CAPITAL,
                timeframe=TIMEFRAME,
            )
            _ma_symbols = _multi_runner.initialize_pairs()
            console.print(
                f"[bold cyan]Multi-Asset Mode: {len(_ma_symbols)} Paare aktiv — "
                f"{', '.join(_ma_symbols)}[/bold cyan]"
            )
            log_event(f"Multi-Asset aktiviert: {_ma_symbols}", "startup")
            _bot_state["multi_asset"] = _multi_runner.get_status()
        except Exception as _mae_init:
            log.warning(f"Multi-Asset Init fehlgeschlagen: {_mae_init} — Single-Pair Fallback")
            _multi_runner = None

    # ── Gap 2: Continuous Market Scanner Thread ───────────────────────────────
    import threading
    from crypto_bot.config.settings import SCANNER_INTERVAL_HOURS
    _scanner_results: dict = {}

    if features.SCANNER:
        def _scanner_loop():
            """Scannt kontinuierlich Binance nach Top-Paaren alle SCANNER_INTERVAL_HOURS Stunden."""
            import time as _time
            while _running:
                try:
                    from crypto_bot.strategy.pair_selector import select_pairs
                    from crypto_bot.data.fetcher import get_exchange as _get_exchange
                    try:
                        _scan_exchange = _get_exchange()
                    except Exception as _ex:
                        log.debug(f"Pair Scanner: Exchange-Init fehlgeschlagen: {_ex}")
                        _scan_exchange = None
                    sel = select_pairs(exchange=_scan_exchange)
                    if sel and sel.scores:
                        top = [p.symbol for p in sel.scores[:5]]
                        _scanner_results["top_pairs"]  = top
                        _scanner_results["scores"]     = {p.symbol: p.score for p in sel.scores[:5]}
                        _scanner_results["last_scan"]  = datetime.now(timezone.utc).isoformat()
                        log_event(f"Scanner: Top-Paare {top}", "scanner")
                        console.print(f"[dim]Scanner: Top-Paare: {', '.join(top)}[/dim]")
                except Exception as e:
                    log.debug(f"Scanner-Thread Fehler: {e}")
                _time.sleep(SCANNER_INTERVAL_HOURS * 3600)

        _scanner_thread = threading.Thread(target=_scanner_loop, daemon=True, name="pair-scanner")
        _scanner_thread.start()

    # WebSocket Streaming (echte Preise, < 1s Latenz)
    streamer = BinanceWSStreamer(SYMBOL, TIMEFRAME)
    streamer.start()

    alerts.alert_bot_started(TRADING_MODE, INITIAL_CAPITAL)
    log_event(f"Bot gestartet | {TRADING_MODE.upper()} | {AI_MODE.upper()}", "startup")

    interval_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
    interval     = interval_map.get(TIMEFRAME, 3600)

    # ── Dead Man's Switch ────────────────────────────────────────────────────
    # max_silence = Cycle-Zeit + 30min Buffer (verhindert False-Positives beim Schlafen)
    heartbeat = get_heartbeat(max_silence_minutes=int(interval / 60 + 30))
    heartbeat.start()
    live_preds: list[dict] = []
    last_summary_date = datetime.now(timezone.utc).date()

    while _running:

        # Telegram /stop Command prüfen
        if _bot_state.get("stop_requested"):
            log_event("Stop via Telegram", "shutdown")
            break

        # Training-Mode-Restart (Dashboard "Restart Training" oder Telegram /retrain)
        if _bot_state.get("training_mode"):
            _bot_state["training_mode"] = False
            console.print("[bold yellow]Training-Mode aktiviert — starte Retraining...[/bold yellow]")
            log_event("Training Mode Restart angefordert", "training")
            try:
                from crypto_bot.ai.trainer import train
                train()
                log_event("Training Mode Restart abgeschlossen", "training")
            except Exception as e:
                log_event(f"Training Mode Restart fehlgeschlagen: {e}", "training", "error")
                console.print(f"[bold red]Training fehlgeschlagen: {e}[/bold red]")

        # Telegram /start: aus Pause fortsetzen oder ignorieren wenn aktiv
        if _bot_state.get("start_requested"):
            _bot_state["start_requested"] = False
            if _bot_state.get("paused"):
                _bot_state["paused"] = False
                log_event("Bot via Telegram /start fortgesetzt", "resume")

        # Protection-Reset via Dashboard
        if _bot_state.get("reset_protection_requested"):
            _bot_state["reset_protection_requested"] = False
            rm.reset_cooldown()
            log_event("Trade Cooldown + StoplossgGuard manuell zurückgesetzt", "risk")
            console.print("[bold green]Protection zurückgesetzt — Trading wieder erlaubt[/bold green]")

        # Pause-Modus: Monitoring läuft weiter, kein Trading
        if _bot_state.get("paused"):
            console.print("[dim]⏸  Bot pausiert — warte...[/dim]")
            time.sleep(interval)
            continue

        try:
            # ── Heartbeat-Ping (Dead Man's Switch) ───────────────────────────────
            heartbeat.ping()

            # ── Log-Level aus Dashboard-Datei lesen (dynamisch änderbar) ────────
            _level_file = BASE_DIR / "data_store" / "log_level.txt"
            if _level_file.exists():
                import logging as _logging
                _lvl_str = _level_file.read_text().strip().upper()
                _lvl_num = getattr(_logging, _lvl_str, None)
                if _lvl_num is not None and log.level != _lvl_num:
                    log.setLevel(_lvl_num)
                    _logging.getLogger().setLevel(_lvl_num)

            now = datetime.now(timezone.utc)
            console.print(f"\n[dim]{now.strftime('%Y-%m-%d %H:%M:%S UTC')}[/dim]")

            # ── Max-Drawdown-Stopp (Risk-Mode-abhängig) ───────────────────────
            total_loss_pct = (INITIAL_CAPITAL - rm.capital) / INITIAL_CAPITAL
            if total_loss_pct >= rm.effective_max_drawdown:
                alerts.alert_max_drawdown(total_loss_pct * 100, rm.capital)
                log_event(f"MAX DRAWDOWN {total_loss_pct*100:.1f}%", "max_drawdown", "critical")
                console.print(f"[bold red]MAX DRAWDOWN {total_loss_pct*100:.1f}% — Bot gestoppt![/bold red]")
                break

            # ── Tages-Circuit-Breaker ─────────────────────────────────────────
            if rm.is_circuit_breaker_active():
                alerts.alert_circuit_breaker(rm.daily_loss, rm.capital)
                console.print("[bold red]CIRCUIT BREAKER — pausiert bis morgen[/bold red]")
                time.sleep(interval)
                continue

            # ── StoplossgGuard + Trade Cooldown (Status-Log, Blocking am Entry) ──
            if rm.is_stoploss_guard_active():
                console.print(f"[bold red]STOPLOSS GUARD aktiv: {rm._consecutive_losses} Verluste in Folge — kein neues Trading[/bold red]")
                _bot_state["last_rejection"] = {"reason": f"StoplossgGuard: {rm._consecutive_losses} Verluste in Folge", "signal": "BLOCKED", "source": "risk"}
            elif rm.is_in_cooldown():
                remaining = rm.cooldown_remaining_minutes()
                console.print(f"[yellow]COOLDOWN: {remaining:.0f} min bis nächster Trade[/yellow]")
                _bot_state["last_rejection"] = {"reason": f"Trade Cooldown: {remaining:.0f} min", "signal": "COOLDOWN", "source": "risk"}

            # ── Marktdaten: REST-History + WebSocket-Overlay ─────────────────
            # REST liefert vollständige History (gecacht + inkrementell aktualisiert).
            # WebSocket überschreibt die letzten Candles mit Live-Daten (<1s Latenz).
            # Kombination aus beiden ergibt immer aktuelle Daten ohne 50h Wartezeit.
            df = fetch_ohlcv(SYMBOL, TIMEFRAME, days=60)
            ws_df = streamer.get_latest_df()
            if ws_df is not None and not ws_df.empty:
                import pandas as _pd
                combined = _pd.concat([df, ws_df])
                combined = combined[~combined.index.duplicated(keep="last")]
                df = combined.sort_index()
                _data_source = f"REST+WebSocket"
            else:
                _data_source = "REST"
            current_price = float(df["close"].iloc[-1])
            _last_candle_age = (datetime.now(timezone.utc) - df.index[-1].to_pydatetime()).total_seconds() / 60
            log.debug(f"Daten: {_data_source} | {len(df)} Candles | letzter Candle {_last_candle_age:.0f} min alt | Preis {current_price:.2f}")
            console.print(f"[dim]Datenquelle: {_data_source} ({len(df)} Candles, {_last_candle_age:.0f} min alt)[/dim]")

            # ── Externe Features injizieren (Funding Rate, Orderbook, On-Chain) ─
            # Werden als Spalten in df geschrieben → features.py kann sie aufnehmen.
            # Feature-Flag-gesteuert, Fehler nicht kritisch.
            if features.FUNDING_RATE:
                try:
                    _funding = fetch_funding_rate(SYMBOL)
                    df["funding_rate"] = _funding
                    log.debug(f"Funding Rate: {_funding:.6f}")
                except Exception as _e:
                    log.debug(f"Funding Rate Injektion: {_e}")

            if features.ORDER_BOOK:
                try:
                    _ob_feat = fetch_orderbook_features(SYMBOL)
                    for _col, _val in _ob_feat.items():
                        df[_col] = _val
                    console.print(
                        f"[dim]OB: imb={_ob_feat['orderbook_imbalance']:+.3f} "
                        f"imb5={_ob_feat['orderbook_imbalance_5']:+.3f} "
                        f"spread={_ob_feat['bid_ask_spread_bps']:.1f}bps[/dim]"
                    )
                except Exception as _e:
                    log.debug(f"Orderbook Injektion: {_e}")

            if features.ONCHAIN_DATA:
                try:
                    _onchain = get_onchain_feature_dict()
                    for _col, _val in _onchain.items():
                        df[_col] = _val
                    if abs(_onchain.get("onchain_score", 0)) > 0.1:
                        console.print(
                            f"[dim]On-Chain: score={_onchain['onchain_score']:+.2f} | "
                            f"MVRV={_onchain['onchain_mvrv_proxy']:.2f} "
                            f"HashTrend={_onchain['onchain_hash_rate_trend']:+.2f}[/dim]"
                        )
                except Exception as _e:
                    log.debug(f"On-Chain Injektion: {_e}")

            # ── Trailing Stop / SL aktualisieren ─────────────────────────────
            if rm.has_open_position():
                if isinstance(trader, PaperTrader):
                    trader.update_stops(current_price)
                elif isinstance(trader, LiveTrader):
                    trader.update_stops(current_price)

                # Unrealized PnL für Dashboard
                _bot_state["unrealized_pnl"] = rm.position.unrealized_pnl(current_price) \
                    if rm.position else 0.0

            # ── AI Entscheidung ───────────────────────────────────────────────
            decision = engine.decide(df)

            # Volatility Regime für Dashboard ermitteln
            vol_regime_str = "NORMAL"
            try:
                from crypto_bot.ai.volatility_forecaster import get_forecaster
                vol_fc = get_forecaster().forecast(df)
                vol_regime_str = vol_fc.regime
                _bot_state["volatility_regime"] = vol_fc.regime
            except Exception:
                pass

            # ── Gap 27: Auto Risk Mode Switching ─────────────────────────────
            import crypto_bot.config.settings as _cfg_live
            current_mode = getattr(_cfg_live, "RISK_MODE", "balanced")
            if vol_regime_str == "EXTREME" and current_mode != "conservative":
                _cfg_live.RISK_MODE = "conservative"
                _auto_risk_downgraded = True
                console.print("[bold yellow]AUTO: Volatilität EXTREME → Risk-Mode auf 'conservative' gesetzt[/bold yellow]")
                log_event("Auto Risk-Mode → conservative (EXTREME Volatilität)", "risk")
            elif vol_regime_str not in ("HIGH", "EXTREME") and _auto_risk_downgraded:
                _cfg_live.RISK_MODE = "balanced"
                _auto_risk_downgraded = False
                console.print("[dim]Auto Risk-Mode wiederhergestellt → 'balanced'[/dim]")
                log_event("Auto Risk-Mode → balanced (Volatilität normalisiert)", "risk")
            _bot_state["risk_mode"] = getattr(_cfg_live, "RISK_MODE", "balanced")

            log_signal(
                symbol=SYMBOL, signal=decision.signal,
                price=current_price, ai_source=decision.source,
                confidence=decision.confidence, reasoning=decision.reasoning,
            )

            regime_name = decision.regime.regime if decision.regime else "?"
            vol_regime  = _bot_state.get("volatility_regime", "?")
            console.print(
                f"Signal: [bold]{decision.signal}[/bold] | "
                f"Konfidenz: {decision.confidence:.0%} | {decision.source} | "
                f"Regime: {regime_name} | Vol: {vol_regime}\n"
                f"  → {decision.reasoning}"
            )
            # Kompakter INFO-Sammellog — immer sichtbar unabhängig vom Log-Level
            log.info(
                f"LOOP {SYMBOL} | {current_price:.2f} USDT | "
                f"Signal={decision.signal} conf={decision.confidence:.0%} src={decision.source} | "
                f"Regime={regime_name} Vol={vol_regime} | "
                f"Capital={rm.capital:.2f} | Daten={_data_source} ({_last_candle_age:.0f}min)"
            )
            log.debug(f"  Reasoning: {decision.reasoning}")

            # Erklärung im State speichern (für Dashboard/Telegram)
            if decision.explanation:
                _bot_state["last_explanation"] = decision.explanation.narrative

            # Aktive Strategie aus Source ableiten und im Tracker merken
            strategy_name = decision.source.split("+")[0] if decision.source else "unknown"
            strategy_tracker.set_active_strategy(strategy_name)

            # Kelly-Faktor aktualisieren (basierend auf letzten Trades)
            rm.kelly_factor = kelly_optimizer.get_sizing_factor(rm.trades[-50:] if rm.trades else [])

            # Strategy retired? → HOLD erzwingen
            if strategy_tracker.is_strategy_retired(strategy_name) and decision.signal != "HOLD":
                console.print(f"[yellow]Strategie '{strategy_name}' ruht (schlechte Performance) → HOLD[/yellow]")
                log_rejection(SYMBOL, decision.signal, current_price,
                              f"Strategie '{strategy_name}' ruht", decision.source, strategy_name)
                _bot_state["last_rejection"] = {
                    "reason": f"Strategie '{strategy_name}' ruht — schlechte historische Performance",
                    "signal": decision.signal, "source": decision.source,
                }
                decision = type(decision)(
                    signal="HOLD", confidence=0.0, source=decision.source,
                    reasoning=f"Strategie '{strategy_name}' ruht",
                    regime=decision.regime, trend=decision.trend,
                    regime_factor=decision.regime_factor, atr=decision.atr,
                )

            # ── Round 8: Microstructure Analysis ─────────────────────────────
            if _microstructure is not None:
                try:
                    ms_analysis = _microstructure.analyze(df)
                    _bot_state["microstructure"] = {
                        "signal_bias": ms_analysis.signal_bias,
                        "confidence":  ms_analysis.confidence,
                        "cvd_trend":   ms_analysis.cvd.cvd_trend,
                        "pressure":    ms_analysis.cvd.pressure,
                    }
                    log.debug(f"Microstructure: bias={ms_analysis.signal_bias} conf={ms_analysis.confidence:.0%} cvd={ms_analysis.cvd.cvd_trend} pressure={ms_analysis.cvd.pressure}")
                    if ms_analysis.signal_bias != "NEUTRAL":
                        console.print(f"[dim]Microstructure: {ms_analysis.signal_bias} "
                                      f"(conf {ms_analysis.confidence:.0%})[/dim]")
                except Exception as e:
                    log.debug(f"Microstructure Fehler: {e}")

            # ── Round 8: Cross-Market Analysis ───────────────────────────────
            if _cross_market is not None:
                try:
                    cm_analysis = _cross_market.analyze(df)
                    _bot_state["cross_market"] = {
                        "market_regime": cm_analysis.market_regime,
                        "sentiment":     cm_analysis.sentiment.sentiment,
                        "fg_proxy":      cm_analysis.sentiment.fear_greed_proxy,
                    }
                    log.debug(f"Cross-Market: regime={cm_analysis.market_regime} sentiment={cm_analysis.sentiment.sentiment} fg_proxy={cm_analysis.sentiment.fear_greed_proxy:.0f}")
                    console.print(f"[dim]Cross-Market: {cm_analysis.market_regime} | "
                                  f"Sentiment: {cm_analysis.sentiment.sentiment}[/dim]")
                except Exception as e:
                    log.debug(f"Cross-Market Fehler: {e}")

            # ── Round 10: Fear & Greed Index ──────────────────────────────────
            _fg_result = None
            if _fear_greed is not None:
                try:
                    _fg_result = _fear_greed.fetch()
                    _bot_state["fear_greed"] = {
                        "value":           _fg_result.value,
                        "label":           _fg_result.label,
                        "position_factor": _fg_result.position_factor,
                        "block_buy":       _fg_result.block_buy,
                    }
                    log.debug(f"Fear & Greed: value={_fg_result.value} label={_fg_result.label} factor={_fg_result.position_factor:.2f} block_buy={_fg_result.block_buy}")
                    if _fg_result.value < 25 or _fg_result.value >= 75:
                        console.print(
                            f"[{'red' if _fg_result.block_buy else 'yellow'}]"
                            f"Fear & Greed: {_fg_result.value} — {_fg_result.label} "
                            f"(Faktor ×{_fg_result.position_factor})[/]"
                        )
                except Exception as e:
                    log.debug(f"Fear & Greed Fehler: {e}")

            # ── Round 10: News Sentiment ───────────────────────────────────────
            _sentiment_result = None
            if _news_sentiment is not None:
                try:
                    _sentiment_result = _news_sentiment.analyze()
                    _bot_state["news_sentiment"] = {
                        "score":           _sentiment_result.score,
                        "label":           _sentiment_result.label,
                        "position_factor": _sentiment_result.position_factor,
                        "block_buy":       _sentiment_result.block_buy,
                        "summary":         _sentiment_result.summary,
                        "headlines":       _sentiment_result.headlines[:3],
                        "method":          _sentiment_result.method,
                    }
                    log.debug(f"News Sentiment: score={_sentiment_result.score:+.2f} label={_sentiment_result.label} factor={_sentiment_result.position_factor:.2f} block_buy={_sentiment_result.block_buy} method={_sentiment_result.method}")
                    if abs(_sentiment_result.score) > 0.15:
                        console.print(
                            f"[dim]News Sentiment: {_sentiment_result.label} "
                            f"(score {_sentiment_result.score:+.2f}) — {_sentiment_result.summary}[/dim]"
                        )
                except Exception as e:
                    log.debug(f"News Sentiment Fehler: {e}")

            # ── Round 8: Derivatives Signals ──────────────────────────────────
            _deriv_funding_rate = 0.0001   # Default: 0.01%/8h
            if _derivatives is not None:
                try:
                    deriv_analysis = _derivatives.analyze(df)
                    _deriv_funding_rate = getattr(deriv_analysis.funding, "current_rate", 0.0001)
                    _bot_state["derivatives"] = {
                        "combined_signal": deriv_analysis.combined_signal,
                        "funding_regime":  deriv_analysis.funding.regime,
                        "funding_rate":    _deriv_funding_rate,
                    }
                    log.debug(f"Derivatives: signal={deriv_analysis.combined_signal} funding_regime={deriv_analysis.funding.regime} rate={_deriv_funding_rate:.6f}")
                    if deriv_analysis.combined_signal != "NEUTRAL":
                        console.print(f"[dim]Derivatives: {deriv_analysis.combined_signal} | "
                                      f"Funding: {deriv_analysis.funding.regime}[/dim]")
                except Exception as e:
                    log.debug(f"Derivatives Fehler: {e}")

            # ── Round 8: Regime Forecaster ────────────────────────────────────
            if _regime_forecaster is not None:
                try:
                    regime_forecast = _regime_forecaster.forecast(df, regime_name)
                    if _last_regime_for_forecaster and _last_regime_for_forecaster != regime_name:
                        _regime_forecaster.update(_last_regime_for_forecaster, regime_name)
                    _last_regime_for_forecaster = regime_name
                    _bot_state["regime_forecast"] = {
                        "bias":           regime_forecast.recommended_bias,
                        "persist_pct":    regime_forecast.persistence.persistence_pct,
                        "breakout_prob":  regime_forecast.breakout.probability,
                        "mr_probability": regime_forecast.mean_reversion.probability,
                    }
                    log.debug(f"Regime Forecast: bias={regime_forecast.recommended_bias} persist={regime_forecast.persistence.persistence_pct:.0f}% breakout={regime_forecast.breakout.probability:.0%} mr={regime_forecast.mean_reversion.probability:.0%}")
                    console.print(f"[dim]Regime Forecast: {regime_forecast.recommended_bias} | "
                                  f"Persist {regime_forecast.persistence.persistence_pct:.0f}%[/dim]")
                except Exception as e:
                    log.debug(f"Regime Forecaster Fehler: {e}")

            # ── Round 8: Venue Optimizer ──────────────────────────────────────
            if _venue_optimizer is not None:
                try:
                    venue_rec = _venue_optimizer.recommend()
                    _bot_state["venue"] = {
                        "best": venue_rec.best_venue,
                        "savings_bps": venue_rec.savings_bps,
                    }
                except Exception as e:
                    log.debug(f"Venue Optimizer Fehler: {e}")

            # ── Round 9: Funding Term Structure ───────────────────────────────
            if _funding_ts is not None:
                try:
                    _funding_ts.update(_deriv_funding_rate)
                    fts_result = _funding_ts.analyze(_deriv_funding_rate)
                    _bot_state["funding_ts"] = {
                        "structure":       fts_result.term_structure.structure,
                        "combined_signal": fts_result.combined_signal,
                        "carry_signal":    fts_result.carry.signal,
                        "net_carry":       fts_result.carry.net_carry,
                    }
                    log.debug(f"Funding TS: structure={fts_result.term_structure.structure} signal={fts_result.combined_signal} carry={fts_result.carry.signal} net_carry={fts_result.carry.net_carry:.6f}")
                    if fts_result.combined_signal != "NEUTRAL":
                        console.print(f"[dim]Funding TS: {fts_result.combined_signal} | "
                                      f"{fts_result.term_structure.structure}[/dim]")
                except Exception as e:
                    log.debug(f"Funding Term Structure Fehler: {e}")

            # ── Round 9: Regime Simulation ────────────────────────────────────
            _regime_sim_factor = 1.0   # Default exposure factor
            if _regime_simulation is not None:
                try:
                    trans_matrix = {}
                    if _regime_forecaster is not None:
                        try:
                            trans_matrix = _regime_forecaster.markov.transition_matrix()
                        except Exception:
                            pass
                    sim_result = _regime_simulation.run(regime_name, trans_matrix)
                    _regime_sim_factor = sim_result.exposure_factor
                    _bot_state["regime_simulation"] = {
                        "dominant_regime": sim_result.regime_sim.dominant_regime,
                        "exposure_factor": sim_result.exposure_factor,
                        "bias":            sim_result.proactive_bias,
                        "high_vol_prob":   sim_result.vol_regime.high_vol_prob,
                    }
                    log.debug(f"Regime Sim: dominant={sim_result.regime_sim.dominant_regime} bias={sim_result.proactive_bias} exposure={sim_result.exposure_factor:.0%} high_vol_prob={sim_result.vol_regime.high_vol_prob:.0%}")
                    if sim_result.proactive_bias != "HOLD":
                        console.print(f"[dim]Regime Sim: {sim_result.proactive_bias} | "
                                      f"Exposure {sim_result.exposure_factor:.0%}[/dim]")
                except Exception as e:
                    log.debug(f"Regime Simulation Fehler: {e}")

            # ── Round 9: Stress Test ──────────────────────────────────────────
            _stress_factor = 1.0
            if _stress_tester is not None:
                try:
                    stop_price  = rm.position.stop_loss  if rm.has_open_position() and rm.position else 0.0
                    entry_price = rm.position.entry_price if rm.has_open_position() and rm.position else 0.0
                    stress_result = _stress_tester.run(
                        df               = df,
                        current_price    = current_price,
                        position_usd     = rm.capital * 0.1,
                        stop_loss_price  = stop_price,
                        entry_price      = entry_price,
                        normal_spread_bps = 2.0,
                    )
                    _stress_factor = stress_result.stress_factor
                    _bot_state["stress_test"] = {
                        "factor":   stress_result.stress_factor,
                        "severity": stress_result.severity,
                    }
                    log.debug(f"Stress Test: severity={stress_result.severity} factor={stress_result.stress_factor:.0%}")
                    if stress_result.severity in ("HIGH", "CRITICAL"):
                        console.print(f"[yellow]Stress Test: {stress_result.severity} "
                                      f"(factor {stress_result.stress_factor:.0%})[/yellow]")
                except Exception as e:
                    log.debug(f"Stress Tester Fehler: {e}")

            # ── Gap 14-16: Tail-Risk Check vor Trade ─────────────────────────
            if tail_risk_mgr is not None:
                tail_risk = tail_risk_mgr.assess(df, vol_regime_str)
                if tail_risk.is_black_swan or tail_risk.is_liquidity_crash:
                    console.print(f"[bold red]TAIL RISK: {tail_risk.reason} — kein Trade[/bold red]")
                    log_event(f"Tail-Risk erkannt: {tail_risk.reason}", "tail_risk", "warning")
                    log_rejection(SYMBOL, decision.signal, current_price,
                                  f"Tail-Risk: {tail_risk.reason}", decision.source, strategy_name)
                    _bot_state["last_rejection"] = {
                        "reason": f"Tail-Risk: {tail_risk.reason}",
                        "signal": decision.signal, "source": decision.source,
                    }
                    decision = type(decision)(
                        signal="HOLD", confidence=0.0, source=decision.source,
                        reasoning=f"Tail-Risk blockiert Trade: {tail_risk.reason}",
                        regime=decision.regime, trend=decision.trend,
                        regime_factor=decision.regime_factor * tail_risk.recommended_leverage,
                        atr=decision.atr,
                    )

            # ── Gap 4: Platt-Calibration + Bayesian Adjustment vor BUY ─────────
            explanation_narrative = ""
            if decision.explanation:
                explanation_narrative = getattr(decision.explanation, "narrative", "")

            if decision.signal == "BUY" and not rm.has_open_position():
                if online_learner is not None:
                    try:
                        raw_probs = {"BUY": decision.confidence,
                                     "HOLD": max(0.0, 1.0 - decision.confidence - 0.1),
                                     "SELL": 0.1}
                        adj_conf, cal_probs = online_learner.get_adjusted_confidence(
                            decision.source, decision.confidence, raw_probs,
                        )
                        if abs(adj_conf - decision.confidence) > 0.01:
                            console.print(
                                f"[dim]Platt+Bayes: conf {decision.confidence:.0%} → {adj_conf:.0%}[/dim]"
                            )
                    except Exception:
                        adj_conf = decision.confidence
                else:
                    adj_conf = decision.confidence

                # RL Agent: zweite Meinung — Confidence-Boost oder -Malus
                if _rl_agent is not None:
                    try:
                        from crypto_bot.ai.rl_agent import BaseRLAgent
                        obs = BaseRLAgent.build_observation(df_window, has_position=False,
                                                            confidence=adj_conf)
                        rl_signal = _rl_agent.get_signal(obs)
                        if rl_signal == "BUY":
                            adj_conf = min(1.0, adj_conf * 1.05)   # +5% Boost
                        elif rl_signal == "SELL":
                            adj_conf = adj_conf * 0.85              # -15% Malus
                        _bot_state["rl_signal"] = rl_signal
                        log.debug(f"RL Agent: {rl_signal} → adj_conf={adj_conf:.2%}")
                    except Exception:
                        pass

                # Signal Bus: publiziere BUY-Signal für andere Bots
                if _signal_bus is not None:
                    try:
                        _signal_bus.publish("BUY", SYMBOL, confidence=adj_conf,
                                            price=float(df_window.iloc[-1]["close"]))
                    except Exception:
                        pass

            # ── Round 9: Model Governance — Uncertainty-based sizing ─────────
            if _model_governance is not None and decision.signal == "BUY":
                try:
                    raw_probs = {
                        "BUY":  decision.confidence,
                        "HOLD": max(0.0, 1.0 - decision.confidence - 0.1),
                        "SELL": 0.1,
                    }
                    gov_result = _model_governance.evaluate(
                        probs       = raw_probs,
                        importances = {},
                        base_size   = rm.kelly_factor,
                    )
                    if gov_result.entropy.low_confidence:
                        rm.kelly_factor = gov_result.size_factor
                        console.print(f"[dim]Model Governance: entropy {gov_result.entropy.normalised:.0%} "
                                      f"→ size {gov_result.size_factor:.1%}[/dim]")
                    _bot_state["model_governance"] = {
                        "entropy":        gov_result.entropy.normalised,
                        "low_confidence": gov_result.entropy.low_confidence,
                        "calibration_ok": not gov_result.cal_drift.degraded,
                    }
                except Exception as e:
                    log.debug(f"Model Governance Fehler: {e}")

            # ── Round 8: Growth Optimizer — Positionsgröße ───────────────────
            if _growth_optimizer is not None and decision.signal == "BUY":
                try:
                    growth_result = _growth_optimizer.compute(
                        base_size      = rm.kelly_factor,
                        equity_peak    = max(rm.capital, INITIAL_CAPITAL),
                        current_equity = rm.capital,
                    )
                    rm.kelly_factor = growth_result.final_size
                    _growth_optimizer.update_equity(rm.capital)
                    log.debug(f"Growth Optimizer: size={growth_result.final_size:.1%} regime={growth_result.exposure.regime}")
                    console.print(f"[dim]Growth Optimizer: size {growth_result.final_size:.1%} "
                                  f"({growth_result.exposure.regime})[/dim]")
                except Exception as e:
                    log.debug(f"Growth Optimizer Fehler: {e}")

            # ── Round 9: Capital Allocator — finales Allokations-Cap ─────────
            if _capital_allocator is not None and decision.signal == "BUY":
                try:
                    ms_bias     = _bot_state.get("microstructure", {}).get("signal_bias", "NEUTRAL")
                    cm_regime   = _bot_state.get("cross_market", {}).get("market_regime", "NEUTRAL")
                    persist_pct = _bot_state.get("regime_forecast", {}).get("persist_pct", 50.0)
                    ms_score, cm_score, rs_score = _capital_allocator.get_score_from_signals(
                        ms_bias, cm_regime, persist_pct
                    )
                    vol_30d = float(df["close"].pct_change().std() * (252 ** 0.5))
                    dd_pct  = max(0.0, (INITIAL_CAPITAL - rm.capital) / INITIAL_CAPITAL)
                    alloc_result = _capital_allocator.allocate(
                        regime               = regime_name,
                        microstructure_score = ms_score,
                        cross_market_score   = cm_score,
                        regime_score         = rs_score,
                        volatility_30d       = vol_30d,
                        drawdown_pct         = dd_pct,
                        stress_factor        = _stress_factor * _regime_sim_factor,
                    )
                    rm.kelly_factor = min(rm.kelly_factor, alloc_result.final_allocation)
                    _bot_state["capital_allocator"] = {
                        "allocation": alloc_result.final_allocation,
                        "tier":       alloc_result.signal_quality.tier,
                    }
                    log.debug(f"Capital Allocator: alloc={alloc_result.final_allocation:.0%} tier={alloc_result.signal_quality.tier} kelly→{rm.kelly_factor:.0%}")
                    console.print(f"[dim]Capital Allocator: {alloc_result.final_allocation:.0%} "
                                  f"(Tier {alloc_result.signal_quality.tier})[/dim]")
                except Exception as e:
                    log.debug(f"Capital Allocator Fehler: {e}")

            # ── Round 10: Fear & Greed + Sentiment Filter (vor BUY) ─────────────
            if decision.signal == "BUY" and not rm.has_open_position():
                # Fear & Greed: Positionsgröße anpassen oder BUY blockieren
                if _fg_result is not None:
                    if _fg_result.block_buy:
                        reason_fg = f"Extreme Greed ({_fg_result.value}) — kein BUY"
                        console.print(f"[bold yellow]Fear & Greed: {reason_fg}[/bold yellow]")
                        log_rejection(SYMBOL, "BUY", current_price, reason_fg, decision.source, strategy_name)
                        _bot_state["last_rejection"] = {"reason": reason_fg, "signal": "BUY", "source": decision.source}
                        decision = type(decision)(
                            signal="HOLD", confidence=0.0, source=decision.source,
                            reasoning=reason_fg, regime=decision.regime, trend=decision.trend,
                            regime_factor=decision.regime_factor, atr=decision.atr,
                        )
                    elif _fg_result.position_factor < 1.0:
                        rm.kelly_factor = round(rm.kelly_factor * _fg_result.position_factor, 4)
                        console.print(f"[dim]Fear & Greed: kelly ×{_fg_result.position_factor} "
                                      f"→ {rm.kelly_factor:.1%}[/dim]")

                # News Sentiment: BUY blockieren oder Größe reduzieren
                if _sentiment_result is not None and decision.signal == "BUY":
                    if _sentiment_result.block_buy:
                        reason_ns = f"Stark bearishes Sentiment ({_sentiment_result.label}) — kein BUY"
                        console.print(f"[bold yellow]Sentiment: {reason_ns}[/bold yellow]")
                        log_rejection(SYMBOL, "BUY", current_price, reason_ns, decision.source, strategy_name)
                        _bot_state["last_rejection"] = {"reason": reason_ns, "signal": "BUY", "source": decision.source}
                        decision = type(decision)(
                            signal="HOLD", confidence=0.0, source=decision.source,
                            reasoning=reason_ns, regime=decision.regime, trend=decision.trend,
                            regime_factor=decision.regime_factor, atr=decision.atr,
                        )
                    elif _sentiment_result.position_factor < 1.0:
                        rm.kelly_factor = round(rm.kelly_factor * _sentiment_result.position_factor, 4)
                        console.print(f"[dim]Sentiment: kelly ×{_sentiment_result.position_factor} "
                                      f"→ {rm.kelly_factor:.1%}[/dim]")

            # ── Round 11: Global Exposure Controller ─────────────────────────
            _exposure_state = None
            if _exposure_ctrl is not None:
                from crypto_bot.risk.global_exposure_controller import ExposureInputs
                _drawdown_pct = max(
                    0.0, (INITIAL_CAPITAL - rm.capital) / max(INITIAL_CAPITAL, 1) * 100
                )
                _exp_inputs = ExposureInputs(
                    regime              = regime_name,
                    vol_regime          = _bot_state.get("volatility_regime", "NORMAL"),
                    fear_greed_value    = (_fg_result.value if _fg_result else 50),
                    ml_confidence       = decision.confidence,
                    stress_factor       = 1.0 - _stress_factor,
                    drawdown_pct        = _drawdown_pct,
                    microstructure_bias = _bot_state.get("microstructure", {}).get("signal_bias", "NEUTRAL"),
                    news_sentiment      = (_sentiment_result.score if _sentiment_result else 0.0),
                    regime_sim_factor   = _regime_sim_factor,
                    funding_extreme     = _bot_state.get("derivatives", {}).get("funding_extreme", False),
                )
                _exposure_state = _exposure_ctrl.compute(_exp_inputs)
                log.debug(f"Exposure: mode={_exposure_state.mode} factor={_exposure_state.exposure_factor:.0%} risk_off={_exposure_state.risk_off} crisis={_exposure_state.crisis_score:.0%} reason={_exposure_state.reason}")

                # Exposure-Faktor auf Kelly anwenden
                if _exposure_state.exposure_factor < 1.0:
                    rm.kelly_factor = round(rm.kelly_factor * _exposure_state.exposure_factor, 4)
                    console.print(
                        f"[dim]Exposure [{_exposure_state.mode}]: "
                        f"kelly ×{_exposure_state.exposure_factor:.0%} | {_exposure_state.reason}[/dim]"
                    )

                # Risk-Off: BUY blockieren
                if _exposure_state.risk_off and decision.signal == "BUY":
                    reason_exp = f"Exposure Controller: {_exposure_state.reason}"
                    console.print(f"[bold red]RISK-OFF: {reason_exp}[/bold red]")
                    log_rejection(SYMBOL, "BUY", current_price, reason_exp, "exposure", strategy_name)
                    _bot_state["last_rejection"] = {
                        "reason": reason_exp, "signal": "BUY", "source": "exposure_controller"
                    }
                    decision = type(decision)(
                        signal="HOLD", confidence=0.0, source="exposure_controller",
                        reasoning=reason_exp, regime=decision.regime, trend=decision.trend,
                        regime_factor=decision.regime_factor, atr=decision.atr,
                    )

                _bot_state["exposure"] = {
                    "factor":        _exposure_state.exposure_factor,
                    "mode":          _exposure_state.mode,
                    "crisis_score":  _exposure_state.crisis_score,
                    "recovery_score": _exposure_state.recovery_score,
                    "risk_off":      _exposure_state.risk_off,
                    "reason":        _exposure_state.reason,
                    "allocation": {
                        "trend":          _exposure_state.trend_allocation,
                        "mean_reversion": _exposure_state.mean_reversion_allocation,
                        "volatility":     _exposure_state.volatility_allocation,
                        "arbitrage":      _exposure_state.arbitrage_allocation,
                    },
                }

            # ── Trade ausführen ───────────────────────────────────────────────
            acted = False

            # BUY: Long eröffnen ODER Short schließen (Cover)
            if decision.signal == "BUY" and rm.has_short_position() and isinstance(trader, PaperTrader):
                # Short covern (BUY-Signal schließt offene Short-Position)
                cover_result = trader.cover(current_price, reason=f"Cover: {decision.reasoning}",
                                            ai_source=decision.source,
                                            explanation=explanation_narrative)
                acted = True
                retrainer.record_trade()
                pnl_realized = cover_result.get("pnl", 0.0)
                strategy_tracker.record_trade_result(pnl_realized, strategy_name)

            elif decision.signal == "BUY" and not rm.has_open_position():
                # ── Cooldown & StoplossgGuard prüfen ─────────────────────────
                if rm.is_stoploss_guard_active():
                    log_rejection(SYMBOL, "BUY", current_price,
                                  f"StoplossgGuard: {rm._consecutive_losses} konsekutive Verluste",
                                  decision.source, strategy_name)
                    continue
                if rm.is_in_cooldown():
                    log_rejection(SYMBOL, "BUY", current_price,
                                  f"Trade Cooldown: {rm.cooldown_remaining_minutes():.0f} min",
                                  decision.source, strategy_name)
                    continue

                # Kelly-Faktor-Untergrenze: verhindert winzige Positionen durch
                # gestapelte Multiplikatoren (Fear/Greed × Sentiment × Exposure)
                rm.kelly_factor = max(rm.kelly_factor, 0.05)
                buy_result = trader.buy(
                    current_price,
                    reason=decision.reasoning,
                    atr=decision.atr,
                    regime_factor=decision.regime_factor,
                    explanation=explanation_narrative,
                )
                if buy_result is not None:
                    acted = True
                    retrainer.record_trade()

            # SELL: Long schließen (+ Post-Trade-Tracking)
            elif decision.signal == "SELL" and rm.has_long_position():
                sell_result  = trader.sell(current_price, reason=decision.reasoning,
                                           ai_source=decision.source,
                                           explanation=explanation_narrative)
                acted = True
                retrainer.record_trade()
                pnl_realized = sell_result.get("pnl", 0.0)
                # Prediction für Retrainer aufzeichnen
                live_preds.append({"predicted": "SELL", "actual_pnl": pnl_realized})
                strategy_tracker.record_trade_result(pnl_realized, strategy_name)

                # ── Gap 11-13: Online Learning Update ────────────────────────
                if online_learner is not None:
                    try:
                        closes = df["close"].tail(6).pct_change().dropna()
                        rsi_val = float(closes.rolling(5).mean().iloc[-1]) if len(closes) >= 5 else 0.0
                        vol_ratio = float(df["volume"].iloc[-1] / df["volume"].tail(20).mean())
                        regime_enc = {"BULL_TREND": 1, "BEAR_TREND": -1, "SIDEWAYS": 0, "HIGH_VOL": 2}.get(
                            (decision.regime.regime if decision.regime else "SIDEWAYS"), 0
                        )
                        feat_vec = [
                            float(df["close"].pct_change(1).iloc[-1]),
                            float(df["close"].pct_change(4).iloc[-1]),
                            rsi_val, vol_ratio, float(regime_enc),
                        ]
                        online_learner.process_trade_outcome(
                            features=feat_vec, signal="SELL", source=decision.source,
                            raw_confidence=decision.confidence, was_profitable=pnl_realized > 0,
                        )
                    except Exception as e:
                        log.debug(f"Online Learning Update Fehler: {e}")

                if _growth_optimizer is not None:
                    try:
                        _growth_optimizer.update_trade(pnl_realized / max(rm.capital, 1.0))
                    except Exception as e:
                        log.debug(f"Growth Optimizer Trade-Update Fehler: {e}")

                if _lifecycle_mgr is not None:
                    try:
                        _lifecycle_mgr.record_trade(strategy_name, pnl_realized / max(rm.capital, 1.0))
                    except Exception as e:
                        log.debug(f"Lifecycle Manager Update Fehler: {e}")

            elif (decision.signal == "SELL" and not rm.has_open_position()
                  and ALLOW_SHORT and isinstance(trader, PaperTrader)):
                # Short eröffnen (kein offener Trade, Signal = SELL, Short erlaubt)
                rm.kelly_factor = max(rm.kelly_factor, 0.05)
                short_result = trader.short(
                    current_price,
                    reason=decision.reasoning,
                    atr=decision.atr,
                    regime_factor=decision.regime_factor,
                    explanation=explanation_narrative,
                )
                if short_result is not None:
                    acted = True
                    retrainer.record_trade()
                    log.info(f"SHORT eröffnet: {short_result.quantity:.6f} BTC @ {current_price:.2f}")

            elif decision.signal == "SELL" and rm.has_open_position() and not rm.has_long_position():
                pass   # Bereits Short — kein weiterer Trade

            elif decision.signal == "HOLD":
                # Trade Rejection Log: nur wenn wir eigentlich handeln wollten (kein leeres Signal)
                if decision.reasoning and decision.source not in ("anomaly", "regime"):
                    log_rejection(SYMBOL, "HOLD", current_price,
                                  decision.reasoning, decision.source, strategy_name)
                    _bot_state["last_rejection"] = {
                        "reason": decision.reasoning,
                        "signal": "HOLD",
                        "source": decision.source,
                    }

            # ── Auto Paper→Live Transition (nur aus Paper-Modus, nie aus Testnet) ──
            if TRADING_MODE == "paper":
                try:
                    model_f1 = retrainer.last_val_f1 if hasattr(retrainer, "last_val_f1") else 0.0
                    switched = try_auto_transition(rm, model_f1=model_f1, bot_state=_bot_state)
                    if switched:
                        console.print("[bold green]Live-Transition AKTIVIERT — handelt jetzt mit echtem Kapital![/bold green]")
                        log_event("Live-Transition bestätigt und aktiviert", "transition")
                    elif _bot_state.get("live_transition_pending"):
                        console.print(
                            "\n[bold yellow]"
                            "══════════════════════════════════════════════════\n"
                            "  Live-Trading Kriterien ERFÜLLT!\n"
                            "  Der Bot wartet auf deine Bestätigung.\n"
                            "  → Telegram: /approve_live\n"
                            "  → Dashboard: Schaltfläche 'Live bestätigen'\n"
                            "  Der Bot bleibt im Paper-Modus bis zur Bestätigung.\n"
                            "══════════════════════════════════════════════════"
                            "[/bold yellow]\n"
                        )
                except Exception as e:
                    log.debug(f"Auto-Transition Check fehlgeschlagen: {e}")

            # ── Manuelles Retraining (Dashboard / Telegram /retrain) ─────────
            if _bot_state.get("retrain_requested") and AI_MODE in ("ml", "combined"):
                _bot_state["retrain_requested"] = False
                log.info("Manuelles Retraining angefordert — starte...")
                log_event("Manuelles Retraining gestartet", "retraining")
                retrainer.check_and_maybe_retrain(live_preds)

            # ── Auto-Retraining + Drift Detection ────────────────────────────
            if (retrainer.should_check() or retrainer.should_check_by_time()) \
                    and AI_MODE in ("ml", "combined"):
                retrainer.check_and_maybe_retrain(live_preds)
                # Drift-Check auf aktueller Live-Accuracy
                if live_preds:
                    recent = live_preds[-20:]
                    correct = sum(
                        1 for p in recent
                        if (p.get("predicted") == "BUY"  and p.get("actual_pnl", 0) > 0)
                        or (p.get("predicted") == "SELL" and p.get("actual_pnl", 0) < 0)
                        or p.get("predicted") == "HOLD"
                    )
                    acc = correct / len(recent)
                    drift = retrainer.check_drift(acc)
                    _bot_state["drift_status"] = {
                        "has_drift":   drift.has_drift,
                        "current_f1":  drift.current_f1,
                        "baseline_f1": drift.baseline_f1,
                        "drift_pct":   drift.drift_pct,
                    }

            # ── Dashboard-State aktualisieren ─────────────────────────────────
            import crypto_bot.config.settings as _cfg
            _bot_state.update({
                "capital":              rm.capital,
                "daily_pnl":           -rm.daily_loss,
                "position":             rm.position,
                "running":              _running,
                "current_price":        current_price,
                "regime":               regime_name,
                "ai_confidence":        decision.confidence,
                "risk_mode":            getattr(_cfg, "RISK_MODE", "balanced"),
                "strategy_performance": strategy_tracker.get_summary(),
                "scanner_results":      _scanner_results,
                "rm_summary":           rm.summary(),
                "last_update":          datetime.now(timezone.utc).isoformat(),
            })

            # ── State-Datei schreiben (für Dashboard-Container auf QNAP) ──────
            try:
                import json as _json
                _state_path = Path(BASE_DIR) / "data_store" / "bot_state.json"
                _serializable = {
                    k: v for k, v in _bot_state.items()
                    if not hasattr(v, "__dict__")  # Position-Objekte überspringen
                }
                if _bot_state.get("position") is not None:
                    pos = _bot_state["position"]
                    _serializable["position"] = {
                        "symbol":      getattr(pos, "symbol", SYMBOL),
                        "entry_price": getattr(pos, "entry_price", 0),
                        "stop_loss":   getattr(pos, "stop_loss", 0),
                        "take_profit": getattr(pos, "take_profit", 0),
                        "quantity":    getattr(pos, "quantity", 0),
                    }
                def _json_default(obj):
                    import numpy as _np
                    if isinstance(obj, _np.floating):
                        return float(obj)
                    if isinstance(obj, _np.integer):
                        return int(obj)
                    if isinstance(obj, _np.ndarray):
                        return obj.tolist()
                    return str(obj)
                _state_path.write_text(_json.dumps(_serializable, default=_json_default))
            except Exception:
                pass

            # ── Täglicher Summary ─────────────────────────────────────────────
            today = now.date()
            if today != last_summary_date:
                summary = rm.summary()
                save_performance_snapshot(
                    rm.capital, -rm.daily_loss,
                    rm.capital - INITIAL_CAPITAL,
                    rm.has_open_position(),
                )
                alerts.alert_daily_summary(rm.capital, -rm.daily_loss, summary.get("trades", 0))
                log.debug(f"Daily Summary: capital={rm.capital:.2f} daily_pnl={-rm.daily_loss:+.2f} total_pnl={rm.capital - INITIAL_CAPITAL:+.2f} trades={summary.get('trades', 0)} wins={summary.get('wins', 0)}")
                last_summary_date = today

                # ── Multi-Asset Pair Empfehlungen + Portfolio Allokation ──────
                try:
                    from crypto_bot.strategy.pair_selector import select_pairs
                    from crypto_bot.data.fetcher import get_exchange as _get_exchange
                    try:
                        _sel_exchange = _get_exchange()
                    except Exception as _ex:
                        log.debug(f"Pair Selector: Exchange-Init fehlgeschlagen: {_ex}")
                        _sel_exchange = None
                    selection = select_pairs(exchange=_sel_exchange)
                    if selection and selection.scores:
                        top = [p.symbol for p in selection.scores[:3]]
                        top_scores = {p.symbol: round(p.score, 3) for p in selection.scores[:3]}
                        console.print(f"[dim]Top Paare (Score): {', '.join(top)}[/dim]")
                        log.debug(f"Pair Selector: top={top} scores={top_scores}")
                        log_event(f"Empfohlene Paare: {', '.join(top)}", "pair_selection")
                        if portfolio_alloc is not None:
                            pairs_data = [
                                {"symbol": p.symbol, "vol_pct": p.atr_pct / 100,
                                 "recent_return": 0.005, "score": p.score}
                                for p in selection.scores[:3]
                            ]
                            alloc = portfolio_alloc.get_allocation(pairs_data, vol_regime_str)
                            log_event(f"Portfolio-Allokation ({alloc.method}): {alloc.weights}", "portfolio")

                        # ── Round 8: Opportunity Radar ────────────────────────
                        if _opp_radar is not None:
                            try:
                                radar_pairs = {p.symbol: None for p in selection.scores[:5]}
                                # Nutze nur aktuelles df für Hauptpaar; andere ohne df
                                radar_pairs[SYMBOL] = df
                                radar_pairs_filtered = {k: v for k, v in radar_pairs.items() if v is not None}
                                if radar_pairs_filtered:
                                    radar_result = _opp_radar.scan(
                                        radar_pairs_filtered,
                                        regimes={SYMBOL: regime_name},
                                    )
                                    _bot_state["opportunity_radar"] = {
                                        "best": radar_result.best_symbol,
                                        "top": [
                                            {"symbol": s.symbol, "score": s.total_score, "signal": s.signal}
                                            for s in radar_result.top_opportunities[:5]
                                        ],
                                    }
                            except Exception as e:
                                log.debug(f"Opportunity Radar Fehler: {e}")
                except Exception as e:
                    log.debug(f"Pair-Selector: {e}")

                # ── Täglicher PDF-Report ──────────────────────────────────────
                if features.PDF_REPORTS:
                    try:
                        from crypto_bot.reporting.report_generator import get_report_generator
                        from crypto_bot.monitoring.logger import DB_PATH
                        import sqlite3, json
                        with sqlite3.connect(DB_PATH) as conn:
                            conn.row_factory = sqlite3.Row
                            rows = conn.execute(
                                "SELECT * FROM trades ORDER BY created_at DESC LIMIT 200"
                            ).fetchall()
                            trades_list = [dict(r) for r in rows]
                        if trades_list:
                            get_report_generator().generate(
                                trades      = trades_list,
                                capital     = rm.capital,
                                initial_cap = INITIAL_CAPITAL,
                                symbol      = SYMBOL,
                            )
                    except Exception as e:
                        log.debug(f"PDF-Report Fehler: {e}")

                # ── Multi-Asset Zyklus (läuft nach Single-Pair) ───────────────
                if _multi_runner is not None:
                    try:
                        _multi_runner.refresh_pairs_daily()

                        # Daten für alle Multi-Pair-Symbole laden
                        from crypto_bot.data.fetcher import fetch_ohlcv as _fetch_ma
                        _ma_df_map: dict = {}
                        for _ma_sym in list(_multi_runner.pairs.keys()):
                            try:
                                _ma_df_map[_ma_sym] = _fetch_ma(_ma_sym, TIMEFRAME, days=60)
                            except Exception as _mae_fetch:
                                log.debug(f"Multi-Asset Fetch {_ma_sym}: {_mae_fetch}")

                        _ma_results = _multi_runner.run_cycle(_ma_df_map)
                        _bot_state["multi_asset"] = _multi_runner.get_status()

                        # Ergebnis loggen
                        for _ma_sym, _ma_res in _ma_results.items():
                            sig = _ma_res.get("signal", "?")
                            prc = _ma_res.get("price",  0.0)
                            pnl = _ma_res.get("pnl",    0.0)
                            console.print(
                                f"[dim]Multi-Asset {_ma_sym}: {sig} @ {prc:.4f}"
                                + (f" | PnL={pnl:+.2f}" if pnl else "") + "[/dim]"
                            )
                    except Exception as _ma_err:
                        log.warning(f"Multi-Asset Zyklus Fehler: {_ma_err}")

        except Exception as e:
            log_event(str(e), "error", "error")
            alerts.alert_error(str(e))
            console.print(f"[bold red]Fehler: {e}[/bold red]")

        if _running and not _bot_state.get("stop_requested"):
            console.print(f"[dim]Nächste Analyse in {interval}s...[/dim]")
            # Sleep-Loop mit Heartbeat-Ping alle 10 Minuten (verhindert Dead Man's Switch False-Positives)
            _ping_interval = min(600, interval)
            _slept = 0
            while _slept < interval and _running and not _bot_state.get("stop_requested"):
                time.sleep(min(_ping_interval, interval - _slept))
                _slept += _ping_interval
                heartbeat.ping()

    # ── Graceful Shutdown ─────────────────────────────────────────────────────
    heartbeat.stop()
    streamer.stop()
    dashboard.stop()
    console.print("\n[bold]Abschlussbericht:[/bold]")
    if isinstance(trader, PaperTrader):
        trader.print_summary()
    log_event("Bot beendet", "shutdown")


def health_check() -> bool:
    """
    Prüft ob das System bereit ist. Gibt True zurück wenn alles OK.
    Wird von `python bot.py --check` und `make check` aufgerufen.
    """
    console = Console()
    table   = Table(title="Trading Bot — System-Check", show_header=False, box=None)
    table.add_column("Status", width=4)
    table.add_column("Komponente", style="cyan", width=28)
    table.add_column("Detail")

    issues = []

    def row(ok: bool, name: str, detail: str):
        icon = "[bold green]✓[/bold green]" if ok else "[bold red]✗[/bold red]"
        table.add_row(icon, name, detail)
        if not ok:
            issues.append(name)

    # Python-Version
    v = sys.version_info
    py_ok = (v.major, v.minor) >= (3, 10)
    row(py_ok, "Python", f"{v.major}.{v.minor}.{v.micro} auf {platform.system()}")

    # Pakete
    packages = {"ccxt": "ccxt", "pandas": "pandas", "xgboost": "xgboost",
                "anthropic": "anthropic", "rich": "rich", "sklearn": "sklearn"}
    missing = []
    for name, mod in packages.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(name)
    row(not missing, "Pakete", "alle installiert" if not missing else f"fehlt: {', '.join(missing)}")

    # .env Datei
    env_path = BASE_DIR / ".env"
    env_ok   = env_path.exists()
    row(env_ok, ".env Konfiguration",
        str(env_path) if env_ok else "Nicht gefunden — python setup_wizard.py ausführen")

    # Datenbank
    try:
        from crypto_bot.monitoring.logger import init_db, DB_PATH
        init_db()
        row(True, "SQLite Datenbank", str(DB_PATH))
    except Exception as e:
        row(False, "SQLite Datenbank", str(e))

    # ML-Modell
    try:
        from crypto_bot.config.settings import ML_MODEL_PATH, AI_MODE
        model_path = Path(ML_MODEL_PATH)
        if model_path.exists():
            import joblib
            data  = joblib.load(model_path)
            f1    = data.get("val_f1", "?")
            dated = data.get("trained_on", "?")
            row(True, "ML-Modell", f"F1={f1} | trainiert: {dated}")
        elif AI_MODE in ("ml", "combined"):
            row(False, "ML-Modell", "Nicht gefunden — make train ausführen")
            issues.append("ML-Modell")
        else:
            row(True, "ML-Modell", f"Nicht benötigt (AI_MODE={AI_MODE})")
    except Exception as e:
        row(False, "ML-Modell", str(e))

    # Binance Verbindung (öffentlich, kein Key nötig)
    try:
        import ccxt
        ex = ccxt.binance()
        ex.fetch_ticker("BTC/USDT")
        row(True, "Binance API", "Verbindung OK")
    except Exception as e:
        row(False, "Binance API", f"Keine Verbindung: {e}")

    # Telegram
    try:
        from crypto_bot.config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            row(True, "Telegram", "konfiguriert")
        else:
            row(True, "Telegram", "nicht konfiguriert (optional)")
    except Exception:
        row(True, "Telegram", "nicht konfiguriert (optional)")

    # TRADING_MODE + Leverage
    try:
        from crypto_bot.config.settings import TRADING_MODE, INITIAL_CAPITAL, LEVERAGE, MAX_LEVERAGE
        lev_str = f" | Leverage: {LEVERAGE}x" if LEVERAGE > 1 else " | Spot (1x)"
        row(True, "Handelsmodus",
            f"{TRADING_MODE.upper()} | Kapital: {INITIAL_CAPITAL:.0f} USDT{lev_str}")
        if LEVERAGE > MAX_LEVERAGE:
            row(False, "Leverage", f"{LEVERAGE}x > MAX {MAX_LEVERAGE}x — wird auf {MAX_LEVERAGE}x begrenzt")
    except Exception as e:
        row(False, "Handelsmodus", str(e))

    console.print()
    console.print(table)
    console.print()

    if not issues:
        console.print("[bold green]  Status: BEREIT — starte mit: make start[/bold green]\n")
        return True
    else:
        console.print(f"[bold red]  Status: {len(issues)} Problem(e) gefunden[/bold red]")
        console.print(f"[yellow]  → Lösung: python setup_wizard.py[/yellow]\n")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BTC/USDT AI Trading Bot")
    parser.add_argument("--check",  action="store_true", help="System-Check ausführen")
    parser.add_argument("--paper",  action="store_true", help="Paper-Modus erzwingen")
    parser.add_argument("--live",   action="store_true", help="Live-Modus erzwingen")
    args = parser.parse_args()

    if args.check:
        ok = health_check()
        sys.exit(0 if ok else 1)

    if args.paper:
        os.environ["TRADING_MODE"] = "paper"
    if args.live:
        os.environ["TRADING_MODE"] = "live"

    run()
