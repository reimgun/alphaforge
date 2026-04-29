#!/bin/bash
# ── Crypto Bot → QNAP TS-451 ──────────────────────────────────────────────────
# Verwendung:
#   bash deploy-crypto.sh admin@YOUR_QNAP_IP
#   bash deploy-crypto.sh admin@YOUR_QNAP_IP --no-rebuild   # Image überspringen

set -e
QNAP_HOST="${1:-}"
NO_REBUILD=0
REMOTE_DIR="/share/CACHEDEV1_DATA/trading_bot"
for arg in "$@"; do
    [ "$arg" = "--no-rebuild" ] && NO_REBUILD=1
    [[ "$arg" == /share/* ]] && REMOTE_DIR="$arg"
done

G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[1m"; X="\033[0m"

if [ -z "$PYTHON" ]; then
    [ -f ".venv/bin/python" ] && PYTHON=".venv/bin/python" || PYTHON="python3"
fi
[ -z "$QNAP_HOST" ] && { echo -e "${R}Verwendung: bash deploy-crypto.sh admin@<IP> [--no-rebuild]${X}"; exit 1; }

echo -e "\n${B}══════════════════════════════════════════════════${X}"
echo -e "${B}   Crypto Bot → QNAP Deployment${X}"
echo -e "${B}══════════════════════════════════════════════════${X}\n"

# ── 1. ML-Modell prüfen ───────────────────────────────────────────────────────
echo -e "${B}[1/4] ML-Modell prüfen...${X}"
if [ ! -f "crypto_bot/ai/model.joblib" ]; then
    echo -e "${Y}  ⚠  Kein Modell — starte Training...${X}"
    $PYTHON -m crypto_bot.ai.trainer || { echo -e "${R}  ✗  Training fehlgeschlagen${X}"; exit 1; }
fi
echo -e "  ${G}✓${X} Modell: $(du -h crypto_bot/ai/model.joblib | cut -f1)"

# ── 2. Code + .env übertragen ─────────────────────────────────────────────────
echo -e "\n${B}[2/4] Code übertragen...${X}"
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.env' --exclude='data_store/*.db' \
    --exclude='logs/*' --exclude='reports/*' --filter=':- .gitignore' \
    . "$QNAP_HOST:$REMOTE_DIR/"

if [ -f ".env" ]; then
    rsync -az .env "$QNAP_HOST:$REMOTE_DIR/.env"
    echo -e "  ${G}✓${X} .env übertragen"
else
    echo -e "  ${Y}⚠  Keine .env gefunden — Vorlage: .env.example${X}"
fi
echo -e "  ${G}✓${X} Code übertragen"

# ── 3. Image bauen (optional überspringen) ────────────────────────────────────
if [ "$NO_REBUILD" = "0" ]; then
    echo -e "\n${B}[3/4] Docker Image bauen...${X}"
    ssh "$QNAP_HOST" "
        DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
        cd '$REMOTE_DIR'
        \$DOCKER build -f Dockerfile.qnap -t crypto-bot:qnap . 2>&1 | tail -3
    "
    echo -e "  ${G}✓${X} Image gebaut"
else
    echo -e "\n${B}[3/4] Image-Rebuild übersprungen (--no-rebuild)${X}"
fi

# ── 4. Nur Crypto-Container neu starten ───────────────────────────────────────
echo -e "\n${B}[4/4] Crypto-Container starten...${X}"
ssh "$QNAP_HOST" "
    set -e
    DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
    REMOTE_DIR='$REMOTE_DIR'

    mkdir -p \$REMOTE_DIR/data_store \$REMOTE_DIR/logs \$REMOTE_DIR/reports \
             \$REMOTE_DIR/crypto_bot/ai \$REMOTE_DIR/shared

    \$DOCKER stop  crypto-bot trading-bot trading-dashboard trading-streamlit 2>/dev/null || true
    \$DOCKER rm    crypto-bot trading-bot trading-dashboard trading-streamlit 2>/dev/null || true

    \$DOCKER run -d --name crypto-bot --restart unless-stopped \
        -e FEATURE_LSTM=false -e AUTO_TRAIN=false \
        -v \$REMOTE_DIR/.env:/app/.env:ro \
        -v \$REMOTE_DIR/data_store:/app/data_store \
        -v \$REMOTE_DIR/logs:/app/logs \
        -v \$REMOTE_DIR/reports:/app/reports \
        -v \$REMOTE_DIR/crypto_bot/ai:/app/crypto_bot/ai \
        -v \$REMOTE_DIR/crypto_bot:/app/crypto_bot \
        -v \$REMOTE_DIR/shared:/app/shared \
        --memory=1500m --cpus=2.0 \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=5 \
        --health-cmd 'find /app/logs/bot.log -mmin -10 | grep -q . || exit 1' \
        --health-interval 60s --health-timeout 10s --health-retries 3 --health-start-period 120s \
        crypto-bot:qnap

    \$DOCKER run -d --name trading-dashboard --restart unless-stopped \
        -p 8000:8000 \
        -v \$REMOTE_DIR/.env:/app/.env:ro \
        -v \$REMOTE_DIR/data_store:/app/data_store \
        -v \$REMOTE_DIR/logs:/app/logs \
        -v \$REMOTE_DIR/crypto_bot/ai:/app/crypto_bot/ai \
        -v \$REMOTE_DIR/crypto_bot:/app/crypto_bot \
        --memory=1024m --memory-swap=2048m --cpus=1.0 \
        --log-driver json-file --log-opt max-size=5m --log-opt max-file=3 \
        --health-cmd 'curl -sf http://localhost:8000/health || exit 1' \
        --health-interval 60s --health-timeout 15s --health-retries 3 --health-start-period 30s \
        crypto-bot:qnap \
        python -m uvicorn crypto_bot.dashboard.api:app --host 0.0.0.0 --port 8000

    \$DOCKER run -d --name trading-streamlit --restart unless-stopped \
        -p 8501:8501 \
        -e DASHBOARD_API_URL=http://trading-dashboard:8000 \
        -e FOREX_API_URL=http://forex-bot:8001 \
        --network trading_bot_default \
        --memory=512m --cpus=1.0 \
        --log-driver json-file --log-opt max-size=5m --log-opt max-file=3 \
        --health-cmd 'curl -sf http://localhost:8501/_stcore/health || exit 1' \
        --health-interval 30s --health-timeout 5s --health-retries 3 --health-start-period 20s \
        trading-streamlit:latest

    \$DOCKER network connect trading_bot_default crypto-bot        2>/dev/null || true
    \$DOCKER network connect trading_bot_default trading-dashboard  2>/dev/null || true
    echo 'Crypto-Container gestartet'
"
echo -e "  ${G}✓${X} Crypto-Container laufen"
echo -e "\n  Crypto API:   ${G}http://${QNAP_HOST##*@}:8000${X}"
echo -e "  Dashboard UI: ${G}http://${QNAP_HOST##*@}:8501${X}"
echo -e "  Logs:         make crypto-logs QNAP=$QNAP_HOST\n"
