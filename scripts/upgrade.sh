#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# upgrade.sh — Trading Bot Upgrade-Script
#
# Was es tut:
#   1. Backup: DB + .env + Modelle → backup/YYYY-MM-DD/
#   2. git pull (neuester Code)
#   3. pip install -r requirements.txt (neue Dependencies)
#   4. DB-Schema Migration (additive ALTER TABLE — keine Datenverluste)
#   5. .env: neue Keys aus .env.example ergänzen (bestehende nicht überschreiben)
#   6. Container auf QNAP neu starten (optional, wenn QNAP erreichbar)
#
# Nutzung:
#   bash scripts/upgrade.sh                  # lokal upgraden
#   bash scripts/upgrade.sh admin@192.168.x  # lokal + QNAP-Container neu starten
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

QNAP="${1:-}"
BACKUP_DIR="backup/$(date +%Y-%m-%d_%H-%M-%S)"
DB_PATH="crypto_bot/logs/trades.db"
FOREX_DB="forex_bot/logs/trades.db"
PYTHON="${PYTHON:-.venv/bin/python}"

# Farben
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET} $*"; }
err()  { echo -e "${RED}  ✗${RESET} $*"; }

echo ""
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo -e "${GREEN}   Trading Bot Upgrade${RESET}"
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo ""

# ── 1. Backup ─────────────────────────────────────────────────────────────────
echo "[1/6] Backup erstellen..."
mkdir -p "$BACKUP_DIR"

[ -f "$DB_PATH"   ] && cp "$DB_PATH"   "$BACKUP_DIR/crypto_trades.db"  && ok "Crypto-DB gesichert"
[ -f "$FOREX_DB"  ] && cp "$FOREX_DB"  "$BACKUP_DIR/forex_trades.db"   && ok "Forex-DB gesichert"
[ -f ".env"       ] && cp ".env"       "$BACKUP_DIR/.env.bak"           && ok ".env gesichert"
[ -d "crypto_bot/ai" ] && cp -r crypto_bot/ai/*.joblib "$BACKUP_DIR/" 2>/dev/null && ok "ML-Modelle gesichert" || true
[ -d "forex_bot/ai"  ] && cp forex_bot/ai/*.joblib "$BACKUP_DIR/" 2>/dev/null     && ok "Forex-Modelle gesichert" || true

ok "Backup in: $BACKUP_DIR"

# ── 2. Git Pull ───────────────────────────────────────────────────────────────
echo ""
echo "[2/6] Code aktualisieren (git pull)..."
if git pull --ff-only 2>&1; then
    ok "Code aktuell"
else
    warn "git pull fehlgeschlagen — weiter mit lokaler Version"
fi

# ── 3. Dependencies ───────────────────────────────────────────────────────────
echo ""
echo "[3/6] Python-Packages aktualisieren..."
if [ -f ".venv/bin/pip" ]; then
    .venv/bin/pip install -r requirements.txt -q && ok "Packages installiert"
elif command -v pip3 &>/dev/null; then
    pip3 install -r requirements.txt -q && ok "Packages installiert"
else
    warn "kein pip gefunden — manuell: pip install -r requirements.txt"
fi

# ── 4. DB-Schema Migration ────────────────────────────────────────────────────
echo ""
echo "[4/6] DB-Schema Migration..."
$PYTHON - <<'PYEOF'
import sqlite3, os

def migrate(db_path, migrations):
    if not os.path.exists(db_path):
        print(f"  [skip] {db_path} existiert nicht")
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    # Migrations-Tabelle anlegen falls nicht vorhanden
    cur.execute("CREATE TABLE IF NOT EXISTS _migrations (id TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    applied = {r[0] for r in cur.execute("SELECT id FROM _migrations").fetchall()}
    for mid, sql in migrations.items():
        if mid in applied:
            continue
        try:
            cur.execute(sql)
            cur.execute("INSERT INTO _migrations (id) VALUES (?)", (mid,))
            print(f"  ✓ {os.path.basename(db_path)}: {mid}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                cur.execute("INSERT OR IGNORE INTO _migrations (id) VALUES (?)", (mid,))
            else:
                print(f"  ⚠ {mid}: {e}")
    con.commit()
    con.close()

CRYPTO_MIGRATIONS = {
    "2025_add_fee_column":      "ALTER TABLE trades ADD COLUMN fee REAL DEFAULT 0.0",
    "2025_add_slippage_column": "ALTER TABLE trades ADD COLUMN slippage_bps REAL DEFAULT 0.0",
    "2025_add_strategy_column": "ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT ''",
    "2026_add_tax_year":        "ALTER TABLE trades ADD COLUMN tax_year INTEGER DEFAULT 0",
    "2026_add_signal_source":   "ALTER TABLE trades ADD COLUMN signal_source TEXT DEFAULT ''",
}

FOREX_MIGRATIONS = {
    "2025_add_fee":             "ALTER TABLE trades ADD COLUMN fee REAL DEFAULT 0.0",
    "2026_add_regime":          "ALTER TABLE trades ADD COLUMN regime TEXT DEFAULT ''",
}

migrate("crypto_bot/logs/trades.db",  CRYPTO_MIGRATIONS)
migrate("forex_bot/logs/trades.db",   FOREX_MIGRATIONS)
print("  ✓ Migration abgeschlossen")
PYEOF

# ── 5. .env ergänzen (neue Keys aus .env.example) ────────────────────────────
echo ""
echo "[5/6] .env mit neuen Keys ergänzen..."
if [ -f ".env" ] && [ -f ".env.example" ]; then
    added=0
    while IFS= read -r line; do
        # Nur KEY=default Zeilen (kein Kommentar, kein Leerzeile)
        [[ "$line" =~ ^[A-Z_]+=.* ]] || continue
        key="${line%%=*}"
        # Nur hinzufügen wenn noch nicht in .env
        if ! grep -q "^${key}=" .env 2>/dev/null; then
            echo "$line" >> .env
            ok "Neuer Key: $key"
            ((added++)) || true
        fi
    done < ".env.example"
    [ "$added" -eq 0 ] && ok ".env bereits vollständig" || ok "$added neue Key(s) ergänzt"
else
    warn ".env oder .env.example nicht gefunden — übersprungen"
fi

# ── 6. QNAP Container neu starten ────────────────────────────────────────────
echo ""
echo "[6/6] QNAP Container neu starten..."
if [ -n "$QNAP" ]; then
    DOCKER="/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker"
    if ssh -o ConnectTimeout=5 "$QNAP" "$DOCKER ps -q -f name=crypto-bot" &>/dev/null; then
        ssh "$QNAP" "$DOCKER restart crypto-bot trading-dashboard trading-streamlit forex-bot 2>/dev/null; echo done"
        ok "QNAP Container neu gestartet"
    else
        warn "QNAP nicht erreichbar — Container manuell neu starten"
    fi
else
    warn "Kein QNAP angegeben — übersprungen (make upgrade QNAP=admin@192.168.x.x)"
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo -e "${GREEN}   Upgrade abgeschlossen ✓${RESET}"
echo -e "${GREEN}   Backup: $BACKUP_DIR${RESET}"
echo -e "${GREEN}══════════════════════════════════════════${RESET}"
echo ""
