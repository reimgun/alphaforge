"""
Strategy Loader — lädt IStrategy-Klassen dynamisch.

Suchreihenfolge:
  1. STRATEGY_PATH gesetzt → Datei direkt laden
  2. Name in eingebautem Katalog → aus crypto_bot.strategy.examples laden
  3. Name in strategies/ Verzeichnis (Projekt-Root) → Custom-Strategie laden

Verwendung:
    STRATEGY=MACrossStrategy          → eingebaut
    STRATEGY=MyCustomStrat            → strategies/MyCustomStrat.py
    STRATEGY_PATH=/home/user/my.py    → absoluter Pfad
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Optional, Type

from crypto_bot.strategy.interface import IStrategy

log = logging.getLogger("trading_bot")

# ── Eingebauter Strategie-Katalog ─────────────────────────────────────────────
_BUILTIN: dict[str, str] = {
    "MACrossStrategy":    "crypto_bot.strategy.examples.ma_cross",
    "RSIBBStrategy":      "crypto_bot.strategy.examples.rsi_bb",
}

_CUSTOM_DIR = Path(__file__).parent.parent.parent / "strategies"


def load_strategy(name: str, path: str = "") -> IStrategy:
    """
    Lädt und instanziiert eine Strategy-Klasse.

    Args:
        name: Klassen-Name (z.B. "MACrossStrategy")
        path: Optionaler Dateipfad für Custom-Strategien

    Returns:
        Instanziierte IStrategy-Subklasse

    Raises:
        ValueError: Klasse nicht gefunden oder kein IStrategy-Subtyp
    """
    cls = _resolve_class(name, path)
    if not (inspect.isclass(cls) and issubclass(cls, IStrategy)):
        raise ValueError(f"'{name}' ist kein IStrategy-Subtyp")
    instance = cls()
    log.info(f"Strategie geladen: {instance.name} v{instance.version} | tf={instance.timeframe}")
    return instance


def _resolve_class(name: str, path: str) -> Type:
    if path:
        cls = _load_from_file(path, name)
        if cls is None:
            raise ValueError(f"Klasse '{name}' nicht in {path} gefunden")
        return cls

    if name in _BUILTIN:
        mod = importlib.import_module(_BUILTIN[name])
        return getattr(mod, name)

    if _CUSTOM_DIR.exists():
        for f in _CUSTOM_DIR.glob("*.py"):
            cls = _load_from_file(str(f), name, silent=True)
            if cls is not None:
                return cls

    available = list(_BUILTIN.keys())
    raise ValueError(
        f"Strategie '{name}' nicht gefunden.\n"
        f"Eingebaut: {available}\n"
        f"Custom: .py-Datei mit class {name}(IStrategy) in strategies/ ablegen."
    )


def _load_from_file(path: str, name: str, silent: bool = False) -> Optional[Type]:
    try:
        spec = importlib.util.spec_from_file_location("_strategy_module", path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, name, None)
    except Exception as e:
        if not silent:
            raise ValueError(f"Fehler beim Laden von {path}: {e}")
        return None


def list_strategies() -> list[dict]:
    """Alle verfügbaren Strategien (eingebaut + custom) für Dashboard/API."""
    result: list[dict] = []

    for name, mod_path in _BUILTIN.items():
        try:
            mod  = importlib.import_module(mod_path)
            inst = getattr(mod, name)()
            result.append({
                "name":        name,
                "version":     inst.version,
                "description": inst.description,
                "author":      inst.author,
                "timeframe":   inst.timeframe,
                "type":        "builtin",
                "error":       False,
            })
        except Exception as e:
            result.append({"name": name, "type": "builtin", "error": True, "message": str(e)})

    if _CUSTOM_DIR.exists():
        for f in sorted(_CUSTOM_DIR.glob("*.py")):
            entry: dict = {"name": f.stem, "path": str(f), "type": "custom", "error": False}
            for cls_name in [f.stem, f.stem.replace("_", ""), f.stem.title().replace("_", "")]:
                cls = _load_from_file(str(f), cls_name, silent=True)
                if cls and inspect.isclass(cls) and issubclass(cls, IStrategy):
                    try:
                        inst = cls()
                        entry.update({
                            "name":        inst.name,
                            "version":     inst.version,
                            "description": inst.description,
                            "author":      inst.author,
                            "timeframe":   inst.timeframe,
                        })
                    except Exception:
                        pass
                    break
            result.append(entry)

    return result
