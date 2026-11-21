"""Журнал событий в памяти: кольцевой буфер с номерами, ожиданием (long-poll) и подписчиками."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable

from ..application.ports import JournalEntry
from ..domain.shared import DomainEvent

log = logging.getLogger(__name__)


class InMemoryJournal:
    def __init__(self, capacity: int = 2000):
        self._entries: deque[JournalEntry] = deque(maxlen=capacity)
        self._seq = 0
        self._changed = threading.Condition()
        self._subscribers: list[Callable[[JournalEntry], None]] = []

    def publish(self, events: Iterable[DomainEvent]) -> None:
        fresh: list[JournalEntry] = []
        with self._changed:
            for event in events:
                self._seq += 1
                entry = JournalEntry(self._seq, event.kind, event.at, _jsonable(event.payload()))
                self._entries.append(entry)
                fresh.append(entry)
            if fresh:
                self._changed.notify_all()
        for entry in fresh:  # подписчиков зовём вне блокировки: они могут быть медленными
            for callback in list(self._subscribers):
                try:
                    callback(entry)
                except Exception:
                    log.exception("Подписчик журнала упал")

    def last_seq(self) -> int:
        with self._changed:
            return self._seq

    def after(self, seq: int) -> list[JournalEntry]:
        with self._changed:
            return [e for e in self._entries if e.seq > seq]

    def wait(self, after: int, timeout_s: float) -> list[JournalEntry]:
        with self._changed:
            self._changed.wait_for(lambda: self._seq > after, timeout=max(timeout_s, 0))
            return [e for e in self._entries if e.seq > after]

    def subscribe(self, callback: Callable[[JournalEntry], None]) -> None:
        self._subscribers.append(callback)


def _jsonable(data: dict) -> dict:
    """Перечисления и даты → строки, чтобы событие можно было сразу отдать в JSON."""
    out = {}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat(timespec="seconds")
        elif hasattr(value, "value"):
            value = value.value
        out[key] = value
    return out
