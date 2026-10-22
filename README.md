# myWealth

App desktop personale per gestire conti, spese, entrate, trasferimenti e investimenti. Gira in locale (`127.0.0.1`) e mostra ogni importo anche in EUR.

- Specifica: [`docs/SPEC.md`](docs/SPEC.md)
- Istruzioni per Claude Code: [`CLAUDE.md`](CLAUDE.md)

## Privacy

I dati restano sul computer, in `%APPDATA%\myWealth\` (modificabile con `MYWEALTH_DATA_DIR`), fuori dal repository. Le uniche chiamate di rete vanno a Yahoo Finance e contengono solo ticker e date.

## Avvio

Serve [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run mywealth          # dati reali, apre il browser
uv run mywealth --demo   # database temporaneo, nessuna rete
uv run pytest            # test
```

Opzioni: `--port N` (default 8777, se occupata prova le successive), `--no-browser`.
`mywealth-gui` fa lo stesso senza finestra di terminale; i log vanno in `<cartella dati>\logs\`.

Se l'app è già aperta, un nuovo avvio riapre la finestra dell'istanza in esecuzione. Per chiuderla usa **Esci** nella barra laterale (o Ctrl+C nel terminale).
