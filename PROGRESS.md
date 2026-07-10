# Progress Log

Newest entries on top. One entry per work session, plus extra entries when a
decision is worth capturing on its own.

## 2026-07-09 — Five improvements shipped; running on live Alpaca data

**What changed:** Built five improvements on top of the v1 app and pushed them to
a personal public fork (`thotbreakerr/trading-trainer`): (1) **one-command app** —
FastAPI serves the built UI at `:8000`, root `run.ps1` bootstraps a fresh clone
(venv / pip / npm ci / build / open browser); (2) **replay step deltas** — the
step endpoint returns only the aggregated buckets it touched, the client merges
into the react-query cache and the chart applies incremental `series.update()`
instead of refetching all bars every second; (3) **CI + ruff + vitest** (first
frontend tests); (4) **secrets + backups** — `.env` moved out of the
OneDrive-synced project folder to `%LOCALAPPDATA%`, plus startup backups of the
five non-rebuildable tables; (5) **drill mode** — deliberate-practice reps of a
chosen setup mined from cached history (blind replay → trade or pass → reveal
with coach grade + hindsight outcome → per-concept stats). Also fixed two bugs:
session restart dropped `sim.mode` (mislabeled journaled trades), and the chart
crashed (`setVisibleRange` "Value is null") when a replay restart shrank the data
under a saved visible range. Verified live in-browser on real Alpaca data.

**Why:** The app is meant for daily all-session use, so the two-process launch and
the per-second bars refetch during replay were the main friction points. Secrets/
DB hygiene matters because the project folder syncs to OneDrive (WAL corruption +
secret exposure). Drill mode turns the existing detector/replay/grader engines
into unlimited reps — the actual product thesis — with **no schema migration**
(the `mode`/`status` columns are unconstrained, so `mode='drill'` is pure data).

**Notable bits:**
- Step-delta merge is one contract mirrored on both sides and pinned by a golden
  test: `backend/app/api/chart_payload.py :: slice_step_delta`,
  `frontend/src/lib/mergeStepDelta.ts :: spliceTail`,
  `backend/tests/test_step_delta.py :: test_merge_equals_fresh_fetch_full_day_mixed_steps`
  (merge(prev, delta) must equal a fresh fetch). The trailing slice is exact
  because `bucket_start` is monotone and the ema/vwap series never rewrite past
  points.
- Drill anti-lookahead is structural, not client-trusted: signal data stays
  server-side in `backend/app/drill/runs.py`, the attempt payload carries only
  session bounds, and the fire moment hides behind an 8–20 bar randomized lead —
  `backend/app/drill/service.py :: jitter_start`. A no-leak test walks the payload
  for forbidden keys.
- Backups copy only the 5 user tables via `ATTACH` + `INSERT ... SELECT`, guarded
  by a drift test that forces every future schema table into user-vs-cache —
  `backend/app/backup.py :: create_backup`.
- Chart-crash fix: scroll preservation is cosmetic, so every `setVisibleRange` is
  wrapped and falls back to re-fitting the day —
  `frontend/src/chart/ChartPane.tsx :: fitAnchor` (in the data effect).

**Open threads:**
- **CI unverified:** the first GitHub Actions run on `thotbreakerr/trading-trainer`
  and the README badge haven't been confirmed green.
- **Drill not exercised on the real account:** it's gated behind Module 8, which
  hasn't been completed on the real DB (only verified earlier with seeded
  fixtures in `test_drill.py`). Standing offer to fast-unlock by inserting
  `progress` rows for modules 1–8.
- **`run.ps1` default port 8000 collides with the user's other app (BookFinder,
  also on 8000).** BookFinder answers `/api/health` with 200, which false-triggers
  run.ps1's "already running → just open browser" check. User runs `-Port 8100`
  manually; changing the default to 8100 was offered but not taken.
- **Watchlist RVOL shows "–" after hours** — claimed expected (no intraday volume
  to compare) but not confirmed it populates during an open/replay session.
- **origin was repointed** from `MachoMuchacho99/Trading-Trainer` (no push access —
  403 as `thotbreakerr`) to the user's own `thotbreakerr/trading-trainer`. `main`
  on the fork is a single **squashed** commit; the granular 11-commit history
  survives only on the local `improvements` branch (unpushed).
- **Alpaca key rotation** was advised if `.env` ever lived in OneDrive; on this
  machine the keys were entered fresh into `%LOCALAPPDATA%`, so likely moot here.
- **favicon 404** in the console is harmless (`index.html` has no favicon link);
  add one to silence it if desired.
