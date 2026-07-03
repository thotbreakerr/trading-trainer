"""Mechanical enforcement of the no-lookahead contract (doc §8): raw bar
reads exist ONLY inside the gate modules. Everything else must go through a
clock-bound BarWindow."""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

RESTRICTED_READS = ("get_bars_1m_raw", "get_bars_daily_raw", "last_bar_ts")
GATE_MODULES = {
    "marketdata/store.py",   # defines them
    "marketdata/fetcher.py",  # ingest side
    "marketdata/window.py",   # the clock-bound gate
}


def _sources():
    for path in APP.rglob("*.py"):
        yield path.relative_to(APP).as_posix(), path.read_text(encoding="utf-8")


def test_raw_bar_reads_only_in_gate_modules():
    violations = [
        f"{rel} references {name}"
        for rel, text in _sources()
        if rel not in GATE_MODULES
        for name in RESTRICTED_READS
        if name in text
    ]
    assert not violations, "no-lookahead contract broken:\n" + "\n".join(violations)


def test_no_direct_sql_on_bar_tables_outside_store():
    violations = [
        f"{rel} queries {table} directly"
        for rel, text in _sources()
        if rel != "marketdata/store.py" and not rel.endswith("schema.sql")
        for table in ("FROM bars_1m", "FROM bars_daily")
        if table in text
    ]
    assert not violations, "raw SQL on bar tables outside store.py:\n" + "\n".join(violations)