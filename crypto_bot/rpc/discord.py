"""
Discord Webhook Alerting.

Konfiguration:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
    FEATURE_DISCORD_RPC=true

Discord Webhook erstellen:
    Server → Einstellungen → Integrationen → Webhooks → Webhook erstellen → URL kopieren
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("trading_bot")

# Discord Embed-Farben
COLOR_GREEN  = 0x00FF88
COLOR_RED    = 0xFF4444
COLOR_YELLOW = 0xFFAA00
COLOR_BLUE   = 0x0088FF
COLOR_GREY   = 0x888888


def send_discord(
    webhook_url: str,
    message:     str,
    title:       str  = "",
    color:       int  = COLOR_BLUE,
    fields:      list[dict] | None = None,
    retries:     int  = 2,
) -> bool:
    """
    Sendet Nachricht via Discord Webhook.

    Args:
        webhook_url: Discord Webhook URL
        message:     Nachricht (Embed description)
        title:       Embed-Titel (optional)
        color:       Embed-Farbe (Hex-Integer)
        fields:      Zusätzliche Felder [{"name": "...", "value": "...", "inline": True}]
        retries:     Anzahl Wiederholungsversuche bei Rate-Limit

    Returns:
        True wenn erfolgreich
    """
    if not webhook_url:
        return False

    embed: dict = {"description": message, "color": color}
    if title:
        embed["title"] = title
    if fields:
        embed["fields"] = fields

    payload = {"embeds": [embed]}

    for attempt in range(retries + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                return True
            if resp.status_code == 429 and attempt < retries:
                # Rate-Limit: retry_after in Sekunden
                retry_after = float(resp.json().get("retry_after", 5))
                time.sleep(min(retry_after, 30))
                continue
            log.warning(f"Discord HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except Exception as e:
            log.warning(f"Discord-Fehler: {e}")
            return False
    return False


def send_trade_embed(
    webhook_url: str,
    side:        str,   # "BUY" | "SELL"
    symbol:      str,
    price:       float,
    pnl:         float  = 0.0,
    reason:      str    = "",
    capital:     float  = 0.0,
) -> bool:
    """Vorgefertigtes Trade-Embed für BUY/SELL Events."""
    if side == "BUY":
        title = f"🟢 BUY — {symbol}"
        color = COLOR_GREEN
        msg   = f"**Preis:** ${price:,.4f}"
    else:
        icon  = "✅" if pnl >= 0 else "🔴"
        title = f"{icon} SELL — {symbol}"
        color = COLOR_GREEN if pnl >= 0 else COLOR_RED
        msg   = f"**Preis:** ${price:,.4f}\n**PnL:** {pnl:+.2f} USDT"

    fields = []
    if reason:
        fields.append({"name": "Grund", "value": reason, "inline": True})
    if capital:
        fields.append({"name": "Kapital", "value": f"${capital:,.2f}", "inline": True})

    return send_discord(webhook_url, msg, title=title, color=color, fields=fields)
