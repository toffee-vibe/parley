"""Живое состояние одного запуска: персонаж и реплики — звучащие, прозвучавшие и ждущие тишины.

Хранится в памяти: после перезапуска разговор начинается заново, а фразы и ошибки
остаются в базе (см. ports.PhraseRepository / MistakeRepository).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from ..domain.companion import Companion
from ..domain.speech import Speech

KEEP_SPEECHES = 50


@dataclass
class LiveState:
    companion: Companion = field(default_factory=Companion)
    speeches: OrderedDict[str, Speech] = field(default_factory=OrderedDict)
    waiting: list[Speech] = field(default_factory=list)  # ждут, пока человек договорит; ещё не отданы рту

    def remember(self, speech: Speech) -> None:
        self.speeches[speech.id] = speech
        while len(self.speeches) > KEEP_SPEECHES:
            self.speeches.popitem(last=False)

    def unfinished_speeches(self) -> list[Speech]:
        return [s for s in self.speeches.values() if not s.is_over]

    def current_speech(self) -> Speech | None:
        return next((s for s in self.speeches.values() if s.started and not s.is_over), None)
