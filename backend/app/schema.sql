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
