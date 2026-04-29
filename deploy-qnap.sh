#!/bin/bash
# ── Trading Bot → QNAP TS-451 Deployment ──────────────────────────────────────
# Verwendung:
#   bash deploy-qnap.sh admin@192.168.1.100
#   bash deploy-qnap.sh admin@192.168.1.100 /share/trading_bot
#
# Was passiert:
#   1. Prüft ob trainiertes Modell vorhanden ist
#   2. Überträgt Code + Modell via rsync (git-ignored Files bleiben lokal)
#   3. SSH: Container neu bauen und starten
#   4. Zeigt Live-Logs zur Bestätigung

set -e

# ── Parameter ─────────────────────────────────────────────────────────────────
QNAP_HOST="${1:-}"
REMOTE_DIR="${2:-/share/CACHEDEV1_DATA/trading_bot}"

G="\033[92m"; Y="\033[93m"; R="\033[91m"; B="\033[1m"; X="\033[0m"

# Python-Interpreter ermitteln: vom Makefile übergeben > venv > system
if [ -z "$PYTHON" ]; then
    if [ -f ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="python3"
    fi
fi

if [ -z "$QNAP_HOST" ]; then
    echo -e "${R}Verwendung: bash deploy-qnap.sh admin@<QNAP-IP> [remote-pfad]${X}"
    echo -e "  Beispiel:  bash deploy-qnap.sh admin@192.168.1.100"
    exit 1
fi

echo -e "\n${B}══════════════════════════════════════════════════${X}"
echo -e "${B}   Trading Bot → QNAP TS-451 Deployment${X}"
echo -e "${B}══════════════════════════════════════════════════${X}\n"

# ── 1. Trainiertes Modell prüfen ──────────────────────────────────────────────
echo -e "${B}[1/4] ML-Modell prüfen...${X}"
if [ ! -f "crypto_bot/ai/model.joblib" ]; then
    echo -e "${Y}  ⚠  Kein trainiertes Modell gefunden (crypto_bot/ai/model.joblib)${X}"
    echo -e "     Modell wird jetzt trainiert (dauert 3-5 Minuten)..."
    $PYTHON -m crypto_bot.ai.trainer || {
        echo -e "${R}  ✗  Training fehlgeschlagen. Bitte manuell trainieren: make train${X}"
        exit 1
    }
fi
echo -e "  ${G}✓${X} Modell vorhanden: $(du -h crypto_bot/ai/model.joblib | cut -f1)"

# ── 2. Code sync via rsync ────────────────────────────────────────────────────
echo -e "\n${B}[2/4] Code übertragen nach $QNAP_HOST:$REMOTE_DIR ...${X}"
rsync -avz --progress \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='data_store/*.db' \
    --exclude='logs/*' \
    --exclude='reports/*' \
    --exclude='.env.encrypted' \
    --filter=':- .gitignore' \
    . "$QNAP_HOST:$REMOTE_DIR/"
echo -e "  ${G}✓${X} Übertragung abgeschlossen"

# ── 3. .env Dateien übertragen ────────────────────────────────────────────────
if [ -f ".env" ]; then
    echo -e "\n${B}  Crypto .env übertragen...${X}"
    rsync -az .env "$QNAP_HOST:$REMOTE_DIR/.env"
    echo -e "  ${G}✓${X} Crypto .env übertragen"
else
    echo -e "\n  ${Y}⚠  Keine .env (Crypto) gefunden — bitte manuell auf QNAP erstellen${X}"
    echo -e "     Vorlage: $REMOTE_DIR/.env.example"
fi

if [ -f "forex_bot/.env" ]; then
    echo -e "\n${B}  Forex .env übertragen...${X}"
    ssh "$QNAP_HOST" "mkdir -p '$REMOTE_DIR/forex_bot'"
    rsync -az forex_bot/.env "$QNAP_HOST:$REMOTE_DIR/forex_bot/.env"
    echo -e "  ${G}✓${X} Forex .env übertragen"
else
    echo -e "\n  ${Y}⚠  Keine forex_bot/.env gefunden — Forex Bot wird auf QNAP nicht gestartet${X}"
    echo -e "     Erstellen: cp forex_bot/.env.example forex_bot/.env  (dann ausfüllen)"
    echo -e "     Danach:    make qnap-deploy  (erneut ausführen)"
fi

# ── 4. Container neu starten ──────────────────────────────────────────────────
echo -e "\n${B}[3/4] Container auf QNAP neu starten...${X}"
ssh "$QNAP_HOST" "
    set -e
    DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker
    cd '$REMOTE_DIR'

    # Verzeichnisse anlegen (idempotent)
    mkdir -p '$REMOTE_DIR/shared'

    # Alte Container stoppen und entfernen (falls vorhanden)
    \$DOCKER stop trading-bot trading-dashboard trading-streamlit \
                 forex-bot forex-dashboard 2>/dev/null || true
    \$DOCKER rm   trading-bot trading-dashboard trading-streamlit \
                 forex-bot forex-dashboard 2>/dev/null || true

    # Image neu bauen
    \$DOCKER build -f Dockerfile.qnap -t trading-bot:qnap .

    # Bot starten
    \$DOCKER run -d \
        --name trading-bot \
        --restart unless-stopped \
        --env-file .env \
        -e FEATURE_LSTM=false \
        -e AUTO_TRAIN=false \
        -e SHARED_EXPOSURE_PATH=/app/shared/trading_shared_exposure.json \
        -v '$REMOTE_DIR/data_store':/app/data_store \
        -v '$REMOTE_DIR/logs':/app/logs \
        -v '$REMOTE_DIR/reports':/app/reports \
        -v '$REMOTE_DIR/crypto_bot/ai':/app/crypto_bot/ai \
        -v '$REMOTE_DIR/crypto_bot':/app/crypto_bot \
        -v '$REMOTE_DIR/shared':/app/shared \
        --memory=1500m \
        --cpus=2.0 \
        --log-driver json-file \
        --log-opt max-size=10m \
        --log-opt max-file=5 \
        trading-bot:qnap

    # Dashboard API starten (Port 8000 — REST API + Swagger)
    \$DOCKER run -d \
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
        --log-opt max-size=5m \
        --log-opt max-file=3 \
        trading-bot:qnap \
        python -m uvicorn crypto_bot.dashboard.api:app --host 0.0.0.0 --port 8000

    # Streamlit UI starten (Port 8501 — Web-Dashboard für Crypto + Forex)
    \$DOCKER run -d \
        --name trading-streamlit \
        --restart unless-stopped \
        --env-file .env \
        -p 8501:8501 \
        -e DASHBOARD_API_URL=http://YOUR_QNAP_IP:8000 \
        -e FOREX_API_URL=http://YOUR_QNAP_IP:8001 \
        -v '$REMOTE_DIR/data_store':/app/data_store \
        -v '$REMOTE_DIR/logs':/app/logs \
        -v '$REMOTE_DIR/crypto_bot':/app/crypto_bot \
        --memory=512m \
        --cpus=1.0 \
        --log-driver json-file \
        --log-opt max-size=5m \
        --log-opt max-file=3 \
        trading-bot:qnap \
        python -m streamlit run crypto_bot/dashboard/app.py \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.headless true \
            --browser.gatherUsageStats false

    # ── Forex Bot (läuft nur wenn forex_bot/.env vorhanden) ──────────────────
    if [ -f '$REMOTE_DIR/forex_bot/.env' ]; then
        echo '  Forex .env gefunden — starte Forex Bot...'

        # Forex Bot (Port intern, kein direkter Zugriff nötig)
        \$DOCKER run -d \
            --name forex-bot \
            --restart unless-stopped \
            --env-file '$REMOTE_DIR/forex_bot/.env' \
            -e SHARED_EXPOSURE_PATH=/app/shared/trading_shared_exposure.json \
            -v '$REMOTE_DIR/forex_bot':/app/forex_bot \
            -v '$REMOTE_DIR/shared':/app/shared \
            --memory=256m \
            --cpus=0.5 \
            --log-driver json-file \
            --log-opt max-size=5m \
            --log-opt max-file=3 \
            trading-bot:qnap \
            python -m forex_bot.bot

        # Forex Dashboard API (Port 8001)
        \$DOCKER run -d \
            --name forex-dashboard \
            --restart unless-stopped \
            --env-file '$REMOTE_DIR/forex_bot/.env' \
            -p 8001:8001 \
            -v '$REMOTE_DIR/forex_bot':/app/forex_bot \
            --memory=128m \
            --cpus=0.5 \
            --log-driver json-file \
            --log-opt max-size=5m \
            --log-opt max-file=3 \
            trading-bot:qnap \
            python -m uvicorn forex_bot.dashboard.api:app --host 0.0.0.0 --port 8001

        echo '  Forex Bot gestartet (Port 8001)'
    else
        echo '  Kein forex_bot/.env gefunden — Forex Bot übersprungen'
        echo '  Zum Aktivieren: scp forex_bot/.env admin@<IP>:/share/CACHEDEV1_DATA/trading_bot/forex_bot/.env'
    fi

    echo 'Container gestartet'
"
echo -e "  ${G}✓${X} Container läuft"

# ── 5. Live-Logs anzeigen ─────────────────────────────────────────────────────
echo -e "\n${B}[4/4] Live-Logs (Strg+C zum Beenden):${X}"
echo -e "  Dashboard UI:    ${G}http://${QNAP_HOST##*@}:8501${X}   (Crypto + Forex Toggle)"
echo -e "  Crypto API:      ${G}http://${QNAP_HOST##*@}:8000${X}   (REST + Swagger /docs)"
echo -e "  Forex API:       ${G}http://${QNAP_HOST##*@}:8001${X}   (REST + Swagger /docs)"
echo -e "  Crypto Logs:     ${G}ssh $QNAP_HOST 'docker logs -f trading-bot'${X}"
echo -e "  Forex Logs:      ${G}ssh $QNAP_HOST 'docker logs -f forex-bot'${X}\n"
ssh "$QNAP_HOST" "docker logs -f trading-bot" 2>/dev/null || true
