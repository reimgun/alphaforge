"""
Strategy Marketplace — Strategie-Registry, Metadaten und Import/Export.

Jede Strategie ist eine Python-Datei in crypto_bot/strategy/ mit einem
optionalen YAML-Sidecar (.strategy.yaml) für Metadaten.

Format einer .strategy.yaml:
    name:        "Momentum v2"
    description: "EMA-Cross + RSI-Filter + Regime-Gate"
    author:      "alphaforge"
    version:     "1.2.0"
    tags:        [momentum, trend, crypto]
    asset_class: crypto              # crypto | forex | equities | multi
    timeframes:  [1h, 4h]
    risk_level:  balanced            # conservative | balanced | aggressive
    min_capital: 500                 # USD
    params:
      FAST_MA: 20
      SLOW_MA: 50
      RSI_PERIOD: 14
    performance:                     # optional, aus Backtests
      sharpe: 1.4
      win_rate: 58.2
      max_drawdown: 12.3
      backtest_days: 365
    created_at:  "2026-04-24"
    updated_at:  "2026-04-24"

Verwendung:
    from crypto_bot.strategy.marketplace import StrategyRegistry
    registry = StrategyRegistry()
    strategies = registry.list_all()
    registry.export("momentum", "/tmp/momentum_strategy.zip")
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

STRATEGY_DIR = Path(__file__).parent
MARKETPLACE_DIR = Path(__file__).parent.parent.parent / "data_store" / "marketplace"

# Bekannte Strategie-Dateien in diesem Paket
_KNOWN_STRATEGIES = [
    "momentum", "mean_reversion", "breakout", "scalping",
    "volatility_expansion", "multi_timeframe", "liquidity_signals",
]


class StrategyMeta:
    """Metadaten einer Strategie."""

    def __init__(self, module_name: str, data: dict):
        self.module_name = module_name
        self.name        = data.get("name", module_name.replace("_", " ").title())
        self.description = data.get("description", "")
        self.author      = data.get("author", "")
        self.version     = data.get("version", "1.0.0")
        self.tags        = data.get("tags", [])
        self.asset_class = data.get("asset_class", "crypto")
        self.timeframes  = data.get("timeframes", ["1h"])
        self.risk_level  = data.get("risk_level", "balanced")
        self.min_capital = data.get("min_capital", 100)
        self.params      = data.get("params", {})
        self.performance = data.get("performance", {})
        self.created_at  = data.get("created_at", "")
        self.updated_at  = data.get("updated_at", "")
        self.local        = True   # lokal installiert

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "name":        self.name,
            "description": self.description,
            "author":      self.author,
            "version":     self.version,
            "tags":        self.tags,
            "asset_class": self.asset_class,
            "timeframes":  self.timeframes,
            "risk_level":  self.risk_level,
            "min_capital": self.min_capital,
            "params":      self.params,
            "performance": self.performance,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
            "local":       self.local,
        }


class StrategyRegistry:
    """Verwaltet alle lokalen Strategien."""

    def __init__(self):
        self._cache: dict[str, StrategyMeta] | None = None

    def _load_meta(self, module_name: str) -> StrategyMeta:
        """Lädt Metadaten aus .strategy.yaml oder generiert sie aus dem Modul."""
        yaml_path = STRATEGY_DIR / f"{module_name}.strategy.yaml"
        data: dict = {}

        if _HAS_YAML and yaml_path.exists():
            try:
                with yaml_path.open() as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                pass

        # Fallback: Beschreibung aus Docstring
        if not data.get("description"):
            try:
                mod = importlib.import_module(f"crypto_bot.strategy.{module_name}")
                data["description"] = (inspect.getdoc(mod) or "").split("\n")[0]
            except Exception:
                pass

        return StrategyMeta(module_name, data)

    def list_all(self) -> list[dict]:
        """Alle verfügbaren Strategien als Liste von Dicts."""
        results = []
        # Alle .py Dateien im strategy/-Verzeichnis
        for py_file in sorted(STRATEGY_DIR.glob("*.py")):
            name = py_file.stem
            if name.startswith("_") or name in ("marketplace", "selector"):
                continue
            try:
                meta = self._load_meta(name)
                results.append(meta.to_dict())
            except Exception:
                results.append({
                    "module_name": name,
                    "name": name.replace("_", " ").title(),
                    "description": "",
                    "local": True,
                })
        return results

    def get(self, module_name: str) -> StrategyMeta | None:
        """Einzelne Strategie-Metadaten."""
        py_path = STRATEGY_DIR / f"{module_name}.py"
        if not py_path.exists():
            return None
        return self._load_meta(module_name)

    def save_meta(self, module_name: str, data: dict) -> bool:
        """Speichert Metadaten als .strategy.yaml."""
        if not _HAS_YAML:
            return False
        data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yaml_path = STRATEGY_DIR / f"{module_name}.strategy.yaml"
        try:
            with yaml_path.open("w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            return True
        except Exception:
            return False

    def export(self, module_name: str, output_path: str | None = None) -> str:
        """
        Exportiert eine Strategie als ZIP für Sharing.
        Enthält: strategy.py + .strategy.yaml (falls vorhanden)
        """
        py_path   = STRATEGY_DIR / f"{module_name}.py"
        yaml_path = STRATEGY_DIR / f"{module_name}.strategy.yaml"
        if not py_path.exists():
            raise FileNotFoundError(f"Strategie '{module_name}' nicht gefunden")

        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = output_path or str(MARKETPLACE_DIR / f"{module_name}.strategy.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(py_path, f"{module_name}.py")
            if yaml_path.exists():
                zf.write(yaml_path, f"{module_name}.strategy.yaml")
        return zip_path

    def import_zip(self, zip_path: str) -> str:
        """
        Importiert eine Strategie aus einer ZIP-Datei.
        Gibt den Modul-Namen zurück.
        """
        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            py_files = [n for n in names if n.endswith(".py")]
            if not py_files:
                raise ValueError("Keine .py-Datei in ZIP gefunden")
            module_name = py_files[0].removesuffix(".py")
            for name in names:
                zf.extract(name, STRATEGY_DIR)
        return module_name

    def get_performance_summary(self) -> list[dict]:
        """Aggregierte Performance aller Strategien aus bot_state (API-Daten)."""
        results = []
        state_file = Path(__file__).parent.parent.parent / "data_store" / "bot_state.json"
        if state_file.exists():
            try:
                import json as _json
                state = _json.loads(state_file.read_text())
                perf  = state.get("strategy_performance", {})
                for name, data in perf.items():
                    results.append({"strategy": name, **data})
            except Exception:
                pass
        return results


# ── YAML-Sidecar-Generator ────────────────────────────────────────────────────

def generate_default_yaml(module_name: str) -> bool:
    """Generiert eine Standard-.strategy.yaml wenn noch keine vorhanden."""
    if not _HAS_YAML:
        return False
    yaml_path = STRATEGY_DIR / f"{module_name}.strategy.yaml"
    if yaml_path.exists():
        return False
    py_path = STRATEGY_DIR / f"{module_name}.py"
    if not py_path.exists():
        return False

    description = ""
    try:
        mod = importlib.import_module(f"crypto_bot.strategy.{module_name}")
        description = (inspect.getdoc(mod) or "").split("\n")[0]
    except Exception:
        pass

    data = {
        "name":        module_name.replace("_", " ").title(),
        "description": description,
        "author":      "alphaforge",
        "version":     "1.0.0",
        "tags":        [module_name.split("_")[0]],
        "asset_class": "crypto",
        "timeframes":  ["1h"],
        "risk_level":  "balanced",
        "min_capital": 100,
        "params":      {},
        "performance": {},
        "created_at":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "updated_at":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    with yaml_path.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    return True
