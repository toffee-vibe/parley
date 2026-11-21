"""Обучение: фразы для активного словаря и журнал ошибок.

Метод (подробно — в docs/method.md):
1. Пробел. Пользователь не смог что-то сказать (перешёл на русский, запнулся, ошибся).
2. Новая информация. Claude даёт естественную английскую формулировку — это `Phrase`.
3. Употребление. Фраза возвращается по интервальному повторению, но проверяется не карточкой,
   а в живой речи: Claude строит вопрос так, чтобы фраза понадобилась, и отмечает результат.
4. Ошибки копятся в `Mistake`: одна и та же правильная форма — одна ошибка со счётчиком,
   поэтому видно, что повторяется, а что уже ушло.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .shared import Aggregate, DomainEvent, new_id

# Через сколько фраза вернётся после очередного успешного употребления.
# Ступень 0 — новая фраза: первое возвращение в той же беседе.
INTERVALS: tuple[timedelta, ...] = (
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
    timedelta(days=16),
    timedelta(days=35),
)
LEARNED_STAGE = 4  # ступень, начиная с которой фраза считается выученной (≈ неделя без сбоев)


class ReviewOutcome(StrEnum):
    USED = "used"            # сам употребил к месту и без ошибок
    STRUGGLED = "struggled"  # употребил, но с ошибкой или после подсказки
    MISSED = "missed"        # ситуация была, а фразы не было


@dataclass(frozen=True, kw_only=True)
class PhraseReviewed(DomainEvent):
    kind = "phrase_reviewed"
    phrase_id: str
    text: str
    outcome: ReviewOutcome
    stage: int
    due_at: datetime


@dataclass
class Phrase(Aggregate):
    text: str                     # английская формулировка, которую надо уметь сказать
    meaning: str                  # что пользователь хотел сказать (обычно по-русски)
    example: str                  # пример употребления в контексте собеседования
    created_at: datetime
    id: str = field(default_factory=new_id)
    stage: int = 0
    due_at: datetime | None = None
    used: int = 0
    struggled: int = 0
    missed: int = 0

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("Фраза не может быть пустой")
        if self.due_at is None:
            self.due_at = self.created_at + INTERVALS[0]

    @property
    def learned(self) -> bool:
        return self.stage >= LEARNED_STAGE

    def is_due(self, now: datetime) -> bool:
        return self.due_at is not None and self.due_at <= now

    def review(self, outcome: ReviewOutcome, now: datetime) -> None:
        match outcome:
            case ReviewOutcome.USED:
                self.used += 1
                self.stage = min(self.stage + 1, len(INTERVALS) - 1)
            case ReviewOutcome.STRUGGLED:
                self.struggled += 1  # ступень не меняется: закрепить ещё раз на том же интервале
            case ReviewOutcome.MISSED:
                self.missed += 1
                self.stage = max(self.stage - 2, 0)
        self.due_at = now + INTERVALS[self.stage]
        self._record(PhraseReviewed(at=now, phrase_id=self.id, text=self.text, outcome=outcome,
                                    stage=self.stage, due_at=self.due_at))


class MistakeKind(StrEnum):
    GRAMMAR = "grammar"              # времена, артикли, согласование
    WORD_CHOICE = "word_choice"      # не то слово, кальки с русского
    WORD_ORDER = "word_order"
    PREPOSITION = "preposition"
    PRONUNCIATION = "pronunciation"  # видно по странному распознаванию
    MISSING_WORD = "missing_word"    # не знал слова и перешёл на русский


@dataclass(frozen=True, kw_only=True)
class MistakeNoted(DomainEvent):
    kind = "mistake"
    mistake_id: str
    category: MistakeKind
    wrong: str
    right: str
    explanation: str
    count: int


def mistake_key(right: str) -> str:
    """Одна и та же правильная форма — одна ошибка (регистр и пунктуация не важны)."""
    return re.sub(r"[^\w' ]+", "", right.lower()).strip()


@dataclass
class Mistake(Aggregate):
    category: MistakeKind
    wrong: str
    right: str
    explanation: str
    first_seen: datetime
    id: str = field(default_factory=new_id)
    count: int = 0
    last_seen: datetime | None = None

    @property
    def key(self) -> str:
        return mistake_key(self.right)

    @property
    def recurring(self) -> bool:
        return self.count >= 3

    def happened(self, wrong: str, explanation: str, now: datetime) -> None:
        """Ошибка случилась (в первый или в очередной раз)."""
        self.count += 1
        self.wrong = wrong or self.wrong
        self.explanation = explanation or self.explanation
        self.last_seen = now
        self._record(MistakeNoted(at=now, mistake_id=self.id, category=self.category, wrong=self.wrong,
                                  right=self.right, explanation=self.explanation, count=self.count))
