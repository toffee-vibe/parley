"""Общие кирпичики домена: события, идентификаторы, базовый агрегат.

Домен ничего не знает о Qt, MCP, PipeWire и OpenRouter — только правила.
Время всегда передаётся снаружи (аргумент `now`), поэтому любое правило легко проверить в тесте.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, ClassVar


def new_id() -> str:
    """Короткий читаемый идентификатор: его удобно называть голосом и видеть в логах."""
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Что-то произошло. `kind` — имя события для журнала, SSE и интерфейса."""

    kind: ClassVar[str] = "event"
    at: datetime

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("at")
        return data


@dataclass
class Aggregate:
    """Агрегат копит события, а приложение забирает их после выполнения команды."""

    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False, compare=False)

    def _record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events
