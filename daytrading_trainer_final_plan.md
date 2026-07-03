# Day Trading Trainer — Final Plan (v1)

Working title TBD. A personal-first education app that teaches the fundamentals of day trading on **actual market data** — structured lessons replayed on real historical days, plus a daily coach that watches today's market, calls out textbook setups, and grades your decisions.

---

## Design principles (cross-cutting DNA)

- **Actual data only.** No synthetic ticks, no canned charts. Every lesson, replay, and callout runs on real bars.
- **Deterministic math, no LLM near the numbers.** Detectors and graders are pure Python.
- **Hard no-lookahead.** Nothing may read bars beyond the replay/session clock. Enforced at one point in the data access layer.
- **Worst-case bias in the sim.** Fills and ambiguity resolve pessimistically — honest teaching beats flattering results.
- **The coach only knows what you know.** Signals fire only for concepts you've unlocked.
- **Config in YAML, state in SQLite.** No settings screen; overrides are config edits.

---

## 1. Product definition

- Personal learning tool, single user, no auth.
- Data layer cleanly separated from UI so it *could* become a shareable product later.
- Two modes: **Learn** (historical replay lessons) and **Market Day** (daily coach loop).

## 2. Stack & architecture

- Local web app: **Python / FastAPI + SQLite** backend, **React** frontend, **TradingView Lightweight Charts** for candlestick/volume charting.
- Run locally, open in browser. Two processes (backend + frontend dev server).
- Backend fetches and caches all market data; frontend reads only from the backend.

## 3. Data source

- **Alpaca Market Data API only** (free Basic plan via paper-account signup). Key/secret in `.env`.
- Wrapped in a `data_provider.py` abstraction (Beethoven `llm.py` pattern) — swappable later.
- Free-tier facts the design relies on: historical bars at any 1–59 min aggregation, years of minute history, recent data available only up to 15 min ago, real-time is IEX-feed only (not used in v1).

## 4. Symbol universe

- US equities only. No crypto, futures, or options in v1.
- Fixed watchlist of ~8–10 ultra-liquid names, defined in config: **SPY, QQQ, AAPL, NVDA, TSLA, MSFT, AMD, META**.
- Editable via YAML; no screener, no watchlist-editing UI in v1.

## 5. Data layer

- **1-minute bars are the atomic unit**, stored in SQLite. 5m/15m/hourly derived by aggregation on the fly. Daily bars in their own table.
- Extended hours included in fetches; each bar tagged pre / RTH / post.
- **Lazy per-day fetch, cache forever.** Loading a day always fetches its lookback window too (prior-day levels + ~20-day RVOL baseline).
- First launch backfill: watchlist × last 30 trading days + today.
- Scale: ~10 symbols × 400–900 bars/day — years of cache is a few hundred MB. Fine.

## 6. Curriculum (10 modules, linear)

1. **Reading the chart** — candlesticks, volume, timeframes, sessions, bid-ask & spread
2. **Order types** — market vs. limit, stops, stop-limit, slippage
3. **Key levels** — prior day H/L, pre-market H/L, swing points, round numbers
4. **Trend & structure** — HH/HL, 9/20 EMA, 200 SMA context
5. **VWAP** — the intraday anchor
6. **Volume analysis** — relative volume, confirmation vs. divergence
7. **The open** — gap types, opening range, first 5/15/30 min dynamics
8. **Core setups** — opening range breakout, VWAP pullback/reclaim, key-level break, gap fill
9. **Risk management** — position sizing, stop placement, R-multiples, R:R, max daily loss, expectancy vs. win rate
10. **Trade planning, journaling, psychology** — plan before entry, review after, FOMO/revenge/overtrading

Scope calls: **shorts included**; **no indicator zoo** (no RSI/MACD/Bollinger — price, volume, levels, VWAP, EMAs only; one lesson mentions indicators exist); **out of v1:** options, Level 2 / tape reading, news catalysts (mentioned conceptually, never used by the coach).

## 7. Lesson engine

- Lessons are **YAML content files, not code** — an ordered list of steps: `action`, `explain`, `replay`, `quiz`, `practice`. Each step declares symbol+date to load, pause points, annotations by bar timestamp, questions.
- **Phase order is per-lesson data.** Default template is action-first: **Do → Read → Watch → Practice.** Lessons without a natural "do" hook (e.g., psychology) may order Read-first.
- **Guided pointer is the only interaction mode inside lessons:** everything dims except one target element, arrow + short label, only that element clickable. One valid action, no spam-click ambiguity. Free interaction is reserved for Practice and Market Day.
- Demo days are **hand-picked** in the YAML (known textbook-clean dates). Deterministic and testable.
- Lesson YAMLs are validated on startup (demo days fetchable → clear error, not a broken lesson).

## 8. Replay engine

- Single **replay clock** as source of truth. **Whole 1-min bars only** — no simulated intra-candle wiggle.
- Controls: pause, step-one-bar, 1×/2×/5× (bars per second), lesson auto-jump to next scripted moment.
- **No rewind in Practice — restart the day only.** (Scripted lesson Watch steps may navigate back a step.)
- Timeframe switching aggregates from 1-min, clipped to the clock. Prior days visible for context; the replay day starts hidden.
- No-lookahead enforced in the data access layer, not scattered checks.

## 9. Sim engine (paper trading)

- Orders: market, limit, stop, **brackets** (entry + stop-loss + target) — brackets are the default UI path.
- Fill model (honest with whole bars):
  - Market → fills at **next bar's open**.
  - Limit → fills when a bar trades through the price.
  - Stop → triggers on bar high/low cross; fills at stop price, **or the bar's open if price gapped past it**.
  - Same-bar stop+target ambiguity → **assume the stop fired** (worst case).
- Account: **$30k starting paper balance** (config), zero commission, no artificial slippage (next-open fills already impose real cost), **4× intraday buying power**. PDT rule taught, not enforced.
- **Sizing calculator:** entry + stop + 1% risk → share count.
- EOD discipline: warning at 3:50 ET, **auto-flatten at 4:00** at close price, logged as "forced EOD close."
- Every fill logs to the trade journal with its R-multiple.
- Sim edges: whole fills only (liquid names); unfilled entries and limits cancel at EOD; buying-power breach → clean reject.

## 10. Rules engine (the coach's brain)

**Layer 1 — Signal detectors.** One pure function per taught concept, reading only bars ≤ clock: gap up/down, opening-range breakout/breakdown, VWAP reclaim / pullback-hold, key-level break (PDH/PDL, pre-market H/L), relative-volume spike, trend state (9/20 EMA alignment). Each emits `{symbol, time, setup_type, direction, entry/stop/target refs, R:R}`. All thresholds (gap %, RVOL cutoff, OR minutes, min R:R, watch windows) live in `rules_config.yaml`.

**Layer 2 — Grader.** Any trade (coach-proposed or user-taken) is scored against a per-setup checklist: with trend? RVOL sufficient? R:R ≥ 2? stop behind structure? not chasing an extended move? Grade = pass count: **Textbook / Solid / Risky / Reckless.** The checklist is always displayed — no black box.

Structural rules:
- **Same engine in both modes** (replay Practice and live Market Day call identical code).
- **Signals fire only for unlocked concepts.**
- Detectors run in **two modes: live** (clock advances) and **batch** (scan a backfilled range).
- Chop mitigation: "Textbook" requires confluence (e.g., ORB needs RVOL above threshold); otherwise flagged "low quality — likely trap" as a teachable callout.

## 11. Market Day mode

### Data flow
- **Delayed-live via REST polling** every 60s — no websocket in v1. Session clock = **now − 15 min**, labeled honestly in the UI.
- Rationale: free real-time is IEX-only (~2% of volume — breaks RVOL); delayed SIP bars have correct OHLC *and* volume. Delayed-live is just the replay engine fed by a poller. Going truly live later = paid SIP feed as a config change.

### Callout lifecycle (state machine per fired setup)
1. **Fired** — card appears: setup, direction, entry/stop/target, R:R, grade + checklist, "watching for N min."
2. **Watching** — visible countdown (default ~10 min / 10 bars, per-setup in config); engine monitors confirmation vs. invalidation.
3. **Resolution** — exactly one of:
   - **You act** → bracket pre-filled from the card; grader scores the decision *at that moment* (acting on an already-invalidated setup = Reckless, with the reason).
   - **Invalidated** → card flips to "failed breakout — this was a trap, here's the tell."
   - **Expired** → fades to the day's log.
4. **Hindsight tracking** — every fired setup is tracked to its natural outcome (target/stop/EOD) whether traded or not. Pass decisions become learnable.
- Notifications: in-app cards + sound only; v1 requires the app open. Discord alerts deferred post-v1.

### Morning briefing
- Generated on-demand from cached pre-market bars when the app opens before 9:30 ET; **snapshot saved** for plan-vs-reality.
- Three sections:
  1. **Watchlist stat cards** — gap % vs. prior close, pre-market RVOL, pre-market H/L, prior day H/L/C, distance to nearest key level, daily trend state.
  2. **Focus list** — top 2–3 names by gap size × pre-market RVOL, with plain-language what-to-watch.
  3. **Game plan card** — setups in play (unlocked only) + key times (open, OR completion, 10:00 reversal window, 3:50 flatten warning) shown in **CT with ET labels**.
- Refreshing regenerates; the saved snapshot is what EOD grades against. No prediction quiz in v1.

### EOD recap
- Generated once after the 4:00 ET close; waits for the next app open. Four sections:
  1. **Setup ledger** — every fired setup: quality grade, took/passed, outcome.
  2. **Your trades** — grade + checklist, R-multiple, and a **Review button that opens the replay engine at that exact symbol/day/bar**.
  3. **Plan vs. reality** — briefing snapshot vs. what actually moved.
  4. **Trajectory stats** — cumulative + rolling-20-day: win rate, avg R, expectancy, and **grade distribution over time** (the primary progress metric).

## 12. Progression

- **Linear unlock, Module 1 → 10.** No skipping in the UI.
- Completion = all lesson steps done; modules with a Practice phase additionally require **executing the taught setup with an entry grade ≥ Solid** (infinitely retryable).
- **Market Day is accessible from day one in observe mode** — briefing, charts, and ledger work; un-learned setups appear as **locked cards**: "*Something* fired at 9:47 — unlocks in Module 8."
- **Trading inside Market Day unlocks after Module 9** (risk management). Lesson Practice is where trading lives before that.
- Escape hatch in config, not UI: `allow_untrained_trading: true`.

## 13. First-run experience

1. **Key setup (one-time, unskippable):** paste Alpaca key/secret → validated with a live test call → stored in `.env`. Blurb + link to free paper-account signup. No bundled sample data, no keyless demo mode.
2. **Initial fetch with visible progress** (watchlist × last 30 trading days + today).
3. **Land on today's chart**, market-state aware ("Market closed — showing Friday"). Any setups that fired today already sit there as locked cards.
4. **Guided pointer to Module 1** — dogfooding the lesson interaction from second zero.

## 14. Persistence

**YAML (human-editable):** watchlist, `rules_config.yaml`, lesson content files, escape hatches, starting balance.

**SQLite (8 tables):**
- `bars_1m` — symbol, ts (UTC), OHLCV, session tag; PK (symbol, ts)
- `bars_daily` — symbol, date, OHLCV
- `cached_days` — symbol, date, fetched_at (lazy-fetch bookkeeping)
- `progress` — module/step completions + practice grades
- `setups` — every fired setup: type, direction, entry/stop/target, grade, checklist JSON, outcome, taken?, user action + grade
- `orders` — sim order lifecycle (bracket legs carry state)
- `trades` — the journal: entries/exits, R-multiple, grade, checklist JSON, mode, setup link
- `briefings` — date + snapshot JSON

**Conventions:** timestamps stored UTC → session logic in ET → displayed in CT. Account equity / win rate / expectancy are **derived from `trades` at read time, never stored**. Recaps are views over `setups` + `trades` + `briefings`, not a table.

## 15. UI shell

Three top-level tabs, dark theme default:

1. **Market Day** *(default landing)* — chart-dominant: main chart with 1m/5m/15m switcher and session shading; **watchlist rail** left (price, gap %, RVOL; click to switch); **callout card stack** right (live countdowns); slim top bar (session clock "−15 min", market state, paper equity). Briefing takes over this tab pre-9:30; recap takes over post-close — same tab, market-state aware.
2. **Learn** — module list with progress states. A lesson is a **full-screen takeover**: chart on top, step panel below, guided-pointer overlay on top.
3. **Journal** — trades table (click → replay jump-back) + trajectory dashboard (grade distribution over time, equity curve, expectancy, win rate).

No settings screen — config is YAML, re-read on restart.

## 16. Edge cases (locked resolutions)

1. **Holidays / half days** — cache Alpaca's market calendar endpoint; *all* session logic reads it; half days flatten at 12:50/1:00 ET. No hardcoded times.
2. **DST** — safe by construction (UTC storage; ET/CT shift together).
3. **Stock splits** — fetch split-adjusted bars; detect any >40% overnight "move" in the daily table → warn + auto-refetch that symbol's cache.
4. **Sparse pre-market bars** — charts render real gaps; RVOL uses cumulative time-of-day comparison (robust to missing minutes).
5. **Lookback dependency** — "load day X" always fetches X + its lookback window; lesson YAMLs validated on startup.
6. **Poller failure mid-session** — banner "data stale since HH:MM," countdowns pause, auto-retry with backoff. Never silently stale.
7. **App closed during session** — on reopen, batch-scan the missed window; ledger entries marked "missed (app closed)." EOD recap always builds from a batch scan.
8. **Days the app never opened** — ledger/recap computable on demand for any cached day; plan-vs-reality shows "no briefing taken."
9. **Bad/expired API key** — re-prompt with the first-run validation screen.
10. **Sim edges** — whole fills only; unfilled entries/limits cancel at EOD; buying-power breach → clean reject; same-bar bracket conflict → stop assumed.

## 17. Build phases (each ends runnable + testable)

1. **Foundation** — FastAPI skeleton, SQLite schema, Alpaca provider, lazy fetch/cache, market calendar, first-run key flow. CLI-testable before any UI.
2. **Chart shell** — React three-tab shell, Lightweight Charts on cached data, timeframe aggregation, session shading, watchlist rail.
3. **Replay engine** — clock, controls, no-lookahead enforcement in the data layer.
4. **Lesson engine + Modules 1–7 content** — YAML step player, guided-pointer overlay (these modules need no sim).
5. **Sim engine** — orders, brackets, fill rules, journal table.
6. **Rules engine + Modules 8–10** — detectors in batch mode first (testable against cached history), grader, then the setup/risk modules whose Practice phases need both engines.
7. **Market Day** — poller, delayed-live clock, callout lifecycle, briefing, recap, hindsight tracking.
8. **Journal dashboard + hardening** — trajectory stats, edge-case sweep verification.

Sequencing logic: sim before rules (the grader scores trades); batch detectors before live (test on history you already have); Market Day last because it composes everything.

## 18. Explicitly deferred (post-v1)

- Discord bot alerts
- True real-time (paid SIP feed — config swap, not redesign)
- Websocket streaming
- Watchlist-editing UI / screener
- Keyless demo mode / bundled sample data
- Options, Level 2 / tape reading, news catalysts
- Briefing prediction quiz
