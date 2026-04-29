"""
SecretProvider — Multi-Backend Secret Management.

Backends (automatische Priorität, erste verfügbare wird genutzt):
  1. AWS Secrets Manager   (wenn AWS_REGION gesetzt)
  2. Azure Key Vault        (wenn AZURE_KEYVAULT_URL gesetzt)
  3. HashiCorp Vault        (wenn VAULT_ADDR gesetzt)
  4. macOS Keychain         (Darwin + security binary)
  5. Windows Credential Store (wenn win32cred installiert)
  6. pass (GPG)             (wenn pass binary vorhanden)
  7. .env Datei             (Fallback)

Verwendung:
    from crypto_bot.config.secret_provider import get_provider
    provider = get_provider()
    token = provider.get("TELEGRAM_TOKEN")
    status = provider.status()
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class SecretProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Gibt Secret-Wert zurück oder None wenn nicht gefunden."""

    @abstractmethod
    def available(self) -> bool:
        """True wenn dieses Backend verfügbar ist."""

    def status(self) -> dict:
        return {"backend": self.name, "available": self.available()}


# ── Backends ──────────────────────────────────────────────────────────────────

class EnvFileProvider(SecretProvider):
    name = "env_file"

    def __init__(self, env_path: Path | None = None):
        self._path = env_path or Path(".env")

    def available(self) -> bool:
        return self._path.exists()

    def get(self, key: str) -> Optional[str]:
        val = os.getenv(key)
        if val:
            return val
        if not self._path.exists():
            return None
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
        return None

    def status(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available(),
            "path": str(self._path),
            "warning": "Secrets im Klartext — nur für lokale Entwicklung empfohlen",
        }


class PassProvider(SecretProvider):
    name = "pass"

    def __init__(self, prefix: str = "trading-bot"):
        self._prefix = prefix

    def available(self) -> bool:
        return shutil.which("pass") is not None

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        pass_key = f"{self._prefix}/{key.lower().replace('_', '-')}"
        try:
            result = subprocess.run(
                ["pass", "show", pass_key],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def status(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available(),
            "binary": shutil.which("pass"),
        }


class MacKeychainProvider(SecretProvider):
    name = "macos_keychain"

    def available(self) -> bool:
        return platform.system() == "Darwin" and shutil.which("security") is not None

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", key, "-w"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def status(self) -> dict:
        return {"backend": self.name, "available": self.available()}


class WindowsCredentialProvider(SecretProvider):
    name = "windows_credential_store"

    def available(self) -> bool:
        try:
            import win32cred  # noqa: F401
            return platform.system() == "Windows"
        except ImportError:
            return False

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            import win32cred
            cred = win32cred.CredRead(key, win32cred.CRED_TYPE_GENERIC, 0)
            return cred["CredentialBlob"].decode("utf-16")
        except Exception:
            return None

    def status(self) -> dict:
        return {"backend": self.name, "available": self.available()}


class AWSSecretsProvider(SecretProvider):
    name = "aws_secrets_manager"

    def available(self) -> bool:
        if not os.getenv("AWS_REGION"):
            return False
        try:
            import boto3  # noqa: F401
            return True
        except ImportError:
            return False

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            import boto3
            import json as _json
            client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION"))
            secret_name = os.getenv("AWS_SECRET_NAME", "trading-bot")
            response = client.get_secret_value(SecretId=secret_name)
            secrets = _json.loads(response.get("SecretString", "{}"))
            return secrets.get(key)
        except Exception:
            return None

    def status(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available(),
            "region": os.getenv("AWS_REGION"),
            "secret_name": os.getenv("AWS_SECRET_NAME", "trading-bot"),
        }


class AzureKeyVaultProvider(SecretProvider):
    name = "azure_key_vault"

    def available(self) -> bool:
        if not os.getenv("AZURE_KEYVAULT_URL"):
            return False
        try:
            from azure.keyvault.secrets import SecretClient  # noqa: F401
            from azure.identity import DefaultAzureCredential  # noqa: F401
            return True
        except ImportError:
            return False

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            from azure.keyvault.secrets import SecretClient
            from azure.identity import DefaultAzureCredential
            client = SecretClient(
                vault_url=os.getenv("AZURE_KEYVAULT_URL"),
                credential=DefaultAzureCredential()
            )
            secret_name = key.lower().replace("_", "-")
            return client.get_secret(secret_name).value
        except Exception:
            return None

    def status(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available(),
            "vault_url": os.getenv("AZURE_KEYVAULT_URL"),
        }


class HashiCorpVaultProvider(SecretProvider):
    name = "hashicorp_vault"

    def available(self) -> bool:
        if not os.getenv("VAULT_ADDR"):
            return False
        try:
            import hvac  # noqa: F401
            return True
        except ImportError:
            return False

    def get(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            import hvac
            client = hvac.Client(
                url=os.getenv("VAULT_ADDR"),
                token=os.getenv("VAULT_TOKEN")
            )
            path = os.getenv("VAULT_SECRET_PATH", "secret/trading-bot")
            response = client.secrets.kv.read_secret_version(path=path)
            return response["data"]["data"].get(key)
        except Exception:
            return None

    def status(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available(),
            "addr": os.getenv("VAULT_ADDR"),
        }


# ── Factory + Auto-Detection ──────────────────────────────────────────────────

_PROVIDER_PRIORITY: list[type[SecretProvider]] = [
    AWSSecretsProvider,
    AzureKeyVaultProvider,
    HashiCorpVaultProvider,
    MacKeychainProvider,
    WindowsCredentialProvider,
    PassProvider,
    EnvFileProvider,
]

_active_provider: SecretProvider | None = None


def get_provider(force: str | None = None) -> SecretProvider:
    """
    Gibt den ersten verfügbaren SecretProvider zurück.
    force: Name eines Backends erzwingen (z.B. "pass", "env_file", "aws_secrets_manager")
    """
    global _active_provider
    if _active_provider and not force:
        return _active_provider

    if force:
        for cls in _PROVIDER_PRIORITY:
            if cls.name == force:
                _active_provider = cls()
                return _active_provider
        raise ValueError(f"Unbekannter Provider: {force}. Verfügbar: {[c.name for c in _PROVIDER_PRIORITY]}")

    for cls in _PROVIDER_PRIORITY:
        provider = cls()
        if provider.available():
            _active_provider = provider
            return provider

    # Absoluter Fallback
    _active_provider = EnvFileProvider()
    return _active_provider


def all_backends_status() -> list[dict]:
    """Status aller Backends — für Dashboard System-Tab."""
    result = []
    for cls in _PROVIDER_PRIORITY:
        try:
            p = cls()
            s = p.status()
        except Exception as e:
            s = {"backend": cls.name, "available": False, "error": str(e)}
        result.append(s)
    return result
