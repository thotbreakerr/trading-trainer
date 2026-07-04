"""Lesson loader: the REAL content files must parse; broken files/demo days
mark modules unavailable with a precise reason — the app always boots
(doc §7)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.config import PROJECT_ROOT
from app.lessons.loader import (
    STATUS_OK,
    STATUS_UNAVAILABLE,
    load_lessons,
    validate_demo_days,
)
from app.marketdata.calendar import MarketCalendar
from app.marketdata.fetcher import Fetcher
from tests.conftest import NOW_AFTER_CLOSE, FakeProvider, fixture_calendar

LESSONS_DIR = PROJECT_ROOT / "lessons"


def test_shipped_lesson_files_all_parse():
    modules = load_lessons(LESSONS_DIR)
    assert [m.module for m in modules] == [1, 2, 3, 4, 5, 6, 7]
    for mod in modules:
        assert mod.status == STATUS_OK, f"module {mod.module}: {mod.status_reason}"
        assert mod.steps, mod.path.name
        assert mod.demo_days, f"module {mod.module} teaches without data?"
        types = {s.type for s in mod.steps}
        assert "quiz" in types, f"module {mod.module} has no quiz"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_bad_yaml_marks_module_unavailable_not_fatal(tmp_path):
    _write(tmp_path, "module_03_broken.yaml", "module: 3\ntitle: X\nsteps: [\n")
    modules = load_lessons(tmp_path)
    assert len(modules) == 1
    assert modules[0].status == STATUS_UNAVAILABLE
    assert modules[0].module == 3  # recovered from the filename
    assert "module_03_broken.yaml" in (modules[0].status_reason or "")


def test_schema_violations_carry_file_and_step_context(tmp_path):
    _write(
        tmp_path,
        "module_02_bad.yaml",
        """
module: 2
title: Bad quiz
steps:
  - type: quiz
    title: Two rights make a wrong
    question: Pick one
    choices:
      - {text: A, correct: true}
      - {text: B, correct: true}
""",
    )
    modules = load_lessons(tmp_path)
    reason = modules[0].status_reason or ""
    assert "module_02_bad.yaml" in reason
    assert "step 1" in reason and "exactly 1 correct" in reason


def test_action_step_requires_pointer(tmp_path):
    _write(
        tmp_path,
        "module_01_x.yaml",
        """
module: 1
title: X
steps:
  - type: action
    title: Click something
""",
    )
    modules = load_lessons(tmp_path)
    assert modules[0].status == STATUS_UNAVAILABLE
    assert "pointer.target" in (modules[0].status_reason or "")


def test_validate_demo_days_flags_non_trading_day(conn, tmp_path):
    _write(
        tmp_path,
        "module_01_x.yaml",
        """
module: 1
title: X
steps:
  - type: replay
    title: Weekend replay
    symbol: SPY
    date: "2026-06-13"
    pauses: []
""",
    )
    modules = load_lessons(tmp_path)
    assert modules[0].status == STATUS_OK
    provider = FakeProvider(fixture_calendar())
    calendar = MarketCalendar(conn, provider)
    fetcher = Fetcher(conn, provider, calendar, rvol_baseline_days=3, now_fn=lambda: NOW_AFTER_CLOSE)
    validate_demo_days(modules, fetcher, calendar)
    assert modules[0].status == STATUS_UNAVAILABLE
    assert "not a trading day" in (modules[0].status_reason or "")


def test_validate_demo_days_passes_good_days(conn, tmp_path):
    _write(
        tmp_path,
        "module_01_x.yaml",
        """
module: 1
title: X
chart: {symbol: SPY, date: "2026-06-16"}
steps:
  - type: replay
    title: Good replay
    symbol: SPY
    date: "2026-06-17"
    pauses:
      - {at: "09:45", note: look}
""",
    )
    modules = load_lessons(tmp_path)
    provider = FakeProvider(fixture_calendar())
    calendar = MarketCalendar(conn, provider)
    fetcher = Fetcher(conn, provider, calendar, rvol_baseline_days=3, now_fn=lambda: NOW_AFTER_CLOSE)
    validate_demo_days(modules, fetcher, calendar)
    assert modules[0].status == STATUS_OK
    assert ("SPY", date(2026, 6, 16)) in modules[0].demo_days  # module chart included
