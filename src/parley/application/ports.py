"""Порты — всё, что приложению нужно от внешнего мира. Реализации лежат в infrastructure/.

Хочешь заменить распознавание, озвучку или базу — пишешь новый класс с такими же методами
и подставляешь его в bootstrap.py. Остальной код не меняется.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..domain.conversation import Utterance
from ..domain.learning import Mistake, Phrase
from ..domain.memory import Fact
from ..domain.shared import DomainEvent


class Clock(Protocol):
    def now(self) -> datetime: ...


# --- журнал событий: то, что видят Claude (listen / SSE) и интерфейс ---


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    kind: str
    at: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "at": self.at.isoformat(timespec="seconds"), **self.data}


class Journal(Protocol):
    def publish(self, events: Iterable[DomainEvent]) -> None: ...
    def last_seq(self) -> int: ...
    def after(self, seq: int) -> list[JournalEntry]: ...
    def wait(self, after: int, timeout_s: float) -> list[JournalEntry]:
        """Ждёт записей новее `after` не дольше timeout_s. Пустой список — ничего не случилось."""
        ...
    def subscribe(self, callback: Callable[[JournalEntry], None]) -> None: ...


# --- технический дневник: как работает само приложение (infrastructure/diary.py) ---


class Recorder(Protocol):
    def record(self, kind: str, **data: Any) -> None: ...


# --- хранилища ---


class PhraseRepository(Protocol):
    def add(self, phrase: Phrase) -> None: ...
    def save(self, phrase: Phrase) -> None: ...
    def get(self, phrase_id: str) -> Phrase | None: ...
    def find_by_text(self, text: str) -> Phrase | None: ...
    def due(self, now: datetime, limit: int) -> list[Phrase]: ...
    def all(self) -> list[Phrase]: ...


class MistakeRepository(Protocol):
    def by_key(self, key: str) -> Mistake | None: ...
    def save(self, mistake: Mistake) -> None: ...
    def most_frequent(self, limit: int, since: datetime | None = None) -> list[Mistake]: ...


class FactRepository(Protocol):
    """Память о пользователе (domain/memory.py)."""

    def save(self, fact: Fact) -> None: ...
    def get(self, fact_id: str) -> Fact | None: ...
    def find_by_text(self, text: str) -> Fact | None: ...
    def delete(self, fact_id: str) -> None: ...
    def all(self) -> list[Fact]: ...


class UtteranceLog(Protocol):
    def append(self, utterance: Utterance) -> None: ...
    def since(self, moment: datetime) -> list[Utterance]: ...


# --- голос ---


class SpeechListener(Protocol):
    """Через это рот докладывает приложению, как идёт озвучка."""

    def began(self, speech_id: str) -> None: ...
    def progressed(self, speech_id: str, heard_chars: int) -> None: ...
    def ended(self, speech_id: str) -> None: ...
    def broke(self, speech_id: str, reason: str) -> None: ...


class Mouth(Protocol):
    """Озвучивает реплики строго по очереди в своём потоке; say() не блокирует."""

    @property
    def busy(self) -> bool: ...
    def say(self, speech_id: str, text: str) -> None: ...
    def cancel(self, speech_ids: set[str]) -> None:
        """Оборвать эти реплики: звучащую — сразу, ждущие в очереди — выбросить. Не блокирует."""
        ...
    def murmur(self) -> None:
        """Короткое «Hmm» / «Right» вне реплик: Claude о нём не узнаёт. Не блокирует."""
        ...
    def hush(self) -> None:
        """Оборвать «Hmm», если звучит (человек снова заговорил)."""
        ...


class HearingListener(Protocol):
    """Через это уши докладывают приложению, что услышали."""

    def voice_started(self) -> None: ...
    def voice_finished(self, utterance: Utterance | None) -> None: ...
    def sound(self, label: str, confidence: float) -> None: ...


class Ears(Protocol):
    """Микрофон с детектором речи, распознаванием и детектором звуков."""

    def open(self) -> None: ...
    def close(self) -> None: ...
