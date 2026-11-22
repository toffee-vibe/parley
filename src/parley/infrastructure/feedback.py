"""Отзывы агента о работе Parley — сразу в файл, который читает человек (и разработчик).

~/.local/share/parley/feedback.md, по строке на отзыв:

    - 2026-11-22 02:49 [misheard] «описывать» вместо «овеществлять» (уже 1 раз)
    - 2026-11-22 02:50 [problem] Pip talked over the user — interrupted twice in a row

Пишет агент инструментами `misheard` и `note_for_developer`. Видно в `parley report`, входит в `parley bugreport`.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from ..application.ports import Recorder


class FeedbackBook:
    def __init__(self, path: Path, diary: Recorder | None = None):
        self.path = path
        self.diary = diary
        self._lock = threading.Lock()

    def write(self, kind: str, text: str) -> None:
        line = f"- {datetime.now():%Y-%m-%d %H:%M} [{kind}] {' '.join(text.split())}\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text("# Отзывы агентов о работе Parley\n\n", encoding="utf-8")
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        if self.diary:
            self.diary.record("feedback", feedback=kind, text=text)

    def recent(self, count: int = 20) -> list[str]:
        if not self.path.exists():
            return []
        return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")][-count:]
