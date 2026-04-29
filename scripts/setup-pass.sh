#!/usr/bin/env bash
# ── Pass Store Setup ──────────────────────────────────────────────────────────
# Einmalig ausführen um den GPG-Key und Pass-Store zu initialisieren.
# Danach: scripts/add-secrets.sh um Werte einzutragen.
set -euo pipefail

PASS_STORE_REPO="${PASS_STORE_REPO:-YOUR_PASS_STORE_REPO}"

echo "=== Trading Bot — Pass Store Setup ==="
echo

# 1. GPG Key erstellen
if ! gpg --list-secret-keys --keyid-format LONG 2>/dev/null | grep -q "sec"; then
  echo "Kein GPG Key gefunden. Erstelle neuen Key..."
  echo "(Folge den Anweisungen: Name, E-Mail, Passphrase)"
  echo
  gpg --full-generate-key
else
  echo "GPG Key vorhanden:"
  gpg --list-secret-keys --keyid-format LONG | grep -E "^(sec|uid)"
fi

echo

# 2. GPG Key ID ermitteln
GPG_ID=$(gpg --list-secret-keys --keyid-format LONG 2>/dev/null \
  | grep "^sec" | head -1 | awk '{print $2}' | cut -d/ -f2)

if [ -z "$GPG_ID" ]; then
  echo "FEHLER: Kein GPG Key gefunden. Bitte zuerst 'gpg --full-generate-key' ausführen."
  exit 1
fi

echo "Nutze GPG Key: $GPG_ID"
echo

# 3. Pass Store initialisieren (falls noch nicht geschehen)
if [ ! -d "$HOME/.password-store" ] || [ ! -f "$HOME/.password-store/.gpg-id" ]; then
  pass init "$GPG_ID"
  echo "Pass Store initialisiert."
else
  echo "Pass Store bereits vorhanden: $HOME/.password-store"
fi

echo

# 4. Git Remote setzen
pass git init 2>/dev/null || true
pass git remote remove origin 2>/dev/null || true
pass git remote add origin "$PASS_STORE_REPO"
echo "Git Remote gesetzt: $PASS_STORE_REPO"
echo

echo "=== Setup abgeschlossen ==="
echo
echo "Nächste Schritte:"
echo "  1. Secrets eintragen:  bash scripts/add-secrets.sh"
echo "  2. Store pushen:       pass git push -u origin main"
echo "  3. .env generieren:    make gen-env"
