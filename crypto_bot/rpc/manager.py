"""
RPC Manager — zentrale Benachrichtigungs-Verwaltung.

Routet alle Alerts zu allen konfigurierten Kanälen:
  - Telegram  (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)
  - Discord   (DISCORD_WEBHOOK_URL, FEATURE_DISCORD_RPC=true)
  - Webhook   (WEBHOOK_URL, FEATURE_WEBHOOK_RPC=true)

Verwendung:
    from crypto_bot.rpc.manager import get_rpc
    rpc = get_rpc()
    rpc.send_trade_opened("BTC/USDT", price=42000, ...)
    rpc.send_trade_closed("BTC/USDT", exit_price=44000, pnl=200, ...)
    rpc.send_alert("Bot gestartet", title="Bot Start", level="info")
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("trading_bot")


class RPCManager:
    """Routet Benachrichtigungen zu Telegram + Discord + Webhook."""

    def __init__(self):
        from crypto_bot.config.settings import (
            TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
            DISCORD_WEBHOOK_URL, WEBHOOK_URL, WEBHOOK_SECRET,
        )
        from crypto_bot.config import features as feat

        self._tg_token      = TELEGRAM_TOKEN
        self._tg_chat       = TELEGRAM_CHAT_ID
        self._discord_url   = DISCORD_WEBHOOK_URL if feat.DISCORD_RPC else ""
        self._webhook_url   = WEBHOOK_URL         if feat.WEBHOOK_RPC else ""
        self._webhook_secret= WEBHOOK_SECRET

    # ── High-Level Helpers ────────────────────────────────────────────────────

    def send_trade_opened(
        self,
        symbol:      str,
        price:       float,
        quantity:    float,
        stop_loss:   float,
        take_profit: float,
        reason:      str,
        explanation: str = "",
    ) -> None:
        tg_msg = (
            f"🟢 <b>KAUF {symbol}</b>\n"
            f"Preis: <b>${price:,.4f}</b>\n"
            f"Menge: {quantity:.6f}\n"
            f"Stop-Loss: ${stop_loss:,.4f}\n"
            f"Take-Profit: ${take_profit:,.4f}\n"
            f"Grund: {reason}"
        )
        if explanation:
            tg_msg += f"\n\n🔍 <i>{explanation[:300]}</i>"
        self._telegram(tg_msg)
        self._discord_trade("BUY", symbol, price, reason=reason)
        self._webhook_event("trade_opened", symbol, {
            "price": price, "quantity": quantity, "stop_loss": stop_loss,
            "take_profit": take_profit, "reason": reason,
        })

    def send_trade_closed(
        self,
        symbol:     str,
        exit_price: float,
        pnl:        float,
        pnl_pct:    float,
        reason:     str,
        capital:    float,
        explanation: str = "",
    ) -> None:
        icon  = "✅" if pnl >= 0 else "🔴"
        tg_msg = (
            f"{icon} <b>VERKAUF {symbol}</b>\n"
            f"Preis: <b>${exit_price:,.4f}</b>\n"
            f"PnL: <b>{pnl:+.2f} USDT ({pnl_pct:+.2f}%)</b>\n"
            f"Grund: {reason}\n"
            f"Kapital: ${capital:,.2f}"
        )
        if explanation:
            tg_msg += f"\n\n🔍 <i>{explanation[:300]}</i>"
        self._telegram(tg_msg)
        self._discord_trade("SELL", symbol, exit_price, pnl=pnl, reason=reason, capital=capital)
        self._webhook_event("trade_closed", symbol, {
            "exit_price": exit_price, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason,
        })

    def send_alert(
        self,
        message: str,
        title:   str  = "",
        level:   str  = "info",   # info | warning | error | critical
        symbol:  str  = "",
    ) -> None:
        """Generic alert to all channels."""
        self._telegram(message)
        _colors = {"info": 0x0088FF, "warning": 0xFFAA00, "error": 0xFF4444, "critical": 0xFF0000}
        self._discord_embed(message, title, _colors.get(level, 0x0088FF))
        self._webhook_event("alert", symbol or "bot", {"message": message, "level": level, "title": title})

    def send_daily_summary(self, symbol: str, capital: float, daily_pnl: float, total_trades: int) -> None:
        icon  = "📈" if daily_pnl >= 0 else "📉"
        msg   = (
            f"{icon} <b>Tagesbericht {symbol}</b>\n"
            f"Tages-PnL: <b>{daily_pnl:+.2f} USDT</b>\n"
            f"Trades heute: {total_trades}\n"
            f"Kapital: ${capital:,.2f}"
        )
        self._telegram(msg)
        self._discord_embed(
            f"Tages-PnL: **{daily_pnl:+.2f} USDT** | Trades: {total_trades} | Kapital: ${capital:,.2f}",
            f"{icon} Tagesbericht {symbol}",
            0x00FF88 if daily_pnl >= 0 else 0xFF4444,
        )
        self._webhook_event("daily_summary", symbol, {
            "capital": capital, "daily_pnl": daily_pnl, "trades": total_trades,
        })

    def test_all_channels(self) -> dict[str, bool]:
        """Testet alle konfigurierten Kanäle. Gibt {channel: success} zurück."""
        results: dict[str, bool] = {}

        results["telegram"] = bool(self._tg_token and self._tg_chat and
            self._telegram("🔔 Trading Bot — Telegram Test OK"))

        if self._discord_url:
            from crypto_bot.rpc.discord import send_discord
            results["discord"] = send_discord(self._discord_url, "🔔 Trading Bot — Discord Test OK", title="Test")
        else:
            results["discord"] = False

        if self._webhook_url:
            from crypto_bot.rpc.webhook import send_webhook, build_event
            results["webhook"] = send_webhook(
                self._webhook_url,
                build_event("test", "bot", {"message": "Webhook Test OK"}),
                self._webhook_secret,
            )
        else:
            results["webhook"] = False

        return results

    # ── Private Low-Level ─────────────────────────────────────────────────────

    def _telegram(self, message: str) -> bool:
        if not self._tg_token or not self._tg_chat:
            return False
        try:
            from crypto_bot.monitoring.alerts import _send_telegram
            return _send_telegram(message)
        except Exception as e:
            log.debug(f"Telegram: {e}")
            return False

    def _discord_embed(self, message: str, title: str, color: int) -> bool:
        if not self._discord_url:
            return False
        try:
            from crypto_bot.rpc.discord import send_discord
            return send_discord(self._discord_url, message, title=title, color=color)
        except Exception as e:
            log.debug(f"Discord: {e}")
            return False

    def _discord_trade(self, side: str, symbol: str, price: float, **kwargs) -> bool:
        if not self._discord_url:
            return False
        try:
            from crypto_bot.rpc.discord import send_trade_embed
            return send_trade_embed(self._discord_url, side, symbol, price, **kwargs)
        except Exception as e:
            log.debug(f"Discord trade: {e}")
            return False

    def _webhook_event(self, event: str, symbol: str, data: dict) -> bool:
        if not self._webhook_url:
            return False
        try:
            from crypto_bot.rpc.webhook import send_webhook, build_event
            return send_webhook(
                self._webhook_url,
                build_event(event, symbol, data),
                self._webhook_secret,
            )
        except Exception as e:
            log.debug(f"Webhook: {e}")
            return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_rpc: Optional[RPCManager] = None


def get_rpc() -> RPCManager:
    """Singleton-Accessor für den globalen RPCManager."""
    global _rpc
    if _rpc is None:
        _rpc = RPCManager()
    return _rpc


def reset_rpc() -> None:
    """Singleton zurücksetzen (nach Konfigurationsänderungen)."""
    global _rpc
    _rpc = None
