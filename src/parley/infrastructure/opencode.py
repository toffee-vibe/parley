"""opencode: события Parley приходят агенту сами, как сообщения в его сессию.

Claude Code слушает Parley через Monitor, Codex — вызывая `listen` в цикле. У opencode Monitor нет, а
висеть в `listen` агенту неудобно: пока он там, он не может ответить. Поэтому, когда к Parley подключён
opencode, Parley сам доставляет ему события: находит сессию opencode в папке проекта и отправляет
в неё синтетический ввод (`POST /api/session/{id}/synthetic` через `opencode api` — так не нужно
искать адрес и пароль сервера opencode).

Сообщение выглядит так (по строке JSON на событие, как поток /events.ndjson):

    Parley events (from the microphone, not typed by the user):
    {"seq": 12, "kind": "heard", "text": "I worked on data pipelines", ...}
"""

from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..application.ports import JournalEntry
from ..application.queries import for_agent

log = logging.getLogger(__name__)

HEADER = "Parley events (from the microphone, not typed by the user):"
GATHER_S = 0.4      # события, пришедшие почти одновременно, уходят одним сообщением
SESSIONS_SCANNED = 30


class OpencodeCli:
    """Сервер opencode через его же утилиту `opencode api` (она знает адрес фонового сервиса)."""

    def __init__(self, project: Path, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.project = project.resolve()
        self._run = run

    @property
    def installed(self) -> bool:
        return shutil.which("opencode") is not None

    def latest_session(self) -> str | None:
        """Самая свежая сессия opencode в папке проекта — та, где сейчас идёт разговор с Пипом."""
        data = self._api("GET", "/api/session", "--param", "order=updated", "--param", f"limit={SESSIONS_SCANNED}")
        for session in (data or {}).get("data", []):
            directory = (session.get("location") or {}).get("directory")
            if directory and Path(directory).resolve() == self.project:
                return session["id"]
        return None

    def deliver(self, session_id: str, text: str) -> bool:
        body = {"text": text, "description": "Parley", "delivery": "queue"}
        return self._api("POST", f"/api/session/{session_id}/synthetic", "-d", json.dumps(body, ensure_ascii=False)) \
            is not None

    def _api(self, *args: str) -> dict[str, Any] | None:
        exe = shutil.which("opencode") or "opencode"  # полный путь: на Windows это .cmd-обёртка
        try:
            done = self._run([exe, "api", *args], cwd=self.project, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("opencode api %s: %s", args[1], e)
            return None
        if done.returncode != 0 or not done.stdout.lstrip().startswith("{"):
            log.warning("opencode api %s %s: %s", args[0], args[1], (done.stderr or done.stdout)[:200])
            return None
        return json.loads(done.stdout)


class OpencodeBridge:
    """Подписчик журнала: пока подключён opencode, пересылает ему события, нужные агенту."""

    def __init__(self, cli: OpencodeCli, partner: Callable[[], str]):
        self.cli = cli
        self.partner = partner  # имя подключённого агента (ClaudePresence.client)
        self._events: queue.Queue[JournalEntry] = queue.Queue()
        threading.Thread(target=self._run, name="opencode-bridge", daemon=True).start()

    @property
    def active(self) -> bool:
        return "opencode" in self.partner()

    def on_entry(self, entry: JournalEntry) -> None:
        if for_agent(entry) and self.active:
            self._events.put(entry)

    def _run(self) -> None:
        while True:
            batch = [self._events.get()]
            try:
                while True:
                    batch.append(self._events.get(timeout=GATHER_S))
            except queue.Empty:
                pass
            try:
                self.send(batch)
            except Exception:
                log.exception("opencode: не удалось передать события")

    def send(self, batch: list[JournalEntry]) -> bool:
        session = self.cli.latest_session()
        if session is None:
            log.warning("opencode: нет сессии в %s — события не доставлены", self.cli.project)
            return False
        text = "\n".join([HEADER, *(json.dumps(e.as_dict(), ensure_ascii=False) for e in batch)])
        return self.cli.deliver(session, text)
