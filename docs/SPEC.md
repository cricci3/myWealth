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
| D3 | Interessi salvadanaio | Maturazione giornaliera sul saldo di fine giornata, accreditata come entrata automatica a fine mese (vedi §5.3). |
| D4 | Trasferimenti tra valute diverse | Si inseriscono entrambi gli importi (inviato e ricevuto); il secondo è precompilato col cambio Yahoo ma modificabile (vedi §6.3). |
| D5 | Acquisto asset senza liquidità sufficiente | Bloccato con messaggio d'errore (vedi §7.2). |
| D6 | Formato CSV di import | Formato proprio dell'app con template scaricabile; mappature per banche specifiche in seguito (vedi §9). |
| D7 | Codice di PortfolioTracker | Copiato e adattato dentro myWealth (licenza MIT, stesso autore), non usato come dipendenza. Import opzionale dei dati da `portfolio.json`. |
| D8 | Cambio PC | Un unico file archivio `.mywealth` con tutti i dati, esportato e importato con un pulsante; l'import sostituisce i dati, non li unisce (vedi §12). |
| D9 | Avvio rapido | Collegamenti nel menu Start e sul desktop, creati dall'app; finestra in stile app senza barra del browser; nessuna finestra di terminale (vedi §13). |
| D10 | Browser della finestra app | Brave (browser dell'utente su PC), poi Edge, poi browser predefinito; scelta nelle Impostazioni (vedi §15). |
| D11 | Inserimento da smartphone | PWA per Chrome Android, dati solo sul telefono; export cifrato (AES-256-GCM, chiave abbinata via QR) inviato per email a se stessi; import sul desktop da file o dalla cartella Download (vedi §16). |

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
- Eccezione per lo smartphone (§16): la PWA è ospitata come sito statico (solo codice, nessun dato) e le operazioni registrate sul telefono escono dal telefono **solo cifrate**, in un allegato email che l'utente invia a se stesso.
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

### 5.3 Salvadanaio con rendimento **[DECISIONE D3, confermata con modifica]**
- Campo opzionale "rendimento annuo %" (con storico, vedi `savings_rates`).
- Gli interessi maturano **ogni giorno** sul saldo di fine giornata: `saldo × tasso annuo / 12 / giorni del mese`, con il tasso valido quel giorno (un saldo negativo non matura nulla). Alla fine di ogni mese l'app genera un'operazione di tipo `interest` (entrata, categoria "Interessi", `auto = true`) pari alla somma del mese, arrotondata una sola volta.
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
- Vendita (totale o parziale) di un asset: operazione `sell` che restituisce liquidità al conto al controvalore inserito. Si inseriscono **quote vendute e importo incassato**; il costo delle quote vendute (costo medio) esce dall'investito, la differenza è guadagno realizzato.
- Commissioni di acquisto/vendita opzionali, registrate come `fee`: sono **spese normali** (categoria "Commissioni bancarie") e i rendimenti dell'asset non le considerano, come in PortfolioTracker.
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
| M12 | Finestra app in Brave (§15). |
| M13 | Desktop – smartphone, lato desktop: abbinamento con QR, "configurazione mobile", import dei file cifrati da selezione file e dalla cartella in arrivo, deduplica per `id` (§16.4–16.6). |
| M14 | PWA smartphone: inserimento offline, voci in sospeso, abbinamento da QR, export cifrato e condivisione via email, pubblicazione su GitHub Pages (§16.2–16.3, §16.7). |

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
> Aggiornato da §15: il browser preferito è Brave, poi Edge.

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

---

## 14. Decisioni prese durante lo sviluppo

Punti che la specifica non fissava, scelti durante l'implementazione (M1–M10).

**Conti e operazioni**
- Nomi dei conti unici (senza distinzione maiuscole/minuscole): servono anche all'import CSV. Il saldo iniziale può essere negativo.
- La data di apertura non può superare la data della prima operazione; il comportamento di un tipo di conto non si cambia se il tipo è già usato.
- Le operazioni non possono avere una data futura né precedente all'apertura del conto.
- La commissione di un trasferimento è mostrata nella riga del trasferimento e si modifica solo da lì.
- Le operazioni `buy`/`sell` (e le loro commissioni) si gestiscono solo dalla scheda Investimenti.

**Cambi**
- Tasso usato per un giorno: quello del giorno, altrimenti il più recente precedente; se non ne esiste nessuno precedente, il primo successivo (così un tasso manuale inserito oggi dà subito un controvalore anche alle operazioni passate).
- Un tasso manuale ha la precedenza su Yahoo per lo stesso giorno.
- All'avvio al massimo un download al giorno per coppia (e per ticker); un secondo solo se serve storico più vecchio. Il pulsante "Aggiorna" forza il download.
- Lo snapshot di un'operazione viene completato quando arriva il tasso del suo giorno; una volta che è quello del suo giorno non viene più riscritto.

**Salvadanaio**
- I mesi già calcolati sono registrati: un interesse eliminato o modificato a mano non viene rigenerato. "Ricalcola dal mese" rifà i mesi scelti (dopo operazioni o tassi inseriti nel passato).
- La ritenuta si applica al momento della generazione; i conti archiviati non maturano interessi.

**Investimenti**
- Importi degli acquisti nella valuta del conto investimenti; strumenti in altra valuta convertiti con i cambi verso EUR del giorno (quotazioni in pence divise per 100).
- Un acquisto è bloccato se la liquidità diventa negativa alla sua data o oggi.
- Le quote di un acquisto sono calcolate dal prezzo di chiusura del primo giorno di borsa dalla data (o dal prezzo/numero di quote inseriti) e ricalcolate quando arrivano i prezzi.
- XIRR mostrato dopo 6 mesi di storico, "ultimi 12 mesi" (Modified Dietz) dopo un anno, come in PortfolioTracker.

**Analytics**
- Spese = `expense` + `fee`; entrate = `income` + `interest`; tutto in EUR al cambio di ogni operazione. Le operazioni ancora senza cambio sono escluse e conteggiate a parte.
- Report per conto: entrate, uscite, trasferimenti netti, investito (acquisti − vendite).

**Export, import, archivio**
- L'export CSV delle operazioni usa lo stesso formato dell'import (più valuta e controvalore EUR), con `;` e virgola decimale, quindi si può reimportare.
- Duplicati nell'import CSV = stessa data, conto, importo e descrizione: solo un avviso.
- Le categorie sconosciute nell'import si creano solo se l'utente lo chiede.
- Backup automatico all'avvio solo se il database non è vuoto (e mai in demo).
- "Prova con dati demo" dalla schermata di primo avvio apre un'istanza demo separata (altra porta, dati temporanei).

**M11 (opzionale)**
- Cifratura dei dati e dell'archivio: **non implementata**. Richiede una dipendenza compilata (`cryptography`/SQLCipher) che può essere bloccata da AppLocker/WDAC: va decisa con l'utente.
- PIN di sblocco: PBKDF2-SHA256 con sale, blocca UI e API dell'istanza in esecuzione; dopo 5 tentativi errati attesa di 30 secondi. Non cifra i dati.
- Mappature CSV per banche: invece di formati fissi per banca (non verificabili), mappatura delle colonne scelta dall'utente e salvabile con il nome della banca; le righe passano dall'import normale.
- Import da PortfolioTracker: il portafoglio deve avere la stessa valuta del conto; i contributi diventano acquisti, finanziati dalla liquidità o da un trasferimento per contributo da un altro conto; tutto o niente.

**Avvio**
- La chiusura per inattività vale solo quando è l'app ad aprire la finestra (non con `--no-browser`, usato in sviluppo).
- Formato dei numeri: `1.234,56` (default) o `1,234.56`; date sempre gg/mm/aaaa e testi in italiano.

---

## 15. Browser della finestra app **[DECISIONE D10]**

L'utente usa **Brave** su PC (e Chrome su Android). La finestra app di §13.3 diventa:

- Ordine di ricerca: **Brave → Edge → browser predefinito** (scheda normale).
- Percorsi di Brave: `%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe`, `%ProgramFiles(x86)%\...` e `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe`.
- Stessi parametri di Edge: `--app=<url>`, `--user-data-dir=<data dir>\browser-profile-brave` (profilo separato da quello personale dell'utente: niente estensioni, cronologia o sincronizzazione), `--no-first-run`, `--no-default-browser-check`, `--window-size`.
- Impostazione "Browser della finestra app": Automatico (default) / Brave / Edge / Browser predefinito (scheda). Se il browser scelto non è installato, si usa il successivo e la UI lo segnala.
- Brave Shields non interferisce con `127.0.0.1`; va comunque verificato che la pagina funzioni con Shields attivo (nessuna risorsa esterna, quindi nessun blocco atteso).
- La Web Crypto API (necessaria in §16.5) è disponibile su `http://127.0.0.1`, che i browser Chromium considerano un contesto sicuro.

---

## 16. Inserimento da smartphone **[DECISIONE D11]**

### 16.1 Obiettivo e flusso
Registrare spese, entrate e trasferimenti dal telefono quando si è in giro, anche senza rete, e portarli sul desktop senza che i dati siano leggibili da terzi.

1. **Telefono (PWA, Chrome Android):** inserisco le operazioni; restano sul telefono.
2. **Esporta:** la PWA crea un file cifrato e apre il menu di condivisione di Android → Gmail → lo invio a me stesso.
3. **PC:** apro la mail e scarico l'allegato, che finisce in `Download`.
4. **App desktop:** trova il file nella cartella in arrivo (o lo seleziono a mano), lo decifra, mostra l'anteprima dell'import, confermo; il file viene cancellato.

Nessun server acceso 24/7, nessun account o servizio aggiuntivo.

### 16.2 PWA: struttura e privacy
- Cartella `mobile/` nel repository: HTML/CSS/JS vanilla, nessun framework né build step, nessuna libreria esterna (né CDN). Stessi principi grafici della UI desktop (variabili CSS, tema chiaro/scuro), pensata per una mano sola e schermi piccoli.
- Installabile ("Installa app" / "Aggiungi a schermata Home" in Chrome): `manifest.webmanifest`, icone, service worker che mette in cache tutti i file → funziona completamente **offline** dopo la prima apertura.
- Pubblicata come sito statico su **GitHub Pages** tramite GitHub Actions. Il sito contiene solo codice, mai dati.
  - Da verificare: GitHub Pages su piano gratuito richiede un repository pubblico. Se `myWealth` è privato, pubblicare `mobile/` in un repository pubblico separato (es. `mywealth-mobile`) tramite l'Action.
- Nessuna chiamata di rete dopo il caricamento: Content-Security-Policy con `default-src 'self'; connect-src 'self'`, nessun analytics.
- Dati in **IndexedDB** del telefono; all'avvio si richiede `navigator.storage.persist()` per evitare che Chrome li cancelli. Se ci sono voci non esportate da più di 7 giorni, la PWA lo ricorda.
- Aggiornamenti: quando esiste una nuova versione, la PWA mostra "Aggiornamento disponibile" e si ricarica solo su conferma, mai durante un inserimento.

### 16.3 PWA: schermate
- **Nuova voce** (schermata iniziale): tre schede Spesa / Entrata / Trasferimento.
  - Campi come in §6, con data (default oggi), importo con tastierino numerico (virgola o punto), conto e categoria da menu a tendina, descrizione.
  - Spesa: conto origine. Entrata: conto destinazione. Trasferimento: origine e destinazione; se le valute differiscono, anche l'importo ricevuto. Commissioni di trasferimento e investimenti **non** sono gestiti dal telefono.
  - Il simbolo della valuta segue il conto scelto. Nessun controvalore EUR (niente rete): lo calcola il desktop all'import.
  - Ultimi conto e categoria usati preselezionati.
- **Voci**: elenco delle voci in sospeso (modificabili, eliminabili) e di quelle già esportate (sola lettura, con data di export; "Esporta di nuovo" per rimandare un invio andato perso). Le voci esportate si cancellano dopo 30 giorni o con "Svuota esportate".
- **Esporta**: numero di voci in sospeso e pulsante "Esporta e invia".
- **Impostazioni**: stato dell'abbinamento e data della configurazione, "Abbina / Aggiorna configurazione" (scansione QR), "Rimuovi abbinamento" (cancella chiave e configurazione), tema.
- Prima dell'abbinamento la PWA mostra solo la schermata di abbinamento: senza configurazione non conosce conti e categorie.

### 16.4 Abbinamento e configurazione (QR)
- Desktop, **Impostazioni → Smartphone**:
  - "Abbina smartphone" genera una chiave casuale da 256 bit (CSPRNG: `secrets.token_bytes(32)`) e un identificativo `kid` (primi 8 byte esadecimali dello SHA-256 della chiave). La chiave è salvata nella cartella dati (`mobile_key.json`), mai nel repository.
  - Mostra un **codice QR** con: versione, chiave, `kid` e la **configurazione mobile** = conti non archiviati (nome, valuta) + categorie non archiviate per natura (spesa / entrata / trasferimento). Sotto il QR, lo stesso contenuto come testo da copiare (alternativa alla fotocamera).
  - "Mostra QR configurazione" rimostra lo stesso QR (stessa chiave) per aggiornare conti e categorie sul telefono dopo una modifica.
  - "Rigenera chiave" (es. telefono perso): nuova chiave; i file cifrati con la vecchia vengono rifiutati, e la UI lo spiega.
  - Il QR si genera localmente senza dipendenze compilate (libreria pura Python come `segno`, o JS vendorizzato in `web/`); se la configurazione supera la capacità di un QR, si usano più QR in sequenza.
- Telefono: scansione con la fotocamera tramite l'API `BarcodeDetector` di Chrome Android; in alternativa incolla il testo. La chiave è importata come `CryptoKey` **non esportabile** e salvata in IndexedDB insieme alla configurazione.
- Il QR contiene la chiave: la UI desktop avvisa di non fotografarlo né condividerlo, e lo nasconde dopo 2 minuti.

### 16.5 Formato del file cifrato
- Nome: `mywealth-AAAAMMGG-HHMM.txt`. Estensione `.txt` e tipo `text/plain` perché Chrome Android consente di condividere solo alcuni tipi di file (testo sì, tipi personalizzati no).
- Contenuto (testo ASCII):
  ```
  MYWEALTH-ENC 1
  <base64url(intestazione JSON)>.<base64url(testo cifrato)>
  ```
  - Intestazione: `{"v":1,"alg":"AES-256-GCM","kid":"…","iv":"<12 byte casuali, base64url>","created":"<ISO 8601>"}`. Nessun conteggio di voci né altri metadati.
  - Cifratura **AES-256-GCM** via Web Crypto API, IV casuale nuovo per ogni file, intestazione usata come dati autenticati aggiuntivi (AAD): un'intestazione alterata fa fallire la decifratura.
  - Testo in chiaro: CSV UTF-8 nel formato di import (§9) con in più le colonne `id` (UUID v4 generato sul telefono alla creazione della voce) e `creato_il`.
- Solo primitive standard della Web Crypto API: nessun algoritmo o schema crittografico fatto in casa.

### 16.6 Import sul desktop
- **Da file:** Operazioni → "Importa da smartphone": selezione di uno o più file `.txt` (anche trascinandoli nella finestra).
- **Cartella in arrivo:** impostazione "Cartella in arrivo" (default: `Download` dell'utente; modificabile; disattivabile). All'avvio e ogni 2 minuti mentre l'app è aperta, il server cerca file `mywealth-*.txt` che iniziano con `MYWEALTH-ENC 1`; se ne trova, la barra laterale mostra un badge "N file da smartphone" che apre l'import. Gli altri file della cartella non vengono mai letti.
- **Decifratura nel browser:** il server Python non ha AES nella libreria standard e non si aggiungono dipendenze compilate (AppLocker). Il server passa alla pagina il contenuto del file e la chiave (solo su `127.0.0.1`, con token); la pagina decifra con la Web Crypto API e invia il CSV in chiaro all'anteprima di import esistente.
- Errori chiari: `kid` diverso ("file cifrato con un'altra chiave: rifai l'abbinamento"), decifratura fallita ("file danneggiato o modificato"), versione sconosciuta.
- **Deduplica per `id`:** nuova tabella `mobile_imported_ids` (id, data import). Le righe con `id` già importato sono saltate e indicate come "già importate" nell'anteprima: rinviare lo stesso file o due file con voci in comune non crea doppioni. Il controllo duplicati esistente (§14) resta come avviso per le altre righe.
- Dopo la conferma l'import resta "tutto o niente" (§9). Solo a import riuscito il file viene **cancellato** (dalla cartella in arrivo o, se scelto da altrove, su conferma). File non importati restano dove sono.
- Conti o categorie rinominati o archiviati sul desktop dopo l'ultimo aggiornamento della configurazione sul telefono: le righe interessate danno errore o richiedono di creare la categoria, come nell'import CSV; la UI suggerisce di aggiornare la configurazione sul telefono.

### 16.7 Invio via email
- "Esporta e invia" usa la **Web Share API** (`navigator.share({ files, title, text })`): Android apre il menu di condivisione e l'utente sceglie Gmail; oggetto e testo sono precompilati in modo neutro ("myWealth export", nessun dato). Il destinatario lo scrive l'utente (il proprio indirizzo; Gmail lo ricorda): una PWA non può inviare email da sola, e `mailto:` non supporta allegati.
- Se `navigator.canShare({ files })` restituisce falso, si scarica il file sul telefono e lo si allega a mano.
- Quando la condivisione si conclude, le voci passano a "esportate". La PWA non può sapere se la mail è stata davvero inviata: per questo le voci esportate restano disponibili per "Esporta di nuovo" e la deduplica per `id` rende innocuo un doppio invio.
- Cosa vede il provider email: nome, dimensione e orario dell'allegato. Importi, conti, categorie e descrizioni sono cifrati. Dopo l'import si può eliminare la mail.

### 16.8 Test
- Logica della PWA (formato CSV, cifratura/decifratura, deduplica) testata nel browser Chromium preinstallato con Playwright, in modalità emulazione mobile e offline.
- Vettori di test condivisi: un file cifrato con una chiave di test nota, decifrato dalla pagina desktop e confrontato con il CSV atteso.
- Python: ricerca nella cartella in arrivo su una cartella temporanea (solo i file `mywealth-*.txt` con intestazione valida), deduplica `id`, cancellazione solo a import riuscito.
- Da verificare sul telefono reale (in `TODO.md`): installazione della PWA, uso offline, scansione QR, condivisione su Gmail, persistenza dei dati dopo riavvio del telefono.
