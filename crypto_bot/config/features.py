"""
Feature Flag System — zentrale Steuerung aller Bot-Features.

Jedes Feature ist per .env ein/ausschaltbar:
    FEATURE_MICROSTRUCTURE=false    # deaktiviert Microstructure-Signale
    FEATURE_ONLINE_LEARNING=true    # Standard: aktiviert

Konvention:
  - Standard: alle Features aktiviert (opt-out Modell)
  - Prefix: FEATURE_<NAME> in Großbuchstaben
  - Werte: true/false, 1/0, yes/no

Verwendung:
    from crypto_bot.config import features
    if features.MICROSTRUCTURE:
        ...  # nur ausgeführt wenn aktiviert
"""
from __future__ import annotations

import os


def _flag(name: str, default: bool = True) -> bool:
    """Liest Feature-Flag aus Umgebungsvariable."""
    val = os.getenv(f"FEATURE_{name.upper()}", str(default).lower())
    return val.lower() in ("1", "true", "yes")


# ── Round 6–7: Bestehende Features ───────────────────────────────────────────
ONLINE_LEARNING       = _flag("ONLINE_LEARNING")        # SGD partial_fit + Platt + Bayes
EXPLAINABILITY        = _flag("EXPLAINABILITY")         # TradeExplanation Narrativ
PORTFOLIO_OPTIMIZER   = _flag("PORTFOLIO_OPTIMIZER")    # Risk Parity / Sharpe Allokation
TAIL_RISK             = _flag("TAIL_RISK")              # Black Swan Gate vor Trades
EXECUTION_OPTIMIZER   = _flag("EXECUTION_OPTIMIZER")    # Slippage + Spread + Timing
PDF_REPORTS           = _flag("PDF_REPORTS")            # Täglicher PDF-Report
SCANNER               = _flag("SCANNER")                # Continuous Pair-Scanner Thread
BLACK_SWAN            = _flag("BLACK_SWAN")             # BlackSwanDetector
KELLY_OPTIMIZER       = _flag("KELLY_OPTIMIZER")        # Kelly Fraction Sizing
STRATEGY_TRACKER      = _flag("STRATEGY_TRACKER")       # Strategy P&L Tracking + Retirement

# ── Round 8: Neue Advanced Features ──────────────────────────────────────────
MICROSTRUCTURE        = _flag("MICROSTRUCTURE")         # CVD, Orderbook-Imbalanz, Wick-Analyse
DERIVATIVES_SIGNALS   = _flag("DERIVATIVES_SIGNALS")    # Funding-Rate, Liquidations, Spot-Perp-Basis
CROSS_MARKET          = _flag("CROSS_MARKET")           # BTC-Dominanz, Stablecoin-Flows, Sentiment
REGIME_FORECASTER     = _flag("REGIME_FORECASTER")      # Prädiktive Regime-Übergänge (Markov)
GROWTH_OPTIMIZER      = _flag("GROWTH_OPTIMIZER")       # Rolling Kelly, Profit-Lock, Equity-Feedback
VENUE_OPTIMIZER       = _flag("VENUE_OPTIMIZER")        # Fee-aware Exchange-Routing
RESILIENCE            = _flag("RESILIENCE")             # API-Latenz, WS-Health, Auto-Failover
STRATEGY_LIFECYCLE    = _flag("STRATEGY_LIFECYCLE")     # Aging, Revival, Rotation Scheduling
OPPORTUNITY_RADAR     = _flag("OPPORTUNITY_RADAR")      # Per-Pair Opportunity Scoring + Dashboard

# ── Round 9: Model Governance + Simulation + Stress + Allocator + Funding ─────
MODEL_GOVERNANCE       = _flag("MODEL_GOVERNANCE")       # Entropy, Feature-Drift, Calibration-Drift
REGIME_SIMULATION      = _flag("REGIME_SIMULATION")      # Monte Carlo Markov Regime-Pfade
STRESS_TESTER          = _flag("STRESS_TESTER")          # Flash Crash / Spread / Kaskaden-Szenarien
CAPITAL_ALLOCATOR      = _flag("CAPITAL_ALLOCATOR")      # Autonomer Signal-gewichteter Meta-Allocator
FUNDING_TERM_STRUCTURE = _flag("FUNDING_TERM_STRUCTURE") # Funding-Laufzeitstruktur + Carry-Optimierung


# ── Round 10: Marktkontext & Sicherheit ──────────────────────────────────────
FEAR_GREED     = _flag("FEAR_GREED")      # Crypto Fear & Greed Index (alternative.me)
NEWS_SENTIMENT = _flag("NEWS_SENTIMENT")  # Krypto-News Sentiment via RSS + LLM

# ── Round 11: Global Exposure Controller ─────────────────────────────────────
GLOBAL_EXPOSURE = _flag("GLOBAL_EXPOSURE")  # Portfolio-Level Exposure Management

# ── Round 12: Pro-Features ────────────────────────────────────────────────────
ONCHAIN_DATA    = _flag("ONCHAIN_DATA")     # On-Chain Metriken (blockchain.info + CoinGecko)
ORDER_BOOK      = _flag("ORDER_BOOK")       # Order Book Imbalanz Features
FUNDING_RATE    = _flag("FUNDING_RATE")     # Binance Perpetuals Funding Rate

# ── Multi-Asset ───────────────────────────────────────────────────────────────
MULTI_PAIR      = _flag("MULTI_PAIR", False)  # Multi-Pair Trading (select_pairs + parallele Positionen)

# ── RPC / Alerting ────────────────────────────────────────────────────────────
DISCORD_RPC     = _flag("DISCORD_RPC",  False)  # Discord Webhook Alerts (DISCORD_WEBHOOK_URL)
WEBHOOK_RPC     = _flag("WEBHOOK_RPC",  False)  # Generic HTTP Webhook Alerts (WEBHOOK_URL)

# ── Custom Strategy ───────────────────────────────────────────────────────────
CUSTOM_STRATEGY = _flag("CUSTOM_STRATEGY", False)  # IStrategy-Interface (STRATEGY=KlassenName)

# ── ML Model ──────────────────────────────────────────────────────────────────
LIGHTGBM        = _flag("LIGHTGBM", False)  # LightGBM statt XGBoost (schneller auf CPU, weniger RAM)

# ── Execution ─────────────────────────────────────────────────────────────────
TWAP_EXECUTION  = _flag("TWAP_EXECUTION", False)  # TWAP für Orders >$10k (TWAP_THRESHOLD_USDT)
FUNDING_ARB     = _flag("FUNDING_ARB",    False)  # Funding Rate Arbitrage Long Spot/Short Perp

# ── Multi-Bot ─────────────────────────────────────────────────────────────────
SIGNAL_BUS      = _flag("SIGNAL_BUS",     False)  # Signal Bus für Multi-Bot-Kommunikation

# ── RL Agent ──────────────────────────────────────────────────────────────────
RL_AGENT        = _flag("RL_AGENT",       False)  # Q-Learning Agent als zweite Signal-Quelle

# ── Steuer / Reporting ────────────────────────────────────────────────────────
TAX_JOURNAL     = _flag("TAX_JOURNAL",    False)  # FIFO Trade-Journal für DE/AT Steuer


# ── Feature Metadata ──────────────────────────────────────────────────────────
# Beschreibung, Kategorie und empfohlenes Level (standard / pro) für das Dashboard

_FEATURE_META: dict[str, dict] = {
    "ONLINE_LEARNING":       {"label": "Online Learning",        "desc": "Modell lernt kontinuierlich aus neuen Daten (SGD partial_fit + Platt-Scaling)",         "category": "ML/AI",     "level": "pro"},
    "EXPLAINABILITY":        {"label": "AI Explainability",      "desc": "Menschliche Erklärung für jede Trading-Entscheidung",                                    "category": "ML/AI",     "level": "standard"},
    "PORTFOLIO_OPTIMIZER":   {"label": "Portfolio Optimizer",    "desc": "Risk-Parity / Sharpe-optimierte Kapitalallokation über mehrere Paare",                   "category": "Risk",      "level": "pro"},
    "TAIL_RISK":             {"label": "Tail Risk Gate",         "desc": "Black-Swan-Sperre vor jedem Trade bei extremen Marktbedingungen",                        "category": "Risk",      "level": "standard"},
    "EXECUTION_OPTIMIZER":   {"label": "Execution Optimizer",    "desc": "Slippage-, Spread- und Timing-Optimierung bei der Order-Platzierung",                    "category": "Execution", "level": "pro"},
    "PDF_REPORTS":           {"label": "PDF Reports",            "desc": "Täglicher Performance-Report als PDF (CPU-intensiv)",                                    "category": "Reporting", "level": "pro"},
    "SCANNER":               {"label": "Pair Scanner",           "desc": "Kontinuierlicher Multi-Pair-Scanner — findet die besten Handelsmöglichkeiten",           "category": "Strategy",  "level": "pro"},
    "MULTI_PAIR":            {"label": "Multi-Asset Trading",    "desc": "Handelt gleichzeitig auf mehreren Paaren (BTC/ETH/SOL) mit automatischer Kapitalaufteilung",  "category": "Strategy",  "level": "pro"},
    "DISCORD_RPC":           {"label": "Discord Alerts",         "desc": "Trade-Events und Alerts via Discord Webhook (DISCORD_WEBHOOK_URL in .env setzen)",               "category": "Alerting",  "level": "standard"},
    "WEBHOOK_RPC":           {"label": "HTTP Webhook",           "desc": "Generic HTTP Webhook für Grafana, PagerDuty, n8n und andere Monitoring-Tools",                   "category": "Alerting",  "level": "pro"},
    "CUSTOM_STRATEGY":       {"label": "Custom Strategy",        "desc": "Eigene IStrategy-Klasse laden (STRATEGY=KlassenName, Datei in strategies/ ablegen)",             "category": "Strategy",  "level": "pro"},
    "LIGHTGBM":              {"label": "LightGBM Modell",        "desc": "LightGBM statt XGBoost — schneller auf CPU, weniger RAM (gut für QNAP/Raspberry Pi)",            "category": "ML/AI",     "level": "pro"},
    "BLACK_SWAN":            {"label": "Black Swan Detector",    "desc": "Erkennt Crash-Signale und aktiviert Schutz-Modus",                                       "category": "Risk",      "level": "standard"},
    "KELLY_OPTIMIZER":       {"label": "Kelly Criterion",        "desc": "Optimale Positionsgrößen nach Kelly-Formel",                                              "category": "Risk",      "level": "pro"},
    "STRATEGY_TRACKER":      {"label": "Strategy Tracker",       "desc": "Verfolgt P&L pro Strategie und entfernt schwache automatisch",                           "category": "Strategy",  "level": "pro"},
    "MICROSTRUCTURE":        {"label": "Microstructure",         "desc": "CVD, Orderbook-Imbalanz und Wick-Analyse für präzisere Entries",                         "category": "Signals",   "level": "pro"},
    "DERIVATIVES_SIGNALS":   {"label": "Derivatives Signals",   "desc": "Funding-Rate, Liquidationen und Spot-Perp-Basis als Signalquelle",                        "category": "Signals",   "level": "pro"},
    "CROSS_MARKET":          {"label": "Cross-Market Signals",  "desc": "BTC-Dominanz, Stablecoin-Flows und Sentiment über alle Märkte",                           "category": "Signals",   "level": "pro"},
    "REGIME_FORECASTER":     {"label": "Regime Forecaster",     "desc": "Prädiktive Marktphasen-Übergänge via Markov-Ketten",                                      "category": "ML/AI",     "level": "pro"},
    "GROWTH_OPTIMIZER":      {"label": "Growth Optimizer",      "desc": "Rolling Kelly, Profit-Lock und Equity-Feedback für Kapitalwachstum",                      "category": "Risk",      "level": "pro"},
    "VENUE_OPTIMIZER":       {"label": "Venue Optimizer",       "desc": "Fee-bewusstes Exchange-Routing — handelt wo die Gebühren am niedrigsten sind",            "category": "Execution", "level": "pro"},
    "RESILIENCE":            {"label": "Resilience Monitor",    "desc": "API-Latenz-Überwachung, WebSocket-Health und automatischer Failover",                     "category": "System",    "level": "standard"},
    "STRATEGY_LIFECYCLE":    {"label": "Strategy Lifecycle",    "desc": "Aging, Revival und Rotation-Scheduling für Strategien",                                   "category": "Strategy",  "level": "pro"},
    "OPPORTUNITY_RADAR":     {"label": "Opportunity Radar",     "desc": "Per-Pair Opportunity-Score und Dashboard-Anzeige",                                        "category": "Strategy",  "level": "pro"},
    "MODEL_GOVERNANCE":      {"label": "Model Governance",      "desc": "Entropie, Feature-Drift und Kalibrations-Drift — ML-Modell-Gesundheit",                  "category": "ML/AI",     "level": "pro"},
    "REGIME_SIMULATION":     {"label": "Regime Simulation",     "desc": "Monte-Carlo Markov Regime-Pfade für Exposure-Empfehlung",                                 "category": "ML/AI",     "level": "pro"},
    "STRESS_TESTER":         {"label": "Stress Tester",         "desc": "Flash-Crash, Spread-Crash und Kaskaden-Szenarien simulieren",                             "category": "Risk",      "level": "pro"},
    "CAPITAL_ALLOCATOR":     {"label": "Capital Allocator",     "desc": "Autonomer Signal-gewichteter Meta-Allocator für optimale Kapitalverteilung",              "category": "Risk",      "level": "pro"},
    "FUNDING_TERM_STRUCTURE":{"label": "Funding Term Structure","desc": "Funding-Laufzeitstruktur, Contango/Backwardation und Carry-Optimierung",                  "category": "Signals",   "level": "pro"},
    "FEAR_GREED":            {"label": "Fear & Greed Index",    "desc": "Crypto Fear & Greed Index als Positions-Faktor (alternative.me)",                        "category": "Signals",   "level": "standard"},
    "NEWS_SENTIMENT":        {"label": "News Sentiment",        "desc": "Krypto-News Sentiment via RSS-Feeds + LLM-Analyse",                                       "category": "Signals",   "level": "standard"},
    "GLOBAL_EXPOSURE":       {"label": "Global Exposure Ctrl",  "desc": "Portfolio-Level Exposure Management über alle offenen Positionen",                        "category": "Risk",      "level": "standard"},
    "ONCHAIN_DATA":          {"label": "On-Chain Data",         "desc": "On-Chain Metriken: MVRV, Hash-Rate, Mempool (blockchain.info + CoinGecko)",               "category": "Signals",   "level": "pro"},
    "ORDER_BOOK":            {"label": "Order Book",            "desc": "Orderbook-Imbalanz als zusätzlicher Signalfilter",                                        "category": "Signals",   "level": "pro"},
    "FUNDING_RATE":          {"label": "Funding Rate",          "desc": "Binance Perpetuals Funding Rate als Marktsentiment-Indikator",                            "category": "Signals",   "level": "pro"},
    "TWAP_EXECUTION":        {"label": "TWAP Execution",        "desc": "Große Orders ($10k+) zeitgestreckt ausführen (Time-Weighted Average Price)",                  "category": "Execution", "level": "pro"},
    "FUNDING_ARB":           {"label": "Funding Arbitrage",     "desc": "Long Spot / Short Perpetual bei hoher Funding-Rate (delta-neutral Zinsertrag)",                "category": "Strategy",  "level": "pro"},
    "SIGNAL_BUS":            {"label": "Signal Bus",            "desc": "Multi-Bot Pub/Sub — Crypto Bot sendet Signale an Forex Bot und umgekehrt",                     "category": "System",    "level": "pro"},
    "RL_AGENT":              {"label": "RL Agent",              "desc": "Q-Learning Agent als zweite Signal-Quelle neben dem ML-Modell",                                "category": "ML/AI",     "level": "pro"},
    "TAX_JOURNAL":           {"label": "FIFO Tax Journal",      "desc": "Realisierte Gewinne/Verluste nach FIFO (DE §20 EStG / AT §27 EStG) + CSV-Export für Elster",  "category": "Reporting", "level": "pro"},
}


# ── Helper Functions ──────────────────────────────────────────────────────────

def is_enabled(feature: str) -> bool:
    """Prüft ob ein Feature aktiviert ist (case-insensitive Namenssuche)."""
    return globals().get(feature.upper(), False) is True


def get_all() -> dict[str, bool]:
    """Gibt alle Feature-Flags mit aktuellem Status zurück."""
    return {
        k: v for k, v in globals().items()
        if not k.startswith("_") and isinstance(v, bool)
    }


def get_all_with_meta() -> list[dict]:
    """Gibt alle Feature-Flags mit Status + Metadaten zurück (für Dashboard)."""
    flags = get_all()
    result = []
    for name, enabled in sorted(flags.items()):
        meta = _FEATURE_META.get(name, {})
        result.append({
            "name":     name,
            "enabled":  enabled,
            "env_var":  f"FEATURE_{name}",
            "label":    meta.get("label", name.replace("_", " ").title()),
            "desc":     meta.get("desc", ""),
            "category": meta.get("category", "Other"),
            "level":    meta.get("level", "pro"),
        })
    return result


def set_flag(name: str, enabled: bool, persist: bool = True) -> bool:
    """
    Setzt ein Feature-Flag zur Laufzeit und optional persistent in .env.
    Gibt True zurück wenn erfolgreich.
    """
    name = name.upper()
    if name not in get_all():
        return False

    import sys
    import importlib
    os.environ[f"FEATURE_{name}"] = "true" if enabled else "false"

    # Modul neu laden damit der globale Flag sofort gilt
    mod = sys.modules.get("crypto_bot.config.features")
    if mod:
        setattr(mod, name, enabled)

    if persist:
        _write_flag_to_env(f"FEATURE_{name}", "true" if enabled else "false")

    return True


def _write_flag_to_env(key: str, value: str) -> None:
    """Schreibt Feature-Flag in .env-Datei."""
    from pathlib import Path as _Path
    env_path = _Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def summary() -> str:
    """Formatierte Zusammenfassung aller Features für Logging."""
    all_flags = get_all()
    enabled   = [k for k, v in all_flags.items() if v]
    disabled  = [k for k, v in all_flags.items() if not v]
    lines     = ["Feature Flags:"]
    for k in sorted(enabled):
        lines.append(f"  ✓ {k}")
    for k in sorted(disabled):
        lines.append(f"  ✗ {k} (deaktiviert)")
    return "\n".join(lines)
