"""Lesson content loader (doc §7): lessons are YAML data, not code.

Each lessons/module_NN_*.yaml is parsed and schema-validated independently.
A file that fails validation — or whose hand-picked demo days turn out not
to be fetchable — marks THAT module unavailable with a precise reason; the
app always boots.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

STEP_TYPES = {"action", "explain", "replay", "quiz", "practice"}
PAUSE_RE = re.compile(r"^\d{2}:\d{2}$")

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"


class LessonError(ValueError):
    pass


@dataclass
class LessonStep:
    index: int
    type: str
    title: str
    body: str = ""
    # action
    pointer_target: str | None = None
    pointer_label: str | None = None
    # replay / practice
    symbol: str | None = None
    day: date | None = None
    start: str = "open"
    pauses: list[dict] = field(default_factory=list)  # {"at": "09:35", "note": md}
    goal: str | None = None
    require_grade: str | None = None  # graded practice gate (doc §12)
    # quiz
    question: str | None = None
    choices: list[dict] = field(default_factory=list)  # {"text", "correct", "explain"}


@dataclass
class LessonModule:
    module: int
    title: str
    summary: str
    steps: list[LessonStep]
    path: Path
    chart_symbol: str | None = None  # default chart behind action/explain steps
    chart_day: date | None = None
    status: str = STATUS_OK
    status_reason: str | None = None

    @property
    def demo_days(self) -> list[tuple[str, date]]:
        days = [
            (s.symbol, s.day)
            for s in self.steps
            if s.symbol is not None and s.day is not None
        ]
        if self.chart_symbol and self.chart_day:
            days.append((self.chart_symbol, self.chart_day))
        return days


def _require(cond: bool, path: Path, ctx: str, msg: str) -> None:
    if not cond:
        raise LessonError(f"{path.name}: {ctx}: {msg}")


def _parse_step(raw: dict, index: int, path: Path) -> LessonStep:
    ctx = f"step {index + 1}"
    _require(isinstance(raw, dict), path, ctx, "must be a mapping")
    step_type = raw.get("type")
    _require(step_type in STEP_TYPES, path, ctx, f"type must be one of {sorted(STEP_TYPES)}")
    title = raw.get("title")
    _require(bool(title), path, ctx, "missing title")
    step = LessonStep(index=index, type=step_type, title=str(title), body=str(raw.get("body", "")))

    if step_type == "action":
        pointer = raw.get("pointer") or {}
        _require(bool(pointer.get("target")), path, ctx, "action step needs pointer.target")
        _require(bool(pointer.get("label")), path, ctx, "action step needs pointer.label")
        step.pointer_target = str(pointer["target"])
        step.pointer_label = str(pointer["label"])

    if step_type in ("replay", "practice"):
        _require(bool(raw.get("symbol")), path, ctx, f"{step_type} step needs a symbol")
        _require(bool(raw.get("date")), path, ctx, f"{step_type} step needs a date")
        step.symbol = str(raw["symbol"]).upper()
        raw_date = raw["date"]
        try:
            step.day = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
        except ValueError:
            raise LessonError(f"{path.name}: {ctx}: bad date {raw_date!r} (YYYY-MM-DD)")
        start = raw.get("start", "open")
        _require(start in ("open", "session_open"), path, ctx, "start must be open|session_open")
        step.start = start

    if step_type == "replay":
        for i, pause in enumerate(raw.get("pauses") or []):
            at = str(pause.get("at", ""))
            _require(bool(PAUSE_RE.match(at)), path, ctx, f"pause {i + 1}: at must be ET HH:MM")
            _require(bool(pause.get("note")), path, ctx, f"pause {i + 1}: missing note")
            step.pauses.append({"at": at, "note": str(pause["note"])})

    if step_type == "practice":
        _require(bool(raw.get("goal")), path, ctx, "practice step needs a goal")
        step.goal = str(raw["goal"])
        required = raw.get("require_grade")
        if required is not None:
            _require(
                required in ("Solid", "Textbook"), path, ctx,
                "require_grade must be Solid or Textbook",
            )
            step.require_grade = str(required)

    if step_type == "quiz":
        _require(bool(raw.get("question")), path, ctx, "quiz needs a question")
        step.question = str(raw["question"])
        choices = raw.get("choices") or []
        _require(len(choices) >= 2, path, ctx, "quiz needs at least 2 choices")
        correct = 0
        for i, choice in enumerate(choices):
            _require(bool(choice.get("text")), path, ctx, f"choice {i + 1}: missing text")
            if choice.get("correct"):
                correct += 1
            step.choices.append(
                {
                    "text": str(choice["text"]),
                    "correct": bool(choice.get("correct", False)),
                    "explain": str(choice.get("explain", "")),
                }
            )
        _require(correct == 1, path, ctx, f"quiz needs exactly 1 correct choice, found {correct}")

    return step


def _parse_file(path: Path) -> LessonModule:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), path, "file", "top level must be a mapping")
    module = raw.get("module")
    _require(isinstance(module, int) and 1 <= module <= 10, path, "file", "module must be 1..10")
    _require(bool(raw.get("title")), path, "file", "missing title")
    steps_raw = raw.get("steps")
    _require(isinstance(steps_raw, list) and len(steps_raw) > 0, path, "file", "steps must be a non-empty list")
    steps = [_parse_step(s, i, path) for i, s in enumerate(steps_raw)]
    chart_symbol = chart_day = None
    chart = raw.get("chart")
    if chart is not None:
        _require(isinstance(chart, dict), path, "chart", "must be a mapping")
        _require(bool(chart.get("symbol")) and bool(chart.get("date")), path, "chart", "needs symbol and date")
        chart_symbol = str(chart["symbol"]).upper()
        raw_day = chart["date"]
        try:
            chart_day = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
        except ValueError:
            raise LessonError(f"{path.name}: chart: bad date {raw_day!r}")
    return LessonModule(
        module=module,
        title=str(raw["title"]),
        summary=str(raw.get("summary", "")),
        steps=steps,
        path=path,
        chart_symbol=chart_symbol,
        chart_day=chart_day,
    )


def _placeholder(path: Path, reason: str) -> LessonModule:
    match = re.match(r"module_(\d+)", path.stem)
    number = int(match.group(1)) if match else 0
    return LessonModule(
        module=number,
        title=path.stem,
        summary="",
        steps=[],
        path=path,
        status=STATUS_UNAVAILABLE,
        status_reason=reason,
    )


def load_lessons(lessons_dir: Path) -> list[LessonModule]:
    """Parse every module file; schema failures mark that module unavailable
    (with the file + reason) rather than breaking startup."""
    modules: list[LessonModule] = []
    seen: set[int] = set()
    for path in sorted(lessons_dir.glob("module_*.yaml")):
        try:
            mod = _parse_file(path)
            if mod.module in seen:
                raise LessonError(f"{path.name}: duplicate module number {mod.module}")
            seen.add(mod.module)
            modules.append(mod)
        except LessonError as e:
            logger.error("lesson file invalid: %s", e)
            modules.append(_placeholder(path, str(e)))
        except yaml.YAMLError as e:
            logger.error("lesson file invalid: %s: %s", path.name, e)
            modules.append(_placeholder(path, f"{path.name}: {e}"))
    modules.sort(key=lambda m: m.module)
    return modules


def validate_demo_days(modules: list[LessonModule], fetcher, calendar) -> None:
    """Startup check (doc §7): every hand-picked demo day must be a trading
    day and fetchable. Failures mark the module unavailable — never a broken
    lesson at click time."""
    from app.marketdata.fetcher import NotTradingDay

    for mod in modules:
        if mod.status != STATUS_OK:
            continue
        for symbol, day in mod.demo_days:
            try:
                fetcher.ensure_day(symbol, day)
            except NotTradingDay:
                mod.status = STATUS_UNAVAILABLE
                mod.status_reason = f"{mod.path.name}: {symbol} {day} is not a trading day"
                logger.error("lesson demo day invalid: %s", mod.status_reason)
                break
            except Exception as e:  # provider/calendar errors: report, don't crash
                mod.status = STATUS_UNAVAILABLE
                mod.status_reason = f"{mod.path.name}: {symbol} {day} not fetchable: {e}"
                logger.error("lesson demo day unfetchable: %s", mod.status_reason)
                break
