# Trading Bot — Makefile
ifeq ($(OS),Windows_NT)
    PYTHON := .venv\Scripts\python
    PIP    := .venv\Scripts\pip
else
    PYTHON := .venv/bin/python
    PIP    := .venv/bin/pip
endif

GPU_AVAILABLE := $(shell nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | grep -c . 2>/dev/null || echo 0)
GPU_FLAG      := $(if $(filter 1,$(GPU_AVAILABLE)),--gpu,)
TRAIN_GPU_ENV := $(if $(filter 1,$(GPU_AVAILABLE)),TRAIN_USE_GPU=1,)

QNAP ?= admin@YOUR_QNAP_IP

.DEFAULT_GOAL := help

.PHONY: help install setup \
        crypto-start crypto-train crypto-train-qnap crypto-backtest crypto-backtest-fast \
        crypto-backtest-wf crypto-backtest-wf-fast \
        crypto-deploy crypto-deploy-fast crypto-logs crypto-restart crypto-status \
        crypto-test crypto-test-cov crypto-dashboard crypto-api \
        forex-start forex-train forex-train-qnap forex-backtest \
        forex-deploy forex-deploy-fast forex-logs forex-restart forex-status \
        forex-test forex-test-cov \
        qnap-build qnap-stop qnap-stop-crypto qnap-stop-forex \
        qnap-deploy qnap-logs qnap-forex-logs \
        arm-build arm-deploy \
        pass-setup pass-secrets gen-env gen-env-forex gen-env-crypto \
        upgrade tax-journal tax-export tax-export-at \
        diagnose diagnose-qnap clean

# ── Sentinel ──────────────────────────────────────────────────────────────────
.venv/.deps_ok: requirements.txt
	@[ ! -d ".venv" ] && python3 -m venv .venv || true
	@$(PIP) install -q -r requirements.txt
	@touch .venv/.deps_ok

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Trading Bot"
	@echo "  ──────────────────────────────────────────────────────────────"
	@echo "  CRYPTO BOT"
	@grep -E '^crypto-[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  FOREX BOT"
	@grep -E '^forex-[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  QNAP / INFRASTRUKTUR"
	@grep -E '^qnap-[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  ARM / RASPBERRY PI"
	@grep -E '^arm-[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@grep -E '^(install|setup|clean|diagnose)[a-zA-Z_-]*:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  GPU: $(if $(filter 1,$(GPU_AVAILABLE)),\033[32mVerfügbar\033[0m,\033[33mNicht gefunden\033[0m)"
	@echo "  QNAP: $(QNAP)  (überschreiben: make <target> QNAP=admin@<IP>)"
	@echo ""

# ══════════════════════════════════════════════════════════════════════════════
# CRYPTO BOT
# ══════════════════════════════════════════════════════════════════════════════

crypto-start: .venv/.deps_ok  ## Crypto Bot lokal starten (paper mode)
	@$(PYTHON) -c "from pathlib import Path; exit(0 if Path('crypto_bot/ai/model.joblib').exists() else 1)" 2>/dev/null || \
		(echo "  Kein Modell — starte Training..." && $(TRAIN_GPU_ENV) $(PYTHON) -m crypto_bot.ai.trainer $(GPU_FLAG))
	$(PYTHON) -m crypto_bot.bot

crypto-train: .venv/.deps_ok  ## Crypto ML-Modell lokal trainieren
	$(TRAIN_GPU_ENV) $(PYTHON) -m crypto_bot.ai.trainer $(GPU_FLAG)

crypto-train-qnap: .venv/.deps_ok  ## Crypto Modell trainieren + auf QNAP deployen
	$(TRAIN_GPU_ENV) $(PYTHON) -m crypto_bot.ai.trainer $(GPU_FLAG)
	scp crypto_bot/ai/model.joblib $(QNAP):/share/CACHEDEV1_DATA/trading_bot/crypto_bot/ai/model.joblib
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker restart crypto-bot"
	@echo "  ✓ Crypto Bot läuft mit neuem Modell"

crypto-backtest: .venv/.deps_ok  ## Crypto AI-Pipeline Backtest (vollständig)
	$(PYTHON) -m crypto_bot.backtest_run --mode ai

crypto-backtest-fast: .venv/.deps_ok  ## Crypto AI-Backtest letzte 90 Tage
	$(PYTHON) -m crypto_bot.backtest_run --mode ai --days 90

crypto-backtest-wf: .venv/.deps_ok  ## Crypto Walk-Forward Backtest (Out-of-Sample Validierung)
	$(PYTHON) crypto_bot/walk_forward_run.py

crypto-backtest-wf-fast: .venv/.deps_ok  ## Crypto Walk-Forward (1 Jahr, 4 Fenster)
	$(PYTHON) -c "from crypto_bot.backtest.walk_forward import run_walk_forward; run_walk_forward(total_days=365, n_windows=4, train_ratio=0.7)"

forex-test: .venv/.deps_ok  ## Forex Integration Tests
	$(PYTHON) -m pytest forex_bot/tests/ -v --tb=short

forex-test-cov: .venv/.deps_ok  ## Forex Tests mit Coverage
	$(PYTHON) -m pytest forex_bot/tests/ -v --cov=forex_bot --cov-report=term-missing --tb=short

upgrade:  ## Bot upgraden: Backup + git pull + pip + DB-Migration + .env ergänzen
	bash scripts/upgrade.sh $(QNAP)

tax-journal: .venv/.deps_ok  ## FIFO Tax Journal anzeigen (DE/AT Steuer)
	@$(PYTHON) -c "\
import sys; sys.path.insert(0,'.'); \
from crypto_bot.reporting.tax_journal import get_tax_journal; \
j = get_tax_journal(); j.load_from_db(); \
r = j.get_report(); \
print(f'\n  Tax Journal: {r[\"trades_total\"]} Trades | Steuerpflichtig: {r[\"net_taxable\"]:+.2f} USDT | Steuerfrei: {r[\"net_exempt\"]:+.2f} USDT\n')"

tax-export: .venv/.deps_ok  ## FIFO Tax Journal als CSV exportieren (DE-Format, Elster-kompatibel)
	$(PYTHON) -c "\
import sys; sys.path.insert(0,'.'); \
from crypto_bot.reporting.tax_journal import get_tax_journal; \
j = get_tax_journal(); j.load_from_db(); \
j.export_csv('steuerjournal_de.csv', fmt='de'); print('  ✓ steuerjournal_de.csv')"

tax-export-at: .venv/.deps_ok  ## FIFO Tax Journal als CSV exportieren (AT-Format)
	$(PYTHON) -c "\
import sys; sys.path.insert(0,'.'); \
from crypto_bot.reporting.tax_journal import get_tax_journal; \
j = get_tax_journal(); j.load_from_db(); \
j.export_csv('steuerjournal_at.csv', fmt='at'); print('  ✓ steuerjournal_at.csv')"

crypto-deploy: .venv/.deps_ok  ## Crypto Bot auf QNAP deployen (mit Image-Rebuild)
	PYTHON="$(PYTHON)" bash deploy-crypto.sh $(QNAP)

crypto-deploy-fast: .venv/.deps_ok  ## Crypto Bot deployen ohne Image-Rebuild (nur Code-Update)
	PYTHON="$(PYTHON)" bash deploy-crypto.sh $(QNAP) --no-rebuild

crypto-logs:  ## Crypto Bot Live-Logs vom QNAP
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker logs -f crypto-bot"

crypto-restart:  ## Crypto-Container auf QNAP neu starten
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker restart crypto-bot trading-dashboard trading-streamlit 2>/dev/null; echo done"

crypto-status: .venv/.deps_ok  ## Letzte Trades + Performance (lokal)
	@$(PYTHON) -c "\
import sys; sys.path.insert(0,'.'); \
from crypto_bot.monitoring.logger import get_recent_trades, get_performance_summary; \
s = get_performance_summary(); \
print('\n  Crypto Performance'); \
print(f'  Trades: {s.get(\"total_trades\",0)} | Wins: {s.get(\"wins\",0)} | PnL: {s.get(\"total_pnl\",0):+.2f} USDT'); \
trades = get_recent_trades(5); \
print('\n  Letzte 5 Trades:') if trades else print('  Noch keine Trades.'); \
[print(f'  {t[\"side\"].upper():4} {t[\"symbol\"]} | PnL: {t[\"pnl\"]:+.2f} USDT') for t in trades]; \
print()"

crypto-test: .venv/.deps_ok  ## Crypto Integration Tests
	$(PYTHON) -m pytest crypto_bot/tests/ -v --tb=short

crypto-test-cov: .venv/.deps_ok  ## Crypto Tests mit Coverage
	$(PYTHON) -m pytest crypto_bot/tests/ -v --cov=crypto_bot --cov-report=term-missing --tb=short

crypto-dashboard: .venv/.deps_ok  ## Crypto Streamlit Dashboard starten (Port 8501)
	$(PYTHON) -m streamlit run crypto_bot/dashboard/app.py --server.port 8501

crypto-api: .venv/.deps_ok  ## Crypto FastAPI Backend starten (Port 8000)
	$(PYTHON) -m uvicorn crypto_bot.dashboard.api:app --host 0.0.0.0 --port 8000 --reload

# ══════════════════════════════════════════════════════════════════════════════
# FOREX BOT
# ══════════════════════════════════════════════════════════════════════════════

forex-start: .venv/.deps_ok  ## Forex Bot lokal starten (paper mode)
	$(PYTHON) -m forex_bot.bot

forex-train: .venv/.deps_ok  ## Forex XGBoost Modell lokal trainieren
	$(PYTHON) -m forex_bot.ai.trainer $(GPU_FLAG)

forex-train-qnap: .venv/.deps_ok  ## Forex Modell trainieren + auf QNAP deployen
	$(PYTHON) -m forex_bot.ai.trainer $(GPU_FLAG)
	scp forex_bot/ai/model.joblib $(QNAP):/share/CACHEDEV1_DATA/trading_bot/forex_bot/ai/model.joblib
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker restart forex-bot"
	@echo "  ✓ Forex Bot läuft mit neuem Modell"

forex-backtest: .venv/.deps_ok  ## Forex Walk-Forward Backtest
	$(PYTHON) -m forex_bot.backtest.walk_forward

forex-deploy:  ## Forex Bot auf QNAP deployen (kein Image-Rebuild)
	bash deploy-forex.sh $(QNAP)

forex-deploy-rebuild:  ## Forex Bot deployen + Docker Image neu bauen
	bash deploy-image.sh $(QNAP)
	bash deploy-forex.sh $(QNAP)

forex-logs:  ## Forex Bot Live-Logs vom QNAP
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker logs -f forex-bot"

forex-restart:  ## Forex-Container auf QNAP neu starten
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker restart forex-bot 2>/dev/null; echo done"

forex-status:  ## Forex Bot Status via API
	@curl -s http://$(shell echo "$(QNAP)" | sed 's/.*@//')):8001/api/status 2>/dev/null | \
	python3 -c "import sys,json; d=json.load(sys.stdin); \
	print(f'\n  Forex Status'); \
	print(f'  Broker: {d.get(\"broker\",\"?\")} | Modus: {d.get(\"mode\",\"?\")} | Kapital: {d.get(\"capital\",0):.0f}'); \
	print(f'  Offene Trades: {d.get(\"open_trades\",0)}'); \
	print()" 2>/dev/null || echo "  Forex API nicht erreichbar (http://$(shell echo "$(QNAP)" | sed 's/.*@//'):8001)"

# ══════════════════════════════════════════════════════════════════════════════
# QNAP / INFRASTRUKTUR
# ══════════════════════════════════════════════════════════════════════════════

qnap-build:  ## Docker Image auf QNAP neu bauen (beide Bots)
	bash deploy-image.sh $(QNAP)

qnap-build-streamlit:  ## Streamlit-Dashboard Image auf QNAP bauen + Container starten
	rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
		--exclude='*.pyc' --exclude='.env' --exclude='data_store/*.db' \
		--exclude='logs/*' --filter=':- .gitignore' \
		. $(QNAP):/share/CACHEDEV1_DATA/trading_bot/
	ssh $(QNAP) "DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; \
		cd /share/CACHEDEV1_DATA/trading_bot && \
		\$$DOCKER build -f Dockerfile.streamlit -t trading-streamlit:latest . 2>&1 | tail -5 && \
		\$$DOCKER stop trading-streamlit 2>/dev/null || true && \
		\$$DOCKER rm   trading-streamlit 2>/dev/null || true && \
		\$$DOCKER run -d --name trading-streamlit --restart unless-stopped \
			-p 8501:8501 \
			--network trading_bot_default \
			-e DASHBOARD_API_URL=http://trading-dashboard:8000 \
			-e FOREX_API_URL=http://forex-bot:8001 \
			trading-streamlit:latest && \
			\$$DOCKER network connect bridge trading-streamlit 2>/dev/null || true && \
		echo '✓ trading-streamlit gestartet auf Port 8501'"
	@echo "  ✓ Streamlit Dashboard: http://$(shell echo "$(QNAP)" | sed 's/.*@//'):8501"

qnap-stop:  ## ALLE Container auf QNAP stoppen
	ssh $(QNAP) "DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; \
	\$$DOCKER stop trading-bot trading-dashboard trading-streamlit forex-bot 2>/dev/null || true; \
	\$$DOCKER rm   trading-bot trading-dashboard trading-streamlit forex-bot 2>/dev/null || true; \
	echo 'Alle Container gestoppt'"

qnap-stop-crypto:  ## Nur Crypto-Container stoppen
	ssh $(QNAP) "DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; \
	\$$DOCKER stop trading-bot trading-dashboard trading-streamlit 2>/dev/null || true; echo done"

qnap-stop-forex:  ## Nur Forex-Container stoppen
	ssh $(QNAP) "DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; \
	\$$DOCKER stop forex-bot 2>/dev/null || true; echo done"

qnap-ps:  ## Alle laufenden Container auf QNAP anzeigen
	ssh $(QNAP) "/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

qnap-pull:  ## Code auf QNAP aktualisieren ohne Container-Rebuild
	rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
		--exclude='*.pyc' --exclude='.env' --exclude='**/.env' \
		--exclude='data_store/*.db' --exclude='logs/*' --filter=':- .gitignore' \
		. $(QNAP):/share/CACHEDEV1_DATA/trading_bot/
	ssh $(QNAP) "DOCKER=/share/CACHEDEV1_DATA/.qpkg/container-station/bin/docker; \
	\$$DOCKER restart trading-bot trading-dashboard trading-streamlit forex-bot 2>/dev/null; \
	\$$DOCKER network connect trading_bot_default forex-bot 2>/dev/null || true; \
	echo done"
	@echo "  ✓ Code aktualisiert, alle Container neu gestartet"

# ══════════════════════════════════════════════════════════════════════════════
# ARM / RASPBERRY PI
# ══════════════════════════════════════════════════════════════════════════════

ARM_PI ?= pi@raspberrypi.local
ARM_DIR ?= /home/pi/trading_bot

arm-build:  ## Raspberry Pi ARM64 Docker Image lokal bauen (benötigt docker buildx)
	docker buildx build --platform linux/arm64 -f Dockerfile.arm -t trading-bot:arm .
	@echo "  ✓ ARM64 Image gebaut: trading-bot:arm"

arm-deploy:  ## ARM Image + Code auf Raspberry Pi deployen
	@echo "  Übertrage Code auf $(ARM_PI):$(ARM_DIR) ..."
	rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
		--exclude='*.pyc' --exclude='.env' --exclude='data_store/*.db' \
		--exclude='logs/*' --filter=':- .gitignore' \
		. $(ARM_PI):$(ARM_DIR)/
	@echo "  Speichere Image und lade auf Pi ..."
	docker save trading-bot:arm | ssh $(ARM_PI) "docker load"
	ssh $(ARM_PI) "cd $(ARM_DIR) && \
		docker stop trading-bot 2>/dev/null || true && \
		docker rm   trading-bot 2>/dev/null || true && \
		docker run -d --name trading-bot --restart unless-stopped \
			-v $(ARM_DIR)/.env:/app/.env:ro \
			-v $(ARM_DIR)/data_store:/app/data_store \
			-v $(ARM_DIR)/logs:/app/logs \
			trading-bot:arm && \
		echo '✓ trading-bot läuft auf Raspberry Pi'"
	@echo "  ✓ Deployment abgeschlossen (PI: $(ARM_PI))"
	@echo "  → Überschreiben: make arm-deploy ARM_PI=pi@192.168.x.x"

# ══════════════════════════════════════════════════════════════════════════════
# PASS / SECRETS
# ══════════════════════════════════════════════════════════════════════════════

pass-setup:  ## GPG Key + Pass Store einmalig initialisieren
	bash scripts/setup-pass.sh

pass-secrets:  ## Secrets interaktiv in pass eintragen
	bash scripts/add-secrets.sh

gen-env:  ## .env aus pass neu generieren (beide Bots) — nur bei Änderung nötig
	bash scripts/gen-env.sh all

gen-env-forex:  ## forex_bot/.env aus pass neu generieren — nur bei Änderung nötig
	bash scripts/gen-env.sh forex

gen-env-crypto:  ## .env (Crypto) aus pass neu generieren — nur bei Änderung nötig
	bash scripts/gen-env.sh crypto

# ── Backward-Compat Aliases ───────────────────────────────────────────────────
qnap-deploy: crypto-deploy  ## [Alias] → crypto-deploy
qnap-logs:   crypto-logs    ## [Alias] → crypto-logs
qnap-forex-logs: forex-logs ## [Alias] → forex-logs
start:  crypto-start        ## [Alias] → crypto-start
train:  crypto-train        ## [Alias] → crypto-train
test:   crypto-test         ## [Alias] → crypto-test
backtest-ai: crypto-backtest ## [Alias] → crypto-backtest
backtest-ai-fast: crypto-backtest-fast ## [Alias] → crypto-backtest-fast

# ── Sonstige ──────────────────────────────────────────────────────────────────
install:  ## One-Click Installation
	@bash install.sh

setup:  ## Interaktiver Setup-Assistent
	$(PYTHON) crypto_bot/setup_wizard.py

diagnose: .venv/.deps_ok  ## Crypto Bot Diagnose lokal
	$(PYTHON) crypto_bot/scripts/diagnose.py --log-lines 150

diagnose-qnap: .venv/.deps_ok  ## Crypto Bot Diagnose via QNAP API
	$(PYTHON) crypto_bot/scripts/diagnose.py \
	    --api-url http://$(shell echo "$(QNAP)" | sed 's/.*@//')):8000 --log-lines 150

clean:  ## Cache und Logs aufräumen (.env und DB bleiben)
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	@find . -name "*.pyc" -delete 2>/dev/null; true
	@rm -f logs/*.log 2>/dev/null; true
	@echo "  Bereinigt."
