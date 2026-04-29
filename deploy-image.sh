#!/bin/bash
# ── Docker Image auf QNAP bauen ───────────────────────────────────────────────
# Verwendung:  bash deploy-image.sh admin@YOUR_QNAP_IP
# Wird von deploy-crypto.sh automatisch aufgerufen.
# Direkt aufrufen wenn nur das Image neu gebaut werden soll.

set -e
QNAP_HOST="${1:-}"
REMOTE_DIR="${2:-/share/CACHEDEV1_DATA/trading_bot}"
G="\033[92m"; B="\033[1m"; R="\033[91m"; X="\033[0m"

[ -z "$QNAP_HOST" ] && { echo -e "${R}Verwendung: bash deploy-image.sh admin@<IP>${X}"; exit 1; }

echo -e "\n${B}Docker Image bauen (trading-bot:qnap)...${X}"
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.env' --exclude='data_store/*.db' \
    --exclude='logs/*' --exclude='reports/*' --filter=':- .gitignore' \
    . "$QNAP_HOST:$REMOTE_DIR/"

ssh "$QNAP_HOST" "
    DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
    cd '$REMOTE_DIR'
    \$DOCKER build -f Dockerfile.qnap -t trading-bot:qnap . 2>&1 | tail -5
    echo 'Image gebaut: trading-bot:qnap'
"
echo -e "  ${G}✓${X} Image fertig"
