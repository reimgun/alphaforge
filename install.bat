@echo off
setlocal EnableDelayedExpansion
:: ─────────────────────────────────────────────────────────────────
:: Trading Bot — One-Click Installation & Start (Windows)
::
:: Verwendung: Doppelklick auf install.bat
::
:: Beim ersten Mal:  Assistent → installieren → Bot starten
:: Beim zweiten Mal: direkt Bot starten (oder Einstellungen ändern)
:: ─────────────────────────────────────────────────────────────────

echo.
echo ════════════════════════════════════════════
echo    Trading Bot
echo ════════════════════════════════════════════
echo.

set SCRIPT_DIR=%~dp0
set VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe
set ENV_FILE=%SCRIPT_DIR%.env

:: ── Bereits installiert? ─────────────────────────────────────────
if exist "%VENV_PYTHON%" if exist "%ENV_FILE%" (
    echo   OK  Installation gefunden
    echo.
    echo   Was moechtest du tun?
    echo.
    echo     1   Bot starten  ^(Paper-Modus -- kein echtes Geld^)
    echo     2   Einstellungen aendern  ^(API-Keys, Kapital, Telegram...^)
    echo     3   Beenden
    echo.
    set /p CHOICE="  Auswahl [1]: "
    if "!CHOICE!"=="" set CHOICE=1

    if "!CHOICE!"=="1" goto :start_bot
    if "!CHOICE!"=="2" goto :run_wizard
    if "!CHOICE!"=="3" goto :end
    goto :start_bot
)

:: ── Python suchen ────────────────────────────────────────────────
set PYTHON=
for %%p in (python3 python py) do (
    where %%p >nul 2>&1
    if not errorlevel 1 (
        %%p -c "import sys; exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set PYTHON=%%p
            goto :python_found
        )
    )
)

echo   [FEHLER] Python 3.10+ nicht gefunden.
echo.
echo   Bitte installieren:
echo     https://python.org/downloads
echo     Beim Installieren "Add Python to PATH" ankreuzen!
echo.
pause
exit /b 1

:python_found
for /f "tokens=*" %%v in ('%PYTHON% --version') do echo   OK: %%v
echo.

:run_wizard
%PYTHON% "%SCRIPT_DIR%crypto_bot\setup_wizard.py"
if errorlevel 1 (
    echo.
    echo   [FEHLER] Setup fehlgeschlagen. Bitte Ausgabe oben pruefen.
    pause
    exit /b 1
)
goto :end

:start_bot
echo.
echo   Bot startet...
echo.
"%VENV_PYTHON%" -m crypto_bot.bot

:end
echo.
pause
