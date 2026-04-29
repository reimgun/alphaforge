"""
Alerting — Benachrichtigungen via Telegram + Discord + Webhook.
Graceful Fallback: wenn kein Channel konfiguriert, nur Logging.

Alle Funktionen bleiben rückwärtskompatibel. Discord + Webhook werden
zusätzlich ausgelöst wenn FEATURE_DISCORD_RPC / FEATURE_WEBHOOK_RPC aktiv.
"""
import time
import requests
from crypto_bot.monitoring.logger import log
from crypto_bot.config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SYMBOL


def _route_extra(message: str, title: str = "", level: str = "info", symbol: str = "", event: str = "alert", data: dict = None) -> None:
    """Routet Nachricht zusätzlich zu Discord + Webhook wenn aktiviert."""
    try:
        from crypto_bot.config import features as feat
        if feat.DISCORD_RPC or feat.WEBHOOK_RPC:
            from crypto_bot.rpc.manager import get_rpc
            rpc = get_rpc()
            rpc._discord_embed(message, title, {"info": 0x0088FF, "warning": 0xFFAA00, "error": 0xFF4444, "critical": 0xFF0000}.get(level, 0x0088FF))
            if data:
                rpc._webhook_event(event, symbol or SYMBOL, data)
    except Exception:
        pass


def _send_telegram(message: str, retries: int = 2) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            if resp.status_code == 429 and attempt < retries:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", 5))
                time.sleep(min(retry_after, 30))
                continue
            log.warning(f"Telegram HTTP {resp.status_code}")
            return False
        except Exception as e:
            log.warning(f"Telegram-Fehler: {e}")
            return False
    return False


def alert_trade_opened(
    price: float, quantity: float, stop_loss: float, take_profit: float,
    reason: str, explanation: str = "",
):
    msg = (
        f"🟢 <b>KAUF {SYMBOL}</b>\n"
        f"Preis: <b>${price:,.2f}</b>\n"
        f"Menge: {quantity:.6f} BTC\n"
        f"Stop-Loss: ${stop_loss:,.2f}\n"
        f"Take-Profit: ${take_profit:,.2f}\n"
        f"Grund: {reason}"
    )
    if explanation:
        msg += f"\n\n🔍 <i>{explanation[:300]}</i>"
    log.info(f"ALERT trade_opened: {price:.2f}")
    _send_telegram(msg)
    _route_extra(msg, f"🟢 KAUF {SYMBOL}", "info", SYMBOL, "trade_opened",
                 {"price": price, "quantity": quantity, "stop_loss": stop_loss, "reason": reason})


def alert_trade_closed(
    exit_price: float, pnl: float, pnl_pct: float, reason: str, capital: float,
    explanation: str = "",
):
    icon = "✅" if pnl >= 0 else "🔴"
    msg = (
        f"{icon} <b>VERKAUF {SYMBOL}</b>\n"
        f"Preis: <b>${exit_price:,.2f}</b>\n"
        f"PnL: <b>{pnl:+.2f} USDT ({pnl_pct:+.2f}%)</b>\n"
        f"Grund: {reason}\n"
        f"Kapital: ${capital:,.2f}"
    )
    if explanation:
        msg += f"\n\n🔍 <i>{explanation[:300]}</i>"
    log.info(f"ALERT trade_closed: PnL={pnl:+.2f}")
    _send_telegram(msg)
    _route_extra(msg, f"{'✅' if pnl >= 0 else '🔴'} VERKAUF {SYMBOL}",
                 "info" if pnl >= 0 else "warning", SYMBOL, "trade_closed",
                 {"exit_price": exit_price, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason})


def alert_circuit_breaker(daily_loss: float, capital: float):
    msg = (
        f"🚨 <b>CIRCUIT BREAKER — {SYMBOL}</b>\n"
        f"Tagesverlust: <b>-${abs(daily_loss):.2f} USDT</b>\n"
        f"Bot pausiert bis morgen.\n"
        f"Kapital: ${capital:,.2f}"
    )
    log.warning(f"ALERT circuit_breaker: daily_loss={daily_loss:.2f}")
    _send_telegram(msg)


def alert_max_drawdown(drawdown_pct: float, capital: float):
    msg = (
        f"🚨 <b>MAX DRAWDOWN ERREICHT — {SYMBOL}</b>\n"
        f"Drawdown: <b>{drawdown_pct:.1f}%</b>\n"
        f"<b>Bot wurde gestoppt!</b> Manuelle Prüfung erforderlich.\n"
        f"Kapital: ${capital:,.2f}"
    )
    log.critical(f"ALERT max_drawdown: {drawdown_pct:.1f}%")
    _send_telegram(msg)


def alert_error(error_msg: str):
    msg = (
        f"⚠️ <b>FEHLER — Trading Bot</b>\n"
        f"<code>{error_msg[:400]}</code>"
    )
    log.error(f"ALERT error: {error_msg}")
    _send_telegram(msg)


def alert_daily_summary(capital: float, daily_pnl: float, total_trades: int):
    icon = "📈" if daily_pnl >= 0 else "📉"
    msg = (
        f"{icon} <b>Tagesbericht {SYMBOL}</b>\n"
        f"Tages-PnL: <b>{daily_pnl:+.2f} USDT</b>\n"
        f"Trades heute: {total_trades}\n"
        f"Kapital: ${capital:,.2f}"
    )
    log.info(f"ALERT daily_summary: PnL={daily_pnl:+.2f}, trades={total_trades}")
    _send_telegram(msg)


def alert_bot_started(mode: str, capital: float):
    msg = (
        f"🤖 <b>Bot gestartet — {SYMBOL}</b>\n"
        f"Modus: {mode.upper()}\n"
        f"Kapital: ${capital:,.2f}"
    )
    log.info("ALERT bot_started")
    _send_telegram(msg)


def alert_training_finished(f1: float, samples: int, duration_s: float = 0.0):
    msg = (
        f"✅ <b>Training abgeschlossen</b>\n"
        f"Val F1-Score: <b>{f1:.3f}</b>\n"
        f"Trainings-Samples: {samples}\n"
        f"Dauer: {duration_s:.0f}s\n"
        f"Bot ist bereit für Paper-Trading."
    )
    log.info(f"ALERT training_finished: F1={f1:.3f}")
    _send_telegram(msg)


def alert_model_retrain_complete(f1: float, samples: int, mode: str = "XGBoost"):
    msg = (
        f"🔄 <b>Modell-Retraining abgeschlossen</b>\n"
        f"Modell: {mode}\n"
        f"Val F1-Score: <b>{f1:.3f}</b>\n"
        f"Trainings-Samples: {samples}"
    )
    log.info(f"ALERT model_retrain_complete: F1={f1:.3f}")
    _send_telegram(msg)


def alert_strategy_switched(old_strategy: str, new_strategy: str, regime: str):
    msg = (
        f"🔀 <b>Strategie gewechselt</b>\n"
        f"Von: {old_strategy} → Zu: {new_strategy}\n"
        f"Regime: {regime}"
    )
    log.info(f"ALERT strategy_switched: {old_strategy} → {new_strategy}")
    _send_telegram(msg)
