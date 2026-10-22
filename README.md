# myWealth

App desktop personale per gestire conti, spese, entrate, trasferimenti e investimenti. Gira in locale (`127.0.0.1`) e mostra ogni importo anche in EUR.

- Specifica: [`docs/SPEC.md`](docs/SPEC.md)
- Istruzioni per Claude Code: [`CLAUDE.md`](CLAUDE.md)

## Privacy

I dati restano sul computer, in `%APPDATA%\myWealth\` (modificabile con `MYWEALTH_DATA_DIR`), fuori dal repository. Le uniche chiamate di rete vanno a Yahoo Finance e contengono solo ticker e date.

## Avvio

_In sviluppo — i comandi saranno disponibili dopo la milestone M0._

```
uv sync
uv run mywealth          # dati reali
uv run mywealth --demo   # dati sintetici, nessuna rete
```
