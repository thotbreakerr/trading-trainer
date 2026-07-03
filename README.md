# Day Trading Trainer

Personal education app that teaches day trading fundamentals on **actual market
data** — structured lessons replayed on real historical days, plus a daily coach
that watches today's (15-min-delayed) market, calls out textbook setups, and
grades your decisions. Full product spec: [daytrading_trainer_final_plan.md](daytrading_trainer_final_plan.md).

## Running (two processes)

```powershell
# backend (FastAPI on :8000)
cd backend
.\run.ps1

# frontend (Vite dev server, proxies /api -> :8000)
cd frontend
npm run dev
```

Open the printed Vite URL in a browser. First launch walks you through Alpaca
key setup (free paper-account signup) and the initial data backfill.

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

- `config/app_config.yaml` — watchlist, starting balance, DB path, escape hatches
- `config/rules_config.yaml` — detector thresholds and grading parameters
- `.env` — Alpaca key/secret (written by the first-run flow; **gitignored**, but
  note this folder syncs to OneDrive, so the secret will sync with it)

The SQLite database lives at `%LOCALAPPDATA%\trading-trainer\trainer.db` by
default — deliberately **outside** OneDrive (WAL + cloud sync is a corruption
risk). Market-data cache is rebuildable; progress/trades are not, so back that
file up if you care about your history.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest            # offline suite (fixtures only)
.\.venv\Scripts\python.exe -m pytest -m live    # real-API smoke tests (needs keys)
```
