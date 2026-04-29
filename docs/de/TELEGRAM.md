# Telegram — Einrichtung & Befehle

[🇬🇧 English](../en/TELEGRAM.md)

---

Empfange Push-Nachrichten bei jedem Trade und steuere den Bot per Chat.

## Einrichtung (5 Minuten)

### Schritt 1 — Telegram-Bot erstellen

1. Telegram öffnen und `@BotFather` suchen
2. `/newbot` senden
3. Einen Namen eingeben (z.B. `Mein Trading Bot`)
4. Einen Benutzernamen eingeben (muss auf `_bot` enden, z.B. `mein_trading_bot`)
5. Den **Token** kopieren — sieht aus wie: `123456789:ABC-DEFGhijklmno`

### Schritt 2 — Deine Chat-ID ermitteln

1. `@userinfobot` in Telegram suchen und öffnen
2. `/start` senden
3. Die **ID** kopieren — eine Zahl wie: `987654321`

### Schritt 3 — In `.env` eintragen

```env
TELEGRAM_TOKEN=123456789:ABC-DEFGhijklmno
TELEGRAM_CHAT_ID=987654321
```

### Schritt 4 — Bot aktivieren

Sende deinem neuen Bot **einmalig** eine beliebige Nachricht in Telegram.  
Danach erscheinen alle Befehle automatisch als Menü wenn du `/` tippst.

---

## Automatische Benachrichtigungen

| Ereignis | Nachricht enthält |
|----------|------------------|
| Bot gestartet | Modus, Kapital |
| Trade geöffnet | Preis, Menge, Stop-Loss, Take-Profit, Grund |
| Trade geschlossen | Preis, PnL, Kapitalstand |
| Training abgeschlossen | Val-F1, Samples, Dauer |
| Auto-Retraining abgeschlossen | Neuer F1-Score |
| Strategie gewechselt | Alte → neue Strategie + Regime |
| Circuit Breaker ausgelöst | Tagesverlust erreicht |
| Max. Drawdown erreicht | Bot gestoppt — manuelle Prüfung nötig |
| Live-Trading bereit | Alle Kriterien erfüllt — wartet auf Bestätigung |
| Fehler aufgetreten | Fehlermeldung |
| Tagesbericht (00:00 UTC) | Tages-PnL, Anzahl Trades |

---

## Alle Befehle

### Status & Monitoring

| Befehl | Funktion |
|--------|---------|
| `/start` | Bot starten · aus Pause fortsetzen · Status anzeigen |
| `/stop` | Bot stoppen (wartet auf Ende des aktuellen Zyklus) |
| `/status` | Kapital, offene Position, Tages-PnL |
| `/trades` | Letzte 5 abgeschlossene Trades |
| `/performance` | Sharpe, Sortino, Win-Rate, Profit Factor, Drawdown |
| `/open_positions` | Aktuelle Position mit Entry / Stop-Loss / Take-Profit |
| `/model` | ML-Modell Info (F1-Score, Trainingsdatum, Alter) |
| `/rejections` | Letzte abgelehnte Trades mit Begründung |
| `/progress` | Fortschrittsbalken Paper → Testnet → Live |
| `/help` | Alle Befehle anzeigen |

### Trading-Kontrolle

| Befehl | Funktion |
|--------|---------|
| `/pause` | Trading pausieren (Bot läuft, handelt aber nicht) |
| `/resume` | Trading fortsetzen |
| `/emergency_shutdown` | Sofort stoppen |
| `/approve_live` | Live-Trading nach Benachrichtigung bestätigen |
| `/retrain_models` | Modell sofort neu trainieren |
| `/switch_safe_mode` | Safe Mode ein/aus — Positionsgröße auf 50% |
| `/set_mode conservative` | Konservativ: 1% Risiko/Trade, 10% Max-Drawdown |
| `/set_mode balanced` | Standard: 2% Risiko/Trade, 20% Max-Drawdown |
| `/set_mode aggressive` | Aggressiv: 3% Risiko/Trade, 30% Max-Drawdown |

### Exposure Controller

| Befehl | Funktion |
|--------|---------|
| `/exposure_status` | Aktueller Risikomodus + Exposition in % |
| `/risk_off_mode` | Sofort in RISK_OFF wechseln (max. 15% Exposition) |
| `/resume_trading` | Aus RISK_OFF / EMERGENCY zurück in NORMAL |
| `/set_max_exposure 50` | Maximale Exposition auf 50% setzen |

---

## /progress im Detail

```
📊 Lernfortschritt: Paper → Testnet → Live

Phase: Paper Trading
Gesamt: ████████████░░░░░░░░  62%

Kriterien:
✅ Win-Rate:   51.2% / 48.0%   (100%)
✅ Drawdown:   8.3% / ≤15.0%   (100%)
✅ Model F1:   0.41 / 0.38     (100%)
🔄 Trades:     15 / 20         ( 75%)
🔄 Sharpe:     0.65 / 0.80     ( 81%)

💡 62% erreicht — Testnet-Wechsel bei 60% möglich
```

---

## Troubleshooting

**Keine Nachrichten empfangen**
- Hast du deinem Bot eine Nachricht gesendet? (Pflicht beim ersten Mal)
- Token und Chat-ID in `.env` korrekt eingetragen?
- `make check` ausführen

**Bot antwortet nicht auf Befehle**
- Läuft `bot.py` noch? → `make logs`
- Telegram-Token in `.env` korrekt?

**Befehle erscheinen nicht als Menü**
- Bot neu starten — dann erscheinen die Befehle beim nächsten `/`-Tippen
