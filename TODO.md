# myWealth — TODO

Stato delle milestone di [`docs/SPEC.md`](docs/SPEC.md) §11. Le decisioni prese durante lo sviluppo sono in SPEC §14.

## Milestone

| # | Contenuto | Stato | Commit |
|---|-----------|-------|--------|
| M0 | Scaffolding: server locale con token, istanza singola, SQLite con migrazioni, demo, layout, tema, "Esci" | ✅ Fatta | `3a615ce` |
| M1 | Conti e tipi di conto: CRUD, saldo calcolato, tabella in Home | ✅ Fatta | `badb547` |
| M2 | Operazioni: spese, entrate, trasferimenti, commissioni collegate, categorie, filtri e modifica | ✅ Fatta | `5738380` |
| M3 | Cambi valuta: Yahoo, cache, fallback offline, controvalori EUR | ✅ Fatta | `7aac5c6` |
| M4 | Salvadanaio: tassi con storico, interessi mensili idempotenti (maturazione giornaliera) | ✅ Fatta | `b8117aa` |
| M5 | Investimenti: porting da PortfolioTracker, liquidità vs investito, acquisti/vendite, sottoschede | ✅ Fatta | `c5b6fe7` |
| M6 | Home completa: card, totali, grafico storico | ✅ Fatta | `4cd7ce1` |
| M7 | Analytics | ✅ Fatta | `402edb2` |
| M8 | Import/export CSV-JSON, archivio `.mywealth`, backup automatici, primo avvio | ✅ Fatta | `ac4cc9a` |
| M9 | Avvio rapido: finestra app, collegamenti, chiusura per inattività, avvio con Windows | ✅ Fatta | `a70afca` |
| M10 | Impostazioni complete, rifiniture, README | ✅ Fatta | `e524d7c` |
| M11 | (Opzionale) PIN, mappature CSV per banche, import da PortfolioTracker | 🟡 Parziale | `0e1fbf7` |
| M11 | (Opzionale) Cifratura dei dati e dell'archivio | ⏸️ Rimandata | — |
| M12 | Finestra app in Brave (poi Edge, poi browser predefinito) | ✅ Fatta | `f13189f` |
| M13 | Smartphone, lato desktop: abbinamento QR, cartella in arrivo, import cifrato con deduplica | ✅ Fatta | `f080941` |
| M14 | App smartphone (PWA): inserimento offline, export cifrato, condivisione, GitHub Pages | ✅ Fatta | `184169a` |
| M15 | Importi oscurati: pulsante occhio, Ctrl+Shift+H, stato ricordato, "Avvia con importi oscurati"; PWA: occhio in Voci, Modifica/Elimina per voce | ✅ Fatta | — |

## Da fare

### Rimandato
- [ ] **Cifratura dei dati e dell'archivio `.mywealth`** (SPEC §2.3, §12.1, M11). Richiede una dipendenza compilata (`cryptography` o SQLCipher), da verificare con AppLocker/WDAC prima di adottarla. Per ora la protezione "a riposo" è BitLocker.

### Da verificare sul PC reale (non provabile in sviluppo)
- [ ] Download reale da Yahoo Finance di cambi e prezzi (nei test e in demo la rete è sempre disattivata).
- [ ] Ricerca asset su Yahoo per ticker, ISIN e nome.
- [ ] `uv run mywealth --install-shortcuts`: voce nel menu Start, collegamento sul desktop, icona.
- [ ] Fallback `--vbs` se `mywealth-gui.exe` è bloccato da AppLocker/WDAC.
- [ ] Apertura in finestra Edge (`--app`) e riapertura della finestra con l'app già in esecuzione.
- [ ] Chiusura automatica dopo N minuti senza finestre aperte.
- [ ] Avvio con Windows (collegamento in Esecuzione automatica).
- [ ] Trasferimento su un altro PC: "Esporta tutto" → "Importa tutto" dalla schermata di primo avvio.
- [ ] Finestra app in Brave (anche con Shields attivo) e ripiego su Edge se Brave non c'è.
- [ ] Cartella Download reale come cartella in arrivo (anche se spostata su un altro disco).

### Importi oscurati (da verificare a mano in `--demo`)
- [ ] Pulsante occhio e Ctrl+Shift+H su tutte le schede, in tema chiaro e scuro e a finestra stretta (la verifica nel browser non è stata possibile durante lo sviluppo).
- [ ] Ctrl+Shift+H non in conflitto con Brave/Edge in modalità app.
- [ ] Stato ricordato dopo la riapertura; "Avvia con importi oscurati" ha la precedenza.
- [ ] PWA 1.1.0: occhio visibile solo in Voci e ricordato dopo il riavvio dell'app; pulsanti Modifica/Elimina sulle voci in sospeso (tema chiaro/scuro); banner "Aggiornamento disponibile" dopo la pubblicazione.

### Smartphone (da verificare sul telefono reale)
- [ ] Attivare GitHub Pages: repository → Settings → Pages → Source: **GitHub Actions**; poi push di `mobile/`.
- [ ] Installazione della PWA da Chrome Android e uso completamente offline (modalità aereo).
- [ ] Scansione del QR con la fotocamera (`BarcodeDetector`), anche con configurazione in più QR.
- [ ] "Esporta e invia" → Gmail con allegato `.txt`; download dell'allegato sul PC e import dalla cartella Download.
- [ ] Persistenza dei dati dopo riavvio del telefono (`navigator.storage.persist()`); avviso dopo 7 giorni senza export.
- [ ] Banner "Aggiornamento disponibile" dopo una nuova pubblicazione.

### Miglioramenti noti
- [ ] Import estratto conto: nell'anteprima i numeri di riga si riferiscono al CSV convertito, non alle righe del file della banca.
- [ ] Clic su una categoria in Analytics: il filtro delle Operazioni non considera il conto selezionato in Analytics.
- [ ] Demo: i rendimenti sintetici di alcuni asset sono negativi (solo estetica dei dati finti).
