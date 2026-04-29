"""
VPS Auto-Failover — NAS → VPS automatischer Umschalter.

Wenn die lokale Bot-Instanz (NAS) nicht mehr erreichbar ist,
startet dieses Script den Bot automatisch auf dem konfigurierten VPS.

Ablauf:
  1. Ping-Check: HTTP GET auf localhost:FOREX_API_PORT/health
  2. Bei N aufeinanderfolgenden Fehlern → VPS-Failover auslösen
  3. VPS-Failover: SSH-Befehl via subprocess
  4. Telegram-Benachrichtigung
  5. Cooldown: Kein erneuter Failover für COOLDOWN_MINUTES

Konfiguration (via ENV):
  FAILOVER_VPS_HOST:    VPS IP/Hostname
  FAILOVER_VPS_USER:    SSH-Benutzername
  FAILOVER_VPS_KEY:     Pfad zum SSH-Private-Key
  FAILOVER_VPS_CMD:     Befehl auf VPS (z.B. "cd /opt/trading_bot && docker compose up -d")
  FAILOVER_MAX_FAILS:   Anzahl Fehlversuche vor Failover (default: 3)
  FAILOVER_INTERVAL:    Prüfintervall in Sekunden (default: 60)
  FAILOVER_COOLDOWN:    Cooldown nach Failover in Minuten (default: 30)

Starten (als Daemon):
  python -m forex_bot.scripts.failover
  python -m forex_bot.scripts.failover --once   # Einmalige Prüfung (für Cron)

Auf VPS laufen lassen:
  Cronjob: */1 * * * * python /opt/trading_bot/forex_bot/scripts/failover.py --once >> /var/log/failover.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("failover")

# Konfiguration
VPS_HOST       = os.getenv("FAILOVER_VPS_HOST", "")
VPS_USER       = os.getenv("FAILOVER_VPS_USER", "root")
VPS_KEY        = os.getenv("FAILOVER_VPS_KEY",  "~/.ssh/id_rsa")
VPS_CMD        = os.getenv("FAILOVER_VPS_CMD",  "cd /opt/trading_bot && docker compose up -d forex-bot")
MAX_FAILS      = int(os.getenv("FAILOVER_MAX_FAILS",   "3"))
CHECK_INTERVAL = int(os.getenv("FAILOVER_INTERVAL",    "60"))
COOLDOWN_MIN   = int(os.getenv("FAILOVER_COOLDOWN",    "30"))

# Local API (Dashboard)
try:
    from forex_bot.config import settings as cfg
    LOCAL_PORT = cfg.API_PORT
except Exception:
    LOCAL_PORT = 8001


# ── Health Check ──────────────────────────────────────────────────────────────

def check_local_health(timeout: int = 10) -> bool:
    """Prüft ob lokaler Bot via HTTP erreichbar ist."""
    try:
        import urllib.request
        url = f"http://localhost:{LOCAL_PORT}/health"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        log.debug(f"Health check failed: {e}")
        return False


# ── VPS Failover ──────────────────────────────────────────────────────────────

def trigger_vps_failover() -> bool:
    """
    Startet Bot auf VPS via SSH.

    Returns True bei Erfolg.
    """
    if not VPS_HOST:
        log.error("FAILOVER_VPS_HOST nicht konfiguriert — kein Failover möglich")
        return False

    log.warning(f"Failover: Starte Bot auf VPS {VPS_HOST}...")

    ssh_cmd = [
        "ssh",
        "-i", os.path.expanduser(VPS_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        f"{VPS_USER}@{VPS_HOST}",
        VPS_CMD,
    ]

    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log.info(f"Failover erfolgreich: {result.stdout.strip()[:200]}")
            return True
        else:
            log.error(f"Failover SSH Fehler (rc={result.returncode}): {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Failover SSH Timeout (60s)")
        return False
    except FileNotFoundError:
        log.error("ssh nicht gefunden — OpenSSH installieren")
        return False
    except Exception as e:
        log.error(f"Failover Fehler: {e}")
        return False


def send_telegram_alert(message: str) -> None:
    """Sendet Telegram-Nachricht über Bot-Konfiguration."""
    try:
        from forex_bot.config import settings as cfg
        if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_CHAT_ID:
            return
        import urllib.request, urllib.parse
        url     = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": cfg.TELEGRAM_CHAT_ID,
            "text":    message,
            "parse_mode": "HTML",
        }).encode()
        with urllib.request.urlopen(url, data=payload, timeout=10):
            pass
    except Exception:
        pass


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def run_daemon() -> None:
    """Läuft als Daemon und überwacht lokale Bot-Instanz."""
    log.info(f"Failover Daemon gestartet — prüfe alle {CHECK_INTERVAL}s")
    fail_count       = 0
    last_failover_ts = 0.0
    failover_done    = False

    while True:
        healthy = check_local_health()

        if healthy:
            if fail_count > 0:
                log.info(f"Bot wieder erreichbar nach {fail_count} Fehlversuchen")
            fail_count    = 0
            failover_done = False
        else:
            fail_count += 1
            log.warning(f"Bot nicht erreichbar ({fail_count}/{MAX_FAILS})")

            if fail_count >= MAX_FAILS and not failover_done:
                # Cooldown prüfen
                elapsed = (time.time() - last_failover_ts) / 60
                if elapsed < COOLDOWN_MIN and last_failover_ts > 0:
                    log.info(f"Failover Cooldown noch {COOLDOWN_MIN - elapsed:.0f} Min")
                else:
                    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    send_telegram_alert(
                        f"⚠️ <b>Forex Bot NAS nicht erreichbar!</b>\n"
                        f"Zeit: {ts_str}\n"
                        f"Fehlversuche: {fail_count}\n"
                        f"Starte Failover auf VPS: {VPS_HOST}..."
                    )

                    if trigger_vps_failover():
                        last_failover_ts = time.time()
                        failover_done    = True
                        send_telegram_alert(
                            f"✅ <b>Failover erfolgreich!</b>\n"
                            f"Bot läuft jetzt auf VPS: {VPS_HOST}"
                        )
                    else:
                        send_telegram_alert(
                            f"❌ <b>Failover fehlgeschlagen!</b>\n"
                            f"Manuelle Intervention erforderlich.\n"
                            f"VPS: {VPS_HOST}"
                        )

        time.sleep(CHECK_INTERVAL)


def check_once() -> int:
    """Einmalige Prüfung (für Cron-Job). Returns exit code."""
    healthy = check_local_health()
    if healthy:
        log.info("Bot ist erreichbar — alles OK")
        return 0
    else:
        log.warning("Bot NICHT erreichbar")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forex Bot VPS Failover")
    parser.add_argument("--once", action="store_true", help="Einmalige Prüfung (für Cron)")
    args = parser.parse_args()

    if args.once:
        sys.exit(check_once())
    else:
        try:
            run_daemon()
        except KeyboardInterrupt:
            log.info("Failover Daemon gestoppt")
