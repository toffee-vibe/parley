"""MCP-сервер: инструменты для Claude + поток событий (SSE / NDJSON) + управление для хоткеев.

Каждый инструмент — тонкая обёртка: собрать команду или запрос, отдать в шину, вернуть ответ.
Логики здесь нет — она в application/ и domain/.

HTTP:
    /mcp                MCP (streamable HTTP) — сюда подключается Claude Code
    /events             SSE: text/event-stream
    /events.ndjson      то же, одна JSON-строка на событие (удобно для Monitor + curl)
    /status             состояние персонажа
    /ears/toggle|open|close   POST — для хоткея Hyprland: `curl -X POST .../ears/toggle`
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from ...application.bus import CommandBus, QueryBus
from ...application.commands import (
    CloseEars,
    CompanionIsDeaf,
    Emote,
    HideBoard,
    NoteMistake,
    NotFound,
    OpenEars,
    ReviewPhrase,
    SavePhrase,
    Say,
    ShowBoard,
    StopSpeaking,
    ToggleEars,
)
from ...application.ports import Journal, Recorder
from ...application.queries import FOR_CLAUDE, CompanionStatus, DuePhrases, Listen, Progress, SpeechResult
from ...domain.companion import Mood
from ...domain.learning import MistakeKind, ReviewOutcome

INSTRUCTIONS = Path(__file__).with_name("instructions.md")


class ClaudePresence:
    """Подключён ли Claude: интерфейс показывает это значком."""

    def __init__(self) -> None:
        self.last_call = 0.0
        self.streams = 0
        self._lock = threading.Lock()

    def touched(self) -> None:
        self.last_call = time.monotonic()

    @property
    def online(self) -> bool:
        return self.streams > 0 or time.monotonic() - self.last_call < 90

    def stream_opened(self) -> None:
        with self._lock:
            self.streams += 1

    def stream_closed(self) -> None:
        with self._lock:
            self.streams -= 1


def build_server(commands: CommandBus, queries: QueryBus, journal: Journal, url: str,
                 presence: ClaudePresence, diary: Recorder) -> MCPServer:
    instructions = INSTRUCTIONS.read_text(encoding="utf-8").replace("{url}", url)
    mcp = MCPServer("parley", title="Parley — voice companion", instructions=instructions)

    def execute(command: object):
        presence.touched()
        try:
            return commands.execute(command)
        except (CompanionIsDeaf, NotFound, ValueError) as e:
            raise ToolError(str(e)) from e

    def ask(query: object):
        presence.touched()
        return queries.ask(query)

    # --- слух и речь ---

    @mcp.tool()
    async def listen(after: int = -1, timeout_s: float = 25) -> dict:
        """Wait for new events (long-poll). Returns {cursor, events}. Pass `cursor` back as `after` next time.
        Use only if you can't subscribe to the event stream with Monitor."""
        return await anyio.to_thread.run_sync(ask, Listen(after, min(timeout_s, 55)))

    @mcp.tool()
    async def say(text: str, interrupt_user: bool = False, wait: bool = False) -> dict:
        """Say something out loud as Pip. Plain spoken text, 1–3 sentences; may start sentences with an
        emotion tag like [excited], [curious], [laughing], [whispering], [sad], [surprised].
        By default Pip waits until the user has finished talking; if the user keeps talking, the reply is
        dropped (event `speech_dropped`) and you should answer again. interrupt_user=true speaks right away,
        even over the user — use it very rarely. Refused while the user has muted you.
        wait=true blocks until speech ends and returns what the user heard."""
        speech_id = execute(Say(text, may_interrupt_user=interrupt_user))
        return await anyio.to_thread.run_sync(ask, SpeechResult(speech_id, wait_s=90 if wait else 0))

    @mcp.tool()
    def stop_speaking() -> str:
        """Stop talking right now and drop queued speech."""
        execute(StopSpeaking())
        return "ok"

    @mcp.tool()
    def status() -> dict:
        """Pip's state: activity (waiting/idle/hearing/thinking/speaking/deaf), mood, ears_open, current cursor."""
        return ask(CompanionStatus())

    @mcp.tool()
    def set_ears(open: bool) -> dict:
        """Open or close Pip's ears (microphone). Normally the user does this; use only if asked."""
        execute(OpenEars() if open else CloseEars())
        return ask(CompanionStatus())

    # --- лицо и экран ---

    @mcp.tool()
    def emote(mood: Literal["neutral", "happy", "curious", "surprised", "proud", "thoughtful"]) -> str:
        """Change Pip's facial expression."""
        execute(Emote(Mood(mood)))
        return "ok"

    @mcp.tool()
    def show_board(title: str, markdown: str) -> str:
        """Show a board next to Pip: an explanation, a rule, a table (e.g. English tenses), examples.
        Markdown with tables, lists, **bold**, `code`. Pip steps aside while the board is open. Russian is fine here."""
        execute(ShowBoard(title, markdown))
        return "ok"

    @mcp.tool()
    def hide_board() -> str:
        """Close the board; Pip returns to the center."""
        execute(HideBoard())
        return "ok"

    # --- обратная связь разработчику ---

    @mcp.tool()
    def note_for_developer(problem: str, context: str = "") -> str:
        """Silently note a problem with Parley itself (not with the user's English) for the developer: misheard
        speech you had to guess, Pip cut the user off or talked over them, long delays, a reply that got dropped,
        an awkward voice/language switch, a missing tool you wished you had. One short sentence each;
        `context` = what happened (e.g. heard text). Never mention this to the user."""
        presence.touched()
        diary.record("claude_note", problem=problem, context=context)
        return "noted"

    # --- обучение ---

    @mcp.tool()
    def save_phrase(text: str, meaning: str, example: str) -> dict:
        """Save an English phrase the user needed but couldn't say. text: the English chunk;
        meaning: what the user wanted to say (often Russian); example: a sentence in interview context."""
        return {"phrase_id": execute(SavePhrase(text, meaning, example))}

    @mcp.tool()
    def due_phrases(limit: int = 5) -> list[dict]:
        """Phrases due for practice. Elicit them in conversation; don't show them in advance."""
        return ask(DuePhrases(limit))

    @mcp.tool()
    def review_phrase(phrase_id: str, outcome: Literal["used", "struggled", "missed"]) -> str:
        """Record how the user did with a due phrase: used (correctly, unprompted), struggled, missed."""
        execute(ReviewPhrase(phrase_id, ReviewOutcome(outcome)))
        return "ok"

    @mcp.tool()
    def note_mistake(category: Literal["grammar", "word_choice", "word_order", "preposition",
                                       "pronunciation", "missing_word"],
                     wrong: str, right: str, explanation: str = "") -> dict:
        """Log a real error. The same correct form counts as the same mistake, so recurring ones are visible."""
        return {"mistake_id": execute(NoteMistake(MistakeKind(category), wrong, right, explanation))}

    @mcp.tool()
    def progress(days: int = 1) -> dict:
        """Measured progress for the last N days: words spoken, English share, phrases learned, top mistakes."""
        return ask(Progress(days))

    # --- HTTP для подписки и хоткеев ---

    def stream(request: Request, render: Callable[[dict], str], media_type: str) -> StreamingResponse:
        after = int(request.query_params.get("after", journal.last_seq()))

        async def events() -> AsyncIterator[str]:
            nonlocal after
            presence.stream_opened()
            try:
                yield render({"kind": "hello", "cursor": after})
                while True:
                    entries = await anyio.to_thread.run_sync(journal.wait, after, 15.0, abandon_on_cancel=True)
                    if not entries:
                        yield ": keepalive\n\n" if media_type == "text/event-stream" else ""
                        continue
                    after = entries[-1].seq
                    for entry in entries:
                        if entry.kind in FOR_CLAUDE:
                            yield render(entry.as_dict())
            finally:
                presence.stream_closed()

        return StreamingResponse(events(), media_type=media_type, headers={"Cache-Control": "no-cache"})

    @mcp.custom_route("/events", methods=["GET"])
    async def sse(request: Request) -> Response:
        return stream(request, lambda e: f"event: {e['kind']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n",
                      "text/event-stream")

    @mcp.custom_route("/events.ndjson", methods=["GET"])
    async def ndjson(request: Request) -> Response:
        return stream(request, lambda e: json.dumps(e, ensure_ascii=False) + "\n", "application/x-ndjson")

    @mcp.custom_route("/status", methods=["GET"])
    async def status_route(_: Request) -> Response:
        return JSONResponse(queries.ask(CompanionStatus()))

    @mcp.custom_route("/ears/{action}", methods=["POST"])
    async def ears_route(request: Request) -> Response:
        command = {"toggle": ToggleEars, "open": OpenEars, "close": CloseEars}.get(request.path_params["action"])
        if command is None:
            return JSONResponse({"error": "use toggle, open or close"}, status_code=404)
        commands.execute(command())
        return JSONResponse(queries.ask(CompanionStatus()))

    return mcp
