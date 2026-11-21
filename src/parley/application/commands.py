"""Команды — всё, что меняет состояние. Одна команда = один dataclass + один метод-обработчик.

Добавить команду:
    1. объявить dataclass ниже;
    2. написать метод `_имя` в CommandHandlers;
    3. добавить пару в `CommandHandlers.routes()`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..domain.companion import Activity, Mood
from ..domain.conversation import SoundNoticed, Utterance, heard
from ..domain.learning import Mistake, MistakeKind, Phrase, ReviewOutcome, mistake_key
from ..domain.memory import Fact
from ..domain.shared import Aggregate
from ..domain.speech import Speech
from .ports import Clock, Ears, FactRepository, Journal, MistakeRepository, Mouth, PhraseRepository, UtteranceLog
from .state import LiveState


class CompanionIsDeaf(RuntimeError):
    """Пользователь выключил компаньону слух — значит, сейчас говорить нельзя."""


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class Timing:
    """Тайминги разговора (из config.toml, раздел [conversation])."""

    reply_pause_s: float = 1.2      # сколько тишины после фразы человека, прежде чем говорить
    thinking_patience_s: float = 25  # через сколько перестать «думать», если ответа нет
    murmur_after_s: float = 1.6      # через сколько тишины отозваться «Hmm», пока Claude думает; 0 — никогда


# --- слух ---


@dataclass(frozen=True)
class PartnerArrived:
    """Claude подключился (вызвал инструмент или подписался на поток событий)."""


@dataclass(frozen=True)
class PartnerLeft:
    """Claude давно не появлялся — слушать некому."""


@dataclass(frozen=True)
class CloseEars:
    pass


@dataclass(frozen=True)
class OpenEars:
    pass


@dataclass(frozen=True)
class ToggleEars:
    pass


@dataclass(frozen=True)
class UserStartedTalking:
    pass


@dataclass(frozen=True)
class UserFinishedTalking:
    utterance: Utterance | None  # None — оказалось шумом или распознать не удалось


@dataclass(frozen=True)
class NoticeSound:
    label: str
    confidence: float


@dataclass(frozen=True)
class Tick:
    """Пульс (несколько раз в секунду): выпустить ждущие реплики, вернуть персонажа в покой."""


# --- речь ---


@dataclass(frozen=True)
class Say:
    text: str
    may_interrupt_user: bool = False


@dataclass(frozen=True)
class StopSpeaking:
    pass


@dataclass(frozen=True)
class SpeechBegan:
    speech_id: str


@dataclass(frozen=True)
class SpeechProgressed:
    speech_id: str
    heard_chars: int


@dataclass(frozen=True)
class SpeechEnded:
    speech_id: str


@dataclass(frozen=True)
class SpeechBroke:
    speech_id: str
    reason: str


# --- лицо и доска ---


@dataclass(frozen=True)
class Emote:
    mood: Mood


@dataclass(frozen=True)
class ShowBoard:
    title: str
    markdown: str


@dataclass(frozen=True)
class HideBoard:
    pass


# --- обучение ---


@dataclass(frozen=True)
class SavePhrase:
    text: str
    meaning: str
    example: str


@dataclass(frozen=True)
class ReviewPhrase:
    phrase_id: str
    outcome: ReviewOutcome


@dataclass(frozen=True)
class NoteMistake:
    category: MistakeKind
    wrong: str
    right: str
    explanation: str


# --- память о пользователе ---


@dataclass(frozen=True)
class Remember:
    text: str
    topic: str = "profile"
    replaces: str = ""  # id устаревшего факта: заменить его, а не добавить противоречие


@dataclass(frozen=True)
class Forget:
    fact_id: str


class CommandHandlers:
    def __init__(self, state: LiveState, journal: Journal, clock: Clock, mouth: Mouth,
                 phrases: PhraseRepository, mistakes: MistakeRepository, utterances: UtteranceLog,
                 facts: FactRepository, timing: Timing = Timing()):
        self.state = state
        self.journal = journal
        self.clock = clock
        self.mouth = mouth
        self.phrases = phrases
        self.mistakes = mistakes
        self.utterances = utterances
        self.facts = facts
        self.timing = timing
        self.ears: Ears | None = None  # подставляется в bootstrap: уши и команды ссылаются друг на друга

    def routes(self) -> dict[type, object]:
        return {
            PartnerArrived: self._partner_arrived,
            PartnerLeft: self._partner_left,
            CloseEars: self._close_ears,
            OpenEars: self._open_ears,
            ToggleEars: self._toggle_ears,
            UserStartedTalking: self._user_started_talking,
            UserFinishedTalking: self._user_finished_talking,
            NoticeSound: self._notice_sound,
            Tick: self._tick,
            Say: self._say,
            StopSpeaking: self._stop_speaking,
            SpeechBegan: self._speech_began,
            SpeechProgressed: self._speech_progressed,
            SpeechEnded: self._speech_ended,
            SpeechBroke: self._speech_broke,
            Emote: self._emote,
            ShowBoard: self._show_board,
            HideBoard: self._hide_board,
            SavePhrase: self._save_phrase,
            ReviewPhrase: self._review_phrase,
            NoteMistake: self._note_mistake,
            Remember: self._remember,
            Forget: self._forget,
        }

    @property
    def companion(self):
        return self.state.companion

    def _publish(self, *aggregates: Aggregate) -> None:
        for aggregate in aggregates:
            self.journal.publish(aggregate.pull_events())

    # --- слух ---

    def _close_ears(self, _: CloseEars) -> None:
        self.companion.close_ears(self.clock.now())
        self._stop(self.state.unfinished_speeches() + self.state.waiting)
        if self.ears:
            self.ears.close()
        self._publish(self.companion)

    def _open_ears(self, _: OpenEars) -> None:
        self.companion.open_ears(self.clock.now())
        self._sync_microphone()
        self._publish(self.companion)

    def _partner_arrived(self, _: PartnerArrived) -> None:
        self.companion.partner_arrived(self.clock.now())
        self._sync_microphone()
        self._publish(self.companion)

    def _partner_left(self, _: PartnerLeft) -> None:
        self.companion.partner_left(self.clock.now())
        self._sync_microphone()
        self._publish(self.companion)

    def _sync_microphone(self) -> None:
        """Микрофон работает, только когда слушать есть смысл: без Claude распознавание — деньги на ветер."""
        if self.ears:
            if self.companion.listening:
                self.ears.open()
            else:
                self.ears.close()

    def _toggle_ears(self, _: ToggleEars) -> None:
        if self.companion.ears_open:
            self._close_ears(CloseEars())
        else:
            self._open_ears(OpenEars())

    def _user_started_talking(self, _: UserStartedTalking) -> None:
        """Человек заговорил — всё, чему не разрешено его перебивать, замолкает или отменяется."""
        now = self.clock.now()
        self.companion.user_started_talking(now)
        self.mouth.hush()
        stopped = [s for s in self.state.unfinished_speeches() + self.state.waiting if s.user_started_talking(now)]
        self._after_stop(stopped)
        self._publish(self.companion)

    def _user_finished_talking(self, command: UserFinishedTalking) -> None:
        now = self.clock.now()
        utterance = command.utterance
        if (utterance is not None and utterance.is_empty) or self.companion.activity is not Activity.HEARING:
            utterance = None  # пустая фраза или слушать уже некому (Claude ушёл, слух выключили)
        self.companion.user_finished_talking(now, said_something=utterance is not None)
        self._publish(self.companion)
        if utterance is not None:
            self.utterances.append(utterance)
            self.journal.publish([heard(utterance, now)])

    def _notice_sound(self, command: NoticeSound) -> None:
        if self.companion.listening:
            self.journal.publish([SoundNoticed(at=self.clock.now(), label=command.label,
                                               confidence=round(command.confidence, 2))])

    def _tick(self, _: Tick) -> None:
        now = self.clock.now()
        self.companion.settle(now, timedelta(seconds=self.timing.thinking_patience_s))
        if self.state.waiting and self.companion.user_is_quiet(now, timedelta(seconds=self.timing.reply_pause_s)):
            for speech in self.state.waiting:
                self.mouth.say(speech.id, speech.text)
            self.state.waiting.clear()
        self._maybe_murmur(now)
        self._publish(self.companion)

    def _maybe_murmur(self, now: datetime) -> None:
        """Claude думает дольше обычной паузы — Пип отзывается, чтобы не висела мёртвая тишина."""
        if self.timing.murmur_after_s <= 0 or self.state.waiting or self.state.unfinished_speeches() \
                or self.mouth.busy:
            return
        if self.companion.wants_to_murmur(now, timedelta(seconds=self.timing.murmur_after_s)):
            self.companion.murmur()
            self.mouth.murmur()

    # --- речь ---

    def _say(self, command: Say) -> str:
        if not self.companion.can_speak():
            raise CompanionIsDeaf("Пользователь выключил компаньону слух — сейчас говорить нельзя")
        speech = Speech(text=command.text, may_interrupt_user=command.may_interrupt_user)
        self.state.remember(speech)
        pause = timedelta(seconds=self.timing.reply_pause_s)
        if speech.may_interrupt_user or (not self.state.waiting and self.companion.user_is_quiet(self.clock.now(), pause)):
            self.mouth.say(speech.id, speech.text)
        else:
            self.state.waiting.append(speech)  # дождёмся тишины (Tick)
        return speech.id

    def _stop_speaking(self, _: StopSpeaking) -> None:
        self._stop(self.state.unfinished_speeches() + self.state.waiting)

    def _speech_began(self, command: SpeechBegan) -> None:
        speech = self._speech(command.speech_id)
        now = self.clock.now()
        speech.begin(now)
        self.companion.started_speaking(now)
        self._publish(speech, self.companion)

    def _speech_progressed(self, command: SpeechProgressed) -> None:
        self._speech(command.speech_id).advance(command.heard_chars)

    def _speech_ended(self, command: SpeechEnded) -> None:
        speech = self._speech(command.speech_id)
        speech.finish(self.clock.now())
        self._after_speech(speech)

    def _speech_broke(self, command: SpeechBroke) -> None:
        speech = self._speech(command.speech_id)
        speech.fail(command.reason, self.clock.now())
        self._after_speech(speech)

    def _after_speech(self, speech: Speech) -> None:
        if not self.state.current_speech():
            self.companion.stopped_speaking(self.clock.now())
        self._publish(speech, self.companion)

    def _stop(self, speeches: Iterable[Speech]) -> None:
        now = self.clock.now()
        stopped = []
        for speech in speeches:
            if not speech.is_over:
                speech.stop(now)
                stopped.append(speech)
        self._after_stop(stopped)

    def _after_stop(self, stopped: list[Speech]) -> None:
        if not stopped:
            return
        ids = {s.id for s in stopped}
        self.mouth.cancel(ids)
        self.state.waiting = [s for s in self.state.waiting if s.id not in ids]
        if not self.state.current_speech():
            self.companion.stopped_speaking(self.clock.now())
        self._publish(*stopped)

    def _speech(self, speech_id: str) -> Speech:
        speech = self.state.speeches.get(speech_id)
        if speech is None:
            raise NotFound(f"Нет реплики {speech_id}")
        return speech

    # --- лицо и доска ---

    def _emote(self, command: Emote) -> None:
        self.companion.show(command.mood, self.clock.now())
        self._publish(self.companion)

    def _show_board(self, command: ShowBoard) -> None:
        self.companion.show_board(command.title, command.markdown, self.clock.now())
        self._publish(self.companion)

    def _hide_board(self, _: HideBoard) -> None:
        self.companion.hide_board(self.clock.now())
        self._publish(self.companion)

    # --- обучение ---

    def _save_phrase(self, command: SavePhrase) -> str:
        existing = self.phrases.find_by_text(command.text)
        if existing:
            return existing.id  # та же фраза второй раз — не дубль
        phrase = Phrase(text=command.text, meaning=command.meaning, example=command.example,
                        created_at=self.clock.now())
        self.phrases.add(phrase)
        return phrase.id

    def _review_phrase(self, command: ReviewPhrase) -> None:
        phrase = self.phrases.get(command.phrase_id)
        if phrase is None:
            raise NotFound(f"Нет фразы {command.phrase_id}")
        phrase.review(command.outcome, self.clock.now())
        self.phrases.save(phrase)
        self._publish(phrase)

    def _note_mistake(self, command: NoteMistake) -> str:
        now = self.clock.now()
        mistake = self.mistakes.by_key(mistake_key(command.right)) or Mistake(
            category=command.category, wrong=command.wrong, right=command.right,
            explanation=command.explanation, first_seen=now)
        mistake.happened(command.wrong, command.explanation, now)
        self.mistakes.save(mistake)
        self._publish(mistake)
        return mistake.id

    # --- память о пользователе ---

    def _remember(self, command: Remember) -> str:
        now = self.clock.now()
        fact = (self.facts.get(command.replaces) if command.replaces else None) \
            or self.facts.find_by_text(command.text)
        if command.replaces and fact is None:
            raise NotFound(f"Нет факта {command.replaces}")
        if fact:
            fact.rewrite(command.text, command.topic, now)
        else:
            fact = Fact(command.text, command.topic, now)
        self.facts.save(fact)
        return fact.id

    def _forget(self, command: Forget) -> None:
        if self.facts.get(command.fact_id) is None:
            raise NotFound(f"Нет факта {command.fact_id}")
        self.facts.delete(command.fact_id)
