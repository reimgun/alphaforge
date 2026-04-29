"""
Streamlit Web Dashboard — Hedge-Fund Style Trading Interface.

Start:
    streamlit run dashboard/app.py
    oder: make dashboard

Features:
  - Live Portfolio Value + Equity Curve
  - Performance Metriken (Sharpe, Sortino, Win-Rate, Drawdown)
  - Offene Position + Stop-Loss visualisiert
  - Trade History Tabelle
  - AI Konfidenz + Regime Anzeige
  - Bot-Controls (Start/Stop/Safe Mode/Retrain)
  - CSV/JSON Export
  - Zeitzone wählbar (alle Zeitzonen)
  - Sprache wählbar (Deutsch / English)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import requests
from datetime import datetime, timezone as _tz_utc

# @st.fragment (Streamlit ≥ 1.37) ermöglicht partielles Re-Rendering
_HAS_FRAGMENT = hasattr(st, "fragment")

# ── Konfiguration ─────────────────────────────────────────────────────────────

API_URL       = os.getenv("DASHBOARD_API_URL",  "http://localhost:8000")
FOREX_API_URL = os.getenv("FOREX_API_URL",       "http://localhost:8001")

st.set_page_config(
    page_title="AI Trading Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS
st.markdown("""
<style>
.metric-card { background: #1e1e2e; border-radius: 10px; padding: 15px; }
.positive { color: #00ff88; }
.negative { color: #ff4444; }
.neutral  { color: #aaaaaa; }
</style>
""", unsafe_allow_html=True)


# ── Timezone helpers ──────────────────────────────────────────────────────────

def _tz_list() -> list:
    """Returns list of all timezones, common ones first."""
    _common = [
        "UTC",
        "Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/London",
        "Europe/Paris", "Europe/Rome", "Europe/Amsterdam", "Europe/Madrid",
        "Europe/Warsaw", "Europe/Stockholm", "Europe/Helsinki",
        "Europe/Moscow", "Europe/Istanbul",
        "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "America/Toronto", "America/Sao_Paulo",
        "America/Buenos_Aires", "America/Mexico_City",
        "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok", "Asia/Singapore",
        "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
        "Australia/Sydney", "Australia/Melbourne",
        "Pacific/Auckland", "Pacific/Honolulu",
        "Africa/Cairo", "Africa/Johannesburg",
    ]
    try:
        from zoneinfo import available_timezones
        _rest = sorted(tz for tz in available_timezones() if tz not in _common)
        return _common + _rest
    except Exception:
        return _common


def _fmt_dt(ts: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convert UTC/ISO timestamp to the selected dashboard timezone."""
    if not ts:
        return ""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(st.session_state.get("tz", "Europe/Berlin"))
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz_utc.utc)
        return dt.astimezone(tz).strftime(fmt)
    except Exception:
        return str(ts)[:19].replace("T", " ")


def _fmt_df_ts(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Convert timestamp columns in a DataFrame to the selected timezone."""
    tz_name = st.session_state.get("tz", "Europe/Berlin")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        df = df.copy()
        for col in cols:
            if col in df.columns:
                df[col] = (
                    pd.to_datetime(df[col], utc=True, errors="coerce")
                    .dt.tz_convert(tz)
                    .dt.strftime("%Y-%m-%d %H:%M")
                )
    except Exception:
        pass
    return df


# ── i18n ──────────────────────────────────────────────────────────────────────

_T = {
    "de": {
        "title": "🤖 Crypto Bot",
        # Sidebar
        "s.control": "Steuerung",
        "s.risk_mode": "Risk Mode",
        "s.pair": "📊 Handelspaar",
        "s.pair_select": "Paar wählen",
        "s.pair_custom": "Symbol (z.B. DOGE/USDT)",
        "s.pair_active": "Aktiv",
        "s.pair_warn": "⚠️ Symbol geändert — Bot neu starten + Modell trainieren!",
        "s.export": "Export",
        "s.log_level": "📝 Log-Level",
        "s.log_active": "Aktiv",
        "s.timezone": "🕐 Zeitzone",
        "s.refresh": "⟳ Refresh (s)",
        "s.last_update": "Zuletzt",
        "s.safe_mode_active": "🛡️ Safe Mode aktiv",
        "s.mode": "Modus",
        "s.currently": "Aktuell",
        "s.risk_help_c": "Konservativ",
        "s.risk_help_b": "Balanced",
        "s.risk_help_a": "Aggressiv",
        # Buttons
        "b.start": "▶ Start Bot",
        "b.stop": "⛔ Stop",
        "b.paper": "📄 Paper",
        "b.pause": "⏸ Pause",
        "b.resume": "▶️ Resume",
        "b.safe": "🛡️ Safe Mode",
        "b.retrain": "🔄 Retrain",
        "b.retrain_warn": "🔄 Retrain ⚠️",
        "b.restart": "🎓 Restart Training",
        # Tabs
        "tab.overview": "📊 Übersicht",
        "tab.perf": "📅 Wöchentlich / Monatlich",
        "tab.trades": "📋 Trade History",
        "tab.strategy": "🎯 Strategie-Performance",
        "tab.strategy_cfg": "🔧 Strategie",
        "tab.risk": "🔬 Risk & Market",
        "tab.explain": "🔍 AI Explainability",
        "tab.logs": "📜 Logs",
        "tab.features": "⚙️ Features",
        "tab.system": "🖥️ System",
        "tab.marketplace": "🏪 Strategien",
        "tab.help": "❓ Hilfe",
        "s.view_mode": "Ansicht",
        "s.view_standard": "Standard",
        "s.view_pro": "Pro",
        # Metrics
        "m.capital": "💰 Kapital",
        "m.daily_pnl": "📊 Tages-PnL",
        "m.regime": "Markt-Regime",
        "m.volatility": "Volatilität",
        "m.ai_conf": "🤖 AI Konfidenz",
        "m.strategy": "Strategie",
        "m.total_pnl": "Gesamt PnL",
        "m.win_rate": "Win-Rate",
        "m.sharpe": "Sharpe Ratio",
        "m.drawdown": "Max Drawdown",
        "m.pf": "Profit Factor",
        "m.sortino": "Sortino Ratio",
        "m.avg_win": "Ø Gewinn",
        "m.avg_loss": "Ø Verlust",
        "m.unrealized": "Unrealisierter PnL",
        "m.qty": "Menge",
        # Charts
        "c.equity": "Equity-Kurve",
        "c.capital": "Kapital",
        "c.capital_ax": "Kapital (USDT)",
        "c.start": "Start",
        "c.price": "Preis",
        "c.weekly": "Wöchentliche PnL",
        "c.monthly": "Monatliche PnL",
        "c.week_ax": "Woche",
        "c.month_ax": "Monat",
        "c.pnl_ax": "PnL (USDT)",
        # Sections
        "sec.perf": "Performance",
        "sec.rolling": "Rolling Performance",
        "sec.strategy": "Strategie-Performance",
        "sec.explain": "AI Explainability — Letzte Entscheidungen",
        "sec.drift": "Model Drift Status",
        "sec.rejections": "Trade Rejection Log",
        "sec.signals": "Letzte AI-Signale",
        "sec.trade_hist": "Trade History",
        "sec.logs": "📜 Bot Logs",
        "sec.pos": "Offene Position",
        "sec.risk_active": "Aktiver Risk Mode",
        # Periods
        "p.7d": "Letzte 7 Tage",
        "p.30d": "Letzte 30 Tage",
        "p.total": "Gesamt",
        # Values
        "v.good": "gut",
        "v.weak": "schwach",
        "v.ok": "ok",
        "v.high": "hoch",
        # Phase
        "ph.criteria_met": "Kriterien erfüllt",
        "ph.target": "Ziel",
        "ph.phase": "Trading Phase",
        # Info
        "i.no_equity": "Noch keine Equity-Kurve — Bot muss Trades ausführen",
        "i.no_pos": "Keine offene Position",
        "i.no_trades": "Noch keine Trades aufgezeichnet",
        "i.no_strategy": "Noch keine Strategie-Daten — Bot muss Trades ausführen",
        "i.no_perf": "Noch keine Performance-Daten vorhanden",
        "i.no_weekly": "Noch keine wöchentlichen/monatlichen Daten — Bot muss einige Tage laufen",
        "i.no_hold": "Kein HOLD aufgezeichnet",
        "i.no_rej": "Keine Ablehnungen aufgezeichnet",
        "i.no_sig": "Noch keine Signale aufgezeichnet",
        "i.no_log": "Noch keine Log-Datei vorhanden — Bot muss mindestens einmal gelaufen sein.",
        "i.no_log_entries": "Keine Log-Einträge für diesen Filter.",
        "i.bot_running": "🟢 Bot läuft",
        "i.api_error": "🔌 API nicht erreichbar unter",
        "i.api_docker": "Prüfe ob der Dashboard-API Container läuft:\n`docker ps | grep trading-dashboard`",
        # Log
        "l.filter": "Filter",
        "l.lines": "Zeilen",
        "l.of": "von",
        "l.file": "Datei",
        # Risk mode descriptions
        "rm.c_label": "🛡️ Konservativ",
        "rm.c_desc": "1% Risiko/Trade · Max Drawdown 10%",
        "rm.b_label": "⚖️ Balanced",
        "rm.b_desc": "2% Risiko/Trade · Max Drawdown 20%",
        "rm.a_label": "🔥 Aggressiv",
        "rm.a_desc": "3% Risiko/Trade · Max Drawdown 30%",
        # Misc
        "misc.hold_reason": "Letzter HOLD-Grund",
        "misc.source": "Source",
        "misc.accuracy": "Aktuelle Accuracy",
        "misc.baseline": "Baseline F1",
        "misc.drift_lbl": "Drift",
        "misc.drift_warn": "⚠️ Model Drift erkannt — Retraining empfohlen!",
        # Forex Tabs
        "ftab.overview":  "🏠 Übersicht",
        "ftab.trades":    "📋 Trades",
        "ftab.chart":     "📈 Chart",
        "ftab.calendar":  "📰 Wirtschaftskalender",
        "ftab.positions": "📊 Positionen",
        "ftab.regime":    "🌍 Regime & Markt",
        "ftab.riskmode":  "⚡ Risk Mode",
        "ftab.signals":   "📡 Signale",
        "ftab.logs":      "📜 Logs",
        "ftab.features":  "⚙️ Features",
        "ftab.system":    "🖥️ System",
        "ftab.help":      "❓ Hilfe",
    },
    "en": {
        "title": "🤖 Crypto Bot",
        # Sidebar
        "s.control": "Controls",
        "s.risk_mode": "Risk Mode",
        "s.pair": "📊 Trading Pair",
        "s.pair_select": "Select pair",
        "s.pair_custom": "Symbol (e.g. DOGE/USDT)",
        "s.pair_active": "Active",
        "s.pair_warn": "⚠️ Symbol changed — restart bot + retrain model!",
        "s.export": "Export",
        "s.log_level": "📝 Log Level",
        "s.log_active": "Active",
        "s.timezone": "🕐 Timezone",
        "s.refresh": "⟳ Refresh (s)",
        "s.last_update": "Last update",
        "s.safe_mode_active": "🛡️ Safe Mode active",
        "s.mode": "Mode",
        "s.currently": "Currently",
        "s.risk_help_c": "Conservative",
        "s.risk_help_b": "Balanced",
        "s.risk_help_a": "Aggressive",
        # Buttons
        "b.start": "▶ Start Bot",
        "b.stop": "⛔ Stop",
        "b.paper": "📄 Paper",
        "b.pause": "⏸ Pause",
        "b.resume": "▶️ Resume",
        "b.safe": "🛡️ Safe Mode",
        "b.retrain": "🔄 Retrain",
        "b.retrain_warn": "🔄 Retrain ⚠️",
        "b.restart": "🎓 Restart Training",
        # Tabs
        "tab.overview": "📊 Overview",
        "tab.perf": "📅 Weekly / Monthly",
        "tab.trades": "📋 Trade History",
        "tab.strategy": "🎯 Strategy Performance",
        "tab.strategy_cfg": "🔧 Strategy",
        "tab.risk": "🔬 Risk & Market",
        "tab.explain": "🔍 AI Explainability",
        "tab.logs": "📜 Logs",
        "tab.features": "⚙️ Features",
        "tab.system": "🖥️ System",
        "tab.marketplace": "🏪 Strategies",
        "tab.help": "❓ Help",
        "s.view_mode": "View",
        "s.view_standard": "Standard",
        "s.view_pro": "Pro",
        # Metrics
        "m.capital": "💰 Capital",
        "m.daily_pnl": "📊 Daily PnL",
        "m.regime": "Market Regime",
        "m.volatility": "Volatility",
        "m.ai_conf": "🤖 AI Confidence",
        "m.strategy": "Strategy",
        "m.total_pnl": "Total PnL",
        "m.win_rate": "Win Rate",
        "m.sharpe": "Sharpe Ratio",
        "m.drawdown": "Max Drawdown",
        "m.pf": "Profit Factor",
        "m.sortino": "Sortino Ratio",
        "m.avg_win": "Avg Win",
        "m.avg_loss": "Avg Loss",
        "m.unrealized": "Unrealized PnL",
        "m.qty": "Quantity",
        # Charts
        "c.equity": "Equity Curve",
        "c.capital": "Capital",
        "c.capital_ax": "Capital (USDT)",
        "c.start": "Start",
        "c.price": "Price",
        "c.weekly": "Weekly PnL",
        "c.monthly": "Monthly PnL",
        "c.week_ax": "Week",
        "c.month_ax": "Month",
        "c.pnl_ax": "PnL (USDT)",
        # Sections
        "sec.perf": "Performance",
        "sec.rolling": "Rolling Performance",
        "sec.strategy": "Strategy Performance",
        "sec.explain": "AI Explainability — Recent Decisions",
        "sec.drift": "Model Drift Status",
        "sec.rejections": "Trade Rejection Log",
        "sec.signals": "Latest AI Signals",
        "sec.trade_hist": "Trade History",
        "sec.logs": "📜 Bot Logs",
        "sec.pos": "Open Position",
        "sec.risk_active": "Active Risk Mode",
        # Periods
        "p.7d": "Last 7 Days",
        "p.30d": "Last 30 Days",
        "p.total": "Total",
        # Values
        "v.good": "good",
        "v.weak": "weak",
        "v.ok": "ok",
        "v.high": "high",
        # Phase
        "ph.criteria_met": "criteria met",
        "ph.target": "Target",
        "ph.phase": "Trading Phase",
        # Info
        "i.no_equity": "No equity curve yet — bot must execute trades",
        "i.no_pos": "No open position",
        "i.no_trades": "No trades recorded yet",
        "i.no_strategy": "No strategy data yet — bot must execute trades",
        "i.no_perf": "No performance data available yet",
        "i.no_weekly": "No weekly/monthly data yet — bot must run for a few days",
        "i.no_hold": "No HOLD recorded",
        "i.no_rej": "No rejections recorded",
        "i.no_sig": "No signals recorded yet",
        "i.no_log": "No log file yet — bot must have run at least once.",
        "i.no_log_entries": "No log entries for this filter.",
        "i.bot_running": "🟢 Bot running",
        "i.api_error": "🔌 API unreachable at",
        "i.api_docker": "Check if the dashboard API container is running:\n`docker ps | grep trading-dashboard`",
        # Log
        "l.filter": "Filter",
        "l.lines": "Lines",
        "l.of": "of",
        "l.file": "File",
        # Risk mode descriptions
        "rm.c_label": "🛡️ Conservative",
        "rm.c_desc": "1% risk/trade · Max drawdown 10%",
        "rm.b_label": "⚖️ Balanced",
        "rm.b_desc": "2% risk/trade · Max drawdown 20%",
        "rm.a_label": "🔥 Aggressive",
        "rm.a_desc": "3% risk/trade · Max drawdown 30%",
        # Misc
        "misc.hold_reason": "Last HOLD reason",
        "misc.source": "Source",
        "misc.accuracy": "Current Accuracy",
        "misc.baseline": "Baseline F1",
        "misc.drift_lbl": "Drift",
        "misc.drift_warn": "⚠️ Model drift detected — retraining recommended!",
        # Forex Tabs
        "ftab.overview":  "🏠 Overview",
        "ftab.trades":    "📋 Trades",
        "ftab.chart":     "📈 Chart",
        "ftab.calendar":  "📰 Economic Calendar",
        "ftab.positions": "📊 Positions",
        "ftab.regime":    "🌍 Regime & Market",
        "ftab.riskmode":  "⚡ Risk Mode",
        "ftab.signals":   "📡 Signals",
        "ftab.logs":      "📜 Logs",
        "ftab.features":  "⚙️ Features",
        "ftab.system":    "🖥️ System",
        "ftab.help":      "❓ Help",
    },
}


def _t(key: str) -> str:
    """Return translated string for the current language."""
    lang = st.session_state.get("lang", "de")
    return _T.get(lang, _T["de"]).get(key, _T["de"].get(key, key))


# ── Datenabruf ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=20, show_spinner=False)
def _get(endpoint: str) -> dict:
    try:
        r = requests.get(f"{API_URL}{endpoint}", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


@st.cache_data(ttl=20, show_spinner=False)
def _fget(endpoint: str) -> dict:
    """Forex API GET request."""
    try:
        r = requests.get(f"{FOREX_API_URL}{endpoint}", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _fpost(endpoint: str, json: dict = None) -> dict:
    """Forex API POST request — optionaler JSON-Body."""
    try:
        r = requests.post(f"{FOREX_API_URL}{endpoint}", json=json, timeout=5)
        if r.status_code == 200:
            return r.json()
        return {"error": r.json().get("detail", f"HTTP {r.status_code}")}
    except Exception as e:
        return {"error": str(e)}


def _post(endpoint: str) -> dict:
    try:
        r = requests.post(f"{API_URL}{endpoint}", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _post_url(url: str) -> dict:
    try:
        r = requests.post(f"{API_URL}{url}", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _post_json(endpoint: str, json: dict = None) -> dict:
    """Crypto API POST request mit JSON-Body."""
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=json, timeout=5)
        if r.status_code == 200:
            return r.json()
        return {"error": r.json().get("detail", f"HTTP {r.status_code}")}
    except Exception as e:
        return {"error": str(e)}


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_connection_badge(exchange: str, connected, error: str, env: str = ""):
    """Zeigt 🟢/🔴/⚠️ Badge für Broker/Exchange-Verbindung."""
    env_label = f" ({env})" if env else ""
    if connected is True:
        st.sidebar.success(f"🟢 {exchange.upper()}{env_label} verbunden")
    elif connected is False:
        if not error:
            st.sidebar.error(f"🔴 {exchange.upper()}{env_label} — Credentials fehlen")
        elif "400" in error or "401" in error or "403" in error:
            st.sidebar.error(f"🔴 {exchange.upper()}{env_label} — Login fehlgeschlagen")
        elif "timeout" in error.lower() or "connection" in error.lower():
            st.sidebar.warning(f"🟡 {exchange.upper()}{env_label} — Verbindungsfehler")
        else:
            st.sidebar.error(f"🔴 {exchange.upper()}{env_label} — {error[:60]}")
    else:
        st.sidebar.info(f"📄 {exchange.upper()}{env_label} — Paper Modus")


def render_sidebar(status: dict):
    st.sidebar.title("🤖 Trading Bot")
    st.sidebar.caption(f"Version 2.0 | {status.get('trading_mode', '?').upper()}")

    # ── Standard / Pro Toggle ─────────────────────────────────────────────────
    if "view_mode" not in st.session_state:
        st.session_state["view_mode"] = "standard"
    st.sidebar.markdown("---")
    _vm_col1, _vm_col2 = st.sidebar.columns(2)
    with _vm_col1:
        _std_type = "primary" if st.session_state["view_mode"] == "standard" else "secondary"
        if st.button(_t("s.view_standard"), key="vm_std", use_container_width=True, type=_std_type):
            st.session_state["view_mode"] = "standard"
            st.rerun()
    with _vm_col2:
        _pro_type = "primary" if st.session_state["view_mode"] == "pro" else "secondary"
        if st.button(_t("s.view_pro"), key="vm_pro", use_container_width=True, type=_pro_type):
            st.session_state["view_mode"] = "pro"
            st.rerun()

    # Exchange-Verbindungsstatus
    _render_connection_badge(
        exchange  = status.get("exchange", "Binance"),
        connected = status.get("exchange_connected"),
        error     = status.get("exchange_error", ""),
    )

    running = status.get("running", False)
    bot_pid = status.get("bot_pid")
    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.control"))

    # Start-Button — nur wenn Bot nicht läuft
    if not running:
        if st.sidebar.button(_t("b.start"), use_container_width=True, type="primary"):
            result = _post("/api/control/start")
            if result.get("status") == "ok":
                st.sidebar.success(result.get("message", _t("b.start")))
            else:
                st.sidebar.error(result.get("message", "Fehler beim Starten"))
    else:
        pid_info = f" (PID {bot_pid})" if bot_pid else ""
        st.sidebar.success(f"{_t('i.bot_running')}{pid_info}")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button(_t("b.stop"), use_container_width=True):
            result = _post("/api/control/stop")
            st.toast(result.get("message", "Gesendet"), icon="⛔")

    with col2:
        if st.button(_t("b.paper"), use_container_width=True):
            result = _post("/api/control/simulation")
            st.toast(result.get("message", "Gewechselt"), icon="📄")

    # Pause / Resume
    col3, col4 = st.sidebar.columns(2)
    with col3:
        if st.button(_t("b.pause"), use_container_width=True):
            result = _post("/api/control/pause")
            st.toast(result.get("message", "Pausiert"), icon="⏸")
    with col4:
        if st.button(_t("b.resume"), use_container_width=True):
            result = _post("/api/control/resume")
            st.toast(result.get("message", "Fortgesetzt"), icon="▶️")

    if st.sidebar.button(_t("b.safe"), use_container_width=True):
        result = _post("/api/control/safe_mode")
        st.sidebar.success(result.get("message", "Umgeschaltet"))

    _needs_retrain = status.get("symbol_changed", False)
    _retrain_label = _t("b.retrain_warn") if _needs_retrain else _t("b.retrain")
    _retrain_type  = "primary" if _needs_retrain else "secondary"
    if st.sidebar.button(_retrain_label, use_container_width=True, type=_retrain_type):
        result = _post("/api/control/retrain")
        st.sidebar.info(result.get("message", "Angefordert"))

    if st.sidebar.button(_t("b.restart"), use_container_width=True):
        result = _post("/api/control/restart")
        st.sidebar.warning(result.get("message", "Training Mode gestartet"))

    # Risk Personality Mode
    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.risk_mode"))
    current_mode = status.get("risk_mode", "balanced")
    mode_icons   = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}
    st.sidebar.markdown(f"{_t('s.currently')}: **{mode_icons.get(current_mode, '')} {current_mode.upper()}**")
    col_r1, col_r2, col_r3 = st.sidebar.columns(3)
    with col_r1:
        if st.button("🛡️", use_container_width=True, help=_t("s.risk_help_c")):
            r = _post_url("/api/control/risk_mode/conservative")
            st.sidebar.success(r.get("message", "Gesetzt"))
    with col_r2:
        if st.button("⚖️", use_container_width=True, help=_t("s.risk_help_b")):
            r = _post_url("/api/control/risk_mode/balanced")
            st.sidebar.success(r.get("message", "Gesetzt"))
    with col_r3:
        if st.button("🔥", use_container_width=True, help=_t("s.risk_help_a")):
            r = _post_url("/api/control/risk_mode/aggressive")
            st.sidebar.success(r.get("message", "Gesetzt"))

    # ── Symbol (Handelspaar) ──────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.pair"))
    _popular_pairs = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
                      "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT"]
    _current_symbol = status.get("symbol", "BTC/USDT")
    _symbol_changed = status.get("symbol_changed", False)

    if _symbol_changed:
        st.sidebar.warning(_t("s.pair_warn"))

    _pair_options = _popular_pairs if _current_symbol in _popular_pairs else [_current_symbol] + _popular_pairs
    _pair_options_with_custom = _pair_options + ["✏️ " + (_t("s.pair_custom").split("(")[0].strip() + "...")]
    _cur_idx = _pair_options_with_custom.index(_current_symbol) if _current_symbol in _pair_options_with_custom else 0
    _selected = st.sidebar.selectbox(
        _t("s.pair_select"), _pair_options_with_custom, index=_cur_idx,
        key="symbol_select", label_visibility="collapsed",
    )
    if _selected.startswith("✏️"):
        _selected = st.sidebar.text_input(_t("s.pair_custom"), value="", key="symbol_custom").upper().strip()

    _col_sym1, _col_sym2 = st.sidebar.columns([3, 1])
    with _col_sym1:
        st.sidebar.caption(f"{_t('s.pair_active')}: **{_current_symbol}**")
    with _col_sym2:
        if st.button("✓", key="symbol_apply", help=_t("s.pair_select"),
                     type="primary" if _symbol_changed else "secondary"):
            if _selected and _selected != _current_symbol and "/" in _selected:
                _sym_result = _post_url(f"/api/control/symbol/{_selected.replace('/', '-')}")
                if _sym_result.get("status") == "ok":
                    st.sidebar.success(f"✓ {_selected}")
                    st.sidebar.error("🔴 Bot neu starten erforderlich!")
                else:
                    st.sidebar.error(_sym_result.get("message", "Fehler"))

    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.export"))
    col3, col4 = st.sidebar.columns(2)
    with col3:
        if st.button("📥 CSV", use_container_width=True):
            r = _get("/api/export/csv")
            st.toast(r.get("path", "Exportiert"), icon="📥")
    with col4:
        if st.button("📊 JSON", use_container_width=True):
            r = _get("/api/export/json")
            st.toast(r.get("path", "Exportiert"), icon="📊")

    # ── Log-Level Steuerung ───────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.log_level"))
    _lvl_data    = _get("/api/log_level")
    _cur_level   = _lvl_data.get("level", "INFO")
    _level_opts  = ["DEBUG", "INFO", "WARNING", "ERROR"]
    _level_icons = {"DEBUG": "🔍", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🔴"}
    _level_idx   = _level_opts.index(_cur_level) if _cur_level in _level_opts else 1
    _col_lv1, _col_lv2 = st.sidebar.columns([3, 1])
    with _col_lv1:
        _new_level = st.selectbox(
            _t("s.log_level"), _level_opts, index=_level_idx,
            key="log_level_select", label_visibility="collapsed",
        )
    with _col_lv2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✓", key="log_level_apply", help=f"{_t('s.log_active')}: {_cur_level}"):
            r = _post_url(f"/api/control/log_level/{_new_level}")
            if r.get("status") == "ok":
                st.sidebar.success(f"✓ {_new_level}")
            else:
                st.sidebar.error(r.get("message", "Fehler"))
    st.sidebar.caption(f"{_t('s.log_active')}: {_level_icons.get(_cur_level, '')} {_cur_level}")

    # ── Zeitzone ──────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader(_t("s.timezone"))
    _tz_opts = _tz_list()
    _cur_tz  = st.session_state.get("tz", "Europe/Berlin")
    _tz_idx  = _tz_opts.index(_cur_tz) if _cur_tz in _tz_opts else 0
    _sel_tz  = st.sidebar.selectbox(
        _t("s.timezone"), _tz_opts, index=_tz_idx,
        key="tz_select", label_visibility="collapsed",
    )
    if _sel_tz != _cur_tz:
        st.session_state["tz"] = _sel_tz
        st.rerun()

    # Status-Indikator
    st.sidebar.markdown("---")
    last_update = status.get("last_update", "")
    if last_update:
        st.sidebar.caption(f"{_t('s.last_update')}: {_fmt_dt(last_update)}")

    safe_mode = status.get("safe_mode", False)
    if safe_mode:
        st.sidebar.warning(_t("s.safe_mode_active"))

    mode_color = "🟢" if status.get("trading_mode") == "live" else "🟡"
    st.sidebar.markdown(f"{mode_color} {_t('s.mode')}: **{status.get('trading_mode', '?').upper()}**")


# ── Equity Chart ──────────────────────────────────────────────────────────────

def render_equity_chart(equity_data: dict):
    curve   = equity_data.get("equity_curve", [])
    initial = equity_data.get("initial_capital", 1000)

    if not curve:
        st.info(_t("i.no_equity"))
        return

    df = pd.DataFrame(curve)
    df["date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")
    df = df.sort_values("date").dropna(subset=["capital"])

    color = "#00ff88" if df["capital"].iloc[-1] >= initial else "#ff4444"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["capital"],
        fill="tozeroy", fillcolor="rgba(0,255,136,0.05)",
        line=dict(color=color, width=2),
        name=_t("c.capital"),
        hovertemplate=f"<b>%{{x}}</b><br>{_t('c.capital')}: $%{{y:,.2f}}<extra></extra>",
    ))
    fig.add_hline(
        y=initial, line_dash="dash", line_color="#666",
        annotation_text=f"{_t('c.start')}: ${initial:,.0f}",
    )
    fig.update_layout(
        title=_t("c.equity"),
        xaxis_title="", yaxis_title=_t("c.capital_ax"),
        template="plotly_dark", height=350,
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Performance Metrics ───────────────────────────────────────────────────────

def render_performance(perf: dict):
    st.subheader(_t("sec.perf"))

    c1, c2, c3, c4, c5 = st.columns(5)
    total_pnl  = perf.get("total_pnl", 0)
    ret_pct    = perf.get("return_pct", 0)
    win_rate   = perf.get("win_rate", 0)
    sharpe     = perf.get("sharpe_ratio", 0)
    drawdown   = perf.get("max_drawdown", 0)
    sortino    = perf.get("sortino_ratio", 0)
    pf         = perf.get("profit_factor", 0)

    with c1:
        delta_color = "normal" if total_pnl >= 0 else "inverse"
        st.metric(_t("m.total_pnl"), f"${total_pnl:+,.2f}", f"{ret_pct:+.2f}%",
                  delta_color=delta_color)
    with c2:
        st.metric(_t("m.win_rate"), f"{win_rate:.1f}%",
                  f"{perf.get('wins', 0)}W / {perf.get('losses', 0)}L")
    with c3:
        st.metric(_t("m.sharpe"), f"{sharpe:.2f}",
                  _t("v.good") if sharpe > 1 else _t("v.weak"))
    with c4:
        st.metric(_t("m.drawdown"), f"{drawdown:.1f}%",
                  _t("v.ok") if drawdown < 10 else _t("v.high"), delta_color="inverse")
    with c5:
        st.metric(_t("m.pf"), f"{pf:.2f}",
                  _t("v.good") if pf > 1.5 else _t("v.weak"))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(_t("m.sortino"), f"{sortino:.2f}")
    with col2:
        st.metric(_t("m.avg_win"), f"${perf.get('avg_win', 0):+.2f}")
    with col3:
        st.metric(_t("m.avg_loss"), f"${perf.get('avg_loss', 0):+.2f}")


# ── Live Status ───────────────────────────────────────────────────────────────

def render_live_status(status: dict):
    col1, col2, col3, col4, col5 = st.columns(5)

    capital    = status.get("capital", 0)
    initial    = status.get("initial_capital", 1000)
    daily_pnl  = status.get("daily_pnl", 0)
    regime     = status.get("regime", "UNKNOWN")
    vol_regime = status.get("volatility_regime", "UNKNOWN")
    confidence = status.get("ai_confidence", 0)
    strategy   = status.get("active_strategy", "?")

    with col1:
        delta_color = "normal" if capital >= initial else "inverse"
        st.metric(_t("m.capital"), f"${capital:,.2f}",
                  f"{(capital - initial) / initial * 100:+.2f}%",
                  delta_color=delta_color)
    with col2:
        dc = "normal" if daily_pnl >= 0 else "inverse"
        st.metric(_t("m.daily_pnl"), f"${daily_pnl:+.2f}", delta_color=dc)
    with col3:
        regime_icons = {
            "BULL_TREND": "🐂", "BEAR_TREND": "🐻",
            "SIDEWAYS": "↔️", "HIGH_VOLATILITY": "⚡", "UNKNOWN": "❓"
        }
        icon = regime_icons.get(regime, "❓")
        st.metric(f"{icon} {_t('m.regime')}", regime)
    with col4:
        vol_icons = {"LOW": "🟢", "NORMAL": "🟡", "HIGH": "🟠", "EXTREME": "🔴", "UNKNOWN": "⚪"}
        v_icon = vol_icons.get(vol_regime, "⚪")
        st.metric(f"{v_icon} {_t('m.volatility')}", vol_regime)
    with col5:
        st.metric(_t("m.ai_conf"), f"{confidence:.0%}",
                  f"{_t('m.strategy')}: {strategy}")


# ── Position ──────────────────────────────────────────────────────────────────

def render_position(status: dict):
    pos = status.get("position")
    if not pos:
        st.info(_t("i.no_pos"))
        return

    entry    = pos.get("entry_price", 0)
    current  = status.get("current_price", entry)
    sl       = pos.get("stop_loss", 0)
    tp       = pos.get("take_profit", 0)
    qty      = pos.get("quantity", 0)
    unreal   = (current - entry) * qty
    unreal_p = (current - entry) / entry * 100 if entry > 0 else 0

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = go.Figure()
        fig.add_hline(y=entry, line_color="#ffaa00", line_dash="solid",
                      annotation_text=f"Entry ${entry:,.0f}", annotation_position="left")
        fig.add_hline(y=sl, line_color="#ff4444", line_dash="dash",
                      annotation_text=f"Stop-Loss ${sl:,.0f}", annotation_position="left")
        fig.add_hline(y=tp, line_color="#00ff88", line_dash="dash",
                      annotation_text=f"Take-Profit ${tp:,.0f}", annotation_position="left")
        fig.add_hline(y=current, line_color="#4488ff", line_dash="dot",
                      annotation_text=f"${current:,.0f}", annotation_position="right")
        fig.update_layout(
            title=f"{_t('sec.pos')}: {pos.get('symbol', '')}",
            template="plotly_dark", height=200,
            margin=dict(l=100, r=150, t=40, b=20),
            yaxis_title=_t("c.price"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        dc = "normal" if unreal >= 0 else "inverse"
        st.metric(_t("m.unrealized"), f"${unreal:+.2f}",
                  f"{unreal_p:+.2f}%", delta_color=dc)
        st.metric(_t("m.qty"), f"{qty:.6f}")


# ── Trades Tabelle ────────────────────────────────────────────────────────────

def render_trades(trades_data: dict):
    trades = trades_data.get("trades", [])
    if not trades:
        st.info(_t("i.no_trades"))
        return

    df = pd.DataFrame(trades)
    if "pnl" in df.columns:
        df["pnl"] = df["pnl"].round(2)
        df["pnl_pct"] = df["pnl_pct"].round(2) if "pnl_pct" in df else ""

    # Timestamps in gewählte Zeitzone konvertieren
    df = _fmt_df_ts(df, ["created_at", "entry_time", "exit_time"])

    def highlight_pnl(val):
        if isinstance(val, (int, float)):
            color = "#00ff8844" if val > 0 else "#ff444444" if val < 0 else ""
            return f"background-color: {color}"
        return ""

    cols = ["created_at", "side", "entry_price", "exit_price", "quantity",
            "pnl", "pnl_pct", "reason", "ai_source", "confidence"]
    available = [c for c in cols if c in df.columns]

    st.dataframe(
        df[available].head(20).style.applymap(highlight_pnl, subset=["pnl"] if "pnl" in available else []),
        use_container_width=True, height=300,
    )


# ── Wöchentliche / Monatliche Charts ─────────────────────────────────────────

def _render_periodic_charts():
    periods    = _get("/api/performance/periods")
    chart_data = _get("/api/performance/periods/chart")

    if not periods:
        st.info(_t("i.no_perf"))
        return

    st.subheader(_t("sec.rolling"))
    col1, col2, col3 = st.columns(3)
    for col, (key, label) in zip(
        [col1, col2, col3],
        [("7d", _t("p.7d")), ("30d", _t("p.30d")), ("total", _t("p.total"))],
    ):
        p      = periods.get(key, {})
        trades = p.get("trades") or p.get("total_trades") or 0
        pnl    = p.get("pnl") or p.get("total_pnl") or 0.0
        wr     = p.get("win_rate", 0.0)
        with col:
            st.markdown(f"**{label}**")
            dc = "normal" if pnl >= 0 else "inverse"
            st.metric("PnL", f"${pnl:+.2f}", f"{wr:.0f}% Win | {trades} Trades",
                      delta_color=dc)

    st.markdown("---")

    weekly = chart_data.get("weekly", [])
    if weekly:
        st.subheader(_t("c.weekly"))
        df_w = pd.DataFrame(weekly)
        colors_w = ["#00ff88" if v >= 0 else "#ff4444" for v in df_w["pnl"]]
        fig_w = go.Figure(go.Bar(
            x=df_w["period"], y=df_w["pnl"],
            marker_color=colors_w,
            hovertemplate="<b>%{x}</b><br>PnL: $%{y:+.2f}<extra></extra>",
        ))
        fig_w.update_layout(
            template="plotly_dark", height=280,
            xaxis_title=_t("c.week_ax"), yaxis_title=_t("c.pnl_ax"),
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig_w, use_container_width=True)

    monthly = chart_data.get("monthly", [])
    if monthly:
        st.subheader(_t("c.monthly"))
        df_m = pd.DataFrame(monthly)
        colors_m = ["#00ff88" if v >= 0 else "#ff4444" for v in df_m["pnl"]]
        fig_m = go.Figure(go.Bar(
            x=df_m["period"], y=df_m["pnl"],
            marker_color=colors_m,
            hovertemplate="<b>%{x}</b><br>PnL: $%{y:+.2f}<extra></extra>",
        ))
        fig_m.update_layout(
            template="plotly_dark", height=280,
            xaxis_title=_t("c.month_ax"), yaxis_title=_t("c.pnl_ax"),
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig_m, use_container_width=True)

    if not weekly and not monthly:
        st.info(_t("i.no_weekly"))


# ── Strategie-Performance ─────────────────────────────────────────────────────

def _render_strategy_performance():
    st.subheader(_t("sec.strategy"))
    data = _get("/api/strategy_performance")
    perf = data.get("strategy_performance", {})

    if not perf:
        st.info(_t("i.no_strategy"))
        return

    is_en = st.session_state.get("lang") == "en"
    rows = []
    for name, s in perf.items():
        rows.append({
            "Strategy" if is_en else "Strategie":    name,
            "Trades":       s.get("trades", 0),
            "Win Rate" if is_en else "Win-Rate":     f"{s.get('win_rate_pct', 0):.1f}%",
            "Total PnL" if is_en else "Gesamt PnL":  f"${s.get('total_pnl', 0):+.2f}",
            "Avg PnL" if is_en else "Ø PnL":         f"${s.get('avg_pnl', 0):+.2f}",
            "Conf ×" if is_en else "Konfidenz ×":    f"{s.get('confidence_mult', 1.0):.2f}×",
            "Retired?" if is_en else "Ruht?":        "⚠️ Yes" if s.get("retired") else "✅ Active",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    st.markdown("---")
    risk_mode = data.get("risk_mode", "balanced")
    mode_info = {
        "conservative": (_t("rm.c_label"), _t("rm.c_desc")),
        "balanced":     (_t("rm.b_label"), _t("rm.b_desc")),
        "aggressive":   (_t("rm.a_label"), _t("rm.a_desc")),
    }
    title, desc = mode_info.get(risk_mode, ("?", ""))
    st.metric(_t("sec.risk_active"), title, desc)


# ── AI Explainability ─────────────────────────────────────────────────────────

def _render_explainability(status: dict):
    st.subheader(_t("sec.explain"))

    last_rejection = status.get("last_rejection")
    if last_rejection:
        reason = last_rejection.get("reason", "?")
        source = last_rejection.get("source", "?")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.warning(f"**{_t('misc.hold_reason')}:** {reason}")
        with col2:
            st.caption(f"{_t('misc.source')}: {source}")
    else:
        st.info(_t("i.no_hold"))

    drift = status.get("drift_status")
    if drift:
        st.markdown("---")
        st.subheader(_t("sec.drift"))
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(_t("misc.accuracy"), f"{drift.get('current_f1', 0):.1%}")
        with c2:
            st.metric(_t("misc.baseline"), f"{drift.get('baseline_f1', 0):.1%}")
        with c3:
            drift_pct = drift.get("drift_pct", 0)
            dc = "normal" if drift_pct >= 0 else "inverse"
            st.metric(_t("misc.drift_lbl"), f"{drift_pct:+.1%}", delta_color=dc)
        if drift.get("has_drift"):
            st.error(_t("misc.drift_warn"))

    st.markdown("---")
    st.subheader(_t("sec.rejections"))
    rejections_data = _get("/api/rejections?limit=10")
    rejs = rejections_data.get("rejections", [])
    if rejs:
        df = pd.DataFrame(rejs)
        avail = [c for c in ["created_at", "signal", "price", "source", "strategy", "reason"] if c in df.columns]
        df = _fmt_df_ts(df, ["created_at"])
        st.dataframe(df[avail], use_container_width=True, height=250)
    else:
        st.info(_t("i.no_rej"))

    st.markdown("---")
    st.subheader(_t("sec.signals"))
    signals_data = _get("/api/signals?limit=10")
    signals = signals_data.get("signals", [])
    if signals:
        df_s = pd.DataFrame(signals)
        available = [c for c in ["created_at", "signal", "price", "ai_source", "confidence", "reasoning"]
                     if c in df_s.columns]
        df_s = _fmt_df_ts(df_s, ["created_at"])
        st.dataframe(df_s[available], use_container_width=True, height=250)
    else:
        st.info(_t("i.no_sig"))


# ── Candlestick Chart ─────────────────────────────────────────────────────────

def _render_candle_chart(candles: list, title: str, entry_price: float = None,
                          sl: float = None, tp: float = None):
    """Plotly dark-mode candlestick chart with optional SMA + trade lines."""
    if not candles:
        st.info("Keine Candle-Daten verfügbar.")
        return

    import pandas as pd
    df = pd.DataFrame(candles)
    time_col = next((c for c in df.columns if c in ("time", "timestamp", "datetime", "date")), None)
    if time_col:
        ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    else:
        ts = pd.RangeIndex(len(df))

    fig = go.Figure()

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=ts, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Kurs",
        increasing_line_color="#00cc66", decreasing_line_color="#ff4444",
        increasing_fillcolor="#00cc66", decreasing_fillcolor="#ff4444",
    ))

    # SMA 20 + 50
    if len(df) >= 20:
        fig.add_trace(go.Scatter(
            x=ts, y=df["close"].rolling(20).mean(),
            line=dict(color="#4488ff", width=1), name="SMA 20", opacity=0.8,
        ))
    if len(df) >= 50:
        fig.add_trace(go.Scatter(
            x=ts, y=df["close"].rolling(50).mean(),
            line=dict(color="#ffaa00", width=1), name="SMA 50", opacity=0.8,
        ))

    # Entry / SL / TP Linien
    if entry_price:
        fig.add_hline(y=entry_price, line_color="#ffffff", line_dash="dash",
                      line_width=1, annotation_text="Entry", annotation_position="right")
    if sl:
        fig.add_hline(y=sl, line_color="#ff4444", line_dash="dot",
                      line_width=1, annotation_text="SL", annotation_position="right")
    if tp:
        fig.add_hline(y=tp, line_color="#00cc66", line_dash="dot",
                      line_width=1, annotation_text="TP", annotation_position="right")

    # Volume
    if "volume" in df.columns and df["volume"].sum() > 0:
        colors = ["#00cc66" if c >= o else "#ff4444"
                  for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=ts, y=df["volume"], name="Volume",
            marker_color=colors, opacity=0.3,
            yaxis="y2",
        ))
        fig.update_layout(
            yaxis2=dict(overlaying="y", side="right", showgrid=False,
                        showticklabels=False, range=[0, df["volume"].max() * 5]),
        )

    fig.update_layout(
        title=dict(text=title, x=0.0, xanchor="left", font=dict(size=14)),
        template="plotly_dark",
        height=500,
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h", yanchor="top", y=-0.15,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        margin=dict(l=0, r=60, t=30, b=60),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Forex Phase Progress ──────────────────────────────────────────────────────

def _render_forex_phase_progress():
    prog = _fget("/api/progress")
    if not prog or "error" in prog:
        return

    phase       = prog.get("current_phase", "PAPER_TRADING")
    next_phase  = prog.get("next_phase", "")
    overall_pct = prog.get("overall_pct", 0.0)
    passed      = prog.get("passed_count", 0)
    total       = prog.get("total_checks", 5)
    checks      = prog.get("checks", [])
    eta_label   = prog.get("eta_label", "")
    days_in     = prog.get("days_in_phase", 0)

    _phase_colors = {
        "PAPER_TRADING":  "#4488ff",
        "PRACTICE_LIVE":  "#ffaa00",
        "LIVE_TRADING":   "#00cc66",
    }
    _phase_icons = {
        "PAPER_TRADING":  "📄",
        "PRACTICE_LIVE":  "🔬",
        "LIVE_TRADING":   "🚀",
    }
    _phase_labels = {
        "PAPER_TRADING":  "PAPER",
        "PRACTICE_LIVE":  "PRACTICE",
        "LIVE_TRADING":   "LIVE",
    }
    color      = _phase_colors.get(phase, "#888")
    icon       = _phase_icons.get(phase, "📊")
    label      = _phase_labels.get(phase, phase)
    next_label = _phase_labels.get(next_phase, next_phase)

    st.markdown(
        f"### {icon} Trading Phase: "
        f'<span style="color:{color}"><b>{label}</b></span> → **{next_label}**',
        unsafe_allow_html=True,
    )

    hint_parts = [f"{c['name']}: {c['current']:.2f} → {c['target']:.2f}{c['unit']}"
                  for c in checks if not c.get("passed")]
    hint = ("Fehlt: " + " | ".join(hint_parts[:2])) if hint_parts else "Alle Kriterien erfüllt"

    bar_color = _phase_colors.get(phase, "#4488ff")
    eta_html  = (
        f'<div style="color:#ffaa44;font-size:12px;margin-top:2px;margin-bottom:8px">⏱ '
        f'{eta_label.replace(chr(10), "<br>")}</div>'
        if eta_label else ""
    )
    days_html = (
        f'<div style="color:#888;font-size:11px;margin-bottom:2px">📅 {days_in} Tage in dieser Phase</div>'
        if days_in > 0 else ""
    )
    st.markdown(
        f'<div style="background:#222;border-radius:8px;height:24px;width:100%;margin-bottom:4px">'
        f'<div style="background:{bar_color};width:{overall_pct}%;height:100%;border-radius:8px;'
        f'display:flex;align-items:center;padding-left:8px;font-weight:bold;font-size:13px;color:#fff">'
        f'{overall_pct:.0f}%</div></div>'
        f'<div style="color:#888;font-size:12px;margin-bottom:4px">'
        f'{passed}/{total} Kriterien erfüllt — {hint}</div>'
        f'{eta_html}{days_html}',
        unsafe_allow_html=True,
    )

    if checks:
        cols = st.columns(len(checks))
        for col, c in zip(cols, checks):
            with col:
                c_icon  = "✅" if c["passed"] else "⏳"
                c_color = "#00cc66" if c["passed"] else "#4488ff"
                pct     = c.get("pct", 0.0)
                st.markdown(
                    f'<div style="background:#1a1a2e;border-radius:8px;padding:10px;text-align:center">'
                    f'<div style="font-size:11px;color:#aaa;margin-bottom:4px">{c_icon} {c["name"]}</div>'
                    f'<div style="background:#333;border-radius:4px;height:8px;margin-bottom:4px">'
                    f'<div style="background:{c_color};width:{pct}%;height:100%;border-radius:4px"></div></div>'
                    f'<div style="font-size:13px;font-weight:bold;color:#fff">'
                    f'{c["current"]:.2f}{c["unit"]}</div>'
                    f'<div style="font-size:10px;color:#666">Ziel: {c["target"]:.2f}{c["unit"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ── Phase Progress ────────────────────────────────────────────────────────────

def _render_phase_progress():
    prog = _get("/api/progress")
    if not prog or "error" in prog:
        return

    phase           = prog.get("phase", "PAPER")
    overall_pct     = prog.get("overall_pct", 0.0)
    passed          = prog.get("passed_count", 0)
    total           = prog.get("total_count", 5)
    next_phase      = prog.get("next_phase", "")
    hint            = prog.get("next_phase_hint", "")
    criteria        = prog.get("criteria", [])
    trade_breakdown = prog.get("trade_breakdown", {})

    phase_color = {"PAPER": "#4488ff", "TESTNET": "#ffaa00", "LIVE": "#00cc66"}.get(phase, "#888")
    phase_icon  = {"PAPER": "📄", "TESTNET": "🧪", "LIVE": "🚀"}.get(phase, "📊")

    st.markdown(f"### {phase_icon} {_t('ph.phase')}: "
                f'<span style="color:{phase_color}"><b>{phase}</b></span> '
                f"→ **{next_phase}**", unsafe_allow_html=True)

    bar_color = "#4488ff" if phase == "PAPER" else ("#ffaa00" if phase == "TESTNET" else "#00cc66")
    bt_count   = trade_breakdown.get("backtest", 0)
    live_count = trade_breakdown.get("live", 0)
    trade_note = ""
    if bt_count > 0:
        trade_note = (f' &nbsp;|&nbsp; 📄 {live_count} Live-Trades + '
                      f'<span style="color:#888">🔁 {bt_count} Backtest</span>')

    eta_label = prog.get("eta_label", "")
    eta_html  = (
        f'<div style="color:#ffaa44;font-size:12px;margin-top:2px;margin-bottom:8px">⏱ '
        f'{eta_label.replace(chr(10), "<br>")}</div>'
        if eta_label else ""
    )
    st.markdown(
        f'<div style="background:#222;border-radius:8px;height:24px;width:100%;margin-bottom:4px">'
        f'<div style="background:{bar_color};width:{overall_pct}%;height:100%;border-radius:8px;'
        f'display:flex;align-items:center;padding-left:8px;font-weight:bold;font-size:13px;color:#fff">'
        f'{overall_pct:.0f}%</div></div>'
        f'<div style="color:#888;font-size:12px;margin-bottom:4px">'
        f'{passed}/{total} {_t("ph.criteria_met")} — {hint}{trade_note}</div>'
        f'{eta_html}',
        unsafe_allow_html=True,
    )

    cols = st.columns(len(criteria))
    for col, c in zip(cols, criteria):
        with col:
            icon  = "✅" if c["passed"] else "⏳"
            color = "#00cc66" if c["passed"] else "#4488ff"
            pct   = c["pct"]
            st.markdown(
                f'<div style="background:#1a1a2e;border-radius:8px;padding:10px;text-align:center">'
                f'<div style="font-size:11px;color:#aaa;margin-bottom:4px">{icon} {c["label"]}</div>'
                f'<div style="background:#333;border-radius:4px;height:8px;margin-bottom:4px">'
                f'<div style="background:{color};width:{pct}%;height:100%;border-radius:4px"></div></div>'
                f'<div style="font-size:13px;font-weight:bold;color:#fff">'
                f'{c["current"]}{c["unit"]}</div>'
                f'<div style="font-size:10px;color:#666">{_t("ph.target")}: {c["target"]}{c["unit"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ── Heartbeat / System Health ─────────────────────────────────────────────────

def render_heartbeat(hb: dict):
    alive   = hb.get("alive")
    silence = hb.get("silence_minutes")
    last_ping = hb.get("last_ping")
    if alive is True and silence is not None:
        st.success(f"💓 Bot aktiv — letzter Heartbeat vor {silence:.0f} Min")
    elif alive is False and silence is not None:
        st.error(f"💀 Bot nicht aktiv — Stille seit {silence:.0f} Min!")
    elif alive is False and last_ping is None:
        st.warning("⏳ Bot noch nicht gestartet — kein Heartbeat")
    else:
        st.warning("❓ Heartbeat-Status unbekannt")
    if last_ping:
        st.caption(f"Letzter Ping: {_fmt_dt(last_ping)}")


# ── Market Context ─────────────────────────────────────────────────────────────

def render_market_context():
    fg = _get("/api/fear_greed").get("fear_greed", {})
    ns = _get("/api/news_sentiment").get("news_sentiment", {})
    ms = _get("/api/microstructure").get("microstructure", {})
    cm = _get("/api/cross_market").get("cross_market", {})

    st.subheader("🌍 Markt-Kontext")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        fgi = fg.get("index") or fg.get("value")
        fgl = fg.get("label") or fg.get("classification", "–")
        if fgi is not None:
            icon = "🟢" if fgi > 50 else ("🔴" if fgi < 30 else "🟡")
            st.metric("Fear & Greed", f"{icon} {int(fgi)}", fgl)
        else:
            st.metric("Fear & Greed", "–")

    with c2:
        sent  = ns.get("signal") or ns.get("sentiment", "–")
        score = ns.get("score", 0.0)
        icon  = "🟢" if score > 0.1 else ("🔴" if score < -0.1 else "🟡")
        st.metric("News Sentiment", f"{icon} {sent}", f"Score: {score:+.2f}")

    with c3:
        ms_sig  = ms.get("signal") or ms.get("bias", "–")
        ms_conf = ms.get("confidence") or ms.get("conf", 0)
        conf_str = f"Konf: {ms_conf:.0%}" if ms_conf else ""
        st.metric("Microstructure", ms_sig or "–", conf_str)

    with c4:
        cm_sig = cm.get("signal", "–")
        dom    = cm.get("btc_dominance")
        st.metric("Cross-Market", cm_sig or "–", f"BTC Dom: {dom:.1f}%" if dom else "")


# ── Execution Quality ─────────────────────────────────────────────────────────

def render_execution_quality(eq: dict):
    st.subheader("⚡ Execution Quality")
    if not eq or eq.get("error") or not eq.get("total_fills"):
        st.info("Noch keine Execution-Daten (Paper Mode oder keine abgeschlossenen Trades)")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Ø Slippage", f"{eq.get('avg_slippage_bps', 0):.1f} bps")
    c2.metric("Fill Rate",  f"{eq.get('fill_rate_pct', 0):.1f}%")
    c3.metric("Analysierte Fills", eq.get("total_fills", 0))
    recent = eq.get("recent", [])
    if recent:
        df_eq = pd.DataFrame(recent)
        if "timestamp" in df_eq.columns:
            df_eq = _fmt_df_ts(df_eq, ["timestamp"])
        st.dataframe(df_eq, use_container_width=True, hide_index=True)


# ── Performance Extended ──────────────────────────────────────────────────────

def render_performance_extended(ext: dict):
    st.subheader("📊 Erweiterte Metriken")
    if not ext or ext.get("total_trades", 0) == 0:
        st.info("Noch keine Trade-Daten für erweiterte Metriken.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sharpe",  f"{ext.get('sharpe', 0):.2f}")
    c2.metric("Sortino", f"{ext.get('sortino', 0):.2f}")
    c3.metric("Calmar",  f"{ext.get('calmar', 0):.2f}")
    c4.metric("Omega",   f"{ext.get('omega', 0):.2f}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Rolling Sharpe (20)", f"{ext.get('rolling_sharpe_20', 0):.2f}")
    c6.metric("Profit Factor",       f"{ext.get('profit_factor', 0):.2f}")
    c7.metric("Expectancy",          f"{ext.get('expectancy', 0):.2f} USDT")
    c8.metric("Ø Haltedauer",        f"{ext.get('avg_hold_hours', 0):.1f}h")

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Max Win Streak",  ext.get("max_win_streak", 0))
    c10.metric("Max Loss Streak", ext.get("max_loss_streak", 0))
    c11.metric("Ø Win",  f"{ext.get('avg_win', 0):.2f} USDT")
    c12.metric("Ø Loss", f"{ext.get('avg_loss', 0):.2f} USDT")

    with st.expander("📉 Drawdown-Analyse"):
        d1, d2, d3 = st.columns(3)
        d1.metric("Max Drawdown",       f"{ext.get('max_drawdown_pct', 0):.2f}%")
        d2.metric("Ø Drawdown-Dauer",   f"{ext.get('avg_drawdown_trades', 0):.0f} Trades")
        d3.metric("Max Drawdown-Dauer", f"{ext.get('max_drawdown_trades', 0)} Trades")


# ── Risk & Market Intelligence Tab ────────────────────────────────────────────

def _render_risk_market_tab():
    st.subheader("🔬 Risk & Market Intelligence")

    col_l, col_r = st.columns(2)

    with col_l:
        # Regime Simulation
        rs = _get("/api/regime_simulation").get("regime_simulation", {})
        with st.expander("🎲 Regime-Simulation", expanded=True):
            if rs:
                r1, r2, r3 = st.columns(3)
                r1.metric("Simuliertes Regime", rs.get("simulated_regime") or rs.get("regime", "–"))
                exp_val = rs.get("exposure_pct") or rs.get("exposure")
                r2.metric("Exposure", f"{float(exp_val):.0%}" if exp_val is not None else "–")
                r3.metric("Richtung", rs.get("direction", "–"))
            else:
                st.info("Keine Simulation-Daten")

        # Stress Test
        stress = _get("/api/stress_test").get("stress_test", {})
        with st.expander("🔥 Stress Test"):
            if stress:
                s1, s2 = st.columns(2)
                s1.metric("Stress Level", stress.get("level", stress.get("result", "–")))
                factor = stress.get("factor") or stress.get("exposure_factor")
                s2.metric("Exposure Faktor", f"{float(factor):.0%}" if factor is not None else "–")
                if stress.get("scenarios"):
                    for scenario, val in stress["scenarios"].items():
                        st.caption(f"• {scenario}: {val}")
            else:
                st.info("Keine Stress-Test-Daten")

        # Capital Allocation
        ca = _get("/api/capital_allocation").get("capital_allocator", {})
        with st.expander("💼 Capital Allocation"):
            if ca:
                a1, a2 = st.columns(2)
                a1.metric("Signal Tier", ca.get("signal_tier", "–"))
                a2.metric("Risk Scale", f"{float(ca.get('risk_scale', 0)):.0%}" if ca.get('risk_scale') is not None else "–")
                if ca.get("reason"):
                    st.caption(ca["reason"])
            else:
                st.info("Keine Allokations-Daten")

    with col_r:
        # Opportunity Radar
        radar = _get("/api/opportunity_radar").get("opportunity_radar", {})
        with st.expander("📡 Opportunity Radar", expanded=True):
            if radar:
                best = radar.get("best_pair") or radar.get("top_pair")
                if best:
                    st.markdown(f"**Bestes Paar:** {best}")
                scores = radar.get("scores") or radar.get("pairs", {})
                if isinstance(scores, dict) and scores:
                    df_rad = pd.DataFrame([
                        {"Paar": k, "Score": v} for k, v in scores.items()
                    ]).sort_values("Score", ascending=False)
                    st.dataframe(df_rad, use_container_width=True, hide_index=True)
                elif isinstance(scores, list) and scores:
                    st.dataframe(pd.DataFrame(scores), use_container_width=True, hide_index=True)
                else:
                    st.info("Keine Paar-Scores verfügbar")
            else:
                st.info("Radar nicht aktiv")

        # Regime Forecast
        rf = _get("/api/regime_forecast").get("regime_forecast", {})
        with st.expander("🗺️ Regime-Forecast (Markov)"):
            if rf:
                for regime, prob in rf.items():
                    if isinstance(prob, (int, float)):
                        _p = float(prob) / 100 if float(prob) > 1 else float(prob)
                        st.progress(_p, text=f"{regime}: {_p:.0%}")
            else:
                st.info("Keine Forecast-Daten")

        # Derivatives
        deriv = _get("/api/derivatives").get("derivatives", {})
        with st.expander("📈 Derivatives"):
            if deriv:
                dv1, dv2 = st.columns(2)
                dv1.metric("Funding Rate", f"{deriv.get('funding_rate', 0):.4f}%")
                dv2.metric("Spot-Perp Basis", f"{deriv.get('basis', 0):.4f}%")
            else:
                st.info("Keine Derivatives-Daten")

    # Model Governance — volle Breite
    mg = _get("/api/model_governance").get("model_governance", {})
    if mg:
        with st.expander("🧬 Model Governance"):
            mg1, mg2, mg3 = st.columns(3)
            mg1.metric("Entropie",      f"{mg.get('entropy', 0):.3f}")
            mg2.metric("Feature Drift", f"{mg.get('feature_drift', 0):.3f}")
            mg3.metric("Kalibrations-Drift", f"{mg.get('calibration_drift', 0):.3f}")
            if mg.get("warnings"):
                for w in mg["warnings"]:
                    st.warning(w)

    # Live State
    ls = _get("/api/live_state")
    if ls:
        with st.expander("🔄 Live State Reconciliation"):
            ls1, ls2 = st.columns(2)
            ls1.metric("Modus", ls.get("trading_mode", "–").upper())
            ls2.metric("Reconciled", "✅ Ja" if ls.get("reconciled") else "❌ Nein")
            if ls.get("has_position") and ls.get("position"):
                st.json(ls["position"])


# ── Log Viewer ────────────────────────────────────────────────────────────────

def _render_logs():
    st.subheader(_t("sec.logs"))

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        level = st.selectbox(_t("l.filter"), ["ALL", "INFO", "WARNING", "ERROR"], index=0,
                             key="log_filter_level")
    with col2:
        num_lines = st.slider(_t("l.lines"), 50, 500, 200, step=50, key="log_num_lines")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄", help="Refresh", key="log_refresh_btn"):
            if _HAS_FRAGMENT:
                st.rerun(scope="fragment")
            else:
                st.rerun()

    level_param = "" if level == "ALL" else level
    data = _get(f"/api/logs?lines={num_lines}&level={level_param}")

    if not data.get("exists"):
        st.warning(_t("i.no_log"))
        return

    lines = data.get("lines", [])
    total = data.get("total", 0)
    st.caption(f"{len(lines)} {_t('l.of')} {total} {_t('l.lines')} | {_t('l.file')}: logs/bot.log")

    if not lines:
        st.info(_t("i.no_log_entries"))
        return

    colored = []
    for line in reversed(lines):
        if "[ERROR]" in line or "ERROR" in line:
            colored.append(f'<span style="color:#ff4444">{line}</span>')
        elif "[WARNING]" in line or "WARNING" in line:
            colored.append(f'<span style="color:#ffaa00">{line}</span>')
        elif "[INFO]" in line:
            colored.append(f'<span style="color:#aaaaaa">{line}</span>')
        else:
            colored.append(f'<span style="color:#888888">{line}</span>')

    log_html = (
        '<div style="background:#0e0e0e; padding:12px; border-radius:6px; '
        'font-family:monospace; font-size:12px; line-height:1.6; '
        'max-height:600px; overflow-y:auto;">'
        + "<br>".join(colored)
        + "</div>"
    )
    st.markdown(log_html, unsafe_allow_html=True)


# ── Hilfe / Glossar ──────────────────────────────────────────────────────────

def _render_help():
    if st.session_state.get("lang") == "en":
        _render_help_en()
    else:
        _render_help_de()


def _render_help_de():
    st.markdown("## ❓ Dashboard-Hilfe — Alle Begriffe erklärt")
    st.caption("Hier findest du einfache Erklärungen zu allem was im Dashboard angezeigt wird.")

    with st.expander("📊 Live-Status (die 5 Felder oben)", expanded=True):
        st.markdown("""
| Begriff | Was bedeutet das? |
|---------|-------------------|
| **💰 Kapital** | Wie viel USDT du gerade hast. Startet z.B. bei 1.000 USDT. Der %-Wert zeigt wie viel du seit dem Start gewonnen oder verloren hast. |
| **📊 Tages-PnL** | Dein heutiger Gewinn (grün) oder Verlust (rot) in USDT. Wird jeden Tag um Mitternacht UTC zurückgesetzt. |
| **🐂 Markt-Regime** | Was der Bot gerade vom Markt hält — *BULL_TREND* = Aufwärtstrend, *BEAR_TREND* = Abwärtstrend, *SIDEWAYS* = keine klare Richtung. |
| **Volatilität** | Wie stark der Preis schwankt — *LOW* = ruhig, *NORMAL* = normal, *HIGH* = unruhig, *EXTREME* = sehr unruhig. Bei hoher Vola handelt der Bot vorsichtiger. |
| **🤖 AI Konfidenz** | Wie sicher das KI-Modell gerade in seiner Einschätzung ist (0–100%). Unter 60% macht der Bot keinen Trade. |
""")

    with st.expander("📈 Equity-Kurve"):
        st.markdown("""
Die **Equity-Kurve** zeigt wie sich dein Kapital über die Zeit entwickelt hat.

- Die **gestrichelte Linie** ist dein Startkapital — alles darüber ist Gewinn, alles darunter ist Verlust
- **Grüne Linie** = aktuell im Plus gegenüber Start
- **Rote Linie** = aktuell im Minus

> Beispiel: Du startest mit 1.000 USDT. Nach 3 Monaten zeigt die Kurve 1.150 USDT → du bist 15% im Plus.
""")

    with st.expander("📍 Offene Position (Entry / Stop-Loss / Take-Profit)"):
        st.markdown("""
Wenn der Bot gerade einen Trade offen hat, siehst du hier drei wichtige Preislinien:

| Begriff | Einfach erklärt |
|---------|----------------|
| **Entry** (gelb) | Der Preis zu dem der Bot gekauft hat |
| **Stop-Loss** (rot, gestrichelt) | Der Sicherheitspreis — wenn BTC bis hierher fällt, verkauft der Bot automatisch um größere Verluste zu vermeiden |
| **Take-Profit** (grün, gestrichelt) | Das Gewinnziel — wenn BTC diesen Preis erreicht, verkauft der Bot mit Gewinn |
| **Aktueller Preis** (blau, gepunktet) | Der aktuelle BTC-Preis in Echtzeit |
| **Unrealisierter PnL** | Wie viel Gewinn/Verlust du *gerade* hättest wenn du jetzt verkaufen würdest |

> Beispiel: Entry bei 60.000 USDT, Stop-Loss bei 58.800 USDT (-2%), Take-Profit bei 63.000 USDT (+5%)
""")

    with st.expander("📉 Performance-Metriken — Sharpe, Sortino, Drawdown & Co."):
        st.markdown("""
| Begriff | Einfach erklärt | Guter Wert |
|---------|----------------|------------|
| **Gesamt PnL** | Dein gesamter Gewinn oder Verlust seit Start in USDT | Möglichst positiv |
| **Win-Rate** | Wie viel Prozent deiner Trades Gewinn gemacht haben | > 48% |
| **Sharpe Ratio** | Misst ob du für dein Risiko gut belohnt wirst. Hoher Wert = gutes Verhältnis Gewinn/Risiko | > 1.0 = gut, > 2.0 = sehr gut |
| **Sortino Ratio** | Wie Sharpe, aber zählt nur *schlechte* Schwankungen als Risiko | > 1.0 = gut |
| **Max Drawdown** | Der größte Verlust vom Höchststand bis zum Tiefpunkt | < 15% = ok |
| **Profit Factor** | Verhältnis Gesamtgewinn zu Gesamtverlust. 1.5 = für jeden USDT Verlust 1,50 USDT Gewinn | > 1.5 = gut |
| **Ø Gewinn / Ø Verlust** | Durchschnittliche Größe deiner Gewinntrades vs. Verlusttrades | Ø Gewinn > Ø Verlust |

> **Tipp:** Sharpe Ratio ist die wichtigste Einzelzahl. Ein Fonds mit Sharpe > 1.0 gilt als gut gemanaged.
""")

    with st.expander("🚦 Phase-Fortschrittsbalken (Paper → Live)"):
        st.markdown("""
Der Bot durchläuft zwei Phasen bevor er mit echtem Geld handelt:

| Phase | Was passiert | Risiko |
|-------|-------------|--------|
| **📄 Paper Trading** | Bot handelt mit **virtuellem Geld** — keine echten Transaktionen | Null |
| **🚀 Live Trading** | Bot handelt mit **echtem Geld** auf Binance | Real |

Der Fortschrittsbalken zeigt wie gut der Bot im Paper-Modus abschneidet.
Er wechselt **nicht automatisch** zu Live — du musst es manuell bestätigen.

**Kriterien für den Wechsel:**
| Kriterium | Ziel | Was bedeutet das? |
|-----------|------|------------------|
| Trades | 20 | Mindestens 20 Trades zum Auswerten |
| Sharpe Ratio | ≥ 0.8 | Risiko-adjustierte Rendite ausreichend |
| Win-Rate | ≥ 48% | Fast jeder zweite Trade macht Gewinn |
| Max Drawdown | ≤ 15% | Kein zu großer Verlust passiert |
| Model F1 | ≥ 0.38 | KI-Modell funktioniert zuverlässig |

Wenn alle Kriterien erfüllt sind, erhältst du eine Telegram-Nachricht mit `/approve_live`.
""")

    with st.expander("🤖 AI & ML — Modell, Konfidenz, Drift"):
        st.markdown("""
| Begriff | Einfach erklärt |
|---------|----------------|
| **ML-Modell** | Ein KI-Modell (XGBoost) das aus historischen Kursdaten gelernt hat wann ein guter Kaufzeitpunkt ist. |
| **AI Konfidenz** | Wie sicher das Modell in seiner aktuellen Vorhersage ist. Unter 60% = kein Trade. |
| **F1-Score** | Wie gut das Modell Kauf-/Verkaufssignale erkennt (0–1). Ab 0.38 ist es gut genug für Live-Trading. |
| **Model Drift** | Das Modell verliert an Genauigkeit weil sich der Markt verändert hat. Bei Drift: Retraining empfohlen. |
| **HOLD-Grund** | Warum der Bot bei diesem Signal *nicht* gehandelt hat. |
| **Retraining** | Das Modell auf frischen Daten neu trainieren. Dauert 3–5 Minuten auf deinem PC. |
| **Auto-Retraining** | Bot trainiert automatisch nach 50 Live-Trades neu — auf QNAP deaktiviert (zu langsam). |
""")

    with st.expander("🛡️ Risk Management — Stop-Loss, Kelly, Circuit Breaker"):
        st.markdown("""
| Begriff | Einfach erklärt |
|---------|----------------|
| **Stop-Loss** | Automatischer Verkauf wenn der Preis X% fällt — schützt vor großen Verlusten. Standard: 2% unter Entry. |
| **Take-Profit** | Automatischer Verkauf wenn der Preis X% steigt — sichert Gewinne. Standard: 4% über Entry. |
| **Trailing Stop** | Stop-Loss zieht automatisch nach oben mit wenn der Preis steigt. |
| **Kelly-Sizing** | Berechnet wie viel du pro Trade einsetzen sollst basierend auf deiner bisherigen Win-Rate. |
| **Circuit Breaker** | Wenn du heute mehr als 6% verlierst, stoppt der Bot automatisch. |
| **Max Drawdown-Stop** | Wenn dein Gesamtverlust 20% übersteigt, stoppt der Bot komplett. |
| **Safe Mode** | Halbiert vorübergehend die Positionsgröße. |
""")

    with st.expander("⚖️ Risk Mode (konservativ / balanced / aggressiv)"):
        st.markdown("""
Du kannst jederzeit zwischen drei Risikoniveaus wechseln (Sidebar-Buttons):

| Modus | Risiko pro Trade | Max Drawdown | Für wen? |
|-------|-----------------|--------------|----------|
| 🛡️ **Konservativ** | 1% | 10% | Anfänger, kleine Kontogröße, unsicherer Markt |
| ⚖️ **Balanced** | 2% | 20% | Standard — gutes Gleichgewicht |
| 🔥 **Aggressiv** | 3% | 30% | Erfahrene, hohe Risikobereitschaft, klarer Trend |

> **Beispiel Balanced:** Bei 1.000 USDT Kapital → max. 20 USDT Risiko pro Trade.
""")

    with st.expander("🌡️ Global Exposure Controller (NORMAL / CAUTIOUS / RISK_OFF / EMERGENCY)"):
        st.markdown("""
Der **Global Exposure Controller** ist ein automatischer Krisen-Schutz.

| Modus | Exposition | Wann schaltet er um? |
|-------|-----------|---------------------|
| **NORMAL** | 30–85% | Normaler Markt |
| **CAUTIOUS** | ~60% | Erste Warnsignale |
| **RISK_OFF** | max. 15% | Krisenzeichen |
| **EMERGENCY** | 0% — kein Trading | Extreme Krise |
| **RECOVERY** | Langsam steigend | Nach Krise |
""")

    with st.expander("🐂🐻 Markt-Regime — was der Bot daraus macht"):
        st.markdown("""
| Regime | Bedeutung | Bot-Verhalten |
|--------|-----------|---------------|
| **BULL_TREND** | BTC ist klar im Aufwärtstrend | Volle Positionsgrößen, kauft öfter |
| **SIDEWAYS** | Kein klarer Trend | Reduzierte Größen, weniger Trades |
| **BEAR_TREND** | BTC ist klar im Abwärtstrend | Sehr reduzierte Größen, kaum Käufe |
| **HIGH_VOLATILITY** | Preis schwankt extrem | Kleinere Positionen |
""")

    with st.expander("🎛️ Sidebar-Buttons — was tun die?"):
        st.markdown("""
| Button | Funktion |
|--------|---------|
| **▶ Start Bot** | Startet den Bot als Hintergrundprozess |
| **⛔ Stop** | Stoppt den Bot sauber nach dem aktuellen Zyklus |
| **📄 Paper** | Wechselt zurück auf Paper-Modus |
| **⏸ Pause** | Bot läuft weiter aber macht keine neuen Trades |
| **▶️ Resume** | Hebt die Pause auf |
| **🛡️ Safe Mode** | Halbiert die Positionsgrößen als Vorsichtsmaßnahme |
| **🔄 Retrain** | Fordert Modell-Retraining an |
| **🎓 Restart Training** | Vollständiges Reset + Retraining |
| **📥 CSV** | Exportiert alle Trades als Excel-kompatible CSV-Datei |
| **📊 JSON** | Exportiert Performance-Daten als JSON |
""")

    with st.expander("📑 Was zeigt welcher Tab?"):
        st.markdown("""
| Tab | Inhalt |
|-----|--------|
| **📊 Übersicht** | Das Wichtigste auf einen Blick: Kapital, aktuelle Position, Equity-Kurve, Lernfortschritt |
| **📅 Wöchentlich / Monatlich** | Wie viel du jede Woche / jeden Monat verdient oder verloren hast |
| **📋 Trade History** | Liste aller abgeschlossenen Trades mit Gewinn/Verlust |
| **🎯 Strategie-Performance** | Welche Trading-Strategie am besten funktioniert |
| **🔍 AI Explainability** | Warum der Bot zuletzt NICHT gehandelt hat + ML-Modell Gesundheit |
| **📜 Logs** | Technische Log-Ausgaben des Bots |
| **❓ Hilfe** | Diese Seite |
""")

    with st.expander("🔁 Backtest-Trades vs. Live-Trades"):
        st.markdown("""
| Typ | Was ist das? |
|-----|-------------|
| **Live-Trades** | Echte (oder Paper-)Trades die der Bot selbst ausgeführt hat |
| **Backtest-Trades** | Simulierte historische Trades |

Backtest-Trades werden mit `import-history` importiert um den Fortschrittsbalken schneller zu füllen.
Sie sind im Dashboard **immer getrennt** ausgewiesen.
""")

    with st.expander("📱 Telegram-Befehle — Schnellübersicht"):
        st.markdown("""
```
/status          → Kapital, offene Position, Tages-PnL
/progress        → Lernfortschritt Paper→Live
/trades          → Letzte 5 Trades
/performance     → Alle Kennzahlen (Sharpe, Win-Rate etc.)
/exposure_status → Aktueller Risikomodus
/pause           → Trading pausieren
/resume          → Trading fortsetzen
/help            → Alle Befehle
```
""")


def _render_help_en():
    st.markdown("## ❓ Dashboard Help — All Terms Explained")
    st.caption("Here you'll find simple explanations of everything shown in the dashboard.")

    with st.expander("📊 Live Status (the 5 fields at the top)", expanded=True):
        st.markdown("""
| Term | What does it mean? |
|------|--------------------|
| **💰 Capital** | How much USDT you currently have. Starts at e.g. 1,000 USDT. The % value shows how much you've gained or lost since the start. |
| **📊 Daily PnL** | Your today's profit (green) or loss (red) in USDT. Resets every day at midnight UTC. |
| **🐂 Market Regime** | What the bot currently thinks about the market — *BULL_TREND* = uptrend, *BEAR_TREND* = downtrend, *SIDEWAYS* = no clear direction. |
| **Volatility** | How strongly the price fluctuates — *LOW* = calm, *NORMAL* = normal, *HIGH* = choppy, *EXTREME* = very choppy. At high volatility the bot trades more cautiously. |
| **🤖 AI Confidence** | How confident the AI model is in its current assessment (0–100%). Below 60% the bot won't trade. |
""")

    with st.expander("📈 Equity Curve"):
        st.markdown("""
The **equity curve** shows how your capital has developed over time.

- The **dashed line** is your starting capital — everything above is profit, everything below is loss
- **Green line** = currently above starting capital
- **Red line** = currently below starting capital

> Example: You start with 1,000 USDT. After 3 months the curve shows 1,150 USDT → you're 15% up.
""")

    with st.expander("📍 Open Position (Entry / Stop-Loss / Take-Profit)"):
        st.markdown("""
When the bot has an open trade, you'll see three important price lines:

| Term | Simple explanation |
|------|--------------------|
| **Entry** (yellow) | The price at which the bot bought |
| **Stop-Loss** (red, dashed) | The safety price — if BTC drops to here, the bot sells automatically to avoid larger losses |
| **Take-Profit** (green, dashed) | The profit target — if BTC reaches this price, the bot sells with profit |
| **Current Price** (blue, dotted) | The current BTC price in real time |
| **Unrealized PnL** | How much profit/loss you'd have *right now* if you sold (not yet "realized" because the trade is still open) |

> Example: Entry at 60,000 USDT, Stop-Loss at 58,800 USDT (-2%), Take-Profit at 63,000 USDT (+5%)
""")

    with st.expander("📉 Performance Metrics — Sharpe, Sortino, Drawdown & more"):
        st.markdown("""
| Term | Simple explanation | Good value |
|------|-------------------|------------|
| **Total PnL** | Your total profit or loss since start in USDT | As positive as possible |
| **Win Rate** | What percentage of your trades made a profit | > 48% |
| **Sharpe Ratio** | Measures if you're well rewarded for your risk. Higher = better profit/risk ratio | > 1.0 = good, > 2.0 = excellent |
| **Sortino Ratio** | Like Sharpe, but only counts *downside* volatility as risk | > 1.0 = good |
| **Max Drawdown** | The largest loss from peak to trough | < 15% = ok |
| **Profit Factor** | Ratio of total profit to total loss. 1.5 = for every 1 USDT loss you made 1.50 USDT profit | > 1.5 = good |
| **Avg Win / Avg Loss** | Average size of your winning trades vs. losing trades | Avg Win > Avg Loss |

> **Tip:** Sharpe Ratio is the most important single number. A fund with Sharpe > 1.0 is considered well managed.
""")

    with st.expander("🚦 Phase Progress Bar (Paper → Live)"):
        st.markdown("""
The bot goes through two phases before trading with real money:

| Phase | What happens | Risk |
|-------|-------------|------|
| **📄 Paper Trading** | Bot trades with **virtual money** — no real transactions | Zero |
| **🚀 Live Trading** | Bot trades with **real money** on Binance | Real |

The progress bar shows how well the bot performs in paper mode.
It does **not switch automatically** to live — you must confirm manually.

**Criteria for switching:**
| Criterion | Target | What does it mean? |
|-----------|--------|-------------------|
| Trades | 20 | At least 20 trades to evaluate |
| Sharpe Ratio | ≥ 0.8 | Risk-adjusted return is sufficient |
| Win Rate | ≥ 48% | Almost every second trade is profitable |
| Max Drawdown | ≤ 15% | No excessive loss has occurred |
| Model F1 | ≥ 0.38 | AI model works reliably |

When all criteria are met, you'll receive a Telegram message with `/approve_live`.
""")

    with st.expander("🤖 AI & ML — Model, Confidence, Drift"):
        st.markdown("""
| Term | Simple explanation |
|------|--------------------|
| **ML Model** | An AI model (XGBoost) that learned from historical price data when a good time to buy is. |
| **AI Confidence** | How confident the model is in its current prediction. Below 60% = no trade. |
| **F1 Score** | How well the model identifies buy/sell signals (0–1). From 0.38 it's good enough for live trading. |
| **Model Drift** | The model loses accuracy because the market has changed. When drift occurs: retraining recommended. |
| **HOLD Reason** | Why the bot did *not* trade on this signal. |
| **Retraining** | Retrain the model on fresh data. Takes 3–5 minutes on your PC. |
| **Auto-Retraining** | Bot retrains automatically after 50 live trades — disabled on QNAP (too slow). |
""")

    with st.expander("🛡️ Risk Management — Stop-Loss, Kelly, Circuit Breaker"):
        st.markdown("""
| Term | Simple explanation |
|------|--------------------|
| **Stop-Loss** | Automatic sale when price drops X% — protects against large losses. Default: 2% below entry. |
| **Take-Profit** | Automatic sale when price rises X% — locks in profits. Default: 4% above entry. |
| **Trailing Stop** | Stop-Loss automatically moves up as the price rises — securing more profit over time. |
| **Kelly Sizing** | Calculates how much to risk per trade based on your historical win rate. |
| **Circuit Breaker** | If you lose more than 6% today, the bot stops automatically for the day. |
| **Max Drawdown Stop** | If your total loss exceeds 20%, the bot stops completely. |
| **Safe Mode** | Temporarily halves position sizes — useful when you want to be more cautious. |
""")

    with st.expander("⚖️ Risk Mode (conservative / balanced / aggressive)"):
        st.markdown("""
You can switch between three risk levels at any time (sidebar buttons):

| Mode | Risk per trade | Max drawdown | For whom? |
|------|---------------|--------------|-----------|
| 🛡️ **Conservative** | 1% | 10% | Beginners, small account, uncertain market |
| ⚖️ **Balanced** | 2% | 20% | Standard — good balance |
| 🔥 **Aggressive** | 3% | 30% | Experienced, high risk tolerance, clear trend |

> **Balanced example:** With 1,000 USDT capital → max. 20 USDT risk per trade.
""")

    with st.expander("🌡️ Global Exposure Controller (NORMAL / CAUTIOUS / RISK_OFF / EMERGENCY)"):
        st.markdown("""
The **Global Exposure Controller** is an automatic crisis protection system.

| Mode | Exposure | When does it switch? |
|------|----------|---------------------|
| **NORMAL** | 30–85% | Normal market |
| **CAUTIOUS** | ~60% | First warning signs |
| **RISK_OFF** | max. 15% | Crisis signals |
| **EMERGENCY** | 0% — no trading | Extreme crisis |
| **RECOVERY** | Slowly increasing | After crisis |
""")

    with st.expander("🐂🐻 Market Regime — what the bot does with it"):
        st.markdown("""
| Regime | Meaning | Bot behavior |
|--------|---------|--------------|
| **BULL_TREND** | BTC is clearly in an uptrend | Full position sizes, buys more often |
| **SIDEWAYS** | No clear trend, BTC moves sideways | Reduced sizes, fewer trades |
| **BEAR_TREND** | BTC is clearly in a downtrend | Very reduced sizes, barely any buys |
| **HIGH_VOLATILITY** | Price swings extremely | Smaller positions due to higher risk |
""")

    with st.expander("🎛️ Sidebar Buttons — what do they do?"):
        st.markdown("""
| Button | Function |
|--------|---------|
| **▶ Start Bot** | Starts the bot as a background process |
| **⛔ Stop** | Stops the bot cleanly after the current cycle |
| **📄 Paper** | Switches back to paper mode (virtual money) |
| **⏸ Pause** | Bot keeps running but makes no new trades |
| **▶️ Resume** | Lifts the pause |
| **🛡️ Safe Mode** | Halves position sizes as a precaution |
| **🔄 Retrain** | Requests model retraining (takes 3–5 min, runs in background) |
| **🎓 Restart Training** | Full reset + retraining — for major issues |
| **📥 CSV** | Exports all trades as an Excel-compatible CSV file |
| **📊 JSON** | Exports performance data as JSON |
""")

    with st.expander("📑 What does each tab show?"):
        st.markdown("""
| Tab | Content |
|-----|---------|
| **📊 Overview** | The most important at a glance: capital, current position, equity curve, progress |
| **📅 Weekly / Monthly** | How much you earned or lost each week / month |
| **📋 Trade History** | List of all completed trades with profit/loss |
| **🎯 Strategy Performance** | Which trading strategy (Momentum, Mean-Reversion etc.) works best |
| **🔍 AI Explainability** | Why the bot last did NOT trade + ML model health |
| **📜 Logs** | Technical log output of the bot — useful for troubleshooting |
| **❓ Help** | This page |
""")

    with st.expander("🔁 Backtest Trades vs. Live Trades — what's the difference?"):
        st.markdown("""
| Type | What is it? |
|------|------------|
| **Live Trades** | Real (or paper) trades the bot executed itself |
| **Backtest Trades** | Simulated historical trades — the bot calculated how it would have traded in the past |

Backtest trades are imported with `import-history` to fill the progress bar faster.
They are **always shown separately** in the dashboard.
""")

    with st.expander("📱 Telegram Commands — Quick Reference"):
        st.markdown("""
```
/status          → Capital, open position, daily PnL
/progress        → Progress Paper→Live
/trades          → Last 5 trades
/performance     → All metrics (Sharpe, Win-Rate etc.)
/exposure_status → Current risk mode
/pause           → Pause trading
/resume          → Resume trading
/help            → All commands
```
""")


# ── Forex Dashboard ───────────────────────────────────────────────────────────

def _render_forex_sidebar():
    """Sidebar-Controls für den Forex Bot — spiegelt render_sidebar() für Crypto."""
    status      = _fget("/api/status")
    paused      = status.get("paused", False)
    running     = status.get("running", True)
    mode        = (status.get("trading_mode") or "paper").upper()
    capital     = status.get("capital") or 0
    pnl         = status.get("daily_pnl") or 0
    risk        = (status.get("risk_mode") or "balanced").lower()
    instruments = status.get("instruments", [])
    last_cycle  = status.get("last_cycle", "")

    st.sidebar.title("💱 Forex Bot")
    st.sidebar.caption(f"Version 2.3 | {mode}")

    # ── Standard / Pro Toggle ─────────────────────────────────────────────────
    if "view_mode" not in st.session_state:
        st.session_state["view_mode"] = "standard"
    st.sidebar.markdown("---")
    _fx_vm1, _fx_vm2 = st.sidebar.columns(2)
    with _fx_vm1:
        _std_type = "primary" if st.session_state["view_mode"] == "standard" else "secondary"
        if st.button(_t("s.view_standard"), key="fx_vm_std", use_container_width=True, type=_std_type):
            st.session_state["view_mode"] = "standard"
            st.rerun()
    with _fx_vm2:
        _pro_type = "primary" if st.session_state["view_mode"] == "pro" else "secondary"
        if st.button(_t("s.view_pro"), key="fx_vm_pro", use_container_width=True, type=_pro_type):
            st.session_state["view_mode"] = "pro"
            st.rerun()

    # Broker-Verbindungsstatus
    _render_connection_badge(
        exchange  = status.get("broker", "Broker"),
        connected = status.get("broker_connected"),
        error     = status.get("broker_error", ""),
        env       = status.get("broker_env", ""),
    )

    # ── Status ────────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎮 Bot-Steuerung")
    if running and not paused:
        st.sidebar.success("▶️ Bot läuft")
    elif paused:
        st.sidebar.warning("⏸ Bot pausiert")
    else:
        st.sidebar.error("⏹ Bot gestoppt")

    # Pause + Resume immer sichtbar (wie Crypto)
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("⏸ Pause", use_container_width=True, key="fx_pause_btn"):
            r = _fpost("/api/control/pause")
            st.toast(r.get("message", "Pausiert"), icon="⏸")
    with col2:
        if st.button("▶️ Resume", use_container_width=True, key="fx_resume_btn",
                     type="primary" if paused else "secondary"):
            r = _fpost("/api/control/resume")
            st.toast(r.get("message", "Fortgesetzt"), icon="▶️")

    if st.sidebar.button("⏹ Stop", use_container_width=True, key="fx_stop_btn"):
        r = _fpost("/api/control/stop")
        st.toast(r.get("message", "Gestoppt"), icon="⛔")

    # ── Risk Mode ─────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚡ Risk Mode")
    _mode_icons = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}
    st.sidebar.markdown(f"Aktuell: **{_mode_icons.get(risk, '')} {risk.upper()}**")
    rc1, rc2, rc3 = st.sidebar.columns(3)
    with rc1:
        if st.button("🛡️", help="Conservative", use_container_width=True, key="fx_risk_c",
                     type="primary" if risk == "conservative" else "secondary"):
            _fpost("/api/mode/conservative")
            st.rerun()
    with rc2:
        if st.button("⚖️", help="Balanced", use_container_width=True, key="fx_risk_b",
                     type="primary" if risk == "balanced" else "secondary"):
            _fpost("/api/mode/balanced")
            st.rerun()
    with rc3:
        if st.button("🔥", help="Aggressive", use_container_width=True, key="fx_risk_a",
                     type="primary" if risk == "aggressive" else "secondary"):
            _fpost("/api/mode/aggressive")
            st.rerun()

    # ── Instrumente ───────────────────────────────────────────────────────────
    if instruments:
        st.sidebar.markdown("---")
        st.sidebar.subheader("📊 Instrumente")
        st.sidebar.caption("  ·  ".join(inst.replace("_", "/") for inst in instruments))

    # ── Log-Level ─────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("📋 Log-Level")
    _lvl_data   = _fget("/api/log_level")
    _cur_level  = _lvl_data.get("level", "INFO")
    _level_opts = ["DEBUG", "INFO", "WARNING", "ERROR"]
    _level_icons = {"DEBUG": "🔍", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🔴"}
    _level_idx  = _level_opts.index(_cur_level) if _cur_level in _level_opts else 1
    _col_lv1, _col_lv2 = st.sidebar.columns([3, 1])
    with _col_lv1:
        _new_level = st.selectbox("Log-Level", _level_opts, index=_level_idx,
                                  key="fx_log_level_select", label_visibility="collapsed")
    with _col_lv2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✓", key="fx_log_level_apply", help=f"Aktiv: {_cur_level}"):
            r = _fpost(f"/api/log_level/{_new_level}")
            if r.get("status") == "ok":
                st.sidebar.success(f"✓ {_new_level}")
            else:
                st.sidebar.error(r.get("detail", "Fehler"))
    st.sidebar.caption(f"Aktiv: {_level_icons.get(_cur_level, '')} {_cur_level}")

    # ── Zeitzone ──────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("🕐 Zeitzone")
    _tz_opts = _tz_list()
    _cur_tz  = st.session_state.get("tz", "Europe/Berlin")
    _tz_idx  = _tz_opts.index(_cur_tz) if _cur_tz in _tz_opts else 0
    _sel_tz  = st.sidebar.selectbox("Zeitzone", _tz_opts, index=_tz_idx,
                                    key="fx_tz_select", label_visibility="collapsed")
    if _sel_tz != _cur_tz:
        st.session_state["tz"] = _sel_tz
        st.rerun()

    # ── Data Warnings ─────────────────────────────────────────────────────────
    warnings = status.get("data_warnings", {})
    if warnings:
        st.sidebar.markdown("---")
        for inst, msg in warnings.items():
            st.sidebar.warning(f"⚠️ {inst}: {str(msg)[:60]}")

    # ── Status-Indikator ──────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    if last_cycle:
        st.sidebar.caption(f"Letzter Zyklus: {_fmt_dt(last_cycle)}")
    mode_color = "🟢" if mode == "LIVE" else "🟡"
    st.sidebar.markdown(f"{mode_color} Modus: **{mode}**")

    # ── Bot-Auswahl ───────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    _sb1, _sb2 = st.sidebar.columns(2)
    with _sb1:
        if st.button("📈 Crypto", use_container_width=True, type="secondary", key="fx_to_crypto"):
            st.session_state["bot_mode"] = "crypto"
            st.session_state["_mode_just_switched"] = True
            st.query_params["mode"] = "crypto"
            _get.clear()
            _fget.clear()
            st.rerun()
    with _sb2:
        if st.button("💱 Forex", use_container_width=True, type="primary", key="fx_stay_forex"):
            pass


def _render_forex_dashboard():
    """Forex-Bot Dashboard — verbindet sich mit FOREX_API_URL (Port 8001)."""
    health = _fget("/health")
    if not health:
        st.error(f"Forex Bot API nicht erreichbar: `{FOREX_API_URL}`")
        st.info(
            "Forex Bot starten:\n```\ncd forex_bot\n"
            "cp .env.example .env  # API-Keys eintragen\n"
            "python -m forex_bot.bot\n```"
        )
        return

    st.title("💱 Forex Bot")

    _is_pro = st.session_state.get("view_mode", "standard") == "pro"
    if _is_pro:
        (tab_fx_overview, tab_trades, tab_fx_chart, tab_calendar, tab_positions,
         tab_regime, tab_risk_mode, tab_signals, tab_fx_logs,
         tab_fx_features, tab_fx_system, tab_fx_help) = st.tabs([
            _t("ftab.overview"), _t("ftab.trades"), _t("ftab.chart"),
            _t("ftab.calendar"), _t("ftab.positions"), _t("ftab.regime"),
            _t("ftab.riskmode"), _t("ftab.signals"), _t("ftab.logs"),
            _t("ftab.features"), _t("ftab.system"), _t("ftab.help"),
        ])
    else:
        (tab_fx_overview, tab_trades, tab_fx_chart,
         tab_risk_mode, tab_fx_logs, tab_fx_features, tab_fx_system, tab_fx_help) = st.tabs([
            _t("ftab.overview"), _t("ftab.trades"), _t("ftab.chart"),
            _t("ftab.riskmode"), _t("ftab.logs"), _t("ftab.features"),
            _t("ftab.system"), _t("ftab.help"),
        ])
        tab_calendar = tab_positions = tab_regime = tab_signals = None

    with tab_fx_overview:
        status = _fget("/api/status")
        perf   = _fget("/api/performance")

        # ── Metriken ──────────────────────────────────────────────────────────
        mode    = (status.get("trading_mode") or "paper").upper()
        capital = status.get("capital") or 0
        pnl     = status.get("daily_pnl") or 0
        open_t  = status.get("open_trades") or 0
        paused  = status.get("paused", False)

        status_text = "⏸ Pausiert" if paused else ("▶️ Live" if mode == "LIVE" else f"📄 {mode}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Kapital",       f"${capital:,.2f}")
        c2.metric("Tages-PnL",     f"${pnl:+.2f}")
        c3.metric("Offene Trades", open_t)
        c4.metric("Modus",         status_text)

        st.markdown("---")
        st.subheader("Performance")
        _fx_n         = perf.get("trades", 0)
        _fx_total_pnl = perf.get("total_pnl", 0)
        _fx_cap       = capital or 1
        _fx_ret_pct   = _fx_total_pnl / _fx_cap * 100
        _fx_wr        = perf.get("win_rate", 0)
        _fx_w         = int(_fx_n * _fx_wr / 100)
        _fx_sh        = perf.get("sharpe", 0)
        _fx_dd        = perf.get("drawdown", 0)
        _fx_pf        = perf.get("profit_factor", 0)

        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Gesamt PnL",    f"${_fx_total_pnl:+,.2f}", f"{_fx_ret_pct:+.2f}%")
        p2.metric("Win-Rate",      f"{_fx_wr:.1f}%",
                  f"{_fx_w}W / {_fx_n - _fx_w}L" if _fx_n else "–")
        p3.metric("Sharpe Ratio",  f"{_fx_sh:.2f}", "gut" if _fx_sh > 1 else "schwach")
        p4.metric("Max Drawdown",  f"{_fx_dd:.1f}%", "ok" if _fx_dd < 10 else "hoch",
                  delta_color="inverse")

        p5, p6, p7, p8 = st.columns(4)
        p5.metric("Profit Factor", f"{_fx_pf:.2f}", "gut" if _fx_pf > 1.5 else "schwach")
        p6.metric("Sortino Ratio", f"{perf.get('sortino', 0):.2f}")
        p7.metric("Ø Gewinn",      f"${perf.get('avg_win', 0):+.2f}")
        p8.metric("Ø Verlust",     f"${perf.get('avg_loss', 0):+.2f}")

        if not _fx_n:
            st.info("Noch keine abgeschlossenen Trades — Metriken werden nach dem ersten Trade berechnet.")

        # Per-Instrument Breakdown
        instruments = perf.get("instruments", {})
        if instruments:
            st.markdown("**Performance je Währungspaar**")
            rows = []
            for inst, d in instruments.items():
                wr = round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0
                rows.append({"Paar": inst, "Trades": d["trades"],
                              "Win-Rate": f"{wr}%", "Pips": f"{d['pips']:+.1f}"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── Heartbeat ─────────────────────────────────────────────────────────
        hb = _fget("/api/heartbeat")
        if hb:
            alive   = hb.get("alive")
            silence = hb.get("silence_minutes")
            if alive is True and silence is not None:
                st.success(f"💓 Forex Bot aktiv — letzter Heartbeat vor {silence:.0f} Min")
            elif alive is False and silence is not None:
                st.error(f"💀 Forex Bot nicht aktiv — Stille seit {silence:.0f} Min!")
            elif not hb.get("last_ping"):
                st.warning("⏳ Forex Bot noch nicht gestartet — kein Heartbeat")

        # ── Phase Progress ────────────────────────────────────────────────────
        st.markdown("---")
        _render_forex_phase_progress()

        # ── Broker Selector ───────────────────────────────────────────────────
        st.markdown("---")
        broker_data = _fget("/api/broker")
        if broker_data:
            current_broker = broker_data.get("current", "oanda")
            available      = broker_data.get("available", [])
            configured     = broker_data.get("configured", [])  # [{broker, env}, ...]

            _broker_icons = {"oanda": "🏦", "capital": "💳", "ig": "📈", "ibkr": "🖥️"}
            _broker_names = {"oanda": "OANDA", "capital": "Capital.com", "ig": "IG Group", "ibkr": "IBKR"}
            _env_labels   = {"oanda": ["Practice", "Live"],
                             "capital": ["Demo", "Live"],
                             "ig": ["Demo", "Live"]}
            _env_vals     = {"oanda": ["practice", "live"],
                             "capital": ["demo", "live"],
                             "ig": ["demo", "live"]}

            # Konfigurierte Envs als Set für schnellen Lookup
            _configured_set = {(c["broker"], c["env"]) for c in configured}

            st.markdown(
                f"**Broker:** {_broker_icons.get(current_broker, '🏦')} "
                f"**{_broker_names.get(current_broker, current_broker.upper())}**"
            )

            broker_cols = st.columns(len(available))
            for col, b in zip(broker_cols, available):
                name     = b["name"]
                icon     = _broker_icons.get(name, "🏦")
                label    = _broker_names.get(name, name.upper())
                btn_type = "primary" if b.get("active") else "secondary"
                # Zeige grünen Punkt wenn mindestens ein Env konfiguriert ist
                has_cfg  = any(c["broker"] == name for c in configured)
                badge    = " ✓" if has_cfg else ""
                with col:
                    if st.button(f"{icon} {label}{badge}", key=f"broker_btn_{name}",
                                 use_container_width=True, type=btn_type):
                        cur = st.session_state.get("broker_form")
                        st.session_state["broker_form"] = None if cur == name else name
                        st.rerun()

            # ── Panel für den gewählten Broker ────────────────────────────────
            form_broker = st.session_state.get("broker_form")
            if form_broker:
                form_label = _broker_names.get(form_broker, form_broker.upper())
                form_icon  = _broker_icons.get(form_broker, "🏦")

                with st.container(border=True):
                    st.markdown(f"#### {form_icon} {form_label}")

                    # Welche Envs sind schon konfiguriert?
                    if form_broker == "ibkr":
                        env_options = [("any", "Verbindung")]
                    else:
                        lbls = _env_labels.get(form_broker, ["Demo", "Live"])
                        vals = _env_vals.get(form_broker, ["demo", "live"])
                        env_options = list(zip(vals, lbls))

                    for env_val, env_lbl in env_options:
                        already = (form_broker, env_val) in _configured_set
                        col_env, col_action = st.columns([3, 1])

                        with col_env:
                            if already:
                                st.success(f"✓ **{env_lbl}** konfiguriert")
                            else:
                                st.markdown(f"**{env_lbl}** — noch nicht konfiguriert")

                        with col_action:
                            if already:
                                # Nur verbinden — keine neuen Credentials nötig
                                if st.button(f"Verbinden", key=f"conn_{form_broker}_{env_val}",
                                             use_container_width=True, type="primary"):
                                    with st.spinner("Verbinde…"):
                                        r = _fpost(f"/api/broker/{form_broker}",
                                                   json={"env": env_val} if form_broker != "ibkr" else {})
                                    if r.get("success"):
                                        st.success("✓ Verbunden")
                                        st.session_state["broker_form"] = None
                                        st.rerun()
                                    else:
                                        st.error(r.get("error", "Fehler"))

                        # Formular zum Hinzufügen (nur wenn noch nicht konfiguriert)
                        if not already:
                            with st.expander(f"➕ {env_lbl}-Zugangsdaten hinzufügen",
                                             expanded=st.session_state.get(f"exp_{form_broker}_{env_val}", False)):
                                st.session_state[f"exp_{form_broker}_{env_val}"] = True
                                creds: dict = {"broker": form_broker, "env": env_val}

                                if form_broker == "oanda":
                                    creds["api_key"]    = st.text_input("API Key", type="password",
                                                                         key=f"f_{form_broker}_{env_val}_key")
                                    creds["account_id"] = st.text_input("Account ID",
                                                                         placeholder="101-001-12345678-001",
                                                                         key=f"f_{form_broker}_{env_val}_acc")
                                elif form_broker == "capital":
                                    creds["api_key"]  = st.text_input("API Key", type="password",
                                                                       key=f"f_{form_broker}_{env_val}_key")
                                    creds["email"]    = st.text_input("E-Mail",
                                                                       key=f"f_{form_broker}_{env_val}_email")
                                    creds["password"] = st.text_input("Passwort", type="password",
                                                                       key=f"f_{form_broker}_{env_val}_pw")
                                elif form_broker == "ig":
                                    creds["api_key"]  = st.text_input("API Key", type="password",
                                                                       key=f"f_{form_broker}_{env_val}_key")
                                    creds["username"] = st.text_input("Benutzername",
                                                                       key=f"f_{form_broker}_{env_val}_user")
                                    creds["password"] = st.text_input("Passwort", type="password",
                                                                       key=f"f_{form_broker}_{env_val}_pw")
                                elif form_broker == "ibkr":
                                    st.caption("Port bestimmt die Umgebung: 7497=TWS Paper, 7496=TWS Live")
                                    _c1, _c2 = st.columns(2)
                                    creds["host"]      = _c1.text_input("Host", value="127.0.0.1",
                                                                         key=f"f_ibkr_host")
                                    creds["port"]      = int(_c2.number_input("Port", value=7497, step=1,
                                                                               key=f"f_ibkr_port"))
                                    creds["client_id"] = int(st.number_input("Client ID", value=1, step=1,
                                                                              key=f"f_ibkr_cid"))

                                _ca, _cb = st.columns([2, 1])
                                with _ca:
                                    if st.button(f"💾 Speichern & Verbinden",
                                                 key=f"save_{form_broker}_{env_val}",
                                                 type="primary", use_container_width=True):
                                        with st.spinner("Speichere…"):
                                            save_r = _fpost("/api/broker/credentials",
                                                            json={k: v for k, v in creds.items()
                                                                  if k not in ("broker",)})
                                        if save_r.get("success"):
                                            # Direkt verbinden
                                            conn_r = _fpost(f"/api/broker/{form_broker}",
                                                            json={"env": env_val})
                                            if conn_r.get("success"):
                                                st.success("✓ Gespeichert & Verbunden")
                                                st.session_state["broker_form"] = None
                                                st.rerun()
                                            else:
                                                st.warning("Gespeichert, aber Verbindung fehlgeschlagen: "
                                                           + conn_r.get("error", ""))
                                        else:
                                            err = save_r.get("error", "")
                                            if "Existiert bereits" in err:
                                                st.error(f"⚠️ {err}")
                                            else:
                                                st.error(err or "Fehler beim Speichern")
                                with _cb:
                                    if st.button("Abbrechen", key=f"cancel_{form_broker}_{env_val}",
                                                 use_container_width=True):
                                        st.session_state["broker_form"] = None
                                        st.rerun()

    with tab_trades:
        trades_data = _fget("/api/trades?limit=30")
        trades = trades_data.get("trades", [])
        if not trades:
            st.info("Noch keine Trades.")
        else:
            df = pd.DataFrame(trades)
            show_cols = [c for c in
                ["instrument","direction","units","entry_price","exit_price",
                 "pnl_pips","pnl_usd","status","entry_time"] if c in df.columns]
            df = df[show_cols]
            df = _fmt_df_ts(df, ["entry_time"])
            df.rename(columns={
                "instrument": "Paar", "direction": "Richtung", "units": "Units",
                "entry_price": "Einstieg", "exit_price": "Ausstieg",
                "pnl_pips": "Pips", "pnl_usd": "PnL $",
                "status": "Status", "entry_time": "Zeit",
            }, inplace=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_fx_chart:
        st.subheader("📈 Candlestick Chart")
        pos_data_fx = _fget("/api/positions")
        positions_fx = pos_data_fx.get("positions", []) if pos_data_fx else []

        _fx_gran_opts = ["M1", "M5", "M15", "M30", "H1", "H4", "D"]
        if "chart_gran_forex" not in st.session_state:
            st.session_state["chart_gran_forex"] = "H1"
        if "chart_limit_forex" not in st.session_state:
            st.session_state["chart_limit_forex"] = 100
        if "chart_instr_forex" not in st.session_state:
            _fx_first = positions_fx[0].get("instrument", "EUR_USD") if positions_fx else "EUR_USD"
            st.session_state["chart_instr_forex"] = _fx_first

        _fxc1, _fxc2, _fxc3 = st.columns([2, 2, 1])
        with _fxc1:
            _fx_instr = st.text_input("Instrument", key="chart_instr_forex")
        with _fxc2:
            _fx_gran = st.selectbox("Granularität", _fx_gran_opts, key="chart_gran_forex")
        with _fxc3:
            _fx_limit = st.selectbox("Candles", [50, 100, 150, 200], key="chart_limit_forex")

        _fx_candle_data = _fget(f"/api/candles?instrument={_fx_instr}&granularity={_fx_gran}&limit={_fx_limit}")
        _fx_candles = (_fx_candle_data or {}).get("candles", [])

        # Find entry/SL/TP for selected instrument
        _fx_entry = _fx_sl = _fx_tp = None
        for _pos in positions_fx:
            if _pos.get("instrument", "") == _fx_instr.replace("/", "_"):
                _fx_entry = float(_pos.get("price", 0) or 0) or None
                break

        _render_candle_chart(
            _fx_candles,
            title=f"{_fx_instr.replace('_', '/')} — {_fx_gran}",
            entry_price=_fx_entry,
        )
        if _fx_entry:
            st.caption(f"Offene Position — Einstieg: {_fx_entry:.5f}")

    if _is_pro:
        with tab_calendar:
            st.subheader("📰 Wirtschafts-Events (nächste 48h)")
            cal = _fget("/api/calendar?hours=48")
            events = cal.get("events", [])
            if not events:
                st.info("Keine relevanten Events in den nächsten 48 Stunden.")
            else:
                rows = []
                for ev in events:
                    impact_icon = "🔴" if ev["impact"] == "High" else "🟡"
                    try:
                        dt = datetime.fromisoformat(ev["time"].replace("Z", "+00:00"))
                        time_str = _fmt_dt(ev["time"], "%a %H:%M")
                    except Exception:
                        time_str = ev["time"][:16]
                    rows.append({
                        "": impact_icon,
                        "Zeit": time_str,
                        "Währung": ev["currency"],
                        "Event": ev["event"],
                        "Impact": ev["impact"],
                        "Prognose": ev.get("forecast") or "–",
                        "Vorwert": ev.get("previous") or "–",
                    })
                df_cal = pd.DataFrame(rows)
                st.dataframe(df_cal, use_container_width=True, hide_index=True)

                # News Pause Warnung
                now = datetime.now(timezone.utc)
                for ev in events:
                    try:
                        dt    = datetime.fromisoformat(ev["time"].replace("Z", "+00:00"))
                        mins  = (dt - now).total_seconds() / 60
                        if ev["impact"] == "High" and -30 <= mins <= 30:
                            st.warning(
                                f"⚠️ High-Impact Event in {int(abs(mins))} Min.: "
                                f"{ev['currency']} {ev['event']} — Trading pausiert!"
                            )
                    except Exception:
                        pass

        with tab_positions:
            pos_data = _fget("/api/positions")
            positions = pos_data.get("positions", [])
            note      = pos_data.get("note", "")
            if note:
                st.info(note)
            elif not positions:
                st.info("Keine offenen Positionen.")
            else:
                for p in positions:
                    pl    = float(p.get("unrealizedPL", 0))
                    icon  = "📈" if pl >= 0 else "📉"
                    color = "#00cc66" if pl >= 0 else "#ff4444"
                    st.markdown(
                        f'<div style="background:#1a1a2e;border-radius:8px;padding:12px;margin-bottom:8px">'
                        f'{icon} <b>{p.get("instrument")}</b> — '
                        f'Units: {p.get("currentUnits")} — '
                        f'Einstieg: {p.get("price")} — '
                        f'<span style="color:{color}">PnL: ${pl:+.2f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        with tab_regime:
            st.subheader("🌍 Regime & Markt")

            # Regime pro Paar
            regime_data = _fget("/api/regime")
            regime_map  = regime_data.get("regime", {})
            if regime_map:
                st.markdown("**Markt-Regime je Währungspaar**")
                _regime_colors = {
                    "TREND_UP":        "#00cc66",
                    "TREND_DOWN":      "#ff4444",
                    "SIDEWAYS":        "#888888",
                    "HIGH_VOLATILITY": "#ffaa00",
                    "MEAN_REVERSION":  "#4488ff",
                }
                rcols = st.columns(min(len(regime_map), 4))
                for col, (instr, reg) in zip(rcols * 10, regime_map.items()):
                    color = _regime_colors.get(reg, "#888")
                    with col:
                        st.markdown(
                            f'<div style="background:#1a1a2e;border-radius:8px;padding:10px;text-align:center">'
                            f'<div style="font-size:12px;color:#aaa">{instr.replace("_", "/")}</div>'
                            f'<div style="font-size:14px;font-weight:bold;color:{color}">{reg}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                st.markdown("")
            else:
                st.info("Regime-Daten noch nicht verfügbar — warte auf ersten Bot-Zyklus.")

            # Spreads
            st.markdown("---")
            st.markdown("**Aktuelle Spreads (EMA)**")
            spread_data = _fget("/api/spreads")
            spread_ema  = spread_data.get("spread_ema", {})
            if spread_ema:
                srows = [{"Paar": k.replace("_", "/"), "Spread (Pips)": f"{v:.1f}"}
                         for k, v in spread_ema.items()]
                st.dataframe(pd.DataFrame(srows), use_container_width=True, hide_index=True)
            else:
                st.info("Spread-Daten noch nicht verfügbar.")

            # Macro
            st.markdown("---")
            st.markdown("**Makro-Kontext**")
            macro = _fget("/api/macro")
            if macro and "error" not in macro:
                _mc1, _mc2, _mc3 = st.columns(3)
                _mc1.metric("USD Regime",   macro.get("usd_regime", "–"))
                _mc2.metric("Risk Regime",  macro.get("risk_regime", "–"))
                _mc3.metric("VIX",          f"{macro.get('vix', 0):.1f}" if macro.get("vix") else "–")

                carry = macro.get("carry_signals", [])
                if carry:
                    st.markdown("**Carry Trade Signale**")
                    crows = []
                    for c in carry[:6]:
                        crows.append({
                            "Paar":      c.get("pair", "–"),
                            "Richtung":  c.get("direction", "–"),
                            "Score":     f"{c.get('score', 0):.2f}",
                            "Grund":     c.get("reason", ""),
                        })
                    st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True)

                cot = macro.get("cot", {})
                if cot:
                    st.markdown("**COT (Commitments of Traders)**")
                    cot_rows = [{"Währung": k, "Signal": v} for k, v in cot.items()]
                    st.dataframe(pd.DataFrame(cot_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Makro-Daten noch nicht verfügbar.")

    with tab_risk_mode:
        st.subheader("⚡ Risk Mode Details")
        mode_data = _fget("/api/mode")
        if mode_data:
            current = mode_data.get("current_mode", "balanced")
            params  = mode_data.get("params", {})
            _mode_icons = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}
            st.markdown(f"### {_mode_icons.get(current, '')} {current.upper()}")

            _pm1, _pm2 = st.columns(2)
            with _pm1:
                st.metric("Risiko/Trade",       f"{params.get('risk_per_trade', 0)*100:.1f}%")
                st.metric("Max. offene Trades", params.get("max_open_trades", "–"))
                st.metric("Min. Konfidenz",     f"{params.get('min_confidence', 0):.2f}")
                st.metric("Spread-Limit",       f"{params.get('spread_limit_pips', 0):.1f} Pips")
                st.metric("News-Pause",         f"{params.get('news_pause_min', 0)} Min")
            with _pm2:
                st.metric("Daily Loss Limit",   f"{params.get('daily_loss_limit', 0)*100:.1f}%")
                st.metric("ATR Multiplikator",  f"{params.get('atr_multiplier', 0):.1f}×")
                st.metric("RR Ratio",           f"1:{params.get('rr_ratio', 0):.1f}")
                st.metric("MTF erforderlich",   "✅" if params.get("require_mtf") else "❌")
                st.metric("Session strict",     "✅" if params.get("session_strict") else "❌")

            # Mode-Wechsel Buttons
            st.markdown("---")
            st.markdown("**Modus wechseln**")
            _mb1, _mb2, _mb3 = st.columns(3)
            with _mb1:
                if st.button("🛡️ Conservative", use_container_width=True,
                              type="primary" if current == "conservative" else "secondary",
                              key="rm_tab_conservative"):
                    _fpost("/api/mode/conservative")
                    st.rerun()
            with _mb2:
                if st.button("⚖️ Balanced", use_container_width=True,
                              type="primary" if current == "balanced" else "secondary",
                              key="rm_tab_balanced"):
                    _fpost("/api/mode/balanced")
                    st.rerun()
            with _mb3:
                if st.button("🔥 Aggressive", use_container_width=True,
                              type="primary" if current == "aggressive" else "secondary",
                              key="rm_tab_aggressive"):
                    _fpost("/api/mode/aggressive")
                    st.rerun()

    if _is_pro:
        with tab_signals:
            st.subheader("📡 Signale & Rejections")

            _sg1, _sg2 = st.columns(2)

            with _sg1:
                st.markdown("**✅ Angenommene Signale** (alle Filter bestanden)")
                sig_data = _fget("/api/signals")
                signals_list = sig_data.get("signals", [])
                if not signals_list:
                    st.info("Noch keine Signale — warte auf nächsten Zyklus.")
                else:
                    sdf = pd.DataFrame(signals_list)
                    sdf = _fmt_df_ts(sdf, ["time"])
                    sdf.rename(columns={
                        "instrument": "Paar", "direction": "Richtung",
                        "confidence": "Konfidenz", "reason": "Grund", "time": "Zeit",
                    }, inplace=True)
                    st.dataframe(sdf, use_container_width=True, hide_index=True)

            with _sg2:
                st.markdown("**❌ Rejections** (Filter blockiert)")
                rej_data = _fget("/api/rejections")
                rej_list = rej_data.get("rejections", [])
                if not rej_list:
                    st.info("Noch keine Rejections.")
                else:
                    rdf = pd.DataFrame(rej_list)
                    rdf = _fmt_df_ts(rdf, ["time"])
                    rdf.rename(columns={
                        "instrument": "Paar", "reason": "Grund", "time": "Zeit",
                    }, inplace=True)
                    st.dataframe(rdf, use_container_width=True, hide_index=True)

    with tab_fx_logs:
        st.subheader("📜 Forex Bot Logs")
        _lc1, _lc2, _lc3 = st.columns([2, 2, 1])
        with _lc1:
            _fx_log_level = st.selectbox("Filter", ["ALL", "INFO", "WARNING", "ERROR"],
                                         index=0, key="fx_log_filter",
                                         label_visibility="collapsed")
        with _lc2:
            _fx_log_lines = st.slider("Zeilen", 50, 500, 200, step=50, key="fx_log_lines")
        with _lc3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄", key="fx_log_refresh", help="Refresh"):
                st.rerun()
        _fx_level_param = "" if _fx_log_level == "ALL" else _fx_log_level
        _fx_log_data = _fget(f"/api/logs?lines={_fx_log_lines}&level={_fx_level_param}")
        if not _fx_log_data.get("exists"):
            st.warning(f"Keine Log-Datei gefunden ({_fx_log_data.get('path', '')})")
        else:
            _fx_lines = _fx_log_data.get("lines", [])
            st.caption(f"{len(_fx_lines)} von {_fx_log_data.get('total', 0)} Zeilen | forex_bot/logs/forex_bot.log")
            if not _fx_lines:
                st.info("Keine Log-Einträge.")
            else:
                _fx_colored = []
                for _line in reversed(_fx_lines):
                    if "ERROR" in _line:
                        _fx_colored.append(f'<span style="color:#ff4444">{_line}</span>')
                    elif "WARNING" in _line:
                        _fx_colored.append(f'<span style="color:#ffaa00">{_line}</span>')
                    elif "INFO" in _line:
                        _fx_colored.append(f'<span style="color:#aaaaaa">{_line}</span>')
                    else:
                        _fx_colored.append(f'<span style="color:#888888">{_line}</span>')
                st.markdown(
                    '<div style="background:#0e0e0e;padding:12px;border-radius:6px;'
                    'font-family:monospace;font-size:12px;line-height:1.6;'
                    'max-height:600px;overflow-y:auto;">'
                    + "<br>".join(_fx_colored) + "</div>",
                    unsafe_allow_html=True,
                )

    with tab_fx_features:
        st.subheader("⚙️ Features")
        st.caption("Aktiviere oder deaktiviere Funktionen des Forex Bots — wirkt sofort, bleibt bis zum Neustart aktiv.")
        feats_data = _fget("/api/features")
        feats = feats_data.get("features", [])
        if not feats:
            st.info("Feature-Daten nicht verfügbar — Forex API erreichbar?")
        else:
            for feat in feats:
                col_tog, col_info = st.columns([1, 5])
                with col_tog:
                    new_val = st.toggle(
                        label=feat["label"],
                        value=feat["enabled"],
                        key=f"fx_feat_{feat['name']}",
                        label_visibility="collapsed",
                    )
                    if new_val != feat["enabled"]:
                        r = _fpost(f"/api/features/{feat['name']}", json={"enabled": new_val})
                        if r.get("status") == "ok":
                            st.toast(f"{'✅' if new_val else '❌'} {feat['label']}", icon="⚙️")
                            st.rerun()
                        else:
                            st.error(f"Fehler: {r.get('detail', r)}")
                with col_info:
                    st.markdown(f"**{feat['label']}**")
                    st.caption(feat.get("desc", ""))

    with tab_fx_system:
        st.subheader("🖥️ System")
        _sc1, _sc2 = st.columns(2)
        with _sc1:
            st.markdown("#### API & Broker")
            _fx_health = _fget("/health")
            if _fx_health:
                st.success(f"✅ Forex API erreichbar")
                st.caption(f"URL: `{FOREX_API_URL}`")
                up = _fx_health.get("uptime_s")
                if up is not None:
                    st.caption(f"Uptime: {int(up // 3600)}h {int((up % 3600) // 60)}m")
            else:
                st.error(f"🔴 Forex API nicht erreichbar ({FOREX_API_URL})")
            _s = _fget("/api/status")
            if _s:
                _broker = _s.get("broker", "–")
                _conn   = _s.get("broker_connected", False)
                _mode_s = (_s.get("trading_mode") or "–").upper()
                st.metric("Broker", _broker.upper(), "verbunden ✅" if _conn else "getrennt ❌")
                st.metric("Trading-Modus", _mode_s)
                _instr = _s.get("instruments", [])
                if _instr:
                    st.caption(f"Instrumente: {', '.join(_instr[:8])}")
        with _sc2:
            st.markdown("#### Konfiguration")
            st.caption(f"Forex API: `{FOREX_API_URL}`")
            _ver = _fget("/api/version") or {}
            for k, v in _ver.items():
                st.caption(f"{k}: `{v}`")
            st.markdown("#### Telegram / Alerts")
            _tg = _fget("/api/alerts/status") or {}
            if _tg:
                for k, v in _tg.items():
                    st.caption(f"{'✅' if v else '❌'} {k}")
            else:
                st.caption("Kein Alert-Status verfügbar")

    with tab_fx_help:
        if st.session_state.get("lang") == "en":
            st.markdown("## ❓ Forex Bot — Help")
            st.caption("Quick reference for all Forex Bot dashboard elements.")
            with st.expander("📊 Overview Tab", expanded=True):
                st.markdown("""
| Term | Meaning |
|------|---------|
| **Capital** | Current account balance. |
| **Daily PnL** | Today's profit (green) or loss (red). Resets at UTC midnight. |
| **Open Trades** | Number of currently open positions. |
| **Mode** | PAPER = simulated money, LIVE = real money. |
| **Heartbeat** | Confirms the bot is running. Missing > 10 min = bot stopped. |
""")
            with st.expander("⚡ Risk Mode"):
                st.markdown("""
| Mode | Risk/Trade | Max Trades | For whom? |
|------|-----------|-----------|-----------|
| 🛡️ Conservative | 0.5% | 2 | Beginners, volatile markets |
| ⚖️ Balanced | 1.0% | 4 | Standard operation |
| 🔥 Aggressive | 2.0% | 6 | Experienced, high confidence |

Switch at any time via the sidebar or the Risk Mode tab.
""")
            with st.expander("📋 Trades Tab"):
                st.markdown("""
Shows the last 30 closed trades with instrument, direction, entry/exit price, pips and USD PnL.

**Pips** = price movement in the 4th decimal (e.g. 1.1234 → 1.1244 = +10 pips)
""")
            with st.expander("🌍 Regime & Market (Pro)"):
                st.markdown("""
| Term | Meaning |
|------|---------|
| **Regime** | Current market state per pair: TREND_UP/DOWN, SIDEWAYS, HIGH_VOLATILITY |
| **Spread** | Bid-ask gap in pips — higher spread = higher cost |
| **USD Regime** | Dollar strength: STRONG / WEAK / NEUTRAL |
| **VIX** | Volatility index — high VIX = risk-off environment |
| **Carry Signals** | Interest rate differential opportunities |
| **COT** | Commitments of Traders — large institutional positioning |
""")
            with st.expander("📡 Signals (Pro)"):
                st.markdown("""
- **Accepted signals**: Passed all filters (spread, session, confidence, regime)
- **Rejections**: Blocked — reason shown (e.g. spread too wide, news pause, low confidence)
""")
        else:
            st.markdown("## ❓ Forex Bot — Hilfe")
            st.caption("Kurzreferenz zu allen Dashboard-Elementen des Forex Bots.")
            with st.expander("📊 Übersicht-Tab", expanded=True):
                st.markdown("""
| Begriff | Bedeutung |
|---------|-----------|
| **Kapital** | Aktuelles Guthaben in der Kontowährung. |
| **Tages-PnL** | Heutiger Gewinn (grün) oder Verlust (rot). Wird um Mitternacht UTC zurückgesetzt. |
| **Offene Trades** | Anzahl aktuell offener Positionen. |
| **Modus** | PAPER = Spielgeld, LIVE = echtes Geld. |
| **Heartbeat** | Bestätigt dass der Bot läuft. Fehlt > 10 Min = Bot gestoppt. |
""")
            with st.expander("⚡ Risk Mode"):
                st.markdown("""
| Modus | Risiko/Trade | Max Positionen | Für wen? |
|-------|-------------|----------------|----------|
| 🛡️ Konservativ | 0,5% | 2 | Einsteiger, volatile Märkte |
| ⚖️ Balanced | 1,0% | 4 | Normalbetrieb |
| 🔥 Aggressiv | 2,0% | 6 | Erfahrene Trader, hohe Konfidenz |

Jederzeit wechselbar über Sidebar-Buttons oder den Risk Mode Tab.
""")
            with st.expander("📋 Trades-Tab"):
                st.markdown("""
Zeigt die letzten 30 abgeschlossenen Trades mit Instrument, Richtung, Einstieg/Ausstieg, Pips und PnL in USD.

**Pips** = Kursbewegung in der 4. Nachkommastelle (z.B. 1,1234 → 1,1244 = +10 Pips)
""")
            with st.expander("🌍 Regime & Markt (Pro)"):
                st.markdown("""
| Begriff | Bedeutung |
|---------|-----------|
| **Regime** | Aktueller Marktzustand pro Paar: TREND_UP/DOWN, SIDEWAYS, HIGH_VOLATILITY |
| **Spread** | Geld-Brief-Spanne in Pips — höherer Spread = höhere Handelskosten |
| **USD Regime** | Dollar-Stärke: STRONG / WEAK / NEUTRAL |
| **VIX** | Volatilitätsindex — hoher VIX = Risk-off, aggressive Trades vermeiden |
| **Carry Signale** | Zinsdifferenz-Handelsmöglichkeiten |
| **COT** | Commitments of Traders — Positionierung institutioneller Händler |
""")
            with st.expander("📡 Signale (Pro)"):
                st.markdown("""
- **Angenommene Signale**: Alle Filter bestanden (Spread, Session, Konfidenz, Regime)
- **Rejections**: Blockiert — Grund wird angezeigt (z.B. Spread zu weit, News-Pause, geringe Konfidenz)
""")


# ── Exchange Selector ─────────────────────────────────────────────────────────

def _render_exchange_selector():
    """Exchange-Wechsel mit Credential-Verwaltung — analog zum Forex Broker Selector."""
    exchange_data = _get("/api/exchange")
    if not exchange_data:
        return

    current    = exchange_data.get("current", "binance")
    available  = exchange_data.get("available", [])
    configured = exchange_data.get("configured", [])   # [{exchange, env}, ...]

    _exchange_icons = {
        "binance": "🟡", "bybit": "🔵", "okx": "⚫", "kraken": "🟣",
    }
    _exchange_names = {
        "binance": "Binance", "bybit": "Bybit", "okx": "OKX", "kraken": "Kraken",
    }
    _env_labels = {
        "binance": ["Testnet", "Live"],
        "bybit":   ["Testnet", "Live"],
        "okx":     ["Demo",    "Live"],
        "kraken":  ["Live"],
    }
    _env_vals = {
        "binance": ["testnet", "live"],
        "bybit":   ["testnet", "live"],
        "okx":     ["demo",    "live"],
        "kraken":  ["live"],
    }

    _configured_set = {(c["exchange"], c["env"]) for c in configured}

    st.markdown(
        f"**Exchange:** {_exchange_icons.get(current, '💱')} "
        f"**{_exchange_names.get(current, current.upper())}**"
    )

    exc_cols = st.columns(len(available))
    for col, ex in zip(exc_cols, available):
        name     = ex["name"]
        icon     = _exchange_icons.get(name, "💱")
        label    = _exchange_names.get(name, name.upper())
        has_cfg  = any(c["exchange"] == name for c in configured)
        badge    = " ✓" if has_cfg else ""
        is_active = name == current
        with col:
            if st.button(
                f"{icon} {label}{badge}",
                key=f"exc_btn_{name}",
                type="primary" if is_active else "secondary",
            ):
                cur = st.session_state.get("exchange_form")
                st.session_state["exchange_form"] = None if cur == name else name

    form_exchange = st.session_state.get("exchange_form")
    if form_exchange:
        form_label = _exchange_names.get(form_exchange, form_exchange.upper())
        form_icon  = _exchange_icons.get(form_exchange, "💱")
        st.markdown(f"#### {form_icon} {form_label}")

        envs_labels = _env_labels.get(form_exchange, ["Live"])
        envs_vals   = _env_vals.get(form_exchange,   ["live"])

        for env_lbl, env_val in zip(envs_labels, envs_vals):
            already = (form_exchange, env_val) in _configured_set
            st.markdown(f"**{env_lbl}**")

            if already:
                st.success(f"✓ konfiguriert ({env_val})")
                if st.button(
                    f"Verbinden ({env_lbl})",
                    key=f"exc_conn_{form_exchange}_{env_val}",
                ):
                    r = _post_json(
                        f"/api/exchange/{form_exchange}",
                        json={"env": env_val},
                    )
                    if r.get("success"):
                        st.success(r.get("message", "Exchange gewechselt"))
                        st.session_state["exchange_form"] = None
                        st.rerun()
                    else:
                        st.error(r.get("error", "Fehler"))
            else:
                with st.expander(
                    f"🔑 Credentials eingeben ({env_lbl})",
                    expanded=st.session_state.get(f"exc_exp_{form_exchange}_{env_val}", False),
                ):
                    st.session_state[f"exc_exp_{form_exchange}_{env_val}"] = True
                    creds: dict = {"exchange": form_exchange, "env": env_val}

                    creds["api_key"] = st.text_input(
                        "API Key", type="password",
                        key=f"exc_{form_exchange}_{env_val}_key",
                    )
                    creds["api_secret"] = st.text_input(
                        "API Secret", type="password",
                        key=f"exc_{form_exchange}_{env_val}_secret",
                    )
                    if form_exchange == "okx":
                        creds["passphrase"] = st.text_input(
                            "Passphrase", type="password",
                            key=f"exc_{form_exchange}_{env_val}_pass",
                        )

                    if st.button(
                        f"💾 Speichern & Verbinden ({env_lbl})",
                        key=f"exc_save_{form_exchange}_{env_val}",
                    ):
                        if not creds.get("api_key") or not creds.get("api_secret"):
                            st.error("API Key und Secret sind Pflichtfelder.")
                        else:
                            # 1. In .env speichern
                            save_r = _post_json("/api/exchange/credentials", json=creds)
                            if save_r.get("error"):
                                err = save_r["error"]
                                if "Existiert bereits" in err:
                                    st.warning(f"⚠️ {err}")
                                else:
                                    st.error(f"Fehler: {err}")
                            else:
                                # 2. Exchange wechseln
                                conn_r = _post_json(
                                    f"/api/exchange/{form_exchange}",
                                    json={"env": env_val},
                                )
                                if conn_r.get("success"):
                                    st.success(conn_r.get("message", "Gespeichert & verbunden"))
                                    st.session_state["exchange_form"] = None
                                    st.rerun()
                                else:
                                    st.warning(
                                        f"Credentials gespeichert, aber Verbindung fehlgeschlagen: "
                                        f"{conn_r.get('error', '')}"
                                    )


# ── Strategy Marketplace Tab ──────────────────────────────────────────────────

def _render_marketplace_tab():
    """Strategy-Marketplace: alle Strategien mit Metadaten, Performance, Export."""
    st.subheader("🏪 Strategy Marketplace")
    st.caption("Lokale Strategie-Bibliothek — Metadaten, Performance, Export & Import")

    data = _get("/api/marketplace/strategies")
    strategies = data.get("strategies", [])
    perf_data  = {p["strategy"]: p for p in _get("/api/marketplace/performance").get("performance", [])}

    if not strategies:
        st.warning("Keine Strategien gefunden.")
        return

    # Filter
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        asset_filter = st.selectbox("Asset-Klasse", ["Alle", "crypto", "forex", "equities", "multi"])
    with col_f2:
        risk_filter  = st.selectbox("Risiko", ["Alle", "conservative", "balanced", "aggressive"])
    with col_f3:
        tag_filter   = st.text_input("Tag suchen", placeholder="momentum, trend, ...")

    filtered = strategies
    if asset_filter != "Alle":
        filtered = [s for s in filtered if s.get("asset_class") == asset_filter]
    if risk_filter != "Alle":
        filtered = [s for s in filtered if s.get("risk_level") == risk_filter]
    if tag_filter:
        filtered = [s for s in filtered if tag_filter.lower() in str(s.get("tags", "")).lower()
                    or tag_filter.lower() in s.get("name", "").lower()]

    st.caption(f"{len(filtered)} von {len(strategies)} Strategien")
    st.markdown("---")

    for strat in filtered:
        name    = strat.get("module_name", "?")
        label   = strat.get("name", name)
        desc    = strat.get("description", "")
        tags    = strat.get("tags", [])
        risk    = strat.get("risk_level", "balanced")
        asset   = strat.get("asset_class", "crypto")
        version = strat.get("version", "")
        perf    = perf_data.get(name, strat.get("performance", {}))

        risk_icon  = {"conservative": "🛡️", "balanced": "⚖️", "aggressive": "🔥"}.get(risk, "⚖️")
        asset_icon = {"crypto": "₿", "forex": "💱", "equities": "📈", "multi": "🌐"}.get(asset, "")

        with st.expander(f"{asset_icon} **{label}** `v{version}` {risk_icon}", expanded=False):
            col_info, col_perf, col_act = st.columns([3, 2, 1])

            with col_info:
                if desc:
                    st.markdown(desc)
                if tags:
                    st.caption("Tags: " + " · ".join(f"`{t}`" for t in tags))
                tfs = strat.get("timeframes", [])
                if tfs:
                    st.caption(f"Timeframes: {', '.join(tfs)}")
                mc = strat.get("min_capital")
                if mc:
                    st.caption(f"Min. Kapital: ${mc:,.0f}")
                params = strat.get("params", {})
                if params:
                    st.caption("Default-Parameter: " + " | ".join(f"{k}={v}" for k, v in list(params.items())[:5]))

            with col_perf:
                if perf:
                    sharpe = perf.get("sharpe", perf.get("sharpe_ratio", 0))
                    wr     = perf.get("win_rate", perf.get("win_rate_pct", 0))
                    dd     = perf.get("max_drawdown", 0)
                    if sharpe:
                        st.metric("Sharpe", f"{sharpe:.2f}")
                    if wr:
                        st.metric("Win Rate", f"{wr:.1f}%")
                    if dd:
                        st.metric("Max DD", f"{dd:.1f}%")
                else:
                    st.caption("Noch keine Live-Performance")

            with col_act:
                if st.button("📥 Export", key=f"export_{name}"):
                    r = _get(f"/api/marketplace/strategies/{name}/export")
                    if r:
                        st.success(f"ZIP erstellt")
                    else:
                        st.error("Export fehlgeschlagen")

    st.markdown("---")
    st.markdown("**Import einer Strategie (ZIP)**")
    uploaded = st.file_uploader("Strategy ZIP hochladen", type=["zip"], key="strat_upload")
    if uploaded:
        import tempfile, os as _os
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        r = _post_json("/api/marketplace/strategies/import", json={"zip_path": tmp_path})
        _os.unlink(tmp_path)
        if r.get("status") == "ok":
            st.success(f"Strategie '{r.get('module_name')}' importiert!")
            st.rerun()
        else:
            st.error(f"Import fehlgeschlagen: {r.get('detail', r)}")


# ── Features Tab ─────────────────────────────────────────────────────────────

def _render_strategy_cfg_tab():
    """Strategy-Tab: Strategie auswählen, Hyperopt-Loss konfigurieren, RPC-Alerting testen."""
    st.subheader("🔧 Strategie & Alerting Konfiguration")

    # ── Aktive Strategie ──────────────────────────────────────────────────────
    st.markdown("#### Aktive Strategie")
    active_data  = _get("/api/strategies/active")
    strat_list   = _get("/api/strategies").get("strategies", [])
    active_name  = active_data.get("strategy", "internal")
    model_info   = _get("/api/model/info")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Aktive Strategie", active_name)
        if model_info.get("status") == "ok":
            st.metric("ML-Modell", model_info.get("model_type", "?"),
                      help=f"Val F1: {model_info.get('val_f1','?')} | {model_info.get('n_features','?')} Features")
    with col2:
        if model_info.get("trained_on"):
            st.metric("Trainiert am", model_info.get("trained_on", "?"))
        if active_data.get("custom_active"):
            st.success("Custom IStrategy aktiv")
        else:
            st.info("Interne ML+Regime-Logik aktiv")

    # ── Strategie-Auswahl ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Strategie wählen")

    if strat_list:
        builtin  = [s for s in strat_list if s.get("type") == "builtin" and not s.get("error")]
        custom   = [s for s in strat_list if s.get("type") == "custom"]

        options  = ["internal (ML + Regime)"] + [s["name"] for s in builtin] + [s["name"] for s in custom]
        selected = st.selectbox("Strategie", options,
                                index=options.index(active_name) if active_name in options else 0)

        if selected != "internal (ML + Regime)":
            s_meta = next((s for s in strat_list if s.get("name") == selected), {})
            if s_meta.get("description"):
                st.caption(f"**{s_meta.get('description','')}** | v{s_meta.get('version','?')} | tf={s_meta.get('timeframe','?')}")

        if st.button("Strategie übernehmen (erfordert Restart)", type="primary"):
            if selected == "internal (ML + Regime)":
                r = _post_json("/api/strategies/select", {"strategy": "", "persist": True})
            else:
                r = _post_json("/api/strategies/select", {"strategy": selected, "persist": True})
            if r.get("status") == "ok":
                st.success(f"✅ Strategie auf **{selected}** gesetzt — Bot neu starten!")
            else:
                st.error(f"Fehler: {r.get('detail', r)}")
    else:
        st.warning("Strategie-Liste konnte nicht geladen werden.")

    # ── Custom Strategie ──────────────────────────────────────────────────────
    with st.expander("Custom Strategie (eigene .py-Datei)"):
        st.markdown("""
Eigene Strategie erstellen:
1. `IStrategy` aus `crypto_bot.strategy.interface` importieren
2. `populate_indicators()`, `populate_entry_signal()`, `populate_exit_signal()` implementieren
3. Datei in `strategies/` ablegen (Projektverzeichnis)
4. Hier den Klassen-Namen eingeben und übernehmen
        """)
        custom_name = st.text_input("Klassen-Name", placeholder="MeineCoolStrategie")
        custom_path = st.text_input("Pfad (optional)", placeholder="/pfad/zur/strategie.py")
        if st.button("Custom Strategie laden"):
            r = _post_json("/api/strategies/select",
                           {"strategy": custom_name, "strategy_path": custom_path, "persist": True})
            if r.get("status") == "ok":
                st.success(f"✅ Custom Strategie **{custom_name}** gesetzt — Bot neu starten!")
            else:
                st.error(f"Fehler: {r.get('detail', r)}")

    # ── Hyperopt Loss-Funktion ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Hyperopt Loss-Funktion")
    loss_data = _get("/api/hyperopt/loss_functions")
    loss_list = loss_data.get("available", [])
    active_loss = loss_data.get("active", "multi_metric")

    if loss_list:
        loss_options = [f["name"] for f in loss_list]
        loss_descs   = {f["name"]: f["description"] for f in loss_list}
        sel_idx = loss_options.index(active_loss) if active_loss in loss_options else 0
        selected_loss = st.selectbox("Loss-Funktion", loss_options, index=sel_idx,
                                     format_func=lambda x: f"{x} — {loss_descs.get(x,'')}")
        if selected_loss != active_loss:
            if st.button("Loss-Funktion übernehmen"):
                r = _post_json("/api/hyperopt/loss_functions", {"loss_function": selected_loss, "persist": True})
                if r.get("status") == "ok":
                    st.success(f"✅ Loss-Funktion auf **{selected_loss}** gesetzt")
                    st.rerun()
                else:
                    st.error(str(r))
    else:
        st.metric("Aktive Loss-Funktion", active_loss)

    # ── RPC / Alerting ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Alerting Kanäle")
    rpc_data = _get("/api/rpc/status")
    channels = rpc_data.get("channels", {})

    col_tg, col_dc, col_wh = st.columns(3)
    with col_tg:
        tg = channels.get("telegram", {})
        st.metric("Telegram", "✅ Aktiv" if tg.get("enabled") else "❌ Nicht konfiguriert")
        if not tg.get("configured"):
            st.caption("TELEGRAM_TOKEN + TELEGRAM_CHAT_ID in .env setzen")

    with col_dc:
        dc = channels.get("discord", {})
        icon = "✅ Aktiv" if dc.get("enabled") else ("⚠️ URL fehlt" if not dc.get("configured") else "❌ Feature deaktiviert")
        st.metric("Discord", icon)
        if not dc.get("configured"):
            st.caption("DISCORD_WEBHOOK_URL in .env + FEATURE_DISCORD_RPC=true")

    with col_wh:
        wh = channels.get("webhook", {})
        icon = "✅ Aktiv" if wh.get("enabled") else ("⚠️ URL fehlt" if not wh.get("configured") else "❌ Feature deaktiviert")
        st.metric("HTTP Webhook", icon)
        if wh.get("url"):
            st.caption(f"URL: {wh['url']}")
        elif not wh.get("configured"):
            st.caption("WEBHOOK_URL in .env + FEATURE_WEBHOOK_RPC=true")

    if st.button("🔔 Test-Nachricht an alle Kanäle senden"):
        r = _post_json("/api/rpc/test", {})
        if r.get("status") == "ok":
            results = r.get("results", {})
            for ch, ok in results.items():
                if ok:
                    st.success(f"✅ {ch.title()}: Test OK")
                else:
                    st.warning(f"⚠️ {ch.title()}: Nicht konfiguriert oder Fehler")
        else:
            st.error(str(r))


def _render_features_tab():
    """Features-Tab: alle Feature-Flags als Toggle-Switches mit Beschreibungen."""
    st.subheader("⚙️ Feature Management")

    data = _get("/api/features/all")
    features = data.get("features", [])
    if not features:
        st.warning("Features konnten nicht geladen werden.")
        return

    # Hardware-Profil für "Empfohlen"-Badges laden
    hw = _get("/api/benchmark/hardware")
    recommended = hw.get("profile", {}).get("recommended_features", {}) if hw.get("status") == "ok" else {}

    # Nach Kategorie gruppieren
    by_cat: dict = {}
    for f in features:
        cat = f.get("category", "Other")
        by_cat.setdefault(cat, []).append(f)

    view_mode = st.session_state.get("view_mode", "standard")

    for cat, items in sorted(by_cat.items()):
        # Im Standard-Modus nur standard-Features zeigen
        visible = [f for f in items if view_mode == "pro" or f.get("level") == "standard"]
        if not visible:
            continue

        with st.expander(f"**{cat}** ({sum(1 for f in visible if f['enabled'])}/{len(visible)} aktiv)", expanded=True):
            for feat in visible:
                col_toggle, col_info = st.columns([1, 4])
                with col_toggle:
                    new_val = st.toggle(
                        "",
                        value=feat["enabled"],
                        key=f"feat_{feat['name']}",
                        help=feat.get("desc", ""),
                    )
                    if new_val != feat["enabled"]:
                        result = _post_json(
                            f"/api/features/{feat['name']}",
                            json={"enabled": new_val, "persist": True}
                        )
                        if result.get("status") == "ok":
                            st.toast(f"{'✅' if new_val else '❌'} {feat['label']}", icon="⚙️")
                            st.rerun()
                        else:
                            st.error(f"Fehler: {result.get('detail', result)}")

                with col_info:
                    badges = ""
                    if feat.get("level") == "pro":
                        badges += " `PRO`"
                    feat_env = f"FEATURE_{feat['name']}"
                    if feat_env in recommended:
                        rec_val = recommended[feat_env]
                        if isinstance(rec_val, bool):
                            badges += f" {'✅ empfohlen' if rec_val else '⚠️ nicht empfohlen (Hardware)'}"
                    st.markdown(f"**{feat['label']}**{badges}")
                    if feat.get("desc"):
                        st.caption(feat["desc"])

    if view_mode == "standard":
        st.info("Pro-Features ausgeblendet. Wechsle zu **Pro**-Ansicht für alle Features.")


# ── System Tab ────────────────────────────────────────────────────────────────

def _render_system_tab():
    """System-Tab: Hardware-Profil, Benchmark, Secret-Backends, Disk/RAM."""
    st.subheader("🖥️ System")

    col1, col2 = st.columns(2)

    # Hardware Benchmark
    with col1:
        st.markdown("#### Hardware-Benchmark")
        hw = _get("/api/benchmark/hardware")
        if hw.get("status") == "ok":
            p = hw["profile"]
            hwd = p.get("hardware", {})
            cpu = hwd.get("cpu", {})
            ram = hwd.get("ram", {})
            disk = hwd.get("disk", {})
            net = hwd.get("net", {})
            st.metric("CPU Score", f"{cpu.get('score_kps', 0)} k/s", f"{cpu.get('cores', 0)} Kerne")
            st.metric("RAM", f"{ram.get('total_mb', 0)} MB", f"{ram.get('available_mb', 0)} MB frei")
            st.metric("Disk Write", f"{disk.get('write_mbs', 0)} MB/s")
            st.metric("Netzwerk Latenz", f"{net.get('latency_ms', '?')} ms", "zu Binance API")
            avx2 = hwd.get("avx2", False)
            gpu  = hwd.get("gpu", False)
            st.caption(f"AVX2: {'✅' if avx2 else '❌'} | GPU: {'✅' if gpu else '❌'} | Alter: {hw.get('age_hours', '?')}h")
            if st.button("🔄 Benchmark neu starten", key="bench_run"):
                with st.spinner("Benchmark läuft (~10s)..."):
                    r = _post("/api/benchmark/hardware/run")
                if r.get("status") == "ok":
                    st.success("Benchmark abgeschlossen!")
                    st.rerun()
                else:
                    st.error(f"Fehler: {r.get('message')}")

            st.markdown("**Empfohlene Feature-Flags:**")
            for k, v in p.get("recommended_features", {}).items():
                icon = "✅" if v is True else ("❌" if v is False else "ℹ️")
                st.caption(f"{icon} `{k}={v}`")
        elif hw.get("status") == "not_run":
            st.info("Noch kein Benchmark durchgeführt.")
            if st.button("▶ Benchmark starten", key="bench_run_first"):
                with st.spinner("Benchmark läuft (~10s)..."):
                    r = _post("/api/benchmark/hardware/run")
                if r.get("status") == "ok":
                    st.success("Fertig!")
                    st.rerun()
        else:
            st.warning(f"Benchmark-Status: {hw.get('status')}")

    # System & Secret-Status
    with col2:
        st.markdown("#### System-Info")
        sys_info = _get("/api/system")
        if sys_info:
            disk_info = sys_info.get("disk", {})
            ram_info  = sys_info.get("ram", {})
            st.metric("Platform", f"{sys_info.get('platform')} / {sys_info.get('machine')}")
            if disk_info:
                st.metric("Disk", f"{disk_info.get('free_gb')} GB frei",
                          f"{disk_info.get('pct')}% belegt von {disk_info.get('total_gb')} GB")
            if ram_info:
                st.metric("RAM", f"{ram_info.get('available_mb')} MB frei",
                          f"{ram_info.get('pct')}% belegt")

        st.markdown("#### Secret-Backends")
        sec = _get("/api/secrets/status")
        active = sec.get("active_backend", "?")
        st.caption(f"Aktiv: **{active}**")
        for backend in sec.get("backends", []):
            name      = backend.get("backend", "?")
            available = backend.get("available", False)
            icon      = "🟢" if available else "⚫"
            is_active = name == active
            label     = f"**{name}**" if is_active else name
            st.markdown(f"{icon} {label}" + (" ← aktiv" if is_active else ""))
            for k, v in backend.items():
                if k not in ("backend", "available") and v:
                    st.caption(f"  {k}: `{v}`")


# ── Crypto Dashboard (ausgelagert damit es in st.empty().container() passt) ───

def _render_crypto_dashboard():
    _health = _get("/health")
    if not _health:
        st.error(f"{_t('i.api_error')} `{API_URL}`")
        if "localhost" in API_URL:
            st.code("make dashboard-api   # Terminal 1\nmake dashboard      # Terminal 2")
        else:
            st.info(_t("i.api_docker"))
        st.stop()

    _sidebar_status = _get("/api/status")
    render_sidebar(_sidebar_status)

    st.sidebar.markdown("---")
    refresh_interval = st.sidebar.slider(_t("s.refresh"), 10, 120, 30, key="refresh_iv")
    if not _HAS_FRAGMENT:
        st.sidebar.caption("ℹ Streamlit < 1.37 — full page reload")

    st.title(_t("title"))

    _is_pro = st.session_state.get("view_mode", "standard") == "pro"
    if _is_pro:
        (tab_overview, tab_chart, tab_performance, tab_trades, tab_strategy, tab_strategy_cfg,
         tab_risk, tab_explain, tab_logs, tab_features, tab_marketplace, tab_system, tab_help) = st.tabs([
            _t("tab.overview"), "📈 Chart", _t("tab.perf"), _t("tab.trades"),
            _t("tab.strategy"), _t("tab.strategy_cfg"),
            _t("tab.risk"), _t("tab.explain"), _t("tab.logs"),
            _t("tab.features"), _t("tab.marketplace"), _t("tab.system"), _t("tab.help"),
        ])
    else:
        (tab_overview, tab_chart, tab_trades, tab_strategy_cfg,
         tab_logs, tab_features, tab_marketplace, tab_system, tab_help) = st.tabs([
            _t("tab.overview"), "📈 Chart", _t("tab.trades"), _t("tab.strategy_cfg"),
            _t("tab.logs"), _t("tab.features"), _t("tab.marketplace"),
            _t("tab.system"), _t("tab.help"),
        ])
        tab_performance = tab_strategy = tab_risk = tab_explain = None

    _tz_short = st.session_state.get("tz", "Europe/Berlin").split("/")[-1]

    with tab_overview:
        with st.expander("💱 Exchange & API Keys", expanded=bool(st.session_state.get("exchange_form"))):
            _render_exchange_selector()
        st.markdown("---")

        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_overview():
                s = _get("/api/status")
                e = _get("/api/equity")
                p = _get("/api/performance")
                hb = _get("/api/heartbeat")
                try:
                    from zoneinfo import ZoneInfo
                    _now = datetime.now(ZoneInfo(st.session_state.get("tz", "Europe/Berlin")))
                    st.caption(f"⟳ {_now.strftime('%H:%M:%S')} {_tz_short}")
                except Exception:
                    st.caption(f"⟳ {datetime.now().strftime('%H:%M:%S')}")
                render_heartbeat(hb)
                st.markdown("---")
                _render_phase_progress()
                st.markdown("---")
                render_live_status(s)
                st.markdown("---")
                col_chart, col_pos = st.columns([3, 2])
                with col_chart:
                    render_equity_chart(e)
                with col_pos:
                    st.subheader(_t("sec.pos"))
                    render_position(s)
                st.markdown("---")
                render_performance(p)
                st.markdown("---")
                render_market_context()
            _frag_overview()
        else:
            s = _get("/api/status")
            e = _get("/api/equity")
            p = _get("/api/performance")
            try:
                from zoneinfo import ZoneInfo
                _now = datetime.now(ZoneInfo(st.session_state.get("tz", "Europe/Berlin")))
                st.caption(f"⟳ {_now.strftime('%H:%M:%S')} {_tz_short}")
            except Exception:
                st.caption(f"⟳ {datetime.now().strftime('%H:%M:%S')}")
            _render_phase_progress()
            st.markdown("---")
            render_live_status(s)
            st.markdown("---")
            col_chart, col_pos = st.columns([3, 2])
            with col_chart:
                render_equity_chart(e)
            with col_pos:
                st.subheader(_t("sec.pos"))
                render_position(s)
            st.markdown("---")
            render_performance(p)
            st.markdown("---")
            render_market_context()

    with tab_chart:
        st.subheader("📈 Candlestick Chart")
        s_for_chart = _get("/api/status")
        pos_for_chart = (s_for_chart or {}).get("position", {}) or {}

        _tf_options = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        if "chart_tf_crypto" not in st.session_state:
            st.session_state["chart_tf_crypto"] = "1h"
        if "chart_limit_crypto" not in st.session_state:
            st.session_state["chart_limit_crypto"] = 100
        if "chart_symbol_crypto" not in st.session_state:
            st.session_state["chart_symbol_crypto"] = (
                (s_for_chart or {}).get("symbol", "BTC/USDT") if s_for_chart else "BTC/USDT"
            )

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            _chart_symbol = st.text_input("Symbol", key="chart_symbol_crypto")
        with c2:
            _chart_tf = st.selectbox("Timeframe", _tf_options, key="chart_tf_crypto")
        with c3:
            _chart_limit = st.selectbox("Candles", [50, 100, 150, 200], key="chart_limit_crypto")

        # Direkt Binance REST — kein Umweg über trading-dashboard, kein Timeout
        try:
            _br = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": _chart_symbol.replace("/", ""),
                        "interval": _chart_tf, "limit": _chart_limit},
                timeout=8,
            )
            _candles = [
                {"time": datetime.fromtimestamp(r[0]/1000, tz=_tz_utc.utc).isoformat(),
                 "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                for r in (_br.json() if _br.status_code == 200 else [])
            ]
        except Exception:
            _candles = []

        _entry = pos_for_chart.get("entry_price") if pos_for_chart.get("symbol", "") == _chart_symbol else None
        _sl    = pos_for_chart.get("stop_loss")   if _entry else None
        _tp    = pos_for_chart.get("take_profit")  if _entry else None

        _render_candle_chart(
            _candles,
            title=f"{_chart_symbol} — {_chart_tf}",
            entry_price=_entry, sl=_sl, tp=_tp,
        )
        if _entry:
            st.caption(f"Entry: {_entry:.4f}  |  SL: {_sl or '—'}  |  TP: {_tp or '—'}")

    if tab_performance is not None:
      with tab_performance:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_performance():
                _render_periodic_charts()
                st.markdown("---")
                render_performance_extended(_get("/api/performance/extended"))
            _frag_performance()
        else:
            _render_periodic_charts()
            st.markdown("---")
            render_performance_extended(_get("/api/performance/extended"))

    with tab_trades:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_trades():
                st.subheader(_t("sec.trade_hist"))
                render_trades(_get("/api/trades?limit=20"))
            _frag_trades()
        else:
            st.subheader(_t("sec.trade_hist"))
            render_trades(_get("/api/trades?limit=20"))

    if tab_strategy is not None:
      with tab_strategy:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_strategy():
                _render_strategy_performance()
            _frag_strategy()
        else:
            _render_strategy_performance()

    if tab_risk is not None:
      with tab_risk:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_risk():
                _render_risk_market_tab()
            _frag_risk()
        else:
            _render_risk_market_tab()

    if tab_explain is not None:
      with tab_explain:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_explain():
                _render_explainability(_get("/api/status"))
                st.markdown("---")
                render_execution_quality(_get("/api/execution_quality"))
            _frag_explain()
        else:
            _render_explainability(_sidebar_status)
            st.markdown("---")
            render_execution_quality(_get("/api/execution_quality"))

    with tab_strategy_cfg:
        _render_strategy_cfg_tab()

    with tab_logs:
        if _HAS_FRAGMENT:
            @st.fragment(run_every=refresh_interval)
            def _frag_logs():
                _render_logs()
            _frag_logs()
        else:
            _render_logs()

    with tab_features:
        _render_features_tab()

    with tab_marketplace:
        _render_marketplace_tab()

    with tab_system:
        _render_system_tab()

    with tab_help:
        _render_help()


# ── Haupt-App ─────────────────────────────────────────────────────────────────

def main():
    # Suppress Streamlit's built-in opacity fade during reruns.
    # Without this, stale DOM elements (especially when switching from a
    # taller page to a shorter one) briefly appear at 50% opacity at the bottom.
    st.markdown("""<style>
    .stApp > .main { transition: none !important; opacity: 1 !important; }
    .stApp > .main .block-container > div { transition: none !important; }
    </style>""", unsafe_allow_html=True)

    # Session-State Defaults
    if "lang" not in st.session_state:
        st.session_state["lang"] = "de"
    if "tz" not in st.session_state:
        st.session_state["tz"] = "Europe/Berlin"
    if "bot_mode" not in st.session_state:
        st.session_state["bot_mode"] = st.query_params.get("mode", "crypto")

    # Detect mode switch → clear cache so new mode loads fresh data immediately
    _prev_mode = st.session_state.get("_prev_bot_mode")
    _cur_mode  = st.session_state.get("bot_mode", "crypto")
    if _prev_mode is not None and _prev_mode != _cur_mode:
        _get.clear()
        _fget.clear()
    st.session_state["_prev_bot_mode"] = _cur_mode

    # ── Bot-Auswahl (Crypto / Forex) ──────────────────────────────────────────
    _col_bot, _col_lang = st.columns([9, 1])
    with _col_bot:
        _b1, _b2, _b_rest = st.columns([1, 1, 7])
        with _b1:
            _c_type = "primary" if _cur_mode == "crypto" else "secondary"
            if st.button("📊 Crypto", key="mode_crypto_btn", type=_c_type):
                st.session_state["bot_mode"] = "crypto"
                st.session_state["_mode_just_switched"] = True
                st.query_params["mode"] = "crypto"
                _get.clear()
                _fget.clear()
                st.rerun()
        with _b2:
            _f_type = "primary" if _cur_mode == "forex" else "secondary"
            if st.button("💱 Forex", key="mode_forex_btn", type=_f_type):
                st.session_state["bot_mode"] = "forex"
                st.session_state["_mode_just_switched"] = True
                st.query_params["mode"] = "forex"
                _get.clear()
                _fget.clear()
                st.rerun()
    with _col_lang:
        st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)
        _lc1, _lc2 = st.columns(2)
        with _lc1:
            _de_type = "primary" if st.session_state.get("lang") == "de" else "secondary"
            if st.button("DE", key="lang_de_btn", help="Deutsch", type=_de_type):
                st.session_state["lang"] = "de"
                st.rerun()
        with _lc2:
            _en_type = "primary" if st.session_state.get("lang") == "en" else "secondary"
            if st.button("EN", key="lang_en_btn", help="English", type=_en_type):
                st.session_state["lang"] = "en"
                st.rerun()

    # ── Dashboard-Container — einmaliges clear() verhindert Ghost-Elemente ──────
    # Wenn der Modus gewechselt hat, leeren wir den Container explizit bevor
    # der neue Inhalt gerendert wird. Das verhindert dass überschüssige Elemente
    # des alten Modus kurz sichtbar bleiben (Streamlit DOM-Diff Artefakt).
    _main = st.empty()
    if st.session_state.get("_mode_just_switched"):
        st.session_state.pop("_mode_just_switched", None)
        _main.empty()

    with _main.container():
        if st.session_state.get("bot_mode") == "forex":
            _render_forex_sidebar()
            _render_forex_dashboard()
            return
        _render_crypto_dashboard()


if __name__ == "__main__":
    main()
