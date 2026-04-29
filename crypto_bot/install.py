#!/usr/bin/env python3
"""
Plattformunabhängige Installations-Routine für den Trading Bot.
Läuft auf macOS, Linux und Windows.

Verwendung:
    python install.py
"""
import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path

MIN_PYTHON = (3, 10)
BASE_DIR = Path(__file__).parent
VENV_DIR = BASE_DIR / ".venv"

# ANSI-Farben (Windows 10+ unterstützt das)
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str):    print(f"{GREEN}  ✓ {msg}{RESET}")
def warn(msg: str):  print(f"{YELLOW}  ⚠ {msg}{RESET}")
def err(msg: str):   print(f"{RED}  ✗ {msg}{RESET}")
def info(msg: str):  print(f"{CYAN}  → {msg}{RESET}")
def header(msg: str): print(f"\n{BOLD}{msg}{RESET}\n{'─' * 50}")


def check_python():
    header("1. Python-Version prüfen")
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        err(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ benötigt, gefunden: {v.major}.{v.minor}")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro} ({platform.system()})")


def create_venv():
    header("2. Virtuelle Umgebung erstellen")
    if VENV_DIR.exists():
        warn(f"Venv existiert bereits: {VENV_DIR}")
        return
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    ok(f"Venv erstellt: {VENV_DIR}")


def get_venv_python() -> str:
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "python.exe")
    return str(VENV_DIR / "bin" / "python")


def get_venv_pip() -> str:
    if platform.system() == "Windows":
        return str(VENV_DIR / "Scripts" / "pip.exe")
    return str(VENV_DIR / "bin" / "pip")


def install_dependencies():
    header("3. Abhängigkeiten installieren")
    pip = get_venv_pip()
    req = BASE_DIR / "requirements.txt"
    info(f"pip install -r {req}")
    result = subprocess.run(
        [pip, "install", "--upgrade", "pip", "-q"],
        capture_output=True
    )
    result = subprocess.run(
        [pip, "install", "-r", str(req)],
        capture_output=False
    )
    if result.returncode != 0:
        err("Installation fehlgeschlagen!")
        sys.exit(1)
    ok("Alle Pakete installiert")


def create_env_file():
    header("4. .env Konfiguration")
    env_file = BASE_DIR / ".env"
    example_file = BASE_DIR / ".env.example"

    if env_file.exists():
        warn(".env existiert bereits — wird nicht überschrieben")
        return

    if not example_file.exists():
        err(".env.example nicht gefunden!")
        return

    shutil.copy(example_file, env_file)
    ok(f".env erstellt: {env_file}")
    warn("Bitte .env mit deinen API-Keys befüllen!")


def create_directories():
    header("5. Verzeichnisse anlegen")
    dirs = [
        BASE_DIR / "data_store",
        BASE_DIR / "logs",
        BASE_DIR / "ai",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        ok(f"{d.relative_to(BASE_DIR)}/")


def init_database():
    header("6. Datenbank initialisieren")
    python = get_venv_python()
    result = subprocess.run(
        [python, "-c",
         "import sys; sys.path.insert(0, '.'); "
         "from monitoring.logger import init_db; init_db(); print('OK')"],
        cwd=BASE_DIR,
        capture_output=True, text=True,
    )
    if "OK" in result.stdout:
        ok("SQLite Datenbank initialisiert")
    else:
        warn(f"DB-Init Ausgabe: {result.stderr[:200]}")


def verify_installation():
    header("7. Installation verifizieren")
    python = get_venv_python()
    checks = [
        ("ccxt", "ccxt"),
        ("pandas", "pandas"),
        ("xgboost", "xgboost"),
        ("anthropic", "anthropic"),
        ("rich", "rich"),
        ("sklearn", "sklearn"),
    ]
    all_ok = True
    for name, module in checks:
        result = subprocess.run(
            [python, "-c", f"import {module}; print({module}.__version__)"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok(f"{name} {result.stdout.strip()}")
        else:
            err(f"{name} fehlt!")
            all_ok = False
    return all_ok


def print_next_steps():
    header("Installation abgeschlossen!")

    activate = ""
    if platform.system() == "Windows":
        activate = f".venv\\Scripts\\activate"
    else:
        activate = f"source .venv/bin/activate"

    print(f"""
{BOLD}Nächste Schritte:{RESET}

  {YELLOW}1. API-Keys eintragen:{RESET}
     Öffne {BASE_DIR / '.env'} und trage deine Keys ein.

  {YELLOW}2. Virtuelle Umgebung aktivieren:{RESET}
     {activate}

  {YELLOW}3. ML-Modell trainieren (einmalig, ~2-5 Min):{RESET}
     python -m ai.trainer

  {YELLOW}4. Backtest ausführen:{RESET}
     python backtest_run.py

  {YELLOW}5. Paper Trading starten:{RESET}
     python bot.py

  {YELLOW}6. Optional — Docker (produktionsreif):{RESET}
     docker compose up -d

{GREEN}Tipp:{RESET} Starte immer mit TRADING_MODE=paper in der .env
      Mindestens 2-3 Monate Paper Trading vor echtem Geld!
""")


def main():
    print(f"\n{BOLD}{'='*50}")
    print("   Trading Bot — Installations-Routine")
    print(f"   Platform: {platform.system()} {platform.machine()}")
    print(f"{'='*50}{RESET}")

    check_python()
    create_venv()
    install_dependencies()
    create_env_file()
    create_directories()
    init_database()
    success = verify_installation()

    if success:
        print_next_steps()
    else:
        err("Installation unvollständig — bitte Fehler oben prüfen")
        sys.exit(1)


if __name__ == "__main__":
    main()
