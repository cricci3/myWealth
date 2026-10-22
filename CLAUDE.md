# myWealth

Personal desktop app (local web server + browser UI) to track bank accounts, expenses, income, transfers and investments, with every amount also shown in EUR.

**The full specification is in `docs/SPEC.md`. Read it before starting any milestone.** `docs/REQUISITI_originali.txt` is the original, informal requirements note (kept for reference only; SPEC.md wins on conflicts).

## Privacy rules — non-negotiable

- **Never read, print, search, copy or open the user's real data.** It lives in `%APPDATA%\myWealth\` (Windows) or `~/.mywealth/`, or wherever `MYWEALTH_DATA_DIR` points. Do not run the app against the real data folder, and do not query the real database.
- Develop and test only with `--demo` mode or with temporary data dirs (`tmp_path` in pytest, `MYWEALTH_DATA_DIR` pointing to a temp folder).
- Never add CDNs, external fonts, analytics, telemetry or cloud services. All frontend assets are served locally.
- The only allowed outbound traffic is Yahoo Finance, and requests must contain only tickers/currency pairs and dates — never amounts, account names or other user data. Demo mode makes no network calls at all.
- The server binds only to `127.0.0.1`, checks the `Host` header and requires the per-run `X-MyWealth-Token` header on every API call. Do not weaken these checks.
- Never commit databases, exports, backups, `.mywealth` archives or `.env` files. Never open a real `.mywealth` archive; tests build their own from temporary data.
- Shortcuts, autostart entries and the Edge app-window profile are created on the user's machine only by the user (`--install-shortcuts` or Settings). Do not run those commands yourself.

## Commands

- `uv sync` — install dependencies
- `uv run mywealth --demo` — run with synthetic data, no network (use this for development and UI checks)
- `uv run pytest` — run tests
- The real app (`uv run mywealth`, `mywealth-gui`, the Start-menu shortcut) is run by the user, not by Claude.
- `uv run mywealth --install-shortcuts` / `--uninstall-shortcuts` — Start menu and desktop shortcuts (user only, see SPEC §13)
- `uv run python tools/make_icon.py` — regenerate `mywealth/web/icon.ico` from the mark in `icon.svg`

## Tech constraints

- Python ≥ 3.10, managed with `uv`.
- Backend: standard-library HTTP server with a JSON API; `sqlite3` from the stdlib for storage.
- Market data: `yfinance` + `pandas`. **`numpy` is pinned to `2.1.3`**: newer versions are blocked by AppLocker/WDAC on the user's machine. Do not add other dependencies with compiled extensions without asking first (they may be blocked too).
- Frontend: vanilla HTML/CSS/JS, SVG charts, no framework, no build step. Colors only via CSS variables; light and dark themes.
- Reference project: https://github.com/cricci3/PortfolioTracker (same author, MIT). Investment logic and UI (Yahoo access, FX, XIRR, Modified Dietz, charts) should be ported from there and adapted, not added as a dependency.

## Money handling

- Store amounts as integers in minor units; use `Decimal` for calculations. Never use `float` for money.
- Account balances are derived (opening balance + movements), never stored.
- Every transaction stores its EUR exchange rate for its date; historical reports use that snapshot.
- Minor-unit currencies follow ISO 4217 decimals (e.g. JPY has 0).

## Conventions

- Code, identifiers, comments and commit messages in English; UI text in Italian.
- Number display `it-IT` (`1.234,56`); input accepts both `1.234,56` and `1234.56`.
- Schema changes go through versioned migrations.
- Every feature comes with pytest tests on a temporary database.
- UI changes: check them in `--demo` mode, in both themes and at a narrow window width.

## Workflow

- Work one milestone at a time (see SPEC.md §11). At the end of each: tests green, demo checked, short summary of what changed and of any decision taken that the spec didn't cover.
- If the spec is ambiguous on something that touches money (balances, FX, interest, investments), ask before choosing.
