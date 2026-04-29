"""
.env Manager — liest und schreibt Broker-Credentials in forex_bot/.env.

Jeder Broker hat getrennte Einträge für Demo/Practice und Live,
damit beide parallel in der .env stehen können.
"""
from __future__ import annotations

import threading
from pathlib import Path

_ENV_PATH = Path(__file__).parent.parent / ".env"
_LOCK = threading.Lock()

# Schema: broker → env → [(ENV_KEY, creds_field), ...]
# Der erste Key ist der "primary key" — sein Vorhandensein gilt als "exists".
SCHEMA: dict[str, dict[str, list[tuple[str, str]]]] = {
    "oanda": {
        "practice": [
            ("OANDA_API_KEY_PRACTICE",    "api_key"),
            ("OANDA_ACCOUNT_ID_PRACTICE", "account_id"),
        ],
        "live": [
            ("OANDA_API_KEY_LIVE",    "api_key"),
            ("OANDA_ACCOUNT_ID_LIVE", "account_id"),
        ],
    },
    "capital": {
        "demo": [
            ("CAPITAL_API_KEY_DEMO",  "api_key"),
            ("CAPITAL_EMAIL_DEMO",    "email"),
            ("CAPITAL_PASSWORD_DEMO", "password"),
        ],
        "live": [
            ("CAPITAL_API_KEY_LIVE",  "api_key"),
            ("CAPITAL_EMAIL_LIVE",    "email"),
            ("CAPITAL_PASSWORD_LIVE", "password"),
        ],
    },
    "ig": {
        "demo": [
            ("IG_API_KEY_DEMO",  "api_key"),
            ("IG_USERNAME_DEMO", "username"),
            ("IG_PASSWORD_DEMO", "password"),
        ],
        "live": [
            ("IG_API_KEY_LIVE",  "api_key"),
            ("IG_USERNAME_LIVE", "username"),
            ("IG_PASSWORD_LIVE", "password"),
        ],
    },
    "ibkr": {
        # IBKR hat nur einen Satz — Port bestimmt Paper vs Live
        "any": [
            ("IBKR_HOST",      "host"),
            ("IBKR_PORT",      "port"),
            ("IBKR_CLIENT_ID", "client_id"),
            ("IBKR_ACCOUNT",   "account"),
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


def credentials_exist(broker: str, env: str) -> str | None:
    """
    Gibt den primary ENV-Key zurück wenn Credentials bereits vorhanden, sonst None.
    "Vorhanden" = primary key hat einen nicht-leeren Wert in .env.
    """
    env_key = "any" if broker == "ibkr" else env
    schema = SCHEMA.get(broker, {}).get(env_key, [])
    if not schema:
        return None
    primary = schema[0][0]
    return primary if read_env().get(primary) else None


def get_configured() -> list[dict]:
    """Gibt alle konfigurierten Broker+Env zurück."""
    existing = read_env()
    result = []
    for broker, envs in SCHEMA.items():
        for env, schema in envs.items():
            if schema and existing.get(schema[0][0]):
                result.append({"broker": broker, "env": env})
    return result


def write_credentials(broker: str, env: str, creds: dict) -> None:
    """
    Schreibt Credentials für broker+env ans Ende der .env.

    Raises ValueError wenn der Eintrag bereits existiert.
    """
    env_key = "any" if broker == "ibkr" else env
    schema = SCHEMA.get(broker, {}).get(env_key, [])
    if not schema:
        raise ValueError(f"Unbekannte Kombination: broker={broker} env={env}")

    with _LOCK:
        existing = read_env()
        primary = schema[0][0]
        if existing.get(primary):
            raise ValueError(f"Existiert bereits: {primary}")

        broker_label = broker.upper()
        env_label    = env.upper()
        dashes       = "─" * max(1, 46 - len(broker_label) - len(env_label))
        lines = [
            f"\n# ── {broker_label} {env_label} {dashes}",
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
