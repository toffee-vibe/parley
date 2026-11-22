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
from ..domain.conversation import SoundNoticed, UserSaying, Utterance, heard, joined, sounds_unfinished
from ..domain.hearing import Misheard
from ..domain.learning import Mistake, MistakeKind, Phrase, ReviewOutcome, mistake_key
from ..domain.memory import Fact
from ..domain.shared import Aggregate
from ..domain.speech import Speech
from .ports import (
    Clock,
    Ears,
    FactRepository,
    Feedback,
    Journal,
    MisheardRepository,
    MistakeRepository,
    Mouth,
    PhraseRepository,
    UtteranceLog,
)
from .state import LiveState


class CompanionIsDeaf(RuntimeError):
    """Пользователь выключил компаньону слух — значит, сейчас говорить нельзя."""


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class Timing:
    """Тайминги разговора (из config.toml, раздел [conversation])."""

    reply_pause_s: float = 1.2      # сколько тишины после фразы человека, прежде чем говорить
    turn_end_s: float = 3.5         # сколько молчать, чтобы мысль считалась законченной и ушла агенту
    unfinished_factor: float = 1.6  # мысль явно оборвана («потому что…», «and») — ждём во столько раз дольше
    thinking_patience_s: float = 25  # через сколько перестать «думать», если ответа нет
    stuck_transcription_s: float = 30  # распознавание не вернулось за столько — не ждём его, отдаём ход
    bring_back_every: int = 5       # раз в столько ходов подсказывать агенту фразу для повторения
    bring_back_tries: int = 3       # столько раз подсказываем одну фразу, потом берём следующую


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
class UserPaused:
    """Человек замолчал (детектор речи). Ход ещё не окончен — может, он подбирает слова."""

    transcribing: bool  # кусок речи ушёл в распознавание, результат придёт командой UserFinishedTalking


@dataclass(frozen=True)
class UserFinishedTalking:
    """Кусок речи распознан. Агенту он уйдёт вместе с остальными кусками хода, когда ход закончится."""

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


# --- обратная связь о работе Parley ---


@dataclass(frozen=True)
class ReportMisheard:
    """Распознавание записало не то: heard — как записало, meant — что человек сказал на самом деле."""

    heard: str
    meant: str


@dataclass(frozen=True)
class ReportProblem:
    """Агент заметил проблему в работе Parley (не в английском пользователя)."""

    problem: str
    context: str = ""


class CommandHandlers:
    def __init__(self, state: LiveState, journal: Journal, clock: Clock, mouth: Mouth,
                 phrases: PhraseRepository, mistakes: MistakeRepository, utterances: UtteranceLog,
                 facts: FactRepository, timing: Timing = Timing(), misheard: MisheardRepository | None = None,
                 feedback: Feedback | None = None):
        self.state = state
        self.journal = journal
        self.clock = clock
        self.mouth = mouth
        self.phrases = phrases
        self.mistakes = mistakes
        self.utterances = utterances
        self.facts = facts
        self.misheard = misheard
        self.feedback = feedback
        self.timing = timing
        self.ears: Ears | None = None  # подставляется в bootstrap: уши и команды ссылаются друг на друга
        self._transcribing_since = clock.now()

    def routes(self) -> dict[type, object]:
        return {
            PartnerArrived: self._partner_arrived,
            PartnerLeft: self._partner_left,
            CloseEars: self._close_ears,
            OpenEars: self._open_ears,
            ToggleEars: self._toggle_ears,
            UserStartedTalking: self._user_started_talking,
            UserPaused: self._user_paused,
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
            ReportMisheard: self._report_misheard,
            ReportProblem: self._report_problem,
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
        self.state.turn.clear()  # недосказанное до выключения микрофона агенту не уходит
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
        self.state.turn.clear()
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
        stopped = [s for s in self.state.unfinished_speeches() + self.state.waiting if s.user_started_talking(now)]
        self._after_stop(stopped)
        self._publish(self.companion)

    def _user_paused(self, command: UserPaused) -> None:
        self.companion.user_paused(self.clock.now())
        if command.transcribing:
            self.state.transcribing += 1
            self._transcribing_since = self.clock.now()

    def _user_finished_talking(self, command: UserFinishedTalking) -> None:
        """Кусок распознан: копим его в ходе. Агент получит всю мысль, когда ход закончится (_tick)."""
        self.state.transcribing = max(0, self.state.transcribing - 1)
        utterance = command.utterance
        if utterance is None or utterance.is_empty or not self.companion.listening:
            return  # шум, пустая фраза или слушать уже некому (агент ушёл, слух выключили)
        self.state.turn.append(utterance)
        now = self.clock.now()
        # Пока ответ ждал тишины, человек сказал новые слова — ответ устарел (шум и кашель его не отменяют).
        self._after_stop([s for s in self.state.waiting if s.user_started_talking(now)])
        if self.companion.activity is Activity.HEARING:
            self.journal.publish([UserSaying(at=now, text=joined(self.state.turn).text)])
        else:
            self._end_turn(now)  # кусок распознался уже после конца хода — не теряем его

    def _turn_end(self) -> float:
        """Сколько ждать тишины. Последний кусок оборван на союзе или запятой — человек явно не договорил."""
        last = self.state.turn[-1].text if self.state.turn else ""
        unfinished = bool(last) and sounds_unfinished(last)
        return self.timing.turn_end_s * (self.timing.unfinished_factor if unfinished else 1)

    def _end_turn(self, now: datetime) -> None:
        """Мысль закончена: склеиваем куски и отдаём агенту одной фразой."""
        turn, self.state.turn = self.state.turn, []
        self.companion.user_finished_talking(now, said_something=bool(turn))
        self._publish(self.companion)
        if turn:
            utterance = joined(turn)
            self.utterances.append(utterance)
            self.journal.publish([heard(utterance, now, bring_back=self._bring_back(now))])

    def _bring_back(self, now: datetime) -> str:
        """Повторение не должно зависеть от памяти агента: по инструкции «вызывай due_phrases каждые 5 ходов»
        слабые модели получают фразы один раз и забывают о них. Поэтому Parley сам раз в несколько ходов
        кладёт одну фразу прямо в `heard` — туда, куда агент смотрит при каждом ответе."""
        self.state.turns_since_hint += 1
        if self.state.turns_since_hint < self.timing.bring_back_every:
            return ""
        tries = self.timing.bring_back_tries
        phrase = next((p for p in self.phrases.due(now, limit=20) if self.state.hinted.get(p.id, 0) < tries), None)
        if phrase is None:
            return ""
        self.state.turns_since_hint = 0
        self.state.hinted[phrase.id] = self.state.hinted.get(phrase.id, 0) + 1
        return (f'Quietly steer your next reply so the user naturally needs to say "{phrase.text}" '
                f"(= «{phrase.meaning}»). Do NOT say this phrase yourself, don't put it on the board, "
                f"don't ask them to repeat it. If they use it, call review_phrase({phrase.id!r}, \"used\").")

    def _notice_sound(self, command: NoticeSound) -> None:
        if self.companion.listening:
            self.journal.publish([SoundNoticed(at=self.clock.now(), label=command.label,
                                               confidence=round(command.confidence, 2))])

    def _tick(self, _: Tick) -> None:
        now = self.clock.now()
        if self.state.transcribing and now - self._transcribing_since > timedelta(
                seconds=self.timing.stuck_transcription_s):
            self.state.transcribing = 0  # распознавание зависло — не держим ход вечно
        if not self.state.transcribing and self.companion.turn_is_over(now, timedelta(seconds=self._turn_end())):
            self._end_turn(now)
        self.companion.settle(now, timedelta(seconds=self.timing.thinking_patience_s))
        if self.state.waiting and self.companion.user_is_quiet(now, timedelta(seconds=self.timing.reply_pause_s)):
            for speech in self.state.waiting:
                self.mouth.say(speech.id, speech.text)
            self.state.waiting.clear()
        self._publish(self.companion)


    # --- речь ---

    def _say(self, command: Say) -> str:
        if not self.companion.can_speak():
            raise CompanionIsDeaf("Пользователь выключил компаньону слух — сейчас говорить нельзя")
        speech = Speech(text=command.text, may_interrupt_user=command.may_interrupt_user)
        self.state.remember(speech)
        if self.state.turn and self.companion.activity is Activity.HEARING and not speech.may_interrupt_user:
            # Человек уже говорит новое (слова распознаны), а агент их ещё не получил: ответ написан на старое.
            # Не держим его до конца фразы (прозвучал бы мимо) — агент получит speech_dropped, а потом новую фразу.
            speech.stop(self.clock.now())
            self._publish(speech)
            return speech.id
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

    # --- обратная связь о работе Parley ---

    def _report_misheard(self, command: ReportMisheard) -> None:
        """Правильное слово — в словарь распознавания (со следующей фразы), и запись в отзывы."""
        if self.misheard is None:
            return
        now = self.clock.now()
        item = self.misheard.get(command.meant)
        if item:
            item.again(command.heard, now)
        else:
            item = Misheard(meant=command.meant, heard=command.heard, first_seen=now, last_seen=now)
        self.misheard.save(item)
        if self.feedback:
            self.feedback.write("misheard", f"«{item.heard}» вместо «{item.meant}» (уже {item.count} раз)")

    def _report_problem(self, command: ReportProblem) -> None:
        if self.feedback:
            self.feedback.write("problem", command.problem + (f" — {command.context}" if command.context else ""))
