"""
Generic HTTP Webhook Alerting.

Kompatibel mit: Grafana Alerting, Slack Incoming Webhooks, PagerDuty,
                Custom Monitoring-Server, n8n / Zapier / Make

Konfiguration:
    WEBHOOK_URL=https://your-server.com/bot-events
    WEBHOOK_SECRET=your-bearer-token   # optional
    FEATURE_WEBHOOK_RPC=true

Payload-Format (JSON):
    {
        "event":     "trade_opened",
        "symbol":    "BTC/USDT",
        "timestamp": "2026-04-24T10:00:00Z",
        "bot":       "crypto_bot",
        "data": {
            "price":   42000.0,
            "signal":  "BUY",
            ...
        }
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger("trading_bot")


def send_webhook(
    url:     str,
    payload: dict,
    secret:  str    = "",
    method:  str    = "POST",
    timeout: int    = 10,
) -> bool:
    """
    Sendet HTTP Webhook mit JSON-Payload.

    Args:
        url:     Ziel-URL
        payload: JSON-serialisierbares Dict
        secret:  Bearer-Token für Authorization-Header (optional)
        method:  HTTP-Methode (POST oder GET)

    Returns:
        True wenn HTTP 2xx
    """
    if not url:
        return False

    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    try:
        resp = requests.request(method, url, json=payload, headers=headers, timeout=timeout)
        if resp.ok:
            return True
        log.warning(f"Webhook HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"Webhook-Fehler: {e}")
        return False


def build_event(event: str, symbol: str, data: dict, bot: str = "crypto_bot") -> dict:
    """Standardisiertes Event-Payload."""
    return {
        "event":     event,
        "symbol":    symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot":       bot,
        "data":      data,
    }
