-- Additive migration for journal reviews, scenario exploration, adaptive
-- workouts, briefing predictions, and session risk coaching.
CREATE TABLE IF NOT EXISTS trade_reviews (
    trade_id INTEGER PRIMARY KEY REFERENCES trades (id) ON DELETE CASCADE,
    thesis TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    confidence INTEGER CHECK (confidence BETWEEN 1 AND 5), emotion TEXT NOT NULL DEFAULT '',
    mistakes TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]',
    reviewed INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0, 1)), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_catalog (
    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, day TEXT NOT NULL, fired_ts TEXT NOT NULL,
    setup_type TEXT NOT NULL, direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL, grade TEXT,
    checklist TEXT, indexed_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_scenario_filters ON scenario_catalog (setup_type, direction, symbol, day);
CREATE TABLE IF NOT EXISTS scenario_playlists (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES scenario_playlists (id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (playlist_id, scenario_id)
);
CREATE TABLE IF NOT EXISTS workout_runs (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS workout_items (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES workout_runs (id) ON DELETE CASCADE,
    position INTEGER NOT NULL, setup TEXT NOT NULL, reps INTEGER NOT NULL,
    weakness_score REAL NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    completed_at TEXT, UNIQUE (run_id, position)
);
CREATE TABLE IF NOT EXISTS briefing_predictions (
    id INTEGER PRIMARY KEY, day TEXT NOT NULL, symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('bullish','bearish','neutral')),
    key_level REAL, setup TEXT NOT NULL DEFAULT '', invalidation TEXT NOT NULL DEFAULT '',
    confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, locked_at TEXT,
    is_late INTEGER NOT NULL DEFAULT 0 CHECK (is_late IN (0, 1)), UNIQUE (day, symbol)
);
CREATE INDEX IF NOT EXISTS idx_predictions_day ON briefing_predictions (day);
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY, session_id TEXT, mode TEXT NOT NULL, day TEXT NOT NULL,
    ts TEXT NOT NULL, rule_key TEXT NOT NULL, action TEXT NOT NULL,
    disposition TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_events_day ON risk_events (day, ts);
