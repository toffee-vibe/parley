"""То, что компаньон услышал: фразы пользователя и звуки вокруг."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .shared import DomainEvent

_LATIN = re.compile(r"[a-z]", re.I)
_CYRILLIC = re.compile(r"[а-яё]", re.I)
_WORD = re.compile(r"[\w'’-]+", re.U)


@dataclass(frozen=True)
class Utterance:
    """Одна фраза пользователя.

    Доля английского считается по буквам, а не по ответу распознавателя: так метрика
    детерминирована и одинаково работает для любой модели распознавания.
    """

    text: str
    started_at: datetime
    duration_s: float

    @property
    def words(self) -> int:
        return len(_WORD.findall(self.text))

    @property
    def english_share(self) -> float:
        latin = len(_LATIN.findall(self.text))
        cyrillic = len(_CYRILLIC.findall(self.text))
        total = latin + cyrillic
        return latin / total if total else 0.0

    @property
    def language(self) -> str:
        share = self.english_share
        if share >= 0.8:
            return "en"
        if share <= 0.2:
            return "ru"
        return "mixed"

    @property
    def words_per_minute(self) -> float:
        return self.words / self.duration_s * 60 if self.duration_s > 0 else 0.0

    @property
    def is_empty(self) -> bool:
        return self.words == 0


@dataclass(frozen=True, kw_only=True)
class UserSaid(DomainEvent):
    kind = "heard"
    text: str
    language: str
    english_share: float
    words: int
    duration_s: float


@dataclass(frozen=True, kw_only=True)
class SoundNoticed(DomainEvent):
    """Не речь: смех, кашель, клавиатура, музыка, стук…"""

    kind = "sound"
    label: str
    confidence: float


def heard(utterance: Utterance, now: datetime) -> UserSaid:
    return UserSaid(
        at=now,
        text=utterance.text,
        language=utterance.language,
        english_share=round(utterance.english_share, 2),
        words=utterance.words,
        duration_s=round(utterance.duration_s, 1),
    )
