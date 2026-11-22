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
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from ...application.bus import CommandBus, QueryBus
from ...application.commands import (
    CloseEars,
    CompanionIsDeaf,
    Emote,
    Forget,
    HideBoard,
    NoteMistake,
    NotFound,
    OpenEars,
    Remember,
    ReportMisheard,
    ReportProblem,
    ReviewPhrase,
    SavePhrase,
    Say,
    ShowBoard,
    StopSpeaking,
    ToggleEars,
)
from ...application.ports import Journal, Recorder
from ...application.queries import CompanionStatus, DuePhrases, Listen, Progress, Recall, SpeechResult, for_agent
from ...domain.companion import Mood
from ...domain.learning import MistakeKind, ReviewOutcome

INSTRUCTIONS = Path(__file__).with_name("instructions.md")


class ClaudePresence:
    """Подключён ли агент (Claude Code, Codex, opencode…): интерфейс показывает это значком.

    `client` — имя агента из рукопожатия MCP: по нему, например, включается доставка событий в opencode.
    """

    def __init__(self) -> None:
        self.last_call = 0.0
        self.streams = 0
        self.client = ""
        self._lock = threading.Lock()

    def touched(self, client: str = "") -> None:
        self.last_call = time.monotonic()
        if client:
            self.client = client

    @property
    def online(self) -> bool:
        # opencode не держит поток и не вызывает listen: события ему доставляет Parley (infrastructure/opencode.py),
        # а сам агент между репликами молчит. Поэтому и ждём его дольше.
        grace = 1800 if "opencode" in self.client else 90
        return self.streams > 0 or time.monotonic() - self.last_call < grace

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

    delivered: dict[str, int | None] = {"cursor": None,    # до какого события агент дочитал через listen
                                        "answered": None}  # последнее событие на момент прошлого say

    def seen(ctx: Context | None) -> None:
        """Агент что-то вызвал: он здесь. Заодно запоминаем, кто это (имя клиента MCP)."""
        name = _client_name(ctx)
        if name and name != presence.client:
            diary.record("agent", client=name)  # в дневнике видно, с каким агентом шёл разговор
        presence.touched(name)

    def execute(command: object):
        presence.touched()
        try:
            return commands.execute(command)
        except (CompanionIsDeaf, NotFound, ValueError) as e:
            raise ToolError(str(e)) from e

    def ask(query: object):
        presence.touched()
        return queries.ask(query)

    # --- с чего начать ---

    @mcp.tool(name="instructions")
    def read_instructions(ctx: Context) -> str:
        """How to be Pip: how to hear and talk, the teaching method, memory. Read it first if your client did not
        show you Parley's server instructions (some agents don't pass them to the model)."""
        seen(ctx)
        return instructions

    # --- слух и речь ---

    @mcp.tool()
    async def listen(ctx: Context, after: int = -1, timeout_s: float = 25) -> dict:
        """Wait for new events (long-poll). Returns {cursor, events}. Pass `cursor` back as `after` next time.
        Use only if events are not delivered to you otherwise (Monitor in Claude Code, "Parley events" messages
        in opencode)."""
        seen(ctx)
        result = await anyio.to_thread.run_sync(ask, Listen(after, min(timeout_s, 55)))
        delivered["cursor"] = result["cursor"]
        return result

    @mcp.tool()
    async def say(ctx: Context, text: str, interrupt_user: bool = False, wait: bool = False,
                  board_title: str = "", board: str = "") -> dict:
        """Say something out loud as Pip. Plain spoken text, 1–3 sentences; may start sentences with an
        emotion tag like [excited], [curious], [laughing], [whispering], [sad], [surprised].
        board_title + board (Markdown): show a board together with this line, in the same call — the user sees
        it as Pip starts talking. Prefer this to a separate show_board call: every extra tool call delays the voice.
        By default Pip waits until the user has finished talking; if the user keeps talking, the reply is
        dropped (event `speech_dropped`) and you should answer again. interrupt_user=true speaks right away,
        even over the user — use it very rarely. Refused while the user has muted you.
        If the user said something new while you were thinking, the reply is not spoken: you get
        `"status": "not_spoken"` with what they said — answer that.
        wait=true blocks until speech ends and returns what the user heard."""
        seen(ctx)
        unseen = _unseen_speech(journal, delivered.get("cursor"), delivered.get("answered"))
        delivered["answered"] = journal.last_seq()
        if unseen and not interrupt_user:
            # Пока агент думал, пользователь сказал ещё что-то: ответ на старое прозвучал бы мимо.
            if delivered.get("cursor") is not None:
                delivered["cursor"] = journal.last_seq()
            return {"status": "not_spoken", "reason": "While you were thinking the user said something new. "
                    "Your reply was not spoken. Answer their latest words (if your reply already covers them, "
                    "call say again with it).",
                    "cursor": journal.last_seq(), "events": [e.as_dict() for e in unseen]}
        speech_id = execute(Say(text, may_interrupt_user=interrupt_user))
        if board_title or board:
            execute(ShowBoard(board_title, board))
        return await anyio.to_thread.run_sync(ask, SpeechResult(speech_id, wait_s=90 if wait else 0))

    @mcp.tool()
    def stop_speaking() -> str:
        """Stop talking right now and drop queued speech."""
        execute(StopSpeaking())
        return "ok"

    @mcp.tool()
    def status(ctx: Context) -> dict:
        """Pip's state: activity (waiting/idle/hearing/thinking/speaking/deaf), mood, ears_open, current cursor."""
        seen(ctx)
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
        If you are about to say something with it, pass the board to `say` instead (same call, no delay).
        Markdown with tables, lists, **bold**, `code`. Pip steps aside while the board is open. Russian is fine here."""
        execute(ShowBoard(title, markdown))
        return "ok"

    @mcp.tool()
    def hide_board() -> str:
        """Close the board; Pip returns to the center."""
        execute(HideBoard())
        return "ok"

    # --- память о пользователе ---

    @mcp.tool()
    def recall(ctx: Context, topic: str = "") -> dict:
        """What you remember about the user from earlier sessions, grouped by topic (profile, work, projects,
        interview, life, style, session), newest first. Call it quietly when a session starts."""
        seen(ctx)
        return ask(Recall(topic))

    @mcp.tool()
    def remember(fact: str, topic: str = "profile", replaces: str = "") -> dict:
        """Save one short fact about the user for future sessions (<300 chars, write it in English or Russian).
        topic: profile | work | projects | interview | life | style | session. If it updates an old fact
        (new job, changed date), pass the old fact's id as `replaces` instead of adding a contradiction.
        Save quietly — never announce that you are remembering something."""
        return {"id": execute(Remember(fact, topic, replaces))}

    @mcp.tool()
    def forget(fact_id: str) -> str:
        """Delete a wrong or outdated fact (e.g. the user corrected you or asked you to forget it)."""
        execute(Forget(fact_id))
        return "ok"

    # --- обратная связь разработчику ---

    @mcp.tool()
    def note_for_developer(problem: str, context: str = "") -> str:
        """Silently note a problem with Parley itself (not with the user's English): Pip cut the user off or talked
        over them, long delays, a reply that got dropped, a wrong voice or language, a missing tool you wished
        you had. One short sentence; `context` = what happened. It is written immediately to the developer's
        feedback file. Never mention this to the user. For a misrecognized word use `misheard` instead."""
        execute(ReportProblem(problem, context))  # и в файл отзывов, и в дневник
        return "noted"

    @mcp.tool()
    def misheard(heard: str, meant: str) -> str:
        """The speech recognizer wrote a word or phrase wrong. `heard` — what the recognizer wrote (e.g. "Agis GPT",
        "описывать"), `meant` — what the user actually said (e.g. "did", "овеществлять"). Call it silently whenever
        the user corrects the recognizer ("I said X, not Y") or context makes the mistake obvious. Parley adds
        `meant` to the recognizer's vocabulary — from the next phrase it is recognized better. Never mention it."""
        execute(ReportMisheard(heard, meant))
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
                        if for_agent(entry):
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


def _client_name(ctx: Context | None) -> str:
    """Имя агента из рукопожатия MCP: "claude-code", "opencode", "codex-mcp-client"…"""
    try:
        params = ctx.session.client_params if ctx else None
        return (params.client_info.name if params and params.client_info else "").lower()
    except Exception:  # noqa: BLE001 — нет запроса (вызов из тестов) или клиент не представился
        return ""


def _unseen_speech(journal: Journal, cursor: int | None, answered: int | None) -> list:
    """Новые фразы пользователя, которых агент, отвечая сейчас, скорее всего не видел.

    Агент с listen: всё после курсора — точно. Агенту, которому события приходят сами (Monitor, opencode),
    мы не знаем, что он прочёл. Но одну фразу после прошлого ответа он видел — на неё и отвечает; если их
    уже две и больше, значит, пока он думал, пользователь сказал ещё что-то."""
    if cursor is not None:
        fresh = [e for e in journal.after(cursor) if for_agent(e)]
        return fresh if any(e.kind == "heard" for e in fresh) else []
    if answered is None:
        return []
    said = [e for e in journal.after(answered) if e.kind == "heard"]
    return said if len(said) >= 2 else []
