# myWealth

App desktop personale per gestire conti, spese, entrate, trasferimenti e investimenti. Gira in locale (`127.0.0.1`) e mostra ogni importo anche in EUR.

- Specifica: [`docs/SPEC.md`](docs/SPEC.md)
- Istruzioni per Claude Code: [`CLAUDE.md`](CLAUDE.md)

## Cosa fa

- **Conti** in valute diverse (spese, salvadanaio, investimenti + tipi personalizzati), con saldo iniziale; il saldo è sempre calcolato dalle operazioni.
- **Operazioni**: spese, entrate, trasferimenti (anche tra valute, con commissione collegata), categorie, filtri, import da CSV.
- **Cambi** da Yahoo Finance, salvati in locale: senza connessione si usa l'ultimo tasso (con la sua data); tassi manuali se serve. Ogni operazione conserva il cambio del suo giorno.
- **Salvadanaio**: rendimento annuo con storico; gli interessi maturano ogni giorno sul saldo e vengono accreditati a fine mese (con ritenuta facoltativa).
- **Investimenti** (da [PortfolioTracker](https://github.com/cricci3/PortfolioTracker)): asset per ticker/ISIN, acquisti e vendite che spostano la liquidità del conto, valore, guadagno, XIRR, ultimi 12 mesi.
- **Home** con patrimonio totale, card per conto e grafico storico; **Analytics** (spese per categoria, entrate/uscite, tasso di risparmio, report per conto, patrimonio netto); **Export** CSV/JSON.
- **Esporta tutto / Importa tutto** per passare a un altro PC, backup automatici a ogni avvio.
- **Smartphone**: un'app per Chrome Android registra spese, entrate e trasferimenti anche offline e li manda al PC in un file cifrato.

## Privacy

I dati restano sul computer, in `%APPDATA%\myWealth\` (modificabile con `MYWEALTH_DATA_DIR`), fuori dal repository. Le uniche chiamate di rete vanno a Yahoo Finance e contengono solo ticker, coppie valutarie e date, mai importi o nomi di conti. Con la **modalità offline** (Impostazioni) non parte nessuna richiesta.

Il server ascolta solo su `127.0.0.1`, controlla l'header `Host` e richiede un token casuale generato a ogni avvio: altri siti aperti nel browser non possono leggere né modificare i dati.

I dati non sono cifrati dall'app: per proteggerli “a riposo” attiva BitLocker sul disco.

L'app per smartphone è un sito statico (solo codice, nessun dato) e non fa chiamate di rete dopo il caricamento: le voci restano sul telefono e ne escono solo cifrate (AES-256-GCM) con una chiave che conoscono solo il telefono e il PC.

## Installazione

Servono [uv](https://docs.astral.sh/uv/) e Git.

```
git clone <url del repository>
cd myWealth
uv sync
uv run mywealth --install-shortcuts
```

`--install-shortcuts` crea la voce **myWealth** nel menu Start (e, se rispondi sì, sul desktop): da lì l'app si apre in una finestra dedicata, senza terminale (Brave se installato, altrimenti Edge; si sceglie in **Impostazioni → Avvio e finestra**). Per toglierli: `uv run mywealth --uninstall-shortcuts`. Gli stessi comandi, e l'avvio automatico all'accesso a Windows, sono anche in **Impostazioni → Avvio e finestra**.

Se Windows blocca `mywealth-gui.exe` (AppLocker/WDAC), usa `uv run mywealth --install-shortcuts --vbs`: il collegamento avvia l'app tramite uno script VBS e `uv run`, sempre senza finestra di terminale.

## Avvio da terminale

```
uv run mywealth          # dati reali, apre la finestra dell'app
uv run mywealth --demo   # database temporaneo con dati finti, nessuna rete
uv run pytest            # test (compresi quelli JavaScript, se Node.js è installato)
node --test tests/js/*.test.mjs   # solo i test dell'app smartphone
```

Opzioni: `--port N` (default 8777 o quella delle Impostazioni; se occupata prova le successive), `--no-browser`.
`mywealth-gui` fa lo stesso senza finestra di terminale; i log vanno in `<cartella dati>\logs\`.

Se l'app è già aperta, un nuovo avvio riapre la finestra dell'istanza in esecuzione. Per chiuderla usa **Esci** nella barra laterale; si chiude anche da sola quando nessuna finestra è aperta da 5 minuti (configurabile).

## Usare l'app

1. **Home → Nuovo conto**: nome, banca, valuta, data di apertura, saldo a quella data e tipo. Per un salvadanaio puoi indicare subito il rendimento annuo.
2. **Operazioni**: “+ Spesa”, “+ Entrata”, “+ Trasferimento”. Tra valute diverse indica sia l'importo inviato sia quello ricevuto (il secondo è proposto al cambio del giorno). La commissione bancaria del trasferimento diventa una spesa collegata.
3. **Investimenti**: una sottoscheda per conto investimenti. “+ Asset” cerca per ticker Yahoo, ISIN o nome; l'importo viene preso dalla liquidità del conto (se non basta, registra prima un trasferimento). Vendite: quote vendute + importo incassato.
4. **Importa CSV** (Operazioni): scarica il modello, compila, controlla l'anteprima con gli errori per riga, conferma. L'import è tutto o niente.
5. **Estratto conto** (Operazioni): importa il CSV dell'home banking scegliendo le colonne di data, importo (o uscite/entrate) e descrizione; salva la mappatura con il nome della banca per riusarla.
6. **PortfolioTracker** (Investimenti): importa un `portfolio.json`; i contributi diventano acquisti, finanziati dalla liquidità del conto o da trasferimenti da un altro conto.
7. **PIN di sblocco** (Impostazioni, facoltativo): chiede un PIN a ogni apertura. Protegge l'app aperta, non cifra i dati sul disco.

Gli importi si possono scrivere sia `1.234,56` sia `1234.56`.

## Smartphone

1. Sul telefono apri in Chrome <https://cricci3.github.io/myWealth/> e scegli **menu → Installa app**: da quel momento funziona anche senza rete.
2. Sul PC: **Impostazioni → Smartphone → Abbina smartphone**. Sul telefono tocca **Inquadra il codice** e inquadra il QR (oppure copia il codice come testo e incollalo). Il QR contiene la chiave: non fotografarlo e non condividerlo.
3. Sul telefono registra spese, entrate e trasferimenti (conti e categorie sono quelli del PC). Commissioni e investimenti si gestiscono solo dal PC.
4. **Esporta → Esporta e invia**: nel menu di condivisione scegli Gmail e invia la mail a te stesso. L'allegato `mywealth-AAAAMMGG-HHMM.txt` è cifrato.
5. Sul PC scarica l'allegato: myWealth lo trova nella cartella Download (badge “file da smartphone” nella barra laterale), mostra l'anteprima e, dopo la conferma, lo importa e lo cancella. In alternativa **Operazioni → Da smartphone**, o trascina il file nella finestra.

Rinviare lo stesso file non crea doppioni. Dopo aver aggiunto o rinominato conti e categorie sul PC, usa **Mostra QR configurazione** e sul telefono **Impostazioni → Aggiorna configurazione**. Se perdi il telefono: **Rigenera chiave**. Su un nuovo PC lo smartphone va abbinato di nuovo (la chiave non è nell'archivio `.mywealth`).

L'app viene pubblicata su GitHub Pages da `.github/workflows/pages.yml` a ogni push che modifica `mobile/`; la prima volta va attivato **Settings → Pages → Source: GitHub Actions** nel repository.

## Passare a un nuovo PC

1. Vecchio PC: **Export → Esporta tutto** e salva il file `myWealth_AAAA-MM-GG.mywealth` (chiavetta, cloud personale…).
2. Nuovo PC: installa uv e Git, clona il repository, `uv sync`.
3. `uv run mywealth --install-shortcuts`, poi apri l'app dal menu Start.
4. Alla schermata di primo avvio scegli **Importa da un altro PC** e seleziona il file.
5. Cancella il file `.mywealth` dalla chiavetta o dal cloud: contiene tutti i tuoi dati in chiaro.

L'import sostituisce tutti i dati (non li unisce); prima viene fatto un backup automatico, ripristinabile da **Impostazioni → Dati e backup**. Porta, collegamenti e avvio automatico restano quelli del nuovo PC. Un archivio creato da una versione più recente dell'app viene rifiutato: aggiorna prima il repository (`git pull`, `uv sync`).

## Backup

A ogni avvio l'app salva un backup in `<cartella dati>\backups\` (gli ultimi 10, configurabile), nello stesso formato di “Esporta tutto”. Dalle Impostazioni puoi crearne uno al volo, scaricarlo o ripristinarlo.

> Nota: `numpy` è fissato a `2.1.3` perché le versioni più recenti sono bloccate da AppLocker/WDAC su questa macchina.
