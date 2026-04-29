"""
Bot-Diagnose — sammelt alle relevanten Infos in einem Aufruf.
Ausgabe ist für copy-paste optimiert (z.B. an Claude weitergeben).

Verwendung:
    python scripts/diagnose.py                                  # lokal
    python scripts/diagnose.py --api-url http://YOUR_QNAP_IP:8000  # QNAP via API
    python scripts/diagnose.py --log-lines 200
    python scripts/diagnose.py --no-logs
"""
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from rich.console import Console
    from rich.rule import Rule
    console = Console()
    def section(title): console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    def out(text):      console.print(text)
except ImportError:
    def section(title): print(f"\n{'='*60}\n  {title}\n{'='*60}")
    def out(text):      print(text)


# ── Datenquellen: lokal ───────────────────────────────────────────────────────

def _local_state() -> dict:
    state_file = ROOT / "data_store" / "bot_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {}


def _local_db() -> dict:
    db_path = ROOT / "data_store" / "trades.db"
    if not db_path.exists():
        return {"error": "trades.db nicht gefunden"}
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT COUNT(*) as total,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                    AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
                    MIN(created_at) as first_trade,
                    MAX(created_at) as last_trade
                FROM trades
            """).fetchone()
            summary = dict(row) if row else {}

            rows = conn.execute("""
                SELECT side, symbol, entry_price, exit_price, pnl, reason,
                       ai_source, confidence, created_at
                FROM trades ORDER BY created_at DESC LIMIT 10
            """).fetchall()
            recent_trades = [dict(r) for r in rows]

            breakdown = conn.execute("""
                SELECT ai_source, COUNT(*) as cnt, SUM(pnl) as pnl
                FROM trades GROUP BY ai_source
            """).fetchall()
            trade_breakdown = [dict(r) for r in breakdown]

            try:
                sig_rows = conn.execute(
                    "SELECT signal, confidence, reason, created_at FROM signals ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
                signals = [dict(r) for r in sig_rows]
            except Exception:
                signals = []

            try:
                rej_rows = conn.execute(
                    "SELECT signal, reason, confidence, created_at FROM rejections ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
                rejections = [dict(r) for r in rej_rows]
            except Exception:
                rejections = []

        return {"summary": summary, "recent_trades": recent_trades,
                "trade_breakdown": trade_breakdown, "signals": signals, "rejections": rejections}
    except Exception as e:
        return {"error": str(e)}


def _local_config() -> dict:
    try:
        from crypto_bot.config import settings as cfg
        from crypto_bot.config import features
        return {
            "TRADING_MODE":       cfg.TRADING_MODE,
            "AI_MODE":            cfg.AI_MODE,
            "SYMBOL":             cfg.SYMBOL,
            "TIMEFRAME":          cfg.TIMEFRAME,
            "INITIAL_CAPITAL":    cfg.INITIAL_CAPITAL,
            "ML_MIN_CONFIDENCE":  cfg.ML_MIN_CONFIDENCE,
            "RISK_PER_TRADE":     cfg.RISK_PER_TRADE,
            "MAX_DAILY_LOSS_PCT": cfg.MAX_DAILY_LOSS_PCT,
            "STOP_LOSS_PCT":      getattr(cfg, "STOP_LOSS_PCT", "?"),
            "TAKE_PROFIT_PCT":    getattr(cfg, "TAKE_PROFIT_PCT", "?"),
            "features":           features.get_all() if hasattr(features, "get_all") else {},
        }
    except Exception as e:
        return {"error": str(e)}


def _local_model() -> dict:
    model_path = ROOT / "ai" / "model.joblib"
    if not model_path.exists():
        return {"status": "FEHLT — kein Modell trainiert!"}
    try:
        from crypto_bot.ai.retrainer import AutoRetrainer
        return AutoRetrainer().get_model_info()
    except Exception:
        mtime = datetime.fromtimestamp(model_path.stat().st_mtime)
        return {"status": "vorhanden", "modified": mtime.strftime("%Y-%m-%d %H:%M"),
                "size_kb": round(model_path.stat().st_size / 1024, 1)}


def _local_logs(lines: int) -> list:
    log_path = ROOT / "logs" / "bot.log"
    if not log_path.exists():
        return ["logs/bot.log nicht gefunden"]
    try:
        return log_path.read_text(errors="replace").splitlines()[-lines:]
    except Exception as e:
        return [f"Fehler: {e}"]


# ── Datenquellen: API (QNAP / remote) ────────────────────────────────────────

def _api_get(base_url: str, endpoint: str) -> dict:
    try:
        import requests
        r = requests.get(f"{base_url}{endpoint}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        return {"_error": str(e)}
    return {}


def _api_state(base_url: str) -> dict:
    return _api_get(base_url, "/api/status")


def _api_db(base_url: str) -> dict:
    perf   = _api_get(base_url, "/api/performance")
    trades = _api_get(base_url, "/api/trades?limit=10")
    prog   = _api_get(base_url, "/api/progress")
    sigs   = _api_get(base_url, "/api/signals?limit=10")
    rejs   = _api_get(base_url, "/api/rejections?limit=10")

    if "_error" in perf:
        return {"error": perf["_error"]}

    total = perf.get("total_trades") or 0
    wins  = perf.get("wins") or 0
    summary = {
        "total":       total,
        "wins":        wins,
        "losses":      perf.get("losses") or 0,
        "total_pnl":   perf.get("total_pnl") or 0.0,
        "avg_win":     perf.get("avg_win") or 0.0,
        "avg_loss":    perf.get("avg_loss") or 0.0,
        "first_trade": None,
        "last_trade":  None,
        "sharpe":      perf.get("sharpe_ratio") or 0.0,
        "sortino":     perf.get("sortino_ratio") or 0.0,
        "max_drawdown": perf.get("max_drawdown") or 0.0,
        "profit_factor": perf.get("profit_factor") or 0.0,
    }

    # Trade-Aufschlüsselung aus /api/progress
    tb = prog.get("trade_breakdown", {})
    trade_breakdown = []
    if tb:
        trade_breakdown.append({"ai_source": "live",     "cnt": tb.get("live", 0),     "pnl": None})
        trade_breakdown.append({"ai_source": "backtest", "cnt": tb.get("backtest", 0), "pnl": None})

    return {
        "summary":        summary,
        "recent_trades":  trades.get("trades", []),
        "trade_breakdown": trade_breakdown,
        "signals":        sigs.get("signals", []),
        "rejections":     rejs.get("rejections", []),
    }


def _api_config(base_url: str) -> dict:
    status   = _api_get(base_url, "/api/status")
    features = _api_get(base_url, "/api/features")
    if "_error" in status:
        return {"error": status["_error"]}
    cfg = {
        "TRADING_MODE":   status.get("trading_mode", "?"),
        "AI_MODE":        status.get("ai_mode", "?"),
        "SYMBOL":         status.get("symbol", "?"),
        "TIMEFRAME":      status.get("timeframe", "?"),
        "INITIAL_CAPITAL": status.get("initial_capital", "?"),
    }
    feats = features.get("features", {})
    disabled = [k for k, v in feats.items() if not v]
    if disabled:
        cfg["Deaktivierte Features"] = ", ".join(disabled)
    return cfg


def _api_model(base_url: str) -> dict:
    data = _api_get(base_url, "/api/model")
    if "_error" in data:
        return {"status": f"API-Fehler: {data['_error']}"}
    return data


def _api_logs(base_url: str, lines: int) -> list:
    data = _api_get(base_url, f"/api/logs?lines={lines}")
    if "_error" in data:
        return [f"API-Fehler: {data['_error']}"]
    return data.get("lines", ["Keine Logs"])


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def _fmt(ts) -> str:
    if not ts:
        return "—"
    return str(ts)[:19]


def run(log_lines: int = 100, show_logs: bool = True, api_url: str = ""):
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    remote = bool(api_url)
    source = f"QNAP ({api_url})" if remote else "lokal"

    out(f"\n[bold]Bot-Diagnose[/bold]  •  {now}  •  Quelle: {source}\n")

    if remote:
        # Verbindungstest
        health = _api_get(api_url, "/health")
        if "_error" in health:
            out(f"[red]✗ API nicht erreichbar: {api_url}[/red]")
            out(f"[red]  Fehler: {health['_error']}[/red]")
            out("[yellow]  Läuft der Dashboard-API Container? (Port 8000)[/yellow]")
            return
        out(f"[green]✓ API erreichbar ({api_url})[/green]\n")

    # Daten laden
    if remote:
        state   = _api_state(api_url)
        db      = _api_db(api_url)
        cfg     = _api_config(api_url)
        model   = _api_model(api_url)
        logs    = _api_logs(api_url, log_lines) if show_logs else []
    else:
        state   = _local_state()
        db      = _local_db()
        cfg     = _local_config()
        model   = _local_model()
        logs    = _local_logs(log_lines) if show_logs else []

    # ── 1. Bot State ──────────────────────────────────────────────
    section("1. Bot State")
    if not state or "_error" in state:
        if remote:
            out("  [red]✗ Kein Status — API antwortet aber /api/status liefert nichts[/red]")
        else:
            out("  [yellow]⚠ bot_state.json nicht gefunden — Bot läuft nicht oder läuft im selben Prozess[/yellow]")
    else:
        skip = {"strategy_performance", "last_explanation", "position"}
        for k, v in state.items():
            if k not in skip:
                out(f"  {k}: {v}")
        pos = state.get("position")
        if pos:
            out(f"  position: {pos}")

    # ── 2. Konfiguration ──────────────────────────────────────────
    section("2. Konfiguration")
    if "error" in cfg:
        out(f"  [red]Fehler: {cfg['error']}[/red]")
    else:
        for k, v in cfg.items():
            out(f"  {k}: {v}")

    # ── 3. ML-Modell ──────────────────────────────────────────────
    section("3. ML-Modell")
    for k, v in model.items():
        color = ""
        if k == "val_f1" and isinstance(v, float) and v < 0.38:
            color = "[yellow]"
        out(f"  {color}{k}: {v}{'[/yellow]' if color else ''}")

    # ── 4. Performance ────────────────────────────────────────────
    section("4. Performance (trades.db)")
    if "error" in db:
        out(f"  [red]Fehler: {db['error']}[/red]")
    else:
        s     = db["summary"]
        total = s.get("total") or 0
        wins  = s.get("wins") or 0
        pnl   = s.get("total_pnl") or 0.0

        out(f"  Trades gesamt:  {total}")
        if total > 0:
            wr = wins / total * 100
            wr_color = "[green]" if wr >= 48 else "[yellow]" if wr >= 33 else "[red]"
            out(f"  Wins / Losses:  {wins} / {s.get('losses', 0)}")
            out(f"  Win-Rate:       {wr_color}{wr:.1f}%[/{wr_color[1:]}")
            pnl_color = "[green]" if pnl >= 0 else "[red]"
            out(f"  Gesamt PnL:     {pnl_color}{pnl:+.2f} USDT[/{pnl_color[1:]}")
            out(f"  Ø Gewinn:       {s.get('avg_win') or 0:.2f} USDT")
            out(f"  Ø Verlust:      {s.get('avg_loss') or 0:.2f} USDT")
            if s.get("sharpe"):
                out(f"  Sharpe Ratio:   {s['sharpe']:.2f}")
            if s.get("max_drawdown"):
                out(f"  Max Drawdown:   {s['max_drawdown']:.1f}%")
            if s.get("first_trade"):
                out(f"  Erster Trade:   {_fmt(s.get('first_trade'))}")
            if s.get("last_trade"):
                out(f"  Letzter Trade:  {_fmt(s.get('last_trade'))}")
        else:
            out("  [yellow]Noch keine Trades in der Datenbank[/yellow]")

        if db["trade_breakdown"]:
            out("\n  Aufschlüsselung nach Quelle:")
            for b in db["trade_breakdown"]:
                pnl_str = f"  |  PnL: {b['pnl']:+.2f} USDT" if b.get("pnl") is not None else ""
                out(f"    {(b['ai_source'] or 'live'):12} → {b['cnt']:4} Trades{pnl_str}")

        if db["recent_trades"]:
            out("\n  Letzte 10 Trades:")
            for t in db["recent_trades"]:
                p = t.get("pnl")
                pnl_str = f"{p:+.2f}" if p is not None else "?"
                pnl_c = "[green]" if (p or 0) > 0 else "[red]"
                out(f"    {_fmt(t.get('created_at'))}  {str(t.get('side','?')):4}  "
                    f"PnL: {pnl_c}{pnl_str:>8}[/{pnl_c[1:]} USDT  "
                    f"Grund: {t.get('reason','?'):8}  "
                    f"Quelle: {t.get('ai_source','?'):10}  "
                    f"Conf: {t.get('confidence') or 0:.2f}")

    # ── 5. Letzte AI-Signale ──────────────────────────────────────
    section("5. Letzte AI-Signale")
    signals = db.get("signals", [])
    if signals:
        for s in signals:
            out(f"  {_fmt(s.get('created_at'))}  Signal: {str(s.get('signal','?')):5}  "
                f"Conf: {s.get('confidence') or 0:.2f}  "
                f"Grund: {str(s.get('reason',''))[:80]}")
    else:
        out("  [yellow]Keine Signale in DB[/yellow]")

    # ── 6. Letzte Ablehnungen ─────────────────────────────────────
    section("6. Letzte Trade-Ablehnungen (HOLD-Gründe)")
    rejections = db.get("rejections", [])
    if rejections:
        for r in rejections:
            out(f"  {_fmt(r.get('created_at'))}  {str(r.get('signal','?')):5}  "
                f"Conf: {r.get('confidence') or 0:.2f}  "
                f"Grund: {str(r.get('reason',''))[:80]}")
    else:
        out("  [yellow]Keine Ablehnungen in DB[/yellow]")

    # ── 7. Logs ───────────────────────────────────────────────────
    if show_logs:
        section(f"7. Letzte {log_lines} Log-Zeilen (bot.log)")
        for line in logs:
            if "ERROR" in line:
                out(f"  [red]{line}[/red]")
            elif "WARNING" in line or "WARN" in line:
                out(f"  [yellow]{line}[/yellow]")
            else:
                out(f"  {line}")

    # ── Zusammenfassung ───────────────────────────────────────────
    section("Zusammenfassung")
    issues = []
    hints  = []

    running = state.get("running", False)
    if not state or "_error" in state:
        if not remote:
            issues.append("Bot-State nicht lesbar — läuft der Bot?")
    elif not running:
        issues.append("Bot meldet running=False — nicht aktiv")

    if state.get("paused"):
        issues.append("Bot ist PAUSIERT — /resume senden")
    if state.get("training_mode"):
        issues.append("Training Mode aktiv — kein Trading bis Modell fertig")

    f1 = model.get("val_f1", 0) or 0
    if f1 > 0 and f1 < 0.38:
        issues.append(f"F1-Score {f1:.4f} unter Minimum 0.38 — Retraining empfohlen: make train")

    live_trades = next((b["cnt"] for b in db.get("trade_breakdown", []) if b["ai_source"] == "live"), 0) or 0
    total_trades = (db.get("summary") or {}).get("total") or 0
    if total_trades > 0 and live_trades == 0:
        hints.append("Alle Trades sind Backtest-Daten — keine echten/Paper-Trades bisher")

    win_rate = (wins / total * 100) if total > 0 else 0
    if total > 10 and win_rate < 33:
        issues.append(f"Win-Rate {win_rate:.1f}% kritisch niedrig — mathematisch unprofitabel bei 2:1 R/R (Minimum: 33.3%)")

    if total == 0:
        hints.append("Noch keine Trades — wartet auf Signal ≥ 60% Konfidenz (normal bei neuem Bot)")

    if issues:
        out("\n  [bold red]Probleme:[/bold red]")
        for i in issues:
            out(f"  [red]✗[/red]  {i}")
    if hints:
        out("\n  [bold yellow]Hinweise:[/bold yellow]")
        for h in hints:
            out(f"  [yellow]ℹ[/yellow]  {h}")
    if not issues and not hints:
        out("  [green]✓ Alles sieht normal aus[/green]")

    out("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot-Diagnose (lokal oder QNAP via API)")
    parser.add_argument("--api-url",   type=str,  default="",    help="API-URL für Remote-Diagnose (z.B. http://YOUR_QNAP_IP:8000)")
    parser.add_argument("--log-lines", type=int,  default=100,   help="Anzahl Log-Zeilen (Standard: 100)")
    parser.add_argument("--no-logs",   action="store_true",      help="Logs nicht ausgeben")
    args = parser.parse_args()
    run(log_lines=args.log_lines, show_logs=not args.no_logs, api_url=args.api_url)
