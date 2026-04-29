"""
Exchange .env Manager — liest und schreibt Exchange-Credentials in .env.

Jeder Exchange hat getrennte Einträge für Testnet/Demo und Live,
damit beide parallel in der .env stehen können.
"""
from __future__ import annotations

import threading
from pathlib import Path

# Crypto-Bot liest die .env im Projekt-Root (trading_bot/.env)
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
_LOCK = threading.Lock()

# Schema: exchange → env → [(ENV_KEY, creds_field), ...]
# Der erste Key ist der "primary key" — sein Vorhandensein gilt als "exists".
SCHEMA: dict[str, dict[str, list[tuple[str, str]]]] = {
    "binance": {
        "testnet": [
            ("BINANCE_API_KEY_TESTNET",    "api_key"),
            ("BINANCE_API_SECRET_TESTNET", "api_secret"),
        ],
        "live": [
            ("BINANCE_API_KEY_LIVE",    "api_key"),
            ("BINANCE_API_SECRET_LIVE", "api_secret"),
        ],
    },
    "bybit": {
        "testnet": [
            ("BYBIT_API_KEY_TESTNET",    "api_key"),
            ("BYBIT_API_SECRET_TESTNET", "api_secret"),
        ],
        "live": [
            ("BYBIT_API_KEY_LIVE",    "api_key"),
            ("BYBIT_API_SECRET_LIVE", "api_secret"),
        ],
    },
    "okx": {
        "demo": [
            ("OKX_API_KEY_DEMO",     "api_key"),
            ("OKX_API_SECRET_DEMO",  "api_secret"),
            ("OKX_PASSPHRASE_DEMO",  "passphrase"),
        ],
        "live": [
            ("OKX_API_KEY_LIVE",     "api_key"),
            ("OKX_API_SECRET_LIVE",  "api_secret"),
            ("OKX_PASSPHRASE_LIVE",  "passphrase"),
        ],
    },
    "kraken": {
        "live": [
            ("KRAKEN_API_KEY",    "api_key"),
            ("KRAKEN_API_SECRET", "api_secret"),
        ],
    },
}


def read_env() -> dict[str, str]:
    """Liest .env und gibt {KEY: value} zurück."""
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            key, _, val = s.partition("=")
            result[key.strip()] = val.strip()
    return result


def credentials_exist(exchange: str, env: str) -> str | None:
    """
    Gibt den primary ENV-Key zurück wenn Credentials bereits vorhanden, sonst None.
    "Vorhanden" = primary key hat einen nicht-leeren Wert in .env.
    """
    schema = SCHEMA.get(exchange, {}).get(env, [])
    if not schema:
        return None
    primary = schema[0][0]
    return primary if read_env().get(primary) else None


def get_configured() -> list[dict]:
    """Gibt alle konfigurierten Exchange+Env zurück."""
    existing = read_env()
    result = []
    for exchange, envs in SCHEMA.items():
        for env, schema in envs.items():
            if schema and existing.get(schema[0][0]):
                result.append({"exchange": exchange, "env": env})
    return result


def write_credentials(exchange: str, env: str, creds: dict) -> None:
    """
    Schreibt Credentials für exchange+env ans Ende der .env.

    Raises ValueError wenn der Eintrag bereits existiert.
    """
    schema = SCHEMA.get(exchange, {}).get(env, [])
    if not schema:
        raise ValueError(f"Unbekannte Kombination: exchange={exchange} env={env}")

    with _LOCK:
        existing = read_env()
        primary = schema[0][0]
        if existing.get(primary):
            raise ValueError(f"Existiert bereits: {primary}")

        exchange_label = exchange.upper()
        env_label      = env.upper()
        dashes         = "─" * max(1, 46 - len(exchange_label) - len(env_label))
        lines = [
            f"\n# ── {exchange_label} {env_label} {dashes}",
        ]
        for env_var, field in schema:
            value = str(creds.get(field, ""))
            lines.append(f"{env_var}={value}")
        lines.append("")

        with open(_ENV_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # dotenv neu laden damit os.getenv sofort aktuell ist
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=True)
    except Exception:
        pass
