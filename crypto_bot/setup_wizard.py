#!/usr/bin/env python3
"""
Trading Bot — Setup-Assistent
Führt dich in ca. 5 Minuten durch die komplette Einrichtung.
"""
import os
import sys
import subprocess
import platform
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Farben ────────────────────────────────────────────────────────────────────
G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"
def ok(m):    print(f"  {G}✓{X} {m}")
def warn(m):  print(f"  {Y}⚠{X} {m}")
def err(m):   print(f"  {R}✗{X} {m}")
def step(n, m): print(f"\n{B}── Schritt {n}: {m} {'─'*(40-len(str(m)))}{X}")
def ask(q, default=""):
    hint = f" [{default}]" if default else ""
    val  = input(f"  {C}→{X} {q}{hint}: ").strip()
    return val if val else default
def yn(q, default="j") -> bool:
    hint = "J/n" if default == "j" else "j/N"
    val  = input(f"  {C}→{X} {q} [{hint}]: ").strip().lower()
    if not val: val = default
    return val in ("j", "ja", "y", "yes")


# ── Exchange-Definitionen ──────────────────────────────────────────────────────
# (id, label, api_key_env, api_secret_env, extra_env, api_url)
SUPPORTED_EXCHANGES = {
    "1": ("binance",  "Binance",  "BINANCE_API_KEY",  "BINANCE_API_SECRET",  {},
          "https://www.binance.com/en/my/settings/api-management"),
    "2": ("bybit",    "Bybit",    "BYBIT_API_KEY",    "BYBIT_API_SECRET",    {},
          "https://www.bybit.com/app/user/api-management"),
    "3": ("okx",      "OKX",      "OKX_API_KEY",      "OKX_API_SECRET",      {"OKX_PASSPHRASE": ""},
          "https://www.okx.com/account/my-api"),
    "4": ("kraken",   "Kraken",   "KRAKEN_API_KEY",   "KRAKEN_API_SECRET",   {},
          "https://www.kraken.com/u/security/api"),
    "5": ("coinbase", "Coinbase", "COINBASE_API_KEY",  "COINBASE_API_SECRET", {},
          "https://www.coinbase.com/settings/api"),
    "6": ("gateio",   "Gate.io",  "GATEIO_API_KEY",   "GATEIO_API_SECRET",   {},
          "https://www.gate.io/myaccount/apiv4keys"),
    "7": ("kucoin",   "KuCoin",   "KUCOIN_API_KEY",   "KUCOIN_API_SECRET",   {"KUCOIN_PASSPHRASE": ""},
          "https://www.kucoin.com/account/api"),
    "8": ("bitget",   "Bitget",   "BITGET_API_KEY",   "BITGET_API_SECRET",   {"BITGET_PASSPHRASE": ""},
          "https://www.bitget.com/en/account/newapi"),
}


def header():
    print(f"""
{B}{'═'*52}
   Trading Bot — Setup-Assistent
   Multi-Exchange · Crypto & Forex · KI-gestützt
{'═'*52}{X}

Dieser Assistent richtet alles für dich ein:
  • Exchange-Auswahl und API-Keys
  • Handelsmodus (Paper / Testnet / Live)
  • Telegram-Benachrichtigungen (optional)
  • Hardware-Benchmark + automatische Feature-Konfiguration
  • ML-Modell Training (optional)

Credentials werden in {G}.env{X} im Projektordner gespeichert.
Auf macOS/Linux kannst du danach auch den System-Keychain nutzen.

Dauer: ca. 3–7 Minuten — danach kannst du sofort starten.
""")


# ── Schritt 1: Exchange ────────────────────────────────────────────────────────
def step_exchange() -> tuple[str, str, str, str, dict, str]:
    """Gibt zurück: (exc_id, label, key_env, secret_env, extra_env, api_url)"""
    step(1, "Exchange oder Broker wählen")
    print(f"\n  {B}Unterstützte Crypto-Exchanges:{X}\n")
    for key, (exc_id, label, key_env, secret_env, extra, url) in SUPPORTED_EXCHANGES.items():
        extras = ""
        if extra:
            extras = f"  {Y}(+ Passphrase){X}"
        print(f"  {B}{key}{X} — {label}{extras}")
    print(f"\n  {B}P{X} — Paper Trading (kein Exchange nötig, sofort starten)\n")

    choice = ask("Auswahl", default="P").strip().upper()
    if choice == "P" or choice not in SUPPORTED_EXCHANGES:
        ok("Paper Trading — kein Exchange-Account nötig")
        return "binance", "Paper Trading", "BINANCE_API_KEY", "BINANCE_API_SECRET", {}, ""

    exc_id, label, key_env, secret_env, extra, url = SUPPORTED_EXCHANGES[choice]
    ok(f"Exchange: {label}")
    if url:
        print(f"\n  API-Keys erstellen (Link öffnen):\n  {C}{url}{X}\n")
    return exc_id, label, key_env, secret_env, extra, url


# ── Schritt 2: Handelsmodus & API-Keys ────────────────────────────────────────
def step_trading_mode(exchange: str, label: str, key_env: str, secret_env: str,
                      extra_env: dict) -> tuple[str, str, str, dict]:
    """Gibt zurück: (mode, api_key, api_secret, extra_values)"""
    step(2, "Handelsmodus & API-Keys")
    print(f"""
  {B}1 — Paper Trading{X}   Lokale Simulation, virtuelles Geld
                      Kein API-Key nötig — sofort starten
                      {G}Empfohlen für den Einstieg{X}

  {B}2 — Testnet / Demo{X}  Virtuelles Geld, echtes Order-Buch
                      Empfohlen vor dem Live-Einsatz

  {B}3 — Live Trading{X}    Echtes Geld, echte Orders
                      Nur nach ausreichender Paper/Testnet-Phase!
""")
    print(f"  → Auswahl [1/2/3]: ", end="", flush=True)
    choice = input("").strip()

    api_key = api_secret = ""
    extra_values: dict = {}

    if choice == "2":
        testnet_urls = {
            "binance": "testnet.binance.vision (GitHub-Login)",
            "bybit":   "testnet.bybit.com",
            "okx":     "Demo-Account: okx.com/demo-trading",
        }
        hint = testnet_urls.get(exchange, "Testnet/Demo des gewählten Exchanges")
        print(f"\n  {Y}Testnet-Keys erstellen: {hint}{X}\n")
        api_key    = ask(f"{label} Testnet API Key")
        api_secret = ask(f"{label} Testnet API Secret")
        for env_var in extra_env:
            extra_values[env_var] = ask(f"{env_var.replace('_', ' ').title()}")
        mode = "testnet" if (api_key and api_secret) else "paper"
        if mode == "paper":
            warn("Keine Keys eingegeben → Paper-Modus wird verwendet")

    elif choice == "3":
        print(f"\n  {Y}{label} Live API-Keys:{X}")
        print(f"  Nur Spot-/Trading-Berechtigung aktivieren, NIEMALS Withdrawal!\n")
        api_key    = ask(f"{label} API Key")
        api_secret = ask(f"{label} API Secret")
        for env_var in extra_env:
            extra_values[env_var] = ask(f"{env_var.replace('_', ' ').title()}")
        mode = "live" if (api_key and api_secret) else "paper"
        if mode == "paper":
            warn("Keine API-Keys eingegeben → Paper-Modus wird verwendet")

    else:
        mode = "paper"
        ok("Paper Trading — kein API-Key nötig")

    ok(f"Modus: {mode.upper()}")
    return mode, api_key, api_secret, extra_values


# ── Schritt 3: Startkapital ────────────────────────────────────────────────────
def step_capital(mode: str) -> float:
    step(3, "Startkapital")
    unit = "echte USDT" if mode == "live" else "virtuelle USDT"
    print(f"  Wie viel Kapital soll der Bot verwenden? (in {unit})\n")
    while True:
        val = ask("Startkapital", default="1000")
        try:
            amount = float(val)
            if amount < 10:
                warn("Minimum: 10 USDT")
                continue
            real_warn = f"  {Y}Achtung: Echtes Geld!{X}\n" if mode == "live" else ""
            ok(f"Startkapital: {amount:.0f} USDT ({unit})\n{real_warn}")
            return amount
        except ValueError:
            warn("Bitte eine Zahl eingeben (z.B. 1000)")


# ── Schritt 4: KI-Modus ───────────────────────────────────────────────────────
def step_ai_mode() -> tuple[str, str, str, str]:
    step(4, "KI-Modus")
    print(f"""
  {B}1 — Nur ML{X} (empfohlen für den Start)
      XGBoost-Modell · kein API-Key nötig · 100% offline

  {B}2 — ML + LLM{X} (präziser, aber API-Key nötig)
      XGBoost + KI-Sprachmodell analysieren gemeinsam
      Nur BUY wenn beide einig → weniger Fehlsignale
""")
    print(f"  → Auswahl [1/2]: ", end="", flush=True)
    choice = input("").strip()

    if choice != "2":
        ok("KI-Modus: ML (XGBoost)")
        return "ml", "groq", "", ""

    print(f"""
  {B}LLM-Provider wählen:{X}

  {B}1 — Groq LLaMA{X}           Kostenlos, extrem schnell    — console.groq.com
  {B}2 — Claude{X} (Anthropic)   Beste Analyse               — anthropic.com
  {B}3 — GPT-4o-mini{X} (OpenAI) Sehr bekannt                — platform.openai.com
  {B}4 — Gemini Flash{X} (Google) Günstig                    — aistudio.google.com
  {B}5 — Ollama{X} (lokal)       Offline, kein API-Key       — ollama.ai
""")
    print(f"  → Provider [1/2/3/4/5]: ", end="", flush=True)
    p = input("").strip()

    provider_map = {"1": "groq", "2": "claude", "3": "openai", "4": "gemini", "5": "ollama"}
    provider = provider_map.get(p, "groq")

    key_name_map = {
        "groq":    ("Groq API Key",       "GROQ_API_KEY"),
        "claude":  ("Anthropic API Key",  "ANTHROPIC_API_KEY"),
        "openai":  ("OpenAI API Key",     "OPENAI_API_KEY"),
        "gemini":  ("Google API Key",     "GOOGLE_API_KEY"),
        "ollama":  (None,                 None),
    }

    label, env_var = key_name_map[provider]

    if provider == "ollama":
        ok("Provider: Ollama (lokal) — kein API-Key nötig")
        ollama_host = ask("Ollama Host", default="http://localhost:11434")
        return "combined", "ollama", "", ollama_host

    api_key = ask(f"{label}")
    if not api_key:
        warn("Kein Key eingegeben → nur ML wird verwendet")
        return "ml", "groq", "", ""

    ok(f"KI-Modus: ML + {provider.upper()}")
    return "combined", provider, api_key, ""


# ── Schritt 5: Telegram ───────────────────────────────────────────────────────
def step_telegram() -> tuple[str, str]:
    step(5, "Telegram Benachrichtigungen (optional)")
    print(f"""
  Push-Nachrichten bei jedem Trade, Fehler und täglich.
  Auch: /status und /stop Befehle direkt per Chat steuern.

  {Y}Einrichten:{X}
  1. @BotFather in Telegram → /newbot → Token kopieren
  2. @userinfobot → Chat-ID kopieren
""")
    use_tg = yn("Telegram einrichten?", default="n")

    token = chat_id = ""
    if use_tg:
        token   = ask("Telegram Bot Token (von @BotFather)")
        chat_id = ask("Telegram Chat-ID (von @userinfobot)")
        if token and chat_id:
            ok("Telegram konfiguriert")
        else:
            warn("Unvollständig → Telegram deaktiviert")
            token = chat_id = ""

    return token, chat_id


# ── Schritt 6: .env schreiben ─────────────────────────────────────────────────
def write_env(exchange: str, mode: str, key_env: str, secret_env: str,
              api_key: str, api_secret: str, extra_values: dict,
              capital: float, ai_mode: str, ai_provider: str,
              llm_api_key: str, ollama_host: str,
              tg_token: str, tg_chat: str) -> Path:
    step(6, "Konfiguration speichern")

    provider_key_map = {
        "groq":    f"GROQ_API_KEY={llm_api_key}",
        "claude":  f"ANTHROPIC_API_KEY={llm_api_key}",
        "openai":  f"OPENAI_API_KEY={llm_api_key}",
        "gemini":  f"GOOGLE_API_KEY={llm_api_key}",
        "ollama":  f"OLLAMA_HOST={ollama_host or 'http://localhost:11434'}",
    }
    llm_key_line = provider_key_map.get(ai_provider, f"GROQ_API_KEY={llm_api_key}")

    extra_lines = "\n".join(f"{k}={v}" for k, v in extra_values.items())

    env_path = BASE_DIR.parent / ".env"
    content = f"""# Trading Bot Konfiguration — erstellt vom Setup-Assistenten
# Nicht ins Git committen! (steht in .gitignore)

# ── Handelsmodus ──────────────────────────────────────────────
TRADING_MODE={mode}
INITIAL_CAPITAL={capital:.0f}

# ── Exchange ──────────────────────────────────────────────────
EXCHANGE={exchange}
{key_env}={api_key}
{secret_env}={api_secret}
{extra_lines}

# ── KI ────────────────────────────────────────────────────────
AI_MODE={ai_mode}
AI_PROVIDER={ai_provider}
AI_MODEL=
{llm_key_line}

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_TOKEN={tg_token}
TELEGRAM_CHAT_ID={tg_chat}

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL=INFO
TIMEFRAME=1h
TREND_TIMEFRAME=4h
"""
    env_path.write_text(content, encoding="utf-8")
    ok(f".env gespeichert: {env_path}")

    # Hinweis auf Credential-Speicherort
    _print_cred_info(env_path, api_key)
    return env_path


def _print_cred_info(env_path: Path, api_key: str) -> None:
    """Zeigt dem User wo die Credentials liegen und wie er sie sicherer speichern kann."""
    if not api_key:
        return
    sys_name = platform.system()
    print(f"""
  {Y}Credentials-Speicherort:{X}
  Datei: {env_path}
  Format: Plaintext (.env) — nur für dich lesbar (chmod 600 empfohlen)

  {B}Sicherere Alternativen (optional):{X}""")
    if sys_name == "Darwin":
        print(f"""  • macOS Keychain: {C}secret-tool store --label "trading-bot" key binance_api{X}
    → Dann BINANCE_API_KEY=@keychain in .env eintragen
    → SecretProvider erkennt das automatisch""")
    elif sys_name == "Windows":
        print(f"""  • Windows Credential Manager (automatisch erkannt):
    {C}cmdkey /add:trading-bot /user:binance_api /pass:DEIN_KEY{X}
    → SecretProvider erkennt Windows Credential Store automatisch""")
    else:
        print(f"""  • pass (GPG): {C}pass insert trading-bot/binance-api-key{X}
    → Dann scripts/gen-env.sh nutzen für verschlüsselte Secrets
  • AWS/Azure/Vault: SecretProvider unterstützt alle Enterprise-Backends""")
    print()


# ── Schritt 7: Pakete installieren ────────────────────────────────────────────
def step_install() -> bool:
    step(7, "Pakete installieren")
    is_win = platform.system() == "Windows"
    venv   = BASE_DIR.parent / (".venv/Scripts/python.exe" if is_win else ".venv/bin/python")

    if not venv.exists():
        print(f"  Erstelle virtuelle Umgebung ...")
        subprocess.run([sys.executable, "-m", "venv", str(BASE_DIR.parent / ".venv")], check=True)
        ok("Virtuelle Umgebung erstellt")

    pip = BASE_DIR.parent / (".venv/Scripts/pip" if is_win else ".venv/bin/pip")
    req = BASE_DIR.parent / "requirements.txt"
    print(f"  Installiere Pakete (einmalig, ca. 1–3 Minuten) ...")
    result = subprocess.run([str(pip), "install", "-r", str(req), "-q"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        err("Installation fehlgeschlagen:")
        print(result.stderr[-800:])
        return False

    ok("Alle Pakete installiert")
    return True


# ── Schritt 8: Hardware-Benchmark ─────────────────────────────────────────────
def step_benchmark() -> dict:
    step(8, "Hardware-Benchmark")
    print(f"  Analysiert dein System und setzt die optimalen Feature-Flags.")
    print(f"  Dauert ca. 10 Sekunden ...\n")
    try:
        is_win = platform.system() == "Windows"
        python = BASE_DIR.parent / (".venv/Scripts/python.exe" if is_win else ".venv/bin/python")
        result = subprocess.run(
            [str(python), "-m", "crypto_bot.benchmark"],
            cwd=BASE_DIR.parent, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            ok("Benchmark abgeschlossen — Feature-Profil gespeichert")
            # Empfehlung aus output lesen
            for line in result.stdout.splitlines():
                if "FEATURE_" in line or "Empfehlung" in line.title():
                    print(f"    {line.strip()}")
            return {}
        else:
            warn("Benchmark übersprungen (wird beim ersten Start ausgeführt)")
    except Exception:
        warn("Benchmark übersprungen (wird beim ersten Start ausgeführt)")
    return {}


# ── Schritt 9: ML-Training ────────────────────────────────────────────────────
def step_train() -> bool:
    print(f"\n  {B}ML-Modell trainieren{X}")
    print(f"  Lädt ca. 2 Jahre Marktdaten · Dauer: 3–5 Minuten")
    train = yn("Jetzt trainieren?", default="j")

    if not train:
        warn("Übersprungen — vor dem ersten Start nachholen: make crypto-train")
        return False

    is_win = platform.system() == "Windows"
    python = BASE_DIR.parent / (".venv/Scripts/python.exe" if is_win else ".venv/bin/python")
    print(f"\n  Training läuft ...")
    result = subprocess.run([str(python), "-m", "crypto_bot.ai.trainer"], cwd=BASE_DIR.parent)
    if result.returncode == 0:
        ok("Modell trainiert und gespeichert")
        return True
    warn("Training fehlgeschlagen — nachholen mit: make crypto-train")
    return False


# ── DB initialisieren ─────────────────────────────────────────────────────────
def step_init_db():
    is_win = platform.system() == "Windows"
    python = BASE_DIR.parent / (".venv/Scripts/python.exe" if is_win else ".venv/bin/python")
    result = subprocess.run(
        [str(python), "-c",
         "import sys; sys.path.insert(0,'.'); "
         "from crypto_bot.monitoring.logger import init_db; init_db()"],
        cwd=BASE_DIR.parent, capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Datenbank initialisiert")
    else:
        warn("Datenbank-Init übersprungen (wird beim ersten Start erstellt)")


# ── Zusammenfassung ───────────────────────────────────────────────────────────
def print_summary(exchange: str, mode: str, capital: float, ai_mode: str,
                  ai_provider: str, tg_ok: bool, model_ok: bool):
    is_win  = platform.system() == "Windows"
    activate = ".venv\\Scripts\\activate" if is_win else "source .venv/bin/activate"
    ki_label = "ML (XGBoost)" if ai_mode == "ml" else f"ML + {ai_provider.upper()}"

    print(f"""
{B}{'═'*52}
   Setup abgeschlossen!
{'═'*52}{X}

  Exchange:  {exchange.upper()}
  Modus:     {mode.upper()} {"(virtuelles Geld)" if mode == "paper" else "(ECHTES GELD!)"}
  Kapital:   {capital:.0f} USDT
  KI:        {ki_label}
  Telegram:  {"✓ aktiv" if tg_ok else "— nicht konfiguriert"}
  ML-Modell: {"✓ bereit" if model_ok else Y + "⚠  noch trainieren" + X}

{B}Manuell starten:{X}
  {activate}
  make crypto-start

{B}Alle Befehle:{X}
  make help              — Übersicht aller Befehle
  make crypto-backtest   — Backtest auf historischen Daten
  make crypto-dashboard  — Web-Dashboard (Port 8501)
  make crypto-deploy     — Auf QNAP / Server deployen

{Y}Tipp:{X} Lass den Bot mindestens 2–3 Monate im Paper-Modus laufen,
bevor du echtes Geld einsetzt.
""")


# ── Bot starten ───────────────────────────────────────────────────────────────
def step_launch_bot() -> None:
    is_win  = platform.system() == "Windows"
    python  = BASE_DIR.parent / (".venv/Scripts/python.exe" if is_win else ".venv/bin/python")
    if not python.exists():
        warn("Venv nicht gefunden — starte mit: make crypto-start")
        return

    print(f"  {B}Bot jetzt starten?{X}  (Paper-Modus: kein echtes Geld)\n")
    start = yn("Bot direkt starten?", default="j")
    if not start:
        print(f"\n  Starte später mit:  {G}make crypto-start{X}  oder  {G}bash install.sh{X}\n")
        return

    print(f"\n  {G}Bot startet …{X}  (Beenden: Strg+C)\n")
    try:
        subprocess.run([str(python), "-m", "crypto_bot.bot"], cwd=BASE_DIR.parent)
    except KeyboardInterrupt:
        print(f"\n\n  {Y}Bot gestoppt.{X}\n")


# ── Hauptprogramm ─────────────────────────────────────────────────────────────
def main():
    header()
    try:
        exc_id, exc_label, key_env, secret_env, extra_env, _ = step_exchange()
        mode, api_key, api_secret, extra_values               = step_trading_mode(
            exc_id, exc_label, key_env, secret_env, extra_env)
        capital                                                = step_capital(mode)
        ai_mode, ai_provider, llm_key, ollama_host            = step_ai_mode()
        tg_token, tg_chat                                      = step_telegram()

        write_env(
            exc_id, mode, key_env, secret_env, api_key, api_secret, extra_values,
            capital, ai_mode, ai_provider, llm_key, ollama_host,
            tg_token, tg_chat,
        )

        install_ok = step_install()
        if install_ok:
            step_benchmark()
            step_init_db()
            model_ok = step_train()
        else:
            model_ok = False

        print_summary(exc_id, mode, capital, ai_mode, ai_provider,
                      bool(tg_token), model_ok)

        if install_ok:
            step_launch_bot()

    except KeyboardInterrupt:
        print(f"\n\n{Y}Setup abgebrochen. Starte erneut mit:  bash install.sh{X}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
