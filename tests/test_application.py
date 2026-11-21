"""Сценарии приложения целиком: шина, состояние, журнал и SQLite в памяти; рот и уши — подделки."""

from datetime import datetime, timedelta

import pytest

from parley.application.bus import CommandBus, QueryBus
from parley.application.commands import (
    CloseEars,
    CommandHandlers,
    CompanionIsDeaf,
    NoteMistake,
    PartnerArrived,
    PartnerLeft,
    ReviewPhrase,
    SavePhrase,
    Say,
    SpeechBegan,
    SpeechProgressed,
    Tick,
    UserFinishedTalking,
    UserStartedTalking,
)
from parley.application.queries import CompanionStatus, DuePhrases, Listen, Progress, QueryHandlers
from parley.application.state import LiveState
from parley.domain.conversation import Utterance
from parley.domain.learning import MistakeKind, ReviewOutcome
from parley.infrastructure.journal import InMemoryJournal
from parley.infrastructure.sqlite import Database, SqliteMistakes, SqlitePhrases, SqliteUtterances


class FakeClock:
    def __init__(self):
        self.moment = datetime(2026, 11, 21, 12, 0).astimezone()

    def now(self):
        return self.moment


class FakeMouth:
    def __init__(self):
        self.said: list[tuple[str, str]] = []
        self.cancelled: set[str] = set()

    @property
    def busy(self):
        return False

    def say(self, speech_id, text):
        self.said.append((speech_id, text))

    def cancel(self, speech_ids):
        self.cancelled |= speech_ids


@pytest.fixture
def app():
    clock, journal, mouth, state = FakeClock(), InMemoryJournal(), FakeMouth(), LiveState()
    db = Database(":memory:")
    repos = SqlitePhrases(db), SqliteMistakes(db), SqliteUtterances(db)
    commands, queries = CommandBus(), QueryBus()
    for m, h in CommandHandlers(state, journal, clock, mouth, *repos).routes().items():
        commands.register(m, h)
    for m, h in QueryHandlers(state, journal, clock, *repos).routes().items():
        queries.register(m, h)
    commands.execute(PartnerArrived())
    return commands, queries, clock, mouth


def test_without_claude_nothing_is_heard(app):
    commands, queries, clock, _ = app
    commands.execute(PartnerLeft())
    start = len(kinds(queries))
    commands.execute(UserStartedTalking())
    commands.execute(UserFinishedTalking(Utterance("hello", clock.now(), 1.0)))
    assert "heard" not in kinds(queries)[start:]
    assert queries.ask(CompanionStatus())["activity"] == "waiting"


def kinds(queries, after=0):
    return [e["kind"] for e in queries.ask(Listen(after=after, timeout_s=0))["events"]]


def test_user_phrase_reaches_claude(app):
    commands, queries, clock, _ = app
    commands.execute(UserStartedTalking())
    commands.execute(UserFinishedTalking(Utterance("I worked on data pipelines", clock.now(), 2.0)))
    events = queries.ask(Listen(after=0, timeout_s=0))["events"]
    assert events[-1]["kind"] == "heard"
    assert events[-1]["language"] == "en"


def test_cutting_in_silences_pip_and_tells_what_was_not_heard(app):
    commands, queries, _, mouth = app
    speech_id = commands.execute(Say("Tell me about your last project. What was your role?"))
    commands.execute(SpeechBegan(speech_id))
    commands.execute(SpeechProgressed(speech_id, len("Tell me about your last project.")))
    commands.execute(UserStartedTalking())
    assert speech_id in mouth.cancelled
    interrupted = [e for e in queries.ask(Listen(after=0, timeout_s=0))["events"] if e["kind"] == "interrupted"][0]
    assert interrupted["heard"] == "Tell me about your last project."
    assert interrupted["not_heard"] == "What was your role?"


def test_muted_pip_refuses_to_speak(app):
    commands, queries, _, _ = app
    commands.execute(CloseEars())
    with pytest.raises(CompanionIsDeaf):
        commands.execute(Say("Hello"))
    assert "ears_closed" in kinds(queries)


def test_phrase_cycle_and_progress(app):
    commands, queries, clock, _ = app
    phrase_id = commands.execute(SavePhrase("I was in charge of", "я отвечал за", "I was in charge of the ETL."))
    assert commands.execute(SavePhrase("i was in charge of", "", "")) == phrase_id  # без дублей
    assert queries.ask(DuePhrases()) == []
    clock.moment += timedelta(minutes=6)
    assert [p["id"] for p in queries.ask(DuePhrases())] == [phrase_id]
    commands.execute(ReviewPhrase(phrase_id, ReviewOutcome.USED))
    assert queries.ask(DuePhrases()) == []

    for text, seconds in (("I was in charge of the ETL", 2.0), ("ну я короче", 1.0)):
        commands.execute(UserStartedTalking())
        commands.execute(UserFinishedTalking(Utterance(text, clock.now(), seconds)))
    for _ in range(2):
        commands.execute(NoteMistake(MistakeKind.GRAMMAR, "I am work", "I work", "present simple"))
    progress = queries.ask(Progress(days=1))
    assert progress["utterances"] == 2
    assert progress["words_spoken"] == 10
    assert progress["english_share"] == 0.7
    assert progress["top_mistakes"][0]["count"] == 2


def test_listen_skips_service_events(app):
    commands, queries, clock, _ = app
    commands.execute(UserStartedTalking())  # только смена состояния персонажа — Claude это не нужно
    assert queries.ask(Listen(after=0, timeout_s=0))["events"] == []


def test_pip_waits_for_a_pause_and_drops_reply_if_user_keeps_talking(app):
    commands, queries, clock, mouth = app
    commands.execute(UserStartedTalking())
    commands.execute(UserFinishedTalking(Utterance("So I think that", clock.now(), 1.0)))
    first = commands.execute(Say("[curious] That what?"))
    assert mouth.said == []  # пауза ещё не выдержана
    commands.execute(UserStartedTalking())  # человек продолжил мысль
    assert "speech_dropped" in kinds(queries)

    commands.execute(UserFinishedTalking(Utterance("the cache was the bottleneck", clock.now(), 2.0)))
    second = commands.execute(Say("[excited] Nice catch! How did you prove it?"))
    clock.moment += timedelta(seconds=2)
    commands.execute(Tick())
    assert [sid for sid, _ in mouth.said] == [second]
    assert first != second


def test_pip_may_interrupt_only_when_allowed(app):
    commands, _, clock, mouth = app
    commands.execute(UserStartedTalking())
    forced = commands.execute(Say("Sorry to cut in!", may_interrupt_user=True))
    assert [sid for sid, _ in mouth.said] == [forced]
    commands.execute(SpeechBegan(forced))
    commands.execute(UserStartedTalking())
    assert forced not in mouth.cancelled


def test_emotion_tags_are_not_shown_to_people(app):
    commands, queries, clock, mouth = app
    speech_id = commands.execute(Say("[excited] Great answer! [curious] Why Kafka?"))
    commands.execute(SpeechBegan(speech_id))
    assert mouth.said[0][1].startswith("[excited]")
    from parley.application.queries import SpeechNow
    assert queries.ask(SpeechNow())["text"] == "Great answer! Why Kafka?"
