# Trading Bot — Windows PowerShell Installer (nativ, kein WSL2 nötig)
# Aufruf: Rechtsklick → "Mit PowerShell ausführen"
#         ODER in PowerShell: .\install.ps1
#
# Was dieses Skript macht:
#   1. Python 3.10+ prüfen / installieren (via winget)
#   2. Virtuelle Umgebung (.venv) anlegen
#   3. Abhängigkeiten installieren (requirements.txt)
#   4. Setup-Assistent starten (Exchange, Kapital, Telegram ...)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GREEN  = [System.ConsoleColor]::Green
$YELLOW = [System.ConsoleColor]::Yellow
$RED    = [System.ConsoleColor]::Red
$RESET  = [System.ConsoleColor]::White

function Write-Ok   { param($msg) Write-Host "  $([char]0x2713)  $msg" -ForegroundColor $GREEN }
function Write-Info { param($msg) Write-Host "  $msg" -ForegroundColor $YELLOW }
function Write-Err  { param($msg) Write-Host "  $([char]0x2717)  $msg" -ForegroundColor $RED }

Clear-Host
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║     AI Trading Bot — Windows Setup       ║" -ForegroundColor Cyan
Write-Host "  ║     Crypto + Forex + Equities            ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Execution Policy ──────────────────────────────────────────────────────────
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted") {
    Write-Info "Setze Execution Policy auf RemoteSigned ..."
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    Write-Ok "Execution Policy gesetzt"
}

# ── Python prüfen ─────────────────────────────────────────────────────────────
Write-Info "Prüfe Python 3.10+ ..."

$PYTHON = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print('ok' if sys.version_info >= (3,10) else 'old')" 2>$null
        if ($ver -eq "ok") {
            $PYTHON = $cmd
            $pyver  = & $cmd --version 2>&1
            Write-Ok "$pyver gefunden ($cmd)"
            break
        }
    } catch {}
}

if (-not $PYTHON) {
    Write-Info "Python nicht gefunden — installiere via winget ..."
    try {
        winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $PYTHON = "python"
        Write-Ok "Python 3.12 installiert"
        Write-Info "Starte PowerShell-Fenster neu und fuhre install.ps1 erneut aus."
        Write-Host ""
        Write-Host "  Druecke Enter zum Schliessen ..."
        Read-Host
        exit 0
    } catch {
        Write-Err "winget nicht verfuegbar. Bitte Python manuell installieren:"
        Write-Host "  https://python.org/downloads"
        Write-Host "  Wichtig: Haken bei 'Add Python to PATH' setzen!"
        Write-Host ""
        Write-Host "  Druecke Enter zum Schliessen ..."
        Read-Host
        exit 1
    }
}

# ── Virtuelle Umgebung ────────────────────────────────────────────────────────
Write-Info "Erstelle virtuelle Umgebung (.venv) ..."
if (-not (Test-Path ".venv")) {
    & $PYTHON -m venv .venv
    Write-Ok "Virtuelle Umgebung erstellt"
} else {
    Write-Ok "Virtuelle Umgebung bereits vorhanden"
}

$PIP    = ".venv\Scripts\pip.exe"
$PYTHON = ".venv\Scripts\python.exe"

# ── Abhängigkeiten ────────────────────────────────────────────────────────────
Write-Info "Installiere Abhängigkeiten (kann 2-5 Minuten dauern) ..."
& $PIP install --upgrade pip --quiet
& $PIP install -r requirements.txt --quiet
Write-Ok "Abhängigkeiten installiert"

# ── Verzeichnisse ─────────────────────────────────────────────────────────────
$dirs = @("data_store", "logs", "crypto_bot\ai", "reports", "forex_bot\logs")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
Write-Ok "Verzeichnisse erstellt"

# ── Setup-Assistent ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ─────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Setup-Assistent" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host ""

& $PYTHON crypto_bot\setup_wizard.py

Write-Host ""
Write-Ok "Installation abgeschlossen!"
Write-Host ""
Write-Host "  Naechste Schritte:" -ForegroundColor Cyan
Write-Host "    Bot starten:      .venv\Scripts\python -m crypto_bot.bot" -ForegroundColor White
Write-Host "    Dashboard:        .venv\Scripts\python -m streamlit run crypto_bot\dashboard\app.py" -ForegroundColor White
Write-Host "    Alle Befehle:     make help   (erfordert GNU Make fuer Windows)" -ForegroundColor White
Write-Host ""
Write-Host "  Druecke Enter zum Schliessen ..."
Read-Host
