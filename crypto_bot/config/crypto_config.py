"""
Encrypted Config Storage — verschlüsselt sensible .env-Werte mit Fernet (AES-128).

Verwendung:
    # Einmalig: Key generieren und .env verschlüsseln
    python -m config.crypto_config --encrypt

    # Im Bot: verschlüsselte Werte laden
    from crypto_bot.config.crypto_config import load_secure_env
    load_secure_env()   # Überschreibt os.environ mit entschlüsselten Werten

Sicherheit:
  - Key wird in .env.key gespeichert (niemals ins Git!)
  - Verschlüsselte Werte in .env.enc
  - Fernet = AES-128-CBC + HMAC-SHA256 (authenticated encryption)

Abhängigkeit: pip install cryptography
"""
import os
import sys
import logging
from pathlib import Path

log = logging.getLogger("trading_bot")

ENV_KEY_PATH = Path(__file__).parent.parent / ".env.key"
ENV_ENC_PATH = Path(__file__).parent.parent / ".env.enc"
ENV_PATH     = Path(__file__).parent.parent / ".env"

# Schlüsselwörter die verschlüsselt werden
SENSITIVE_KEYS = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "TELEGRAM_TOKEN",
    "ANTHROPIC_API_KEY",
}


def _get_fernet():
    """Lädt oder erstellt Fernet-Instanz."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError(
            "cryptography nicht installiert.\n"
            "Installieren: pip install cryptography"
        )

    if ENV_KEY_PATH.exists():
        key = ENV_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        ENV_KEY_PATH.write_bytes(key)
        log.info(f"Neuer Verschlüsselungs-Key erstellt: {ENV_KEY_PATH}")

    return Fernet(key)


def encrypt_env(env_path: Path = ENV_PATH, enc_path: Path = ENV_ENC_PATH) -> Path:
    """
    Verschlüsselt sensible Werte aus .env und speichert in .env.enc.

    Returns:
        Pfad zur verschlüsselten Datei.
    """
    fernet = _get_fernet()

    if not env_path.exists():
        raise FileNotFoundError(f".env nicht gefunden: {env_path}")

    lines     = env_path.read_text(encoding="utf-8").splitlines()
    enc_lines = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            enc_lines.append(line)
            continue

        if "=" not in line:
            enc_lines.append(line)
            continue

        key, _, value = line.partition("=")
        key = key.strip()

        if key in SENSITIVE_KEYS and value.strip():
            encrypted = fernet.encrypt(value.strip().encode()).decode()
            enc_lines.append(f"{key}=ENC:{encrypted}")
            log.info(f"Verschlüsselt: {key}")
        else:
            enc_lines.append(line)

    enc_path.write_text("\n".join(enc_lines) + "\n", encoding="utf-8")
    log.info(f"Verschlüsselte Config gespeichert: {enc_path}")
    return enc_path


def decrypt_env(enc_path: Path = ENV_ENC_PATH) -> dict:
    """
    Entschlüsselt .env.enc und gibt alle Werte als dict zurück.

    Returns:
        dict mit allen Schlüssel-Wert-Paaren (entschlüsselt).
    """
    if not enc_path.exists():
        return {}

    fernet = _get_fernet()
    result = {}
    lines  = enc_path.read_text(encoding="utf-8").splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip()

        if value.startswith("ENC:"):
            try:
                decrypted = fernet.decrypt(value[4:].encode()).decode()
                result[key] = decrypted
            except Exception as e:
                log.warning(f"Entschlüsselung fehlgeschlagen für {key}: {e}")
        else:
            result[key] = value

    return result


def load_secure_env(enc_path: Path = ENV_ENC_PATH) -> bool:
    """
    Lädt verschlüsselte Konfiguration in os.environ.

    Returns:
        True wenn .env.enc geladen, False wenn nicht vorhanden (Fallback auf .env).
    """
    if not enc_path.exists():
        return False

    try:
        values = decrypt_env(enc_path)
        for k, v in values.items():
            os.environ.setdefault(k, v)
        log.info(f"Verschlüsselte Config geladen: {len(values)} Einträge")
        return True
    except Exception as e:
        log.warning(f"Verschlüsselte Config konnte nicht geladen werden: {e}")
        return False


def is_encrypted() -> bool:
    """Prüft ob eine verschlüsselte Config vorhanden ist."""
    return ENV_ENC_PATH.exists() and ENV_KEY_PATH.exists()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Config Encryption Tool")
    parser.add_argument("--encrypt", action="store_true",
                        help="Verschlüsselt sensible .env-Werte")
    parser.add_argument("--check",   action="store_true",
                        help="Prüft ob verschlüsselte Config vorhanden")
    parser.add_argument("--decrypt", action="store_true",
                        help="Zeigt entschlüsselte Werte (nur für Debug)")
    args = parser.parse_args()

    if args.encrypt:
        path = encrypt_env()
        print(f"✅ Verschlüsselt: {path}")
        print(f"🔑 Key gespeichert: {ENV_KEY_PATH}")
        print("⚠️  Füge .env.key zu .gitignore hinzu!")
    elif args.check:
        if is_encrypted():
            print(f"✅ Verschlüsselte Config vorhanden: {ENV_ENC_PATH}")
        else:
            print("❌ Keine verschlüsselte Config gefunden")
            print(f"   Erstellen mit: python -m config.crypto_config --encrypt")
    elif args.decrypt:
        values = decrypt_env()
        for k, v in values.items():
            if k in SENSITIVE_KEYS:
                print(f"{k}={'*' * 8}{v[-4:] if len(v) > 4 else '****'}")
            else:
                print(f"{k}={v}")
    else:
        parser.print_help()
