"""opencode: Parley узнаёт агента по рукопожатию MCP и сам доставляет ему события в сессию."""

import json
import socket
import subprocess
import time
from datetime import datetime

import anyio
from mcp import Client, types

from parley.application.bus import CommandBus, QueryBus
from parley.application.ports import JournalEntry
from parley.application.queries import CompanionStatus
from parley.infrastructure.diary import NullDiary
from parley.infrastructure.journal import InMemoryJournal
from parley.infrastructure.opencode import HEADER, OpencodeBridge, OpencodeCli
from parley.interfaces.mcp.runner import BackgroundServer
from parley.interfaces.mcp.server import ClaudePresence, build_server


class FakeOpencode:
    """Подмена `opencode api`: две сессии, свежая — в чужой папке."""

    def __init__(self, project):
        self.project = str(project)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[1:])
        if cmd[2:4] == ["GET", "/api/session"]:
            data = {"data": [{"id": "ses_other", "location": {"directory": "/elsewhere"}},
                             {"id": "ses_parley", "location": {"directory": self.project}}]}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(data), "")
        return subprocess.CompletedProcess(cmd, 0, '{"data": {"type": "synthetic"}}', "")


def entry(seq, kind, **data):
    return JournalEntry(seq, kind, datetime(2026, 11, 22, 12, 0).astimezone(), data)


def test_events_go_to_the_opencode_session_of_this_project(tmp_path):
    fake = FakeOpencode(tmp_path)
    bridge = OpencodeBridge(OpencodeCli(tmp_path, run=fake), partner=lambda: "opencode")
    assert bridge.send([entry(1, "heard", text="I worked on pipelines"), entry(2, "sound", label="Laughter")])

    method, path, flag, body = fake.calls[-1][1:]
    assert (method, path, flag) == ("POST", "/api/session/ses_parley/synthetic", "-d")
    text = json.loads(body)["text"].splitlines()
    assert text[0] == HEADER
    assert json.loads(text[1])["text"] == "I worked on pipelines" and json.loads(text[2])["kind"] == "sound"
    assert json.loads(body)["delivery"] == "queue"


def test_only_agent_events_and_only_for_opencode(tmp_path):
    partner = {"name": "claude-code"}
    bridge = OpencodeBridge(OpencodeCli(tmp_path, run=FakeOpencode(tmp_path)), partner=lambda: partner["name"])
    bridge.on_entry(entry(1, "heard", text="hi"))
    assert bridge._events.empty()                   # Claude Code слушает сам, через Monitor
    partner["name"] = "opencode"
    bridge.on_entry(entry(2, "activity", activity="thinking"))
    assert bridge._events.empty()                   # служебное событие интерфейса агенту не нужно


def test_opencode_partner_stays_online_without_polling():
    presence = ClaudePresence()
    presence.touched("claude-code")
    presence.last_call -= 120
    assert not presence.online                      # Claude Code без Monitor и вызовов — ушёл
    presence.touched("opencode")
    presence.last_call -= 600
    assert presence.online                          # opencode ждёт доставки событий молча


def test_agent_name_comes_from_mcp_handshake():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    presence, queries = ClaudePresence(), QueryBus()
    queries.register(CompanionStatus, lambda _: {"activity": "idle"})
    server = BackgroundServer(build_server(CommandBus(), queries, InMemoryJournal(), "http://x", presence,
                                           NullDiary()), "127.0.0.1", port)
    server.start()

    async def call() -> None:
        async with Client(f"http://127.0.0.1:{port}/mcp",
                          client_info=types.Implementation(name="opencode", version="2.2.1")) as client:
            await client.call_tool("status", {})

    try:
        for _ in range(50):  # сервер поднимается в фоне
            try:
                anyio.run(call)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        assert presence.client == "opencode"
    finally:
        server.stop()
