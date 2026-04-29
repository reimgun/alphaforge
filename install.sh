#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Trading Bot — One-Click Installation & Start (macOS / Linux)
#
# Verwendung:
#   bash install.sh
#
# Beim ersten Mal:  Assistent → installieren → Bot starten
# Beim zweiten Mal: direkt Bot starten (oder Einstellungen ändern)
# ─────────────────────────────────────────────────────────────────

BOLD="\033[1m"; GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"
CYAN="\033[96m"; RESET="\033[0m"

# Absoluter Pfad — funktioniert unabhängig vom Aufruf-Verzeichnis
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
ENV_FILE="$SCRIPT_DIR/.env"

echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo -e "${BOLD}   Trading Bot${RESET}"
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo ""

# ── Bereits installiert? ─────────────────────────────────────────
if [ -f "$VENV_PYTHON" ] && [ -f "$ENV_FILE" ]; then

    # Prüfen ob Pakete vollständig installiert sind
    if ! "$VENV_PYTHON" -c "import rich, ccxt, pandas, xgboost" 2>/dev/null; then
        echo -e "  ${YELLOW}⚠  Pakete unvollständig — installiere nach...${RESET}"
        echo ""
        "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
        echo ""
        echo -e "  ${GREEN}✓  Pakete installiert${RESET}"
    fi

    echo -e "  ${GREEN}✓  Installation gefunden${RESET}"
    echo ""
    echo -e "  ${BOLD}Was möchtest du tun?${RESET}"
    echo ""
    echo "    1)  Bot starten  (Paper-Modus — kein echtes Geld)"
    echo "    2)  Einstellungen ändern  (API-Keys, Kapital, Telegram …)"
    echo "    3)  Beenden"
    echo ""
    printf "  → Auswahl [1]: "
    read -r choice
    choice="${choice:-1}"

    case "$choice" in
        1|"")
            echo ""
            echo -e "  ${CYAN}Bot startet …${RESET}"
            echo ""
            exec "$VENV_PYTHON" -m crypto_bot.bot
            ;;
        2)
            echo ""
            ;;
        3)
            echo ""
            exit 0
            ;;
        *)
            echo ""
            echo -e "  ${CYAN}Bot startet …${RESET}"
            echo ""
            exec "$VENV_PYTHON" -m crypto_bot.bot
            ;;
    esac
fi

# ── Python 3.10+ suchen ──────────────────────────────────────────
PYTHON=""
for cmd in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$cmd" &>/dev/null; then
        ok=$("$cmd" -c "import sys; print('ok' if sys.version_info >= (3,10) else 'old')" 2>/dev/null || echo "err")
        if [ "$ok" = "ok" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}  ✗  Python 3.10+ nicht gefunden.${RESET}"
    echo ""
    echo "  Bitte installieren:"
    echo "    macOS:   brew install python@3.12"
    echo "    Linux:   sudo apt install python3.12"
    echo "    Direkt:  https://python.org/downloads"
    echo ""
    exit 1
fi

echo -e "  ${GREEN}✓  $("$PYTHON" --version)${RESET}"
echo ""

# ── Setup-Assistent starten ──────────────────────────────────────
"$PYTHON" "$SCRIPT_DIR/crypto_bot/setup_wizard.py"
