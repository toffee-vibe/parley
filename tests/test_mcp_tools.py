"""Инструменты MCP глазами агента: через настоящий клиент MCP (в памяти, без сети)."""

import json
from datetime import datetime

import anyio
from mcp import Client

from parley.application.bus import CommandBus, QueryBus
from parley.application.commands import Say
from parley.application.queries import Listen, QueryHandlers, SpeechResult
from parley.application.state import LiveState
from parley.domain.conversation import SoundNoticed, Utterance, heard
from parley.infrastructure.diary import NullDiary
from parley.infrastructure.journal import InMemoryJournal
from parley.interfaces.mcp.server import ClaudePresence, build_server

NOW = datetime(2026, 11, 22, 1, 0).astimezone()


def server():
    journal, commands, queries = InMemoryJournal(), CommandBus(), QueryBus()
    spoken = []
    commands.register(Say, lambda c: spoken.append(c.text) or "s1")
    handlers = QueryHandlers(LiveState(), journal, None, None, None, None, None)
    queries.register(Listen, handlers._listen)
    queries.register(SpeechResult, lambda q: {"speech_id": q.speech_id, "status": "queued"})
    return build_server(commands, queries, journal, "http://x", ClaudePresence(), NullDiary()), journal, spoken


def call(client, tool, **args):
    async def go():
        async with Client(client) as c:
            result = await c.call_tool(tool, args)
            return json.loads(result.content[0].text)
    return anyio.run(go)


def test_stale_reply_is_not_spoken_when_user_said_something_new():
    mcp, journal, spoken = server()
    cursor = call(mcp, "listen", timeout_s=0)["cursor"]           # агент дочитал события
    journal.publish([heard(Utterance("wait, what is was?", NOW, 2.0), NOW)])  # пока он думал, ты заговорил
    answer = call(mcp, "say", text="So, next phrase: I am making it now.")
    assert answer["status"] == "not_spoken" and spoken == []
    assert answer["events"][0]["text"] == "wait, what is was?"
    assert answer["cursor"] > cursor

    assert call(mcp, "say", text="Was is the past of be.")["status"] == "queued"  # теперь он в курсе — говорит
    assert spoken == ["Was is the past of be."]


def test_noise_does_not_wake_the_agent():
    mcp, journal, _ = server()
    cursor = call(mcp, "listen", timeout_s=0)["cursor"]
    journal.publish([SoundNoticed(at=NOW, label="Mantra", confidence=0.6),
                     SoundNoticed(at=NOW, label="Laughter", confidence=0.7)])
    events = call(mcp, "listen", after=cursor, timeout_s=0)["events"]
    assert [e["label"] for e in events] == ["Laughter"]
