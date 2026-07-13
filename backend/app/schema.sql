-- Day Trading Trainer — SQLite schema (doc §14, plus the calendar cache §16.1).
-- Applied idempotently on every startup. Timestamps: TEXT ISO-8601 UTC.
-- Dates: TEXT YYYY-MM-DD (ET trading dates). Account equity / win rate /
-- expectancy are DERIVED from trades at read time — never stored.

CREATE TABLE IF NOT EXISTS bars_1m (
    symbol  TEXT NOT NULL,
    ts      TEXT NOT NULL,              -- bar START, UTC
    open    REAL NOT NULL,
    high    REAL NOT NULL,
    low     REAL NOT NULL,
    close   REAL NOT NULL,
    volume  INTEGER NOT NULL,
    session TEXT NOT NULL CHECK (session IN ('pre','rth','post')),
    PRIMARY KEY (symbol, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS bars_daily (
    symbol TEXT NOT NULL,
    day    TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (symbol, day)
) WITHOUT ROWID;

-- Lazy-fetch bookkeeping. A day is COMPLETE when fetched_at is safely after
-- that day's extended close (see fetcher) — until then it stays refetchable.
CREATE TABLE IF NOT EXISTS cached_days (
    symbol     TEXT NOT NULL,
    day        TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, day)
) WITHOUT ROWID;

-- Exchange calendar cache: only trading days appear. Clock times are ET
-- strings as published; all session logic reads this table (no hardcoded times).
CREATE TABLE IF NOT EXISTS calendar (
    day              TEXT PRIMARY KEY,
    open_et          TEXT NOT NULL,     -- '09:30'
    close_et         TEXT NOT NULL,     -- '16:00' ('13:00' on half days)
    session_open_et  TEXT NOT NULL,     -- '04:00'
    session_close_et TEXT NOT NULL      -- '20:00'
) WITHOUT ROWID;

-- Curriculum progress: one row per completed lesson step (doc §12).
CREATE TABLE IF NOT EXISTS progress (
    module         INTEGER NOT NULL,
    step           INTEGER NOT NULL,
    completed_at   TEXT NOT NULL,
    practice_grade TEXT,                -- practice steps: best grade achieved
    PRIMARY KEY (module, step)
);

-- Every fired setup, coach-proposed or batch-scanned (doc §10, §11).
CREATE TABLE IF NOT EXISTS setups (
    id             INTEGER PRIMARY KEY,
    symbol         TEXT NOT NULL,
    day            TEXT NOT NULL,
    fired_ts       TEXT NOT NULL,
    setup_type     TEXT NOT NULL,
    direction      TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry          REAL,
    stop           REAL,
    target         REAL,
    rr             REAL,
    grade          TEXT,                -- Textbook|Solid|Risky|Reckless
    checklist      TEXT,                -- JSON: the always-displayed checklist
    status         TEXT NOT NULL,       -- fired|watching|acted|invalidated|expired
    outcome        TEXT,                -- hindsight tracking: target|stop|eod
    outcome_r      REAL,
    taken          INTEGER NOT NULL DEFAULT 0,
    user_action_ts TEXT,
    user_grade     TEXT,                -- grade of the user's decision at that moment
    user_checklist TEXT,                -- JSON
    mode           TEXT NOT NULL,       -- practice|marketday
    note           TEXT                 -- e.g. 'missed (app closed)'
);
CREATE INDEX IF NOT EXISTS idx_setups_day ON setups (day);

-- Sim order lifecycle; bracket legs share a bracket_id (doc §9).
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY,
    mode        TEXT NOT NULL,          -- practice|marketday
    day         TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL CHECK (side IN ('buy','sell')),
    type        TEXT NOT NULL CHECK (type IN ('market','limit','stop')),
    qty         INTEGER NOT NULL,
    limit_price REAL,
    stop_price  REAL,
    bracket_id  TEXT,
    role        TEXT NOT NULL DEFAULT 'standalone',  -- entry|stop|target|standalone
    status      TEXT NOT NULL,          -- working|filled|canceled|rejected
    placed_ts   TEXT NOT NULL,
    filled_ts   TEXT,
    fill_price  REAL,
    reason      TEXT                    -- reject/cancel reason
);
CREATE INDEX IF NOT EXISTS idx_orders_day ON orders (day);

-- The trade journal: every round trip with its R-multiple (doc §9, §14).
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY,
    mode        TEXT NOT NULL,          -- practice|marketday
    day         TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('long','short')),
    qty         INTEGER NOT NULL,
    entry_ts    TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_ts     TEXT,
    exit_price  REAL,
    exit_reason TEXT,                   -- target|stop|manual|eod
    stop_price  REAL,                   -- initial stop: defines 1R
    r_multiple  REAL,
    grade       TEXT,
    checklist   TEXT,                   -- JSON
    setup_id    INTEGER REFERENCES setups (id)
);
CREATE INDEX IF NOT EXISTS idx_trades_day ON trades (day);

-- Morning briefing snapshots — what EOD grades the plan against (doc §11).
CREATE TABLE IF NOT EXISTS briefings (
    day        TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    snapshot   TEXT NOT NULL            -- JSON
) WITHOUT ROWID;

-- Applied migration ledger. The schema remains a complete fresh-install
-- definition; numbered migrations bring older databases to the same shape.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
) WITHOUT ROWID;

-- User-authored post-trade review. Metrics such as MFE/MAE remain derived
-- from immutable bars and trade timestamps at read time.
CREATE TABLE IF NOT EXISTS trade_reviews (
    trade_id    INTEGER PRIMARY KEY REFERENCES trades (id) ON DELETE CASCADE,
    thesis      TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    confidence  INTEGER CHECK (confidence BETWEEN 1 AND 5),
    emotion     TEXT NOT NULL DEFAULT '',
    mistakes    TEXT NOT NULL DEFAULT '[]',
    tags        TEXT NOT NULL DEFAULT '[]',
    reviewed    INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0, 1)),
    updated_at  TEXT NOT NULL
);

-- Derived scenario index. It can be rebuilt from complete cached days.
CREATE TABLE IF NOT EXISTS scenario_catalog (
    id          TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    day         TEXT NOT NULL,
    fired_ts    TEXT NOT NULL,
    setup_type  TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry       REAL NOT NULL,
    stop        REAL NOT NULL,
    target      REAL NOT NULL,
    grade       TEXT,
    checklist   TEXT,
    indexed_at  TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_scenario_filters
    ON scenario_catalog (setup_type, direction, symbol, day);

CREATE TABLE IF NOT EXISTS scenario_playlists (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES scenario_playlists (id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    position    INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS workout_runs (
    id          INTEGER PRIMARY KEY,
    day         TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS workout_items (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES workout_runs (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    setup       TEXT NOT NULL,
    reps        INTEGER NOT NULL,
    weakness_score REAL NOT NULL,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    completed_at TEXT,
    UNIQUE (run_id, position)
);

CREATE TABLE IF NOT EXISTS briefing_predictions (
    id           INTEGER PRIMARY KEY,
    day          TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('bullish','bearish','neutral')),
    key_level    REAL,
    setup        TEXT NOT NULL DEFAULT '',
    invalidation TEXT NOT NULL DEFAULT '',
    confidence   INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    locked_at    TEXT,
    is_late      INTEGER NOT NULL DEFAULT 0 CHECK (is_late IN (0, 1)),
    UNIQUE (day, symbol)
);
CREATE INDEX IF NOT EXISTS idx_predictions_day ON briefing_predictions (day);

CREATE TABLE IF NOT EXISTS risk_events (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT,
    mode        TEXT NOT NULL,
    day         TEXT NOT NULL,
    ts          TEXT NOT NULL,
    rule_key    TEXT NOT NULL,
    action      TEXT NOT NULL,
    disposition TEXT NOT NULL,
    detail      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_events_day ON risk_events (day, ts);
