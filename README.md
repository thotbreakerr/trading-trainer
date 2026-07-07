# Day Trading Trainer

[![CI](https://github.com/MachoMuchacho99/Trading-Trainer/actions/workflows/ci.yml/badge.svg)](https://github.com/MachoMuchacho99/Trading-Trainer/actions/workflows/ci.yml)

Personal education app that teaches day trading fundamentals on **actual market
data** — structured lessons replayed on real historical days, plus a daily coach
that watches today's (15-min-delayed) market, calls out textbook setups, and
grades your decisions. Full product spec: [daytrading_trainer_final_plan.md](daytrading_trainer_final_plan.md).

## Running

One command from a fresh clone — creates the venv, installs dependencies,
builds the UI, starts the backend on :8000, and opens the browser:

```powershell
.\run.ps1
```

Flags: `-Build` rebuilds the UI after frontend changes, `-Setup` redoes the
venv/npm installs, `-Port` picks the port. Needs Python 3.12+ and Node
installed; everything else is bootstrapped. First launch then walks you
through Alpaca key setup (free paper-account signup) and the initial data
backfill in the app itself.

### Development (two processes, hot reload)

```powershell
# backend (FastAPI on :8000)
cd backend
.\run.ps1

# frontend (Vite dev server, proxies /api -> :8000)
cd frontend
npm run dev
```

Open the printed Vite URL. The backend serves the *built* UI from
`frontend/dist` when it exists — `npm run dev` is the loop for UI work;
`.\run.ps1 -Build` refreshes what the one-command app serves.

## CLI (backend verification without the UI)

```powershell
cd backend
.\.venv\Scripts\python.exe cli.py validate-keys
.\.venv\Scripts\python.exe cli.py fetch SPY 2026-06-15
.\.venv\Scripts\python.exe cli.py backfill
.\.venv\Scripts\python.exe cli.py days SPY
```

## Configuration

No settings screen by design — edit YAML, restart:

- `config/app_config.yaml` — watchlist, starting balance, DB path, backups, escape hatches
- `config/rules_config.yaml` — detector thresholds and grading parameters
- `%LOCALAPPDATA%\trading-trainer\.env` — Alpaca key/secret (written by the
  first-run flow; lives **outside** the OneDrive-synced project folder). A
  legacy `.env` at the repo root is migrated there automatically on startup.
  **Security note:** if you ever had `.env` in the project root, rotate the
  Alpaca key pair — OneDrive's online recycle bin retains deleted files ~30 days.

The SQLite database lives at `%LOCALAPPDATA%\trading-trainer\trainer.db` by
default — deliberately **outside** OneDrive (WAL + cloud sync is a corruption
risk). Market-data cache is rebuildable; progress/trades are not.

### Backups

On startup (at most every `backup_min_interval_hours`), the app snapshots the
non-rebuildable tables (progress, setups, orders, trades, briefings) to
`backups/trainer-<timestamp>.db`, keeping the newest `backup_keep` files
(0 disables). Cold single-file copies are safe in OneDrive — it's the live
WAL database that isn't — so the synced folder doubles as off-machine backup.

**Restore:** stop the app, copy a backup over
`%LOCALAPPDATA%\trading-trainer\trainer.db`, delete any `trainer.db-wal` /
`trainer.db-shm` next to it, start the app. Bars refetch lazily.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest            # offline suite (fixtures only)
.\.venv\Scripts\python.exe -m pytest -m live    # real-API smoke tests (needs keys)
.\.venv\Scripts\python.exe -m ruff check .      # lint

cd frontend
npm test                                        # vitest (pure-logic suites)
```

CI (GitHub Actions) runs the backend suite + ruff and the frontend
typecheck + tests + build on every push and PR.
