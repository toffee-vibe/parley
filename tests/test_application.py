"""Сценарии приложения целиком: шина, состояние, журнал и SQLite в памяти; рот и уши — подделки."""

from datetime import datetime, timedelta

import pytest

from parley.application.bus import CommandBus, QueryBus
from parley.application.commands import (
    CloseEars,
    CommandHandlers,
    CompanionIsDeaf,
    Forget,
    NoteMistake,
    NotFound,
    PartnerArrived,
    PartnerLeft,
    Remember,
    ReviewPhrase,
    SavePhrase,
    Say,
    SpeechBegan,
    SpeechProgressed,
    Tick,
    UserFinishedTalking,
    UserPaused,
    UserStartedTalking,
)
from parley.application.queries import CompanionStatus, DuePhrases, Listen, Progress, QueryHandlers, Recall
from parley.application.state import LiveState
from parley.domain.conversation import Utterance
from parley.domain.learning import MistakeKind, ReviewOutcome
from parley.infrastructure.journal import InMemoryJournal
from parley.infrastructure.sqlite import Database, SqliteFacts, SqliteMistakes, SqlitePhrases, SqliteUtterances


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
    repos = SqlitePhrases(db), SqliteMistakes(db), SqliteUtterances(db), SqliteFacts(db)
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


def part(commands, clock, text, seconds=1.0):
    """Кусок речи: заговорил, замолчал, распознано. Ход ещё не окончен."""
    commands.execute(UserStartedTalking())
    commands.execute(UserPaused(transcribing=True))
    commands.execute(UserFinishedTalking(Utterance(text, clock.now(), seconds)))


def end_turn(commands, clock, seconds=6.0):
    """Человек молчит дольше turn_end_s (3.5 с, а если мысль оборвана — 5.6 с) — мысль закончена."""
    clock.moment += timedelta(seconds=seconds)
    commands.execute(Tick())


def speak(commands, clock, text, seconds=1.0):
    part(commands, clock, text, seconds)
    end_turn(commands, clock)


def kinds(queries, after=0):
    return [e["kind"] for e in queries.ask(Listen(after=after, timeout_s=0))["events"]]


def test_user_phrase_reaches_claude(app):
    commands, queries, clock, _ = app
    speak(commands, clock, "I worked on data pipelines", 2.0)
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
        speak(commands, clock, text, seconds)
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
    speak(commands, clock, "So I think that")
    first = commands.execute(Say("[curious] That what?"))
    commands.execute(UserStartedTalking())  # человек продолжил мысль раньше, чем Пип заговорил
    commands.execute(Tick())
    assert mouth.said == [] or "speech_dropped" in kinds(queries) or "interrupted" in kinds(queries)

    commands.execute(UserPaused(transcribing=True))
    commands.execute(UserFinishedTalking(Utterance("the cache was the bottleneck", clock.now(), 2.0)))
    end_turn(commands, clock)
    second = commands.execute(Say("[excited] Nice catch! How did you prove it?"))
    clock.moment += timedelta(seconds=2)
    commands.execute(Tick())
    assert mouth.said[-1][0] == second
    assert first != second


def test_a_thought_with_pauses_reaches_the_agent_whole(app):
    commands, queries, clock, mouth = app
    part(commands, clock, "So yesterday I")
    clock.moment += timedelta(seconds=1.5)       # подбирает слова — это ещё не конец мысли
    commands.execute(Tick())
    assert "heard" not in kinds(queries)         # агент пока ничего не получает (экран — получает hearing_text)
    assert queries.ask(CompanionStatus())["activity"] == "hearing"
    assert commands.execute(Say("Yesterday what?")) and mouth.said == []  # и Пип не влезает

    part(commands, clock, "fixed a race condition", 2.0)
    end_turn(commands, clock)
    heard = [e for e in queries.ask(Listen(after=0, timeout_s=0))["events"] if e["kind"] == "heard"]
    assert [e["text"] for e in heard] == ["So yesterday I fixed a race condition"]
    assert heard[0]["duration_s"] == 3.0


def test_turn_waits_for_slow_recognition_and_loses_nothing(app):
    commands, queries, clock, _ = app
    commands.execute(UserStartedTalking())
    commands.execute(UserPaused(transcribing=True))
    end_turn(commands, clock)                    # тишина давно, но кусок ещё распознаётся
    assert "heard" not in kinds(queries)
    commands.execute(UserFinishedTalking(Utterance("Python is my main language", clock.now(), 2.0)))
    commands.execute(Tick())
    assert "heard" in kinds(queries)

    speak(commands, clock, "and Go a bit")       # кусок, распознанный уже после конца хода, тоже доходит
    commands.execute(UserFinishedTalking(Utterance("for side projects", clock.now(), 1.0)))
    texts = [e["text"] for e in queries.ask(Listen(after=0, timeout_s=0))["events"] if e["kind"] == "heard"]
    assert texts[-2:] == ["and Go a bit", "for side projects"]


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


def test_pip_remembers_the_user_between_sessions(app):
    commands, queries, clock, _ = app
    job = commands.execute(Remember("Backend developer at a bank, 2 years", "work"))
    commands.execute(Remember("Interview at Yandex on Dec 5", "Interview"))
    assert commands.execute(Remember("backend developer at a bank, 2 years", "work")) == job  # без дублей

    clock.moment += timedelta(days=1)
    assert commands.execute(Remember("Moved to a fintech startup", "work", replaces=job)) == job
    memory = queries.ask(Recall())
    assert memory["facts"]["work"] == [{"id": job, "text": "Moved to a fintech startup", "updated": "2026-11-22"}]
    assert memory["facts"]["interview"][0]["text"] == "Interview at Yandex on Dec 5"
    assert queries.ask(Recall("work"))["total"] == 1

    commands.execute(Forget(job))
    assert "work" not in queries.ask(Recall())["facts"]
    with pytest.raises(NotFound):
        commands.execute(Forget(job))


def test_recall_shows_only_recent_session_notes(app):
    commands, queries, clock, _ = app
    for day in range(8):
        clock.moment += timedelta(days=1)
        commands.execute(Remember(f"Session {day}: talked about tests", "session"))
    notes = queries.ask(Recall())["facts"]["session"]
    assert len(notes) == 5 and notes[0]["text"].startswith("Session 7")


def test_unfinished_thought_gets_more_time(app):
    commands, queries, clock, _ = app
    part(commands, clock, "I worked there because")            # оборвано на «because»
    clock.moment += timedelta(seconds=4)
    commands.execute(Tick())
    assert "heard" not in kinds(queries)                       # 4 с тишины — ещё ждём
    part(commands, clock, "the pay was better.")
    clock.moment += timedelta(seconds=4)
    commands.execute(Tick())
    heard = [e["text"] for e in queries.ask(Listen(after=0, timeout_s=0))["events"] if e["kind"] == "heard"]
    assert heard == ["I worked there because the pay was better."]  # законченная мысль — 3.5 с хватает


def test_what_sounds_unfinished():
    from parley.domain.conversation import sounds_unfinished
    assert sounds_unfinished("Потому что")
    assert sounds_unfinished("Я хотел сказать, что...")
    assert sounds_unfinished("I mean,")
    assert sounds_unfinished("and then I")
    assert not sounds_unfinished("I made it yesterday.")
    assert not sounds_unfinished("Как сказать «услышал»?")


def test_reply_written_before_the_users_new_words_is_not_spoken_after_them(app):
    """Агент думал над первой фразой, а ты уже говоришь вторую: его ответ не должен прозвучать после неё."""
    commands, queries, clock, mouth = app
    speak(commands, clock, "What does hedge mean?")
    part(commands, clock, "oh wait, I remember")           # пока агент думал, ты заговорил снова
    stale = commands.execute(Say("Hedge means to protect yourself."))
    end_turn(commands, clock)
    assert all(sid != stale for sid, _ in mouth.said)
    assert "speech_dropped" in kinds(queries)


def test_reply_waiting_for_silence_is_dropped_when_new_words_arrive(app):
    commands, queries, clock, mouth = app
    speak(commands, clock, "What does hedge mean?")
    commands.execute(UserStartedTalking())
    commands.execute(UserPaused(transcribing=True))         # слова ещё распознаются…
    stale = commands.execute(Say("Hedge means to protect yourself."))
    commands.execute(UserFinishedTalking(Utterance("never mind", clock.now(), 1.0)))  # …и оказались новыми
    end_turn(commands, clock)
    assert all(sid != stale for sid, _ in mouth.said)


def test_a_cough_does_not_cancel_the_reply(app):
    commands, queries, clock, mouth = app
    speak(commands, clock, "What does hedge mean?")
    reply = commands.execute(Say("Hedge means to protect yourself."))
    clock.moment += timedelta(seconds=2)
    commands.execute(Tick())
    assert mouth.said[-1][0] == reply


def test_due_phrase_comes_back_to_the_agent_without_asking(app):
    """Агент не обязан помнить про повторение: раз в несколько ходов фраза приходит прямо в `heard`."""
    commands, queries, clock, _ = app
    commands.execute(SavePhrase("Could you speak more simply?", "говори проще", "Sorry, could you speak more simply?"))
    clock.moment += timedelta(hours=1)                       # фраза созрела для повторения
    hints = []
    for i in range(10):
        speak(commands, clock, f"phrase number {i}")
        last = queries.ask(Listen(after=0, timeout_s=0))["events"][-1]
        hints.append(last.get("bring_back", ""))
    given = [h for h in hints if h]
    assert len(given) == 2 and hints[4] and hints[9]          # раз в 5 ходов, не чаще
    assert "Could you speak more simply?" in given[0] and "Do NOT say this phrase yourself" in given[0]
