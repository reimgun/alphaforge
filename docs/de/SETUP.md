# Erweiterte Einrichtung

[🇬🇧 English](../en/SETUP.md)

---

> **Neu hier?** Die vollständige Schritt-für-Schritt Installationsanleitung für alle Plattformen  
> (Mac, Windows, QNAP, Server) findest du hier:  
> **→ [INSTALL.md](INSTALL.md)**

Diese Seite enthält erweiterte Einrichtungsoptionen und Hintergrundinformationen.

---

## Binance API-Keys einrichten (nur für Live-Trading)

> Für Paper Trading keine API-Keys nötig!

1. Auf [binance.com](https://binance.com) anmelden
2. Profil → **API Management** → **API erstellen**
3. Berechtigungen: nur **Spot & Margin Trading** aktivieren
4. **Auszahlungen: NIEMALS aktivieren**
5. IP-Beschränkung: eigene IP eintragen (empfohlen)
6. API Key + Secret in `.env` eintragen:

```env
BINANCE_API_KEY=dein_key
BINANCE_API_SECRET=dein_secret
TRADING_MODE=live
```

---

## Auto-Training beim ersten Start

Wenn `AI_MODE=ml` oder `combined` gesetzt ist und noch kein Modell existiert:

```
Bot gestartet
     ↓
Kein Modell gefunden (ai/model.joblib)
     ↓
730 Tage Daten laden (oder aus Cache)
     ↓
XGBoost + Walk-Forward Validierung (~3–5 Min)
     ↓
Modell gespeichert → Trading startet
```

Du musst nichts tun — einfach warten.

---

## Manuelles Training

```bash
make train
```

Oder auf QNAP trainieren + übertragen:
```bash
make train-qnap QNAP=admin@YOUR_QNAP_IP
```

---

## Live Trading aktivieren

### Option A — Manuell

```env
TRADING_MODE=live
BINANCE_API_KEY=dein_key
BINANCE_API_SECRET=dein_secret
```

### Option B — Automatisch (empfohlen)

Der Bot schlägt den Wechsel zu Live vor wenn alle Kriterien erfüllt sind.  
Du bekommst eine Telegram-Nachricht und bestätigst mit `/approve_live`.

**Empfehlung:** Mindestens 2–3 Monate Paper Trading. Starte mit kleinem Betrag.

---

## Verschlüsselte API-Keys (empfohlen für Server)

```bash
# Verschlüsseln (einmalig)
python -m config.crypto_config --encrypt
# Erstellt .env.enc (sicher) + .env.key (geheim halten!)

# Status prüfen
python -m config.crypto_config --check
```

`.env.key` **niemals** ins Repository oder auf GitHub pushen.

---

## LSTM-Modell installieren (optional)

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Ohne PyTorch fällt das Modell automatisch auf einen MLP-Klassifikator zurück.  
Auf QNAP: **nicht installieren** — LSTM deaktivieren mit `FEATURE_LSTM=false`.

---

## System-Check

```bash
make check
```

Zeigt Status aller Komponenten: Pakete, Datenbank, Modell, API-Verbindung.
