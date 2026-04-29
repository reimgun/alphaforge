#!/usr/bin/env bash
# ── .env Dateien aus Pass + Templates generieren ─────────────────────────────
# Liest Secrets aus pass, füllt sie in .env.template → .env
# Aufruf: bash scripts/gen-env.sh [forex|crypto|all]
set -euo pipefail

TARGET="${1:-all}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

R="\033[91m"; G="\033[92m"; Y="\033[93m"; X="\033[0m"

# Optionales Secret — leerer String als Fallback wenn nicht vorhanden
secret() {
  local path="$1"
  local fallback="${2:-}"
  pass show "$path" 2>/dev/null || echo "$fallback"
}

# Pflicht-Secret — bricht ab wenn leer oder GPG-Fehler
required_secret() {
  local path="$1"
  local value
  value=$(pass show "$path" 2>/dev/null || true)
  if [ -z "$value" ]; then
    echo -e "${R}FEHLER: pass-Eintrag '$path' ist leer oder nicht entschlüsselbar.${X}" >&2
    echo -e "${Y}  → GPG-Agent entsperren: pass show $path${X}" >&2
    exit 1
  fi
  echo "$value"
}

gen_forex() {
  echo "Generiere forex_bot/.env ..."
  local tmpl="$REPO_ROOT/forex_bot/.env.template"
  local out="$REPO_ROOT/forex_bot/.env"

  if [ ! -f "$tmpl" ]; then
    echo "FEHLER: $tmpl nicht gefunden"
    return 1
  fi

  # Welcher Broker aktiv ist (bestimmt welche Secrets benötigt werden)
  local broker
  broker=$(grep "^FOREX_BROKER=" "$tmpl" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')

  sed \
    -e "s|__IG_API_KEY__|$(secret trading-bot/forex/ig-api-key)|g" \
    -e "s|__IG_USERNAME__|$(secret trading-bot/forex/ig-username)|g" \
    -e "s|__IG_PASSWORD__|$(secret trading-bot/forex/ig-password)|g" \
    -e "s|__IG_ACCOUNT_ID__|$(secret trading-bot/forex/ig-account-id)|g" \
    -e "s|__ALPACA_API_KEY_PAPER__|$(secret trading-bot/forex/alpaca-api-key-paper)|g" \
    -e "s|__ALPACA_API_SECRET_PAPER__|$(secret trading-bot/forex/alpaca-api-secret-paper)|g" \
    -e "s|__ALPACA_API_KEY_LIVE__|$(secret trading-bot/forex/alpaca-api-key-live)|g" \
    -e "s|__ALPACA_API_SECRET_LIVE__|$(secret trading-bot/forex/alpaca-api-secret-live)|g" \
    -e "s|__FOREX_TELEGRAM_TOKEN__|$(required_secret trading-bot/forex/telegram-token)|g" \
    -e "s|__FOREX_TELEGRAM_CHAT_ID__|$(secret trading-bot/forex/telegram-chat-id)|g" \
    -e "s|__FRED_API_KEY__|$(secret trading-bot/forex/fred-api-key)|g" \
    -e "s|__GROQ_API_KEY__|$(secret trading-bot/shared/groq-api-key)|g" \
    "$tmpl" > "$out"

  chmod 600 "$out"
  echo "  ✓ forex_bot/.env geschrieben"
}

gen_crypto() {
  echo "Generiere .env (Crypto) ..."
  local tmpl="$REPO_ROOT/.env.template"
  local out="$REPO_ROOT/.env"

  if [ ! -f "$tmpl" ]; then
    echo "FEHLER: $tmpl nicht gefunden"
    return 1
  fi

  sed \
    -e "s|__BINANCE_API_KEY__|$(secret trading-bot/crypto/binance-api-key)|g" \
    -e "s|__BINANCE_API_SECRET__|$(secret trading-bot/crypto/binance-api-secret)|g" \
    -e "s|__ANTHROPIC_API_KEY__|$(secret trading-bot/crypto/anthropic-api-key)|g" \
    -e "s|__GROQ_API_KEY__|$(secret trading-bot/shared/groq-api-key)|g" \
    -e "s|__TELEGRAM_TOKEN__|$(required_secret trading-bot/crypto/telegram-token)|g" \
    -e "s|__TELEGRAM_CHAT_ID__|$(secret trading-bot/crypto/telegram-chat-id)|g" \
    "$tmpl" > "$out"

  chmod 600 "$out"
  echo "  ✓ .env geschrieben"
}

case "$TARGET" in
  forex)  gen_forex ;;
  crypto) gen_crypto ;;
  all)    gen_forex; gen_crypto ;;
  *)
    echo "Usage: $0 [forex|crypto|all]"
    exit 1
    ;;
esac

echo
echo "Fertig. .env Dateien sind bereit für Deploy."
