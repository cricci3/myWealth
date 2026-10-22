# myWealth — Specifica funzionale

> Versione strutturata di `docs/REQUISITI_originali.txt`.
> Le voci marcate **[DECISIONE PROPOSTA]** colmano punti che il documento originale lasciava aperti:
> sono default ragionevoli, modificabili prima dello sviluppo. La sezione 0 elenca quelle che vanno confermate.

---

## 0. Decisioni aperte da confermare

| # | Tema | Proposta di default |
|---|------|---------------------|
| D1 | Protezione dati "a riposo" | Nessuna cifratura applicativa: dati in `%APPDATA%\myWealth\` + BitLocker di Windows + regole che impediscono a Claude Code di leggerli. Cifratura con password come milestone opzionale (vedi §2.3). |
| D2 | Lingua UI | Italiano; numeri in formato `it-IT` (`1.234,56`), input che accetta anche `1234.56`. Codice e commenti in inglese. |
| D3 | Interessi salvadanaio | Capitalizzazione mensile, accreditata come entrata automatica a fine mese (vedi §5.3). |
| D4 | Trasferimenti tra valute diverse | Si inseriscono entrambi gli importi (inviato e ricevuto); il secondo è precompilato col cambio Yahoo ma modificabile (vedi §6.3). |
| D5 | Acquisto asset senza liquidità sufficiente | Bloccato con messaggio d'errore (vedi §7.2). |
| D6 | Formato CSV di import | Formato proprio dell'app con template scaricabile; mappature per banche specifiche in seguito (vedi §9). |
| D7 | Codice di PortfolioTracker | Copiato e adattato dentro myWealth (licenza MIT, stesso autore), non usato come dipendenza. Import opzionale dei dati da `portfolio.json`. |
| D8 | Cambio PC | Un unico file archivio `.mywealth` con tutti i dati, esportato e importato con un pulsante; l'import sostituisce i dati, non li unisce (vedi §12). |
| D9 | Avvio rapido | Collegamenti nel menu Start e sul desktop, creati dall'app; finestra in stile app senza barra del browser; nessuna finestra di terminale (vedi §13). |

---

## 1. Obiettivo

Applicazione desktop personale per gestire conti, spese, entrate, trasferimenti e investimenti, con valori sempre riportati anche in EUR.
Gira in locale: un server Python su `127.0.0.1` apre la UI nel browser.

## 2. Vincoli non funzionali

### 2.1 Privacy
- Nessun dato finanziario esce dal computer. Il server ascolta solo su `127.0.0.1`.
- Uniche chiamate di rete: Yahoo Finance per cambi valuta e prezzi asset. Le richieste contengono **solo ticker/coppie valutarie e date, mai importi o nomi di conti**.
- Nessuna CDN, font esterni, analytics o servizi cloud: tutto il frontend è servito localmente.
- Impostazione "modalità offline" che disattiva ogni chiamata di rete.
- Claude Code non deve mai leggere i dati reali: lo sviluppo usa la modalità `--demo` (dati sintetici, nessuna rete) e database temporanei nei test. Le regole sono in `CLAUDE.md` e `.claude/settings.json`.

### 2.2 Sicurezza del server locale
- Bind esclusivo su `127.0.0.1`, controllo dell'header `Host` (contro DNS rebinding).
- Token casuale generato all'avvio e richiesto in un header (`X-MyWealth-Token`) su ogni chiamata API, come in PortfolioTracker.

### 2.3 Archiviazione **[DECISIONE PROPOSTA D1]**
- Database SQLite (`sqlite3` della libreria standard) in `%APPDATA%\myWealth\mywealth.db` su Windows, `~/.mywealth/` altrove. Cartella sovrascrivibile con la variabile `MYWEALTH_DATA_DIR`.
- Nota: `%APPDATA%` non è "non leggibile"; tiene i dati fuori dal repository e fuori dalla portata di Claude Code, ma qualsiasi programma eseguito dall'utente può leggerli. Per la protezione reale a riposo si raccomanda BitLocker.
- Alternativa opzionale (milestone M10): cifratura del database con password all'avvio. Da valutare perché richiede una dipendenza compilata (`cryptography`/SQLCipher), che può essere bloccata da AppLocker/WDAC sulla macchina.
- Backup automatico del database all'avvio (ultimi N, configurabile) in `%APPDATA%\myWealth\backups\`.
- Migrazioni di schema versionate (tabella `schema_version`).

### 2.4 Correttezza degli importi
- Importi salvati come **interi in unità minori** (centesimi), mai `float`. Calcoli con `Decimal`.
- Il saldo di un conto **non viene memorizzato**: è calcolato come `saldo iniziale + somma dei movimenti`. Così modifiche e cancellazioni di operazioni restano sempre coerenti.
- Ogni operazione salva il tasso di cambio verso EUR del suo giorno (snapshot), usato per tutti i report storici.

## 3. Stack tecnico

- Python ≥ 3.10, gestito con `uv` (`pyproject.toml` + `uv.lock`).
- Backend: server HTTP della libreria standard con API JSON (stesso approccio di PortfolioTracker). Nessun framework web con dipendenze compilate.
- Dati di mercato: `yfinance` + `pandas`; `numpy` fissato a `2.1.3` (versioni più recenti bloccate da AppLocker/WDAC).
- Frontend: HTML/CSS/JavaScript vanilla, grafici in SVG, nessun build step, nessun framework. Colori solo da variabili CSS, tema chiaro/scuro.
- Test: `pytest` con database temporanei.
- Avvio: `uv run mywealth` (apre il browser), opzioni `--port`, `--no-browser`, `--demo`.

## 4. Modello dati (indicativo)

- **account_types**: id, nome. Predefiniti: `spese`, `salvadanaio`, `investimenti`; l'utente può aggiungerne. Ogni tipo ha un *comportamento* (`standard`, `savings`, `investment`) che determina le funzioni disponibili.
- **accounts**: id, nome, banca, valuta (ISO 4217), data apertura, saldo iniziale, tipo, archiviato (sì/no), note.
- **savings_rates**: account_id, tasso annuo %, valido_da. Storico dei tassi: cambiare il tasso non riscrive il passato.
- **categories**: id, nome, natura (`spesa` / `entrata` / `trasferimento`), archiviata.
- **transactions**: id, tipo (`expense`, `income`, `transfer`, `interest`, `fee`, `buy`, `sell`), data, conto origine, conto destinazione, importo origine (unità minori, valuta conto origine), importo destinazione (unità minori, valuta conto destinazione), cambio verso EUR alla data, categoria, descrizione, `linked_id` (es. commissione collegata a un trasferimento), `auto` (generata dall'app), timestamp creazione/modifica.
- **fx_rates**: data, valuta, tasso verso EUR, fonte (`yahoo` / `manuale`).
- **assets / contributions / prices**: come in PortfolioTracker, ma legati a un conto investimenti.

## 5. Conti

### 5.1 Campi
Nome, banca, valuta, data di apertura, **saldo iniziale alla data di apertura** (mancava nei requisiti originali, è indispensabile), tipo.

### 5.2 Operazioni sui conti
- Creazione e modifica dalla tabella della pagina principale.
- Un conto con operazioni non si elimina: si **archivia** (sparisce dalle selezioni ma resta nello storico). Eliminazione consentita solo se il conto non ha operazioni.
- Cambiare la valuta di un conto con operazioni non è consentito.

### 5.3 Salvadanaio con rendimento **[DECISIONE PROPOSTA D3]**
- Campo opzionale "rendimento annuo %" (con storico, vedi `savings_rates`).
- Alla fine di ogni mese l'app genera un'operazione di tipo `interest` (entrata, categoria "Interessi", `auto = true`) pari a `saldo di fine mese × tasso / 12`.
- All'avvio l'app genera gli interessi per tutti i mesi conclusi non ancora calcolati (recupero idempotente: rieseguire non crea duplicati).
- Gli interessi generati sono visibili e modificabili/eliminabili come ogni altra operazione, così l'utente può allinearli all'importo reale accreditato dalla banca.
- Impostazione per scegliere se applicare la ritenuta fiscale (es. 26%) sugli interessi.

### 5.4 Valute ed EUR
- Per ogni conto non in EUR la UI mostra sempre `X <valuta> = Y EUR`.
- Cambio giornaliero da Yahoo Finance (ticker `<VAL>EUR=X`, es. `CHFEUR=X`), salvato in `fx_rates`.
- Aggiornamento all'avvio e su richiesta; al massimo una richiesta per coppia al giorno.
- Senza connessione (o in modalità offline): si usa l'ultimo tasso salvato. La UI mostra la data del tasso e un indicatore "offline / tasso del gg/mm/aaaa".
- Se non esiste alcun tasso salvato: l'utente può inserirne uno manualmente.
- Per operazioni con data passata si usa il tasso di quella data (storico Yahoo); se mancante, il più recente disponibile precedente.

## 6. Operazioni

Tre tipi inseribili dall'utente: **spesa**, **entrata**, **trasferimento**.

### 6.1 Spesa
Conto origine, importo (nella valuta del conto; l'etichetta della valuta si aggiorna al cambio di conto, con il controvalore EUR accanto), descrizione, data (default oggi), categoria di natura `spesa`.

### 6.2 Entrata
Conto destinazione, importo nella valuta del conto (con controvalore EUR), data, descrizione, categoria di natura `entrata`.

### 6.3 Trasferimento **[DECISIONE PROPOSTA D4]**
- Conto origine, conto destinazione (diverso dall'origine), data, categoria (default "Trasferimento"), descrizione (precompilata: "Trasferimento da <origine> a <destinazione>", modificabile).
- Stessa valuta: un solo importo.
- Valute diverse: importo ricevuto (valuta destinazione, come da requisiti) e importo inviato (valuta origine), precompilato col cambio Yahoo ma modificabile, perché il cambio applicato dalla banca è diverso. Entrambi con controvalore EUR.
- Commissione opzionale: importo + scelta del conto da cui addebitarla (origine o destinazione). Genera un'operazione `fee` collegata (categoria "Commissioni bancarie"). Modificare o eliminare il trasferimento aggiorna o elimina anche la commissione.
- I trasferimenti tra conti propri **non** sono spese né entrate nelle analisi.

### 6.4 Categorie
- Gestione (aggiungi / rinomina / archivia) dalle impostazioni.
- Predefinite spese: Affitto, Bollette, Spesa alimentare, Ristoranti, Trasporti, Abbonamenti, Salute, Svago, Viaggi, Regali, Tasse, Altro.
- Predefinite entrate: Stipendio, Rimborsi, Interessi, Dividendi, Altro.
- Eliminare una categoria usata richiede di indicare la categoria a cui spostare le operazioni.

### 6.5 Regole comuni
- Importo sempre positivo; il segno dipende dal tipo.
- Saldo negativo consentito, con avviso.
- Modifica ed eliminazione (con conferma) di ogni operazione; i saldi si ricalcolano automaticamente (vedi §2.4).

## 7. Investimenti

### 7.1 Struttura
- Ogni conto di tipo `investimenti` ha una propria sottoscheda nella scheda Investimenti.
- UI e logica riprese da PortfolioTracker: asset per ticker Yahoo/ISIN/nome, contributi con data e importo, prezzo unitario opzionale, grafici per asset, rendimento %, XIRR, ultimi 12 mesi (Modified Dietz).

### 7.2 Liquidità vs investito **[DECISIONE PROPOSTA D5]**
- Il saldo del conto (saldo iniziale + entrate + trasferimenti in − uscite) rappresenta la **liquidità** disponibile.
- Aggiungere un asset o un contributo crea un'operazione `buy` che sposta l'importo dalla liquidità alla posizione. Non si possono "creare soldi": se la liquidità è insufficiente l'operazione è bloccata, con il suggerimento di registrare prima un trasferimento o un'entrata.
- Vendita (totale o parziale) di un asset: operazione `sell` che restituisce liquidità al conto al controvalore inserito.
- Commissioni di acquisto/vendita opzionali, registrate come `fee`.
- Dividendi: entrata sul conto investimenti con categoria "Dividendi".
- Valore del conto investimenti = liquidità + valore di mercato delle posizioni.
- Asset quotati in una valuta diversa dal conto: conversione come in PortfolioTracker.
- Gli acquisti di asset **non** sono uscite nelle analisi.

### 7.3 Import da PortfolioTracker (opzionale)
Import di un file `portfolio.json` selezionato dall'utente in un conto investimenti scelto.

## 8. Schede dell'app

Barra di navigazione verticale a sinistra: Home, Operazioni, Investimenti, Analytics, Export, Impostazioni.

### 8.1 Home
- Data di oggi.
- Patrimonio totale in EUR, più i totali per valuta.
- Card per ogni conto: saldo nella valuta del conto + controvalore EUR (per i conti investimento: liquidità + investito).
- Grafico dell'andamento di ogni conto + totale, in EUR, con selettore 30 / 60 / 90 giorni / max. Serie giornaliera ricostruita dalle operazioni; per i conti investimento usa i prezzi storici in cache.
- Tabella conti: nome, banca, valuta, tipo, data apertura, saldo; pulsanti "Nuovo conto", "Modifica", "Archivia".

### 8.2 Operazioni
- Tre pulsanti sempre visibili: "+ Spesa", "+ Entrata", "+ Trasferimento" (più rapidi di un menu a tendina), ognuno apre il proprio modulo.
- Tabella delle operazioni: le ultime 30 di default, con paginazione "carica altre" e filtri per conto, categoria, tipo e periodo; pulsanti modifica/elimina per riga.
- Pulsante "Importa CSV" (vedi §9).

### 8.3 Investimenti
Sottoschede per conto investimenti (§7). Per ogni conto: liquidità disponibile, totale investito, valore attuale, guadagno, XIRR, lista asset.

### 8.4 Analytics
- Spese per categoria (torta o barre orizzontali) con selettore di periodo (mese, trimestre, anno, personalizzato).
- Entrate vs uscite per mese, ultimi 12 mesi o anno selezionabile, in EUR. Esclusi trasferimenti tra conti propri e acquisti/vendite di asset.
- Report mensile per conto: entrate, uscite, investito (netto acquisti/vendite) nella valuta del conto e in EUR.
- Andamento del patrimonio netto nel tempo.
- Tasso di risparmio mensile ((entrate − uscite) / entrate).

### 8.5 Export
- CSV e JSON per: operazioni (con filtro periodo/conto), conti, report investimenti, report mensile, categorie.
- Sezione "Trasferisci su un altro PC": pulsante **Esporta tutto** (archivio `.mywealth`) e pulsante **Importa tutto** (vedi §12).
- Il file viene scaricato tramite il browser; nessun dato resta in cartelle del progetto.

### 8.6 Impostazioni
- Tema chiaro/scuro/sistema.
- Formato numeri e date.
- Modalità offline (nessuna chiamata a Yahoo).
- Aggiornamento automatico dei cambi all'avvio sì/no; aggiunta manuale di un tasso di cambio.
- Gestione categorie e tipi di conto.
- Range predefinito del grafico in Home.
- Ritenuta fiscale sugli interessi del salvadanaio.
- Cartella dati (sola visualizzazione + pulsante "apri cartella"), numero di backup automatici da conservare, backup/ripristino manuale.
- Porta del server.
- Avvio: crea/rimuovi collegamenti menu Start e desktop, apri in finestra app o in scheda del browser, chiusura automatica dopo inattività (vedi §13).
- (Opzionale) PIN di sblocco all'apertura dell'app.

## 9. Import CSV **[DECISIONE PROPOSTA D6]**
- Formato proprio con template scaricabile: `data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione`.
- Separatore `;` o `,`, decimali con virgola o punto, date `gg/mm/aaaa` o `aaaa-mm-gg`.
- Anteprima prima della conferma, con errori per riga (conto inesistente, categoria sconosciuta → proposta di crearla, data non valida).
- Avviso sui possibili duplicati (stessa data, conto, importo e descrizione).
- Import in un'unica transazione: o tutte le righe o nessuna.
- Mappature per gli export CSV di banche specifiche: milestone successiva.

## 10. Modalità demo
`uv run mywealth --demo` avvia l'app con un database temporaneo e dati sintetici (più conti in EUR/CHF/USD, 12 mesi di operazioni, un salvadanaio con interessi, due conti investimento) e prezzi/cambi finti. Nessuna chiamata di rete. È la modalità usata per lo sviluppo e per verificare la UI.

## 11. Milestone di sviluppo

Ogni milestone termina con test verdi e verifica della UI in modalità demo.

| # | Contenuto |
|---|-----------|
| M0 | Scaffolding: `pyproject.toml` (con `mywealth` e `mywealth-gui`), struttura pacchetto, server locale con token, istanza singola, storage SQLite con migrazioni, modalità demo, layout con barra laterale, tema chiaro/scuro, pulsante "Esci". |
| M1 | Conti e tipi di conto: CRUD, saldo calcolato, tabella in Home. |
| M2 | Operazioni: spese, entrate, trasferimenti, commissioni collegate, categorie, tabella con filtri e modifica. |
| M3 | Cambi valuta: Yahoo, cache, fallback offline, controvalori EUR nella UI. |
| M4 | Salvadanaio: tassi con storico, generazione interessi mensili idempotente. |
| M5 | Investimenti: porting da PortfolioTracker, liquidità vs investito, acquisti/vendite, sottoschede per conto. |
| M6 | Home completa: card, totali, grafico storico. |
| M7 | Analytics. |
| M8 | Import CSV ed export CSV/JSON; archivio `.mywealth` (Esporta tutto / Importa tutto), ripristino dai backup automatici, schermata di primo avvio. |
| M9 | Avvio rapido: finestra app, collegamenti menu Start/desktop con icona, chiusura per inattività, avvio con Windows opzionale. |
| M10 | Impostazioni complete, rifiniture, README con guida "nuovo PC". |
| M11 | (Opzionale) cifratura dati e dell'archivio, PIN, mappature CSV per banche, import da PortfolioTracker. |

---

## 12. Migrazione su un nuovo PC **[DECISIONE PROPOSTA D8]**

### 12.1 Esporta tutto
- Pulsante **Esporta tutto** nella scheda Export (e nelle Impostazioni).
- Produce un singolo file `myWealth_AAAA-MM-GG.mywealth`: un archivio ZIP che contiene:
  - `mywealth.db`: copia coerente del database, fatta con l'API di backup di SQLite (mai una copia del file mentre è in uso);
  - `settings.json`: impostazioni dell'app;
  - `manifest.json`: versione dell'app, versione dello schema, data di creazione, numero di conti e operazioni, checksum SHA-256 del database.
- Cache di prezzi e cambi incluse (così il nuovo PC mostra subito i valori anche senza rete).
- Il file viene scaricato tramite il browser; l'utente sceglie dove salvarlo (chiavetta, cloud personale…).
- Avviso nella UI: l'archivio contiene **tutti** i dati finanziari in chiaro; va conservato su un supporto sicuro e cancellato dopo l'uso. La cifratura con password dell'archivio è prevista in M11 (stesso vincolo AppLocker di §2.3).

### 12.2 Importa tutto
- Disponibile in due punti:
  - **schermata di primo avvio**: se il database è vuoto, l'app chiede "Inizia da zero" / "Importa da un altro PC" / "Prova con dati demo";
  - scheda Export / Impostazioni → **Importa tutto**.
- Passi:
  1. scelta del file `.mywealth`;
  2. verifica: archivio valido, checksum corretto, versione dello schema;
  3. riepilogo prima della conferma: data dell'archivio, numero di conti e operazioni, e avviso che i dati attuali verranno **sostituiti**;
  4. backup automatico dei dati attuali in `backups\` (annullabile ripristinando quel backup);
  5. sostituzione del database e delle impostazioni, poi migrazioni di schema se l'archivio viene da una versione precedente dell'app.
- Un archivio creato da una versione **più recente** dell'app viene rifiutato con il messaggio di aggiornare prima l'app.
- Le impostazioni legate al computer (porta, collegamenti, avvio con Windows) non vengono importate.
- Nessuna unione tra due database: l'import sostituisce sempre tutto.

### 12.3 Ripristino da backup
- Le Impostazioni elencano i backup automatici (§2.3) con data e dimensione; ognuno è ripristinabile con lo stesso flusso dell'import.
- Ogni backup automatico usa lo stesso formato `.mywealth`.

### 12.4 Procedura completa per l'utente (da riportare nel README)
1. Vecchio PC: Export → **Esporta tutto** → salva il file `.mywealth`.
2. Nuovo PC: installa `uv` e Git, clona il repository, `uv sync`.
3. `uv run mywealth --install-shortcuts` (vedi §13), poi apri l'app dal menu Start.
4. Schermata di primo avvio → **Importa da un altro PC** → scegli il file.
5. Cancella il file `.mywealth` dalla chiavetta o dal cloud.

---

## 13. Avvio rapido **[DECISIONE PROPOSTA D9]**

Obiettivo: aprire l'app come una normale applicazione Windows, senza VS Code né terminale.

### 13.1 Comando senza console
- `pyproject.toml` definisce due comandi:
  - `mywealth` (`[project.scripts]`): con console, per sviluppo e diagnostica;
  - `mywealth-gui` (`[project.gui-scripts]`): stesso avvio ma senza finestra di terminale. Errori e log vanno in `%APPDATA%\myWealth\logs\` (con rotazione).

### 13.2 Collegamenti
- `uv run mywealth --install-shortcuts` crea:
  - voce **myWealth** nel menu Start (quindi avviabile scrivendo "myWealth" dopo aver premuto il tasto Windows, e fissabile sulla barra delle applicazioni);
  - collegamento sul desktop (opzionale, chiesto durante l'installazione).
- I collegamenti puntano a `mywealth-gui` nell'ambiente del progetto, con cartella di lavoro = cartella del progetto e icona `.ico` dell'app.
- Creati senza dipendenze aggiuntive (file `.lnk` generati via PowerShell / `WScript.Shell`).
- `uv run mywealth --uninstall-shortcuts` li rimuove. Gli stessi comandi sono disponibili anche dalle Impostazioni.
- Nota AppLocker/WDAC: va verificato che l'eseguibile in `.venv\Scripts` sia consentito (lo è già per l'attuale `uv run`). Se viene bloccato, alternativa: collegamento a `wscript.exe` con uno script `.vbs` che lancia `uv run --project "<cartella>" mywealth` a finestra nascosta.

### 13.3 Finestra "app"
- All'avvio l'app si apre in una finestra dedicata senza barra degli indirizzi né schede, usando Microsoft Edge (sempre presente su Windows) in modalità `--app=http://127.0.0.1:<porta>/...`, con un profilo separato in `%APPDATA%\myWealth\browser-profile`.
- Se Edge non è disponibile, o se l'utente preferisce, si apre una normale scheda del browser predefinito (impostazione).

### 13.4 Istanza singola e chiusura
- Se l'app è già in esecuzione, il nuovo avvio non lancia un secondo server: riapre la finestra dell'istanza esistente (file di lock con porta e PID nella cartella dati).
- Senza console serve un modo per chiudere il server:
  - pulsante **Esci** nella barra laterale;
  - chiusura automatica quando la finestra è chiusa da più di N minuti (heartbeat dalla pagina; default 5 minuti, configurabile).
- Prima della chiusura viene completato ogni salvataggio in corso.

### 13.5 Avvio con Windows (opzionale)
Impostazione "Avvia myWealth all'accesso a Windows" (collegamento nella cartella Esecuzione automatica), disattivata di default.
