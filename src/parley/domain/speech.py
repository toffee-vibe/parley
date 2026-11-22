"""Реплика компаньона вслух: от постановки в очередь до конца, перебивания или отмены.

Два правила живут здесь:

1. «Что пользователь успел услышать». Плеер сообщает, сколько символов уже прозвучало (`advance`),
   и при перебивании Claude узнаёт, какая часть фразы до человека не дошла.
2. «Не говорить поверх человека». Реплика, которой не разрешено перебивать (`may_interrupt_user=False`),
   ждёт тишины; если человек продолжил говорить — она отменяется (`drop`), и Claude отвечает заново,
   уже на всю мысль целиком.

Текст может содержать теги эмоций для голоса: «[excited] Great answer!». Синтез получает их как есть,
а человек (экран, события) видит текст без тегов — свойство `clean_text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .shared import Aggregate, DomainEvent, new_id

_TAG = re.compile(r"\[[^\]]*\]\s*")
# Дольше ~20 секунд человек не слушает: перебивает (в разговоре 22.11 — 8 раз на репликах по 200–460 символов).
MAX_SPOKEN_CHARS = 300


def without_tags(text: str) -> str:
    return " ".join(_TAG.sub("", text).split())


class SpeechStatus(StrEnum):
    QUEUED = "queued"            # ждёт тишины или синтеза
    PLAYING = "playing"
    FINISHED = "finished"
    INTERRUPTED = "interrupted"  # пользователь перебил
    DROPPED = "dropped"          # не прозвучала: пользователь продолжил говорить
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class SpeechStarted(DomainEvent):
    kind = "speech_started"
    speech_id: str
    text: str


@dataclass(frozen=True, kw_only=True)
class SpeechFinished(DomainEvent):
    kind = "speech_finished"
    speech_id: str


@dataclass(frozen=True, kw_only=True)
class SpeechInterrupted(DomainEvent):
    kind = "interrupted"
    speech_id: str
    heard: str
    not_heard: str


@dataclass(frozen=True, kw_only=True)
class SpeechDropped(DomainEvent):
    kind = "speech_dropped"
    speech_id: str
    text: str


@dataclass(frozen=True, kw_only=True)
class SpeechFailed(DomainEvent):
    kind = "speech_failed"
    speech_id: str
    reason: str


@dataclass
class Speech(Aggregate):
    text: str                         # как говорить: с тегами эмоций
    may_interrupt_user: bool = False
    id: str = ""
    status: SpeechStatus = SpeechStatus.QUEUED
    heard_chars: int = 0              # позиция в `text` (с тегами), до которой уже прозвучало

    def __post_init__(self) -> None:
        self.id = self.id or new_id()
        self.text = " ".join(self.text.split())
        if not self.clean_text:
            raise ValueError("Нечего сказать: пустой текст")
        if len(self.clean_text) > MAX_SPOKEN_CHARS:
            raise ValueError(f"Too long to say out loud ({len(self.clean_text)} characters, max {MAX_SPOKEN_CHARS}). "
                             "Nobody listens to a monologue: say 1–3 short sentences, put details on the board "
                             "(show_board), then let the user talk.")

    @property
    def clean_text(self) -> str:
        return without_tags(self.text)

    @property
    def is_over(self) -> bool:
        return self.status not in (SpeechStatus.QUEUED, SpeechStatus.PLAYING)

    @property
    def started(self) -> bool:
        return self.status is not SpeechStatus.QUEUED

    @property
    def heard(self) -> str:
        return without_tags(self.text[: self._word_boundary(self.heard_chars)])

    @property
    def not_heard(self) -> str:
        return without_tags(self.text[self._word_boundary(self.heard_chars):])

    def begin(self, now: datetime) -> None:
        if self.status is SpeechStatus.QUEUED:
            self.status = SpeechStatus.PLAYING
            self._record(SpeechStarted(at=now, speech_id=self.id, text=self.clean_text))

    def advance(self, heard_chars: int) -> None:
        if self.status is SpeechStatus.PLAYING:
            self.heard_chars = max(self.heard_chars, min(heard_chars, len(self.text)))

    def finish(self, now: datetime) -> None:
        if not self.is_over:
            self.status = SpeechStatus.FINISHED
            self.heard_chars = len(self.text)
            self._record(SpeechFinished(at=now, speech_id=self.id))

    def user_started_talking(self, now: datetime) -> bool:
        """Человек заговорил. Возвращает True, если реплику надо оборвать (обычно — да)."""
        if self.is_over or self.may_interrupt_user:
            return False
        self.stop(now)
        return True

    def stop(self, now: datetime) -> None:
        """Человек заговорил: начатая реплика перебита, неначатая — отменена."""
        if self.status is SpeechStatus.PLAYING:
            self.status = SpeechStatus.INTERRUPTED
            self._record(SpeechInterrupted(at=now, speech_id=self.id, heard=self.heard, not_heard=self.not_heard))
        elif self.status is SpeechStatus.QUEUED:
            self.status = SpeechStatus.DROPPED
            self._record(SpeechDropped(at=now, speech_id=self.id, text=self.clean_text))

    def fail(self, reason: str, now: datetime) -> None:
        if not self.is_over:
            self.status = SpeechStatus.FAILED
            self._record(SpeechFailed(at=now, speech_id=self.id, reason=reason))

    def _word_boundary(self, chars: int) -> int:
        """Не режем слово пополам: недослушанное слово считаем неуслышанным."""
        if chars >= len(self.text):
            return len(self.text)
        cut = self.text.rfind(" ", 0, chars + 1)
        return max(cut, 0)
