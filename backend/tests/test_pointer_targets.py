"""Every pointer.target in shipped lesson YAML must exist in the frontend's
committed pointer-target manifest — a broken pointer is a broken lesson."""
from __future__ import annotations

import re

from app.config import PROJECT_ROOT
from app.lessons.loader import load_lessons

MANIFEST = PROJECT_ROOT / "frontend" / "src" / "lesson" / "pointerTargets.ts"
LESSONS_DIR = PROJECT_ROOT / "lessons"


def test_lesson_pointer_targets_exist_in_frontend_manifest():
    manifest_ids = set(re.findall(r"'([a-z0-9-]+)'", MANIFEST.read_text(encoding="utf-8")))
    assert manifest_ids, "manifest parsed empty — regex or file moved?"
    missing = []
    for mod in load_lessons(LESSONS_DIR):
        for step in mod.steps:
            if step.pointer_target and step.pointer_target not in manifest_ids:
                missing.append(f"module {mod.module} step {step.index + 1}: {step.pointer_target}")
    assert not missing, "lesson pointers without frontend targets:\n" + "\n".join(missing)
