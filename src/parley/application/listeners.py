"""Мостики от инфраструктуры к командам: уши и рот сообщают о событиях, а мы превращаем их в команды."""

from __future__ import annotations

import logging

from ..domain.conversation import Utterance
from .bus import CommandBus
from .commands import (
    NoticeSound,
    SpeechBegan,
    SpeechBroke,
    SpeechEnded,
    SpeechProgressed,
    UserFinishedTalking,
    UserStartedTalking,
)

log = logging.getLogger(__name__)


class _Reporter:
    def __init__(self, commands: CommandBus):
        self.commands = commands

    def _run(self, command: object) -> None:
        try:
            self.commands.execute(command)
        except Exception:  # поток микрофона или плеера не должен падать из-за одной команды
            log.exception("Команда %s не выполнилась", type(command).__name__)


class SpeechReporter(_Reporter):
    def began(self, speech_id: str) -> None:
        self._run(SpeechBegan(speech_id))

    def progressed(self, speech_id: str, heard_chars: int) -> None:
        self._run(SpeechProgressed(speech_id, heard_chars))

    def ended(self, speech_id: str) -> None:
        self._run(SpeechEnded(speech_id))

    def broke(self, speech_id: str, reason: str) -> None:
        self._run(SpeechBroke(speech_id, reason))


class HearingReporter(_Reporter):
    def voice_started(self) -> None:
        self._run(UserStartedTalking())

    def voice_finished(self, utterance: Utterance | None) -> None:
        self._run(UserFinishedTalking(utterance))

    def sound(self, label: str, confidence: float) -> None:
        self._run(NoticeSound(label, confidence))
