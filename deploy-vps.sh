#!/bin/bash
# ── Trading Bot → VPS Deployment ──────────────────────────────────────────────
# Verwendung:
#   bash deploy-vps.sh user@vps-ip
#   bash deploy-vps.sh user@vps-ip /opt/trading_bot
#
# Was passiert:
#   1. Code via rsync übertragen
#   2. .env Dateien übertragen
#   3. SSH: Docker Image bauen (keine QNAP-Einschränkungen, voller RAM/CPU)
#   4. Alle Container starten (Bot + Dashboard + Forex Bot + Streamlit)
#
# Unterschied zu QNAP:
#   - Kein --only-binary für arch (volle Kompilierung möglich)
#   - Mehr RAM: Trading Bot 2GB, Forex Bot 512MB
#   - GPU optional: --gpus=all wenn nvidia-docker installiert
#   - Kein QNAP-spezifischer Docker-Pfad

set -e

VPS_HOST="${1:-}"
REMOTE_DIR="${2:-/opt/trading_bot}"

G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[1m"; X="\033[0m"

if [ -z "$VPS_HOST" ]; then
    echo -e "${R}Verwendung: bash deploy-vps.sh user@<VPS-IP> [remote-pfad]${X}"
    echo -e "  Beispiel:  bash deploy-vps.sh ubuntu@123.456.789.0"
    exit 1
fi

echo -e "\n${B}══════════════════════════════════════════════════${X}"
echo -e "${B}   Trading Bot → VPS Deployment${X}"
echo -e "${B}   Host: $VPS_HOST${X}"
echo -e "${B}══════════════════════════════════════════════════${X}\n"

# ── 1. Code übertragen ────────────────────────────────────────────────────────
echo -e "${B}[1/4] Code übertragen nach $VPS_HOST:$REMOTE_DIR ...${X}"
rsync -avz --progress \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='data_store/*.db' \
    --exclude='logs/*' \
    --exclude='reports/*' \
    --filter=':- .gitignore' \
    . "$VPS_HOST:$REMOTE_DIR/"
echo -e "  ${G}✓${X} Code übertragen"

# ── 2. .env Dateien übertragen ────────────────────────────────────────────────
if [ -f ".env" ]; then
    rsync -az .env "$VPS_HOST:$REMOTE_DIR/.env"
    echo -e "  ${G}✓${X} Crypto .env übertragen"
fi

if [ -f "forex_bot/.env" ]; then
    ssh "$VPS_HOST" "mkdir -p '$REMOTE_DIR/forex_bot'"
    rsync -az forex_bot/.env "$VPS_HOST:$REMOTE_DIR/forex_bot/.env"
    echo -e "  ${G}✓${X} Forex .env übertragen"
else
    echo -e "  ${Y}⚠  Keine forex_bot/.env — Forex Bot wird nicht gestartet${X}"
fi

# ── 3. Container neu starten ──────────────────────────────────────────────────
echo -e "\n${B}[3/4] Container auf VPS starten...${X}"
ssh "$VPS_HOST" "
    set -e
    cd '$REMOTE_DIR'

    # Verzeichnisse anlegen
    mkdir -p data_store logs reports crypto_bot/ai shared
    mkdir -p forex_bot/data_store forex_bot/logs

    # Alte Container stoppen
    docker stop trading-bot trading-dashboard trading-streamlit \
                forex-bot forex-dashboard 2>/dev/null || true
    docker rm   trading-bot trading-dashboard trading-streamlit \
                forex-bot forex-dashboard 2>/dev/null || true

    # Image neu bauen (VPS: volle Ressourcen, kein QNAP-Limit)
    docker build -f Dockerfile.qnap -t trading-bot:latest .

    # ── Crypto Bot ────────────────────────────────────────────────────────────
    docker run -d \
        --name trading-bot \
        --restart unless-stopped \
        --env-file .env \
        -e FEATURE_LSTM=false \
        -e AUTO_TRAIN=true \
        -e SHARED_EXPOSURE_PATH=/app/shared/trading_shared_exposure.json \
        -v '$REMOTE_DIR/data_store':/app/data_store \
        -v '$REMOTE_DIR/logs':/app/logs \
        -v '$REMOTE_DIR/reports':/app/reports \
        -v '$REMOTE_DIR/crypto_bot/ai':/app/crypto_bot/ai \
        -v '$REMOTE_DIR/crypto_bot':/app/crypto_bot \
        -v '$REMOTE_DIR/shared':/app/shared \
        --memory=2g \
        --cpus=2.0 \
        --log-driver json-file \
        --log-opt max-size=20m \
        --log-opt max-file=5 \
        trading-bot:latest

    # ── Dashboard API ─────────────────────────────────────────────────────────
    docker run -d \
        --name trading-dashboard \
        --restart unless-stopped \
        --env-file .env \
        -p 8000:8000 \
        -v '$REMOTE_DIR/data_store':/app/data_store \
        -v '$REMOTE_DIR/logs':/app/logs \
        -v '$REMOTE_DIR/crypto_bot/ai':/app/crypto_bot/ai \
        -v '$REMOTE_DIR/crypto_bot':/app/crypto_bot \
        --memory=512m \
        --cpus=1.0 \
        --log-driver json-file \
        --log-opt max-size=10m \
        --log-opt max-file=3 \
        trading-bot:latest \
        python -m uvicorn crypto_bot.dashboard.api:app --host 0.0.0.0 --port 8000

    # ── Streamlit UI ──────────────────────────────────────────────────────────
    docker run -d \
        --name trading-streamlit \
        --restart unless-stopped \
        --env-file .env \
        -p 8501:8501 \
        -v '$REMOTE_DIR/data_store':/app/data_store \
        -v '$REMOTE_DIR/logs':/app/logs \
        -v '$REMOTE_DIR/crypto_bot':/app/crypto_bot \
        --memory=512m \
        --cpus=1.0 \
        --log-driver json-file \
        --log-opt max-size=10m \
        --log-opt max-file=3 \
        trading-bot:latest \
        python -m streamlit run crypto_bot/dashboard/app.py \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.headless true \
            --browser.gatherUsageStats false

    # ── Forex Bot ─────────────────────────────────────────────────────────────
    if [ -f '$REMOTE_DIR/forex_bot/.env' ]; then
        docker run -d \
            --name forex-bot \
            --restart unless-stopped \
            --env-file '$REMOTE_DIR/forex_bot/.env' \
            -e SHARED_EXPOSURE_PATH=/app/shared/trading_shared_exposure.json \
            -v '$REMOTE_DIR/forex_bot':/app/forex_bot \
            -v '$REMOTE_DIR/shared':/app/shared \
            --memory=512m \
            --cpus=1.0 \
            --log-driver json-file \
            --log-opt max-size=10m \
            --log-opt max-file=3 \
            trading-bot:latest \
            python -m forex_bot.bot

        docker run -d \
            --name forex-dashboard \
            --restart unless-stopped \
            --env-file '$REMOTE_DIR/forex_bot/.env' \
            -p 8001:8001 \
            -v '$REMOTE_DIR/forex_bot':/app/forex_bot \
            --memory=256m \
            --cpus=0.5 \
            --log-driver json-file \
            --log-opt max-size=10m \
            --log-opt max-file=3 \
            trading-bot:latest \
            python -m uvicorn forex_bot.dashboard.api:app --host 0.0.0.0 --port 8001

        echo '  Forex Bot gestartet'
    fi

    echo 'Alle Container gestartet'
"
echo -e "  ${G}✓${X} Container laufen"

# ── 4. Status anzeigen ────────────────────────────────────────────────────────
echo -e "\n${B}[4/4] Status:${X}"
echo -e "  Crypto API:  ${G}http://${VPS_HOST##*@}:8000${X}"
echo -e "  Forex API:   ${G}http://${VPS_HOST##*@}:8001${X}"
echo -e "  Dashboard:   ${G}http://${VPS_HOST##*@}:8501${X}"
echo -e ""
echo -e "  Live-Logs:"
echo -e "    Crypto:  ssh $VPS_HOST 'docker logs -f trading-bot'"
echo -e "    Forex:   ssh $VPS_HOST 'docker logs -f forex-bot'"
echo -e ""
ssh "$VPS_HOST" "docker logs --tail 20 trading-bot 2>/dev/null || true"
