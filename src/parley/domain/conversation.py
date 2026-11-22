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
    bring_back: str = ""   # подсказка агенту: какую сохранённую фразу вернуть в разговор (не каждый ход)

    def as_dict(self) -> dict:
        data = super().as_dict()
        if not self.bring_back:
            data.pop("bring_back")
        return data


@dataclass(frozen=True, kw_only=True)
class UserSaying(DomainEvent):
    """Часть хода уже распознана, а ход ещё идёт — для экрана (агент получит всю мысль одним `heard`)."""

    kind = "hearing_text"
    text: str


_UNFINISHED_END = re.compile(r"(\.\.\.|…|,|;|:|—|-)\s*$")
_DANGLING = {"и", "а", "но", "или", "что", "чтобы", "потому", "если", "когда", "как", "ну", "вот", "типа", "короче",
             "в", "на", "с", "к", "по", "для", "and", "but", "or", "so", "because", "that", "the", "a", "an", "to",
             "of", "with", "if", "when", "which", "like"}


def sounds_unfinished(text: str) -> bool:
    """Мысль явно оборвана: кончается союзом, предлогом, запятой, многоточием или вовсе без точки."""
    text = text.strip()
    if not text or _UNFINISHED_END.search(text) or not re.search(r"[.!?»\"]$", text):
        return True
    last = re.findall(r"[\w'-]+", text.lower())
    return bool(last) and last[-1] in _DANGLING


def joined(parts: list[Utterance]) -> Utterance:
    """Куски одного хода (детектор речи режет фразу по коротким паузам) — одной фразой."""
    return Utterance(" ".join(p.text.strip() for p in parts), parts[0].started_at,
                     sum(p.duration_s for p in parts))


@dataclass(frozen=True, kw_only=True)
class SoundNoticed(DomainEvent):
    """Не речь: смех, кашель, клавиатура, музыка, стук…"""

    kind = "sound"
    label: str
    confidence: float


def heard(utterance: Utterance, now: datetime, bring_back: str = "") -> UserSaid:
    return UserSaid(
        bring_back=bring_back,
        at=now,
        text=utterance.text,
        language=utterance.language,
        english_share=round(utterance.english_share, 2),
        words=utterance.words,
        duration_s=round(utterance.duration_s, 1),
    )
