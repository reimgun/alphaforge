#!/bin/bash
# ── Forex Bot → QNAP TS-451 ───────────────────────────────────────────────────
# Kein Image-Rebuild — nutzt bestehendes trading-bot:qnap Image.
# Image neu bauen: bash deploy-image.sh admin@<IP>
#
# Verwendung:
#   bash deploy-forex.sh admin@YOUR_QNAP_IP

set -e
QNAP_HOST="${1:-}"
REMOTE_DIR="${2:-/share/CACHEDEV1_DATA/trading_bot}"

G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[1m"; X="\033[0m"

[ -z "$QNAP_HOST" ] && { echo -e "${R}Verwendung: bash deploy-forex.sh admin@<IP>${X}"; exit 1; }

echo -e "\n${B}══════════════════════════════════════════════════${X}"
echo -e "${B}   Forex Bot → QNAP Deployment${X}"
echo -e "${B}══════════════════════════════════════════════════${X}\n"

# ── 1. .env prüfen ────────────────────────────────────────────────────────────
echo -e "${B}[1/3] Konfiguration prüfen...${X}"
if [ ! -f "forex_bot/.env" ]; then
    echo -e "${R}  ✗  forex_bot/.env fehlt — bitte erstellen:${X}"
    echo -e "     cp forex_bot/.env.example forex_bot/.env"
    exit 1
fi
echo -e "  ${G}✓${X} forex_bot/.env vorhanden"

# ── 2. Code + .env übertragen ─────────────────────────────────────────────────
echo -e "\n${B}[2/3] Code übertragen...${X}"
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='**/.env' --exclude='data_store/*.db' \
    --exclude='logs/*' --exclude='reports/*' --filter=':- .gitignore' \
    . "$QNAP_HOST:$REMOTE_DIR/"

ssh "$QNAP_HOST" "mkdir -p '$REMOTE_DIR/forex_bot'"
rsync -az forex_bot/.env "$QNAP_HOST:$REMOTE_DIR/forex_bot/.env"
echo -e "  ${G}✓${X} Code + forex_bot/.env übertragen"

# ── 3. Nur Forex-Container neu starten ───────────────────────────────────────
echo -e "\n${B}[3/3] Forex-Container starten...${X}"
ssh "$QNAP_HOST" "
    set -e
    DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
    REMOTE_DIR='$REMOTE_DIR'

    mkdir -p \$REMOTE_DIR/forex_bot/data_store \$REMOTE_DIR/forex_bot/logs \
             \$REMOTE_DIR/forex_bot/ai \$REMOTE_DIR/shared
    chmod -R 777 \$REMOTE_DIR/forex_bot/data_store \$REMOTE_DIR/forex_bot/logs \
                 \$REMOTE_DIR/forex_bot/ai 2>/dev/null || true

    # forex-dashboard war ein eigener Container ohne bot_state-Zugriff — konsolidiert in forex-bot
    \$DOCKER stop  forex-bot forex-dashboard 2>/dev/null || true
    \$DOCKER rm    forex-bot forex-dashboard 2>/dev/null || true

    \$DOCKER run -d --name forex-bot --restart unless-stopped \
        -p 8001:8001 \
        -v \$REMOTE_DIR/forex_bot:/app/forex_bot \
        -v \$REMOTE_DIR/shared:/app/shared \
        --memory=768m --cpus=1.0 \
        --log-driver json-file --log-opt max-size=5m --log-opt max-file=3 \
        --health-cmd 'curl -sf http://localhost:8001/health || exit 1' \
        --health-interval 30s --health-timeout 5s --health-retries 3 --health-start-period 30s \
        trading-bot:qnap python -m forex_bot.bot

    \$DOCKER network connect trading_bot_default forex-bot 2>/dev/null || true
    echo 'Forex-Container gestartet'
"
echo -e "  ${G}✓${X} Forex-Container laufen"
echo -e "\n  Forex API: ${G}http://${QNAP_HOST##*@}:8001${X}"
echo -e "  Logs:      make forex-logs QNAP=$QNAP_HOST\n"
