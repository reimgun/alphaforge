#!/usr/bin/env bash
# ── Secrets in Pass eintragen ─────────────────────────────────────────────────
# Interaktiv: fragt jeden Wert ab und speichert ihn verschlüsselt.
# Bereits vorhandene Einträge werden übersprungen (--force zum Überschreiben).
set -euo pipefail

FORCE="${1:-}"

add_secret() {
  local path="$1"
  local prompt="$2"
  local default="${3:-}"

  if pass show "$path" &>/dev/null && [ "$FORCE" != "--force" ]; then
    echo "  ✓ $path (bereits vorhanden — '--force' zum Überschreiben)"
    return
  fi

  if [ -n "$default" ]; then
    read -r -p "  $prompt [$default]: " value
    value="${value:-$default}"
  else
    read -r -s -p "  $prompt: " value
    echo
  fi

  if [ -z "$value" ]; then
    echo "  ⚠ $path übersprungen (leer)"
    return
  fi

  echo "$value" | pass insert --echo "$path" > /dev/null
  echo "  ✓ $path gespeichert"
}

echo "=== Trading Bot — Secrets eintragen ==="
echo "(Bereits vorhandene Einträge werden übersprungen)"
echo

echo "── Forex: IG Group API ───────────────────────────────────────────────────"
add_secret "trading-bot/forex/ig-api-key"   "IG API Key"
add_secret "trading-bot/forex/ig-username"  "IG Benutzername"
add_secret "trading-bot/forex/ig-password"  "IG Passwort"
add_secret "trading-bot/forex/ig-env"       "IG Umgebung" "demo"
add_secret "trading-bot/forex/ig-account-id" "IG Account ID (optional, leer lassen = auto)"

echo
echo "── Forex: Telegram ───────────────────────────────────────────────────────"
add_secret "trading-bot/forex/telegram-token"    "Forex Telegram Bot Token"
add_secret "trading-bot/forex/telegram-chat-id"  "Telegram Chat ID"

echo
echo "── Forex: Externe APIs ───────────────────────────────────────────────────"
add_secret "trading-bot/forex/fred-api-key"  "FRED API Key (St. Louis Fed)"
add_secret "trading-bot/shared/groq-api-key" "Groq API Key"

echo
echo "── Crypto: Binance ───────────────────────────────────────────────────────"
add_secret "trading-bot/crypto/binance-api-key"    "Binance API Key"
add_secret "trading-bot/crypto/binance-api-secret" "Binance API Secret"

echo
echo "── Crypto: Telegram ──────────────────────────────────────────────────────"
add_secret "trading-bot/crypto/telegram-token"   "Crypto Telegram Bot Token"
add_secret "trading-bot/crypto/telegram-chat-id" "Telegram Chat ID"

echo
echo "── Crypto: KI APIs ───────────────────────────────────────────────────────"
add_secret "trading-bot/crypto/anthropic-api-key" "Anthropic API Key"

echo
echo "── Pass Store sichern ────────────────────────────────────────────────────"
pass git add -A
pass git commit -m "Update secrets $(date +%Y-%m-%d)" 2>/dev/null || echo "  (keine Änderungen)"

echo
echo "=== Fertig. Jetzt .env generieren: make gen-env ==="
