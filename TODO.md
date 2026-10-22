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

### Miglioramenti noti
- [ ] Import estratto conto: nell'anteprima i numeri di riga si riferiscono al CSV convertito, non alle righe del file della banca.
- [ ] Clic su una categoria in Analytics: il filtro delle Operazioni non considera il conto selezionato in Analytics.
- [ ] Demo: i rendimenti sintetici di alcuni asset sono negativi (solo estetica dei dati finti).
