"""Чему распознавание речи учится по ходу разговоров.

Распознавание не знает, о чём разговор, и путает слова, особенно с акцентом и на смеси языков:
«did» → «Agis GPT», «had» → «хеджет», «овеществлять» → «описывать». Две вещи помогают:

- Контекст. Человек чаще всего повторяет то, что Пип только что сказал или показал на доске.
  Эти слова подсказываются распознаванию вместе со словарём (`RecognitionHints`).
- Поправки. Когда слово распознано неправильно, агент сообщает об этом (`Misheard`): правильное
  слово попадает в словарь распознавания и дальше узнаётся лучше.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MAX_HINT_WORDS = 40      # столько выученных слов уходит в подсказку (самые частые и свежие)


@dataclass
class Misheard:
    meant: str            # что человек на самом деле сказал
    heard: str            # как это записало распознавание
    first_seen: datetime
    last_seen: datetime
    count: int = 1

    def __post_init__(self) -> None:
        self.meant = " ".join(self.meant.split())
        self.heard = " ".join(self.heard.split())
        if not self.meant:
            raise ValueError("Пустая поправка: укажи, что человек сказал на самом деле")
        if len(self.meant) > 80:
            raise ValueError("Поправка — это слово или короткая фраза (до 80 символов)")

    def again(self, heard: str, now: datetime) -> None:
        self.heard = " ".join(heard.split()) or self.heard
        self.count += 1
        self.last_seen = now


@dataclass(frozen=True)
class RecognitionHints:
    """Что подсказать распознаванию прямо сейчас."""

    words: tuple[str, ...]      # выученные поправками слова
    pip_said: str = ""          # последняя реплика Пипа — человек часто её повторяет
    board: str = ""             # заголовок доски

    def vocabulary(self) -> str:
        """Постоянная часть: выученные слова и тема доски. Если распознавание вернуло это на тишине — утечка."""
        parts = []
        if self.words:
            parts.append("Words the speaker uses: " + ", ".join(self.words) + ".")
        if self.board:
            parts.append(f"On the tutor's board: {self.board}.")
        return "\n".join(parts)

    def recent(self) -> str:
        """Последняя реплика Пипа. Её человек вправе повторить слово в слово — это не утечка."""
        return f"The tutor (Pip) just said: {self.pip_said}" if self.pip_said else ""
