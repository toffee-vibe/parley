"""Распознавание учится: агент сообщает о неправильно распознанном слове — оно сразу попадает в отзывы и
в подсказку распознаванию; в подсказке есть и последняя реплика Пипа. Без сети: OpenRouter подменён."""

import json
from datetime import datetime

import httpx
import numpy as np

from parley.application.bus import CommandBus, QueryBus
from parley.application.commands import CommandHandlers, ReportMisheard, Say, ShowBoard, SpeechBegan
from parley.application.queries import HintsForRecognition, QueryHandlers
from parley.application.state import LiveState
from parley.config import OpenRouterSettings
from parley.domain.companion import Companion
from parley.infrastructure.audio.ears import _imagined
from parley.infrastructure.feedback import FeedbackBook
from parley.infrastructure.journal import InMemoryJournal
from parley.infrastructure.openrouter import OpenRouter
from parley.infrastructure.sqlite import (
    Database,
    SqliteFacts,
    SqliteMisheard,
    SqliteMistakes,
    SqlitePhrases,
    SqliteUtterances,
)


class Clock:
    def now(self):
        return datetime(2026, 11, 22, 2, 0).astimezone()


class Mouth:
    busy = False

    def say(self, *a):
        pass

    def cancel(self, *a):
        pass


def app(tmp_path):
    db, state, journal, clock = Database(":memory:"), LiveState(Companion(partner_here=True)), InMemoryJournal(), Clock()
    misheard, feedback = SqliteMisheard(db), FeedbackBook(tmp_path / "feedback.md")
    commands, queries = CommandBus(), QueryBus()
    repos = SqlitePhrases(db), SqliteMistakes(db), SqliteUtterances(db), SqliteFacts(db)
    for m, h in CommandHandlers(state, journal, clock, Mouth(), *repos, misheard=misheard,
                                feedback=feedback).routes().items():
        commands.register(m, h)
    for m, h in QueryHandlers(state, journal, clock, *repos, misheard=misheard).routes().items():
        queries.register(m, h)
    return commands, queries, feedback


def stt(queries, reply="did"):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"text": reply})

    client = OpenRouter(OpenRouterSettings(api_key="k", transcription_prompt="Python, FastAPI."),
                        hints=lambda: queries.ask(HintsForRecognition()))
    client.http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(handler))
    return client, sent


def test_corrected_word_and_pip_reply_go_into_the_next_prompt(tmp_path):
    commands, queries, feedback = app(tmp_path)
    speech = commands.execute(Say("Did is the past form of do. Did you work there?"))
    commands.execute(SpeechBegan(speech))
    commands.execute(ShowBoard("Past Simple: did", "| did |"))
    commands.execute(ReportMisheard(heard="Agis GPT", meant="did"))
    commands.execute(ReportMisheard(heard="описывать", meant="овеществлять"))

    client, sent = stt(queries)
    assert client.transcribe(np.zeros(16000, np.float32)) == "did"
    prompt = sent[0]["prompt"]
    assert prompt.startswith("Python, FastAPI.")
    assert "did" in prompt and "овеществлять" in prompt           # выученные слова
    assert "Past Simple: did" in prompt                           # доска
    assert "Did you work there?" in prompt                        # последняя реплика Пипа

    lines = feedback.recent()
    assert "«Agis GPT» вместо «did»" in lines[0] and "[misheard]" in lines[0]


def test_repeating_pip_word_for_word_is_not_a_leak(tmp_path):
    commands, queries, _ = app(tmp_path)
    phrase = "The difference between a text file and a database is"
    commands.execute(SpeechBegan(commands.execute(Say(phrase + " the format."))))
    client, _ = stt(queries, reply=phrase)
    assert client.transcribe(np.zeros(16000 * 4, np.float32)) == phrase   # человек повторил — оставляем


def test_impossible_speed_is_a_leak_not_speech():
    leak = "English speaking practice with Parley Pip. The speaker is Russian and mixes English and Russian."
    assert _imagined(leak, duration=2.0)                  # 16 слов за 2 с — так не говорят
    assert not _imagined("I have made it before and I'm making it now.", duration=3.5)
