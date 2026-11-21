"""Сборка приложения (composition root). Единственное место, где выбираются реализации портов.

Заменить голос, распознавание или базу — правка только здесь.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .application.bus import CommandBus, QueryBus
from .application.commands import CommandHandlers, OpenEars, PartnerArrived, PartnerLeft, Tick, Timing
from .application.listeners import HearingReporter, SpeechReporter
from .application.queries import QueryHandlers
from .application.state import LiveState
from .config import PROJECT_DIR, Settings
from .infrastructure.audio.devices import Volume, backend
from .infrastructure.audio.ears import MicrophoneEars
from .infrastructure.audio.local_stt import FirstThatWorks, LocalTranscriber, Transcriber
from .infrastructure.audio.models import LocalModels
from .infrastructure.audio.mouth import QueuedMouth
from .infrastructure.audio.murmurs import Murmurs
from .infrastructure.audio.voices import Bilingual, CloudVoice, PiperVoice, VoiceChain
from .infrastructure.clock import SystemClock
from .infrastructure.diary import Diary
from .infrastructure.journal import InMemoryJournal
from .infrastructure.opencode import OpencodeBridge, OpencodeCli
from .infrastructure.openrouter import OpenRouter
from .infrastructure.sqlite import Database, SqliteFacts, SqliteMistakes, SqlitePhrases, SqliteUtterances
from .interfaces.mcp.runner import BackgroundServer
from .interfaces.mcp.server import ClaudePresence, build_server

log = logging.getLogger(__name__)


class Pulse:
    """Фоновый пульс: несколько раз в секунду выполняет команду Tick (выпустить ждущие реплики и т.п.)."""

    def __init__(self, beat: Callable[[], None], every_s: float = 0.15):
        self.beat = beat
        self.every_s = every_s
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="pulse", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.every_s):
            try:
                self.beat()
            except Exception:
                log.exception("Пульс: команда упала")


class Levels:
    """Громкость для анимации: микрофон (пользователь) и голос персонажа. Пишут потоки звука, читает интерфейс."""

    def __init__(self) -> None:
        self.hearing = 0.0
        self.voice = 0.0

    def set_hearing(self, value: float) -> None:
        self.hearing = value

    def set_voice(self, value: float) -> None:
        self.voice = value


@dataclass
class Parley:
    settings: Settings
    commands: CommandBus
    queries: QueryBus
    journal: InMemoryJournal
    presence: ClaudePresence
    levels: Levels
    voice: VoiceChain
    volume: Volume
    server: BackgroundServer
    closers: list[Callable[[], None]]  # что остановить при выходе: микрофон, звук
    diary: Diary

    def __post_init__(self) -> None:
        self._partner_online = False
        self._pulse = Pulse(self._beat)
        self._started = time.monotonic()

    def _beat(self) -> None:
        online = self.presence.online
        if online != self._partner_online:  # Claude пришёл или ушёл
            self._partner_online = online
            self.commands.execute(PartnerArrived() if online else PartnerLeft())
        self.commands.execute(Tick())

    @property
    def cloud_ready(self) -> bool:
        return bool(self.settings.openrouter.api_key)

    def start(self) -> None:
        self._started = time.monotonic()
        o, v = self.settings.openrouter, self.settings.voice
        self.diary.record("session_start", stt=stt_engine(self.settings), stt_cloud=o.transcription_model, stt_fallback=o.fallback_transcription_model,
                          tts=o.voice_model if self.cloud_ready else "", voices=[v.english, v.russian],
                          volume=self.volume.value, audio=backend(), platform=sys.platform)
        self.server.start()
        self.commands.execute(OpenEars())
        self._pulse.start()
        log.info("Parley слушает (звук: %s). MCP: %s/mcp", backend(), self.settings.server.url)

    def stop(self) -> None:
        self.diary.record("session_end", minutes=round((time.monotonic() - self._started) / 60, 1))
        self._pulse.stop()
        for close in self.closers:
            try:
                close()
            except Exception:
                log.exception("Не удалось остановить %s", close)
        self.server.stop()


def build(settings: Settings, with_microphone: bool = True) -> Parley:
    clock = SystemClock()
    diary = Diary(settings.diary_dir)
    diary.capture_warnings()
    journal = InMemoryJournal()
    journal.subscribe(diary.conversation_event)
    state = LiveState()
    db = Database(settings.database)
    phrases, mistakes, utterances = SqlitePhrases(db), SqliteMistakes(db), SqliteUtterances(db)
    facts = SqliteFacts(db)
    models = LocalModels(settings.models_dir)
    openrouter = OpenRouter(settings.openrouter, diary)
    levels = Levels()

    commands, queries = CommandBus(), QueryBus()

    v = settings.voice
    voices = [Bilingual("piper", PiperVoice(models, v.fallback_en), PiperVoice(models, v.fallback_ru))]
    if openrouter.configured and settings.openrouter.voice_model:
        voices.insert(0, Bilingual("cloud", CloudVoice(openrouter, v.english, "cloud-en"),
                                   CloudVoice(openrouter, v.russian, "cloud-ru")))
    voice = VoiceChain(*voices)
    volume = Volume(v.volume)
    # «Hmm» — тем же английским голосом, что и реплики: лучшим из доступных
    murmurs = Murmurs(voices[0].english, settings.murmurs_dir, voice_key=f"{voices[0].english.name}|{v.english}")
    mouth = QueuedMouth(voice, SpeechReporter(commands), v.output, on_level=levels.set_voice, volume=volume,
                        murmurs=murmurs)

    c = settings.conversation
    timing = Timing(reply_pause_s=c.reply_pause_s, turn_end_s=c.turn_end_s, murmur_after_s=c.murmur_after_s)
    handlers = CommandHandlers(state, journal, clock, mouth, phrases, mistakes, utterances, facts, timing)
    for message, handler in handlers.routes().items():
        commands.register(message, handler)
    for message, handler in QueryHandlers(state, journal, clock, phrases, mistakes, utterances, facts).routes().items():
        queries.register(message, handler)

    if settings.conversation.murmur_after_s > 0:
        murmurs.prepare_in_background()
    closers: list[Callable[[], None]] = [mouth.close]
    if with_microphone:
        handlers.ears = MicrophoneEars(settings.hearing, models, transcriber(settings, openrouter, models, diary),
                                       HearingReporter(commands),
                                       companion_speaking=lambda: mouth.busy, voice_level=lambda: levels.voice,
                                       on_level=levels.set_hearing, diary=diary)
        closers.append(handlers.ears.close)

    presence = ClaudePresence()
    # opencode не умеет подписаться на поток событий — Parley доставляет их в его сессию сам
    bridge = OpencodeBridge(OpencodeCli(PROJECT_DIR), partner=lambda: presence.client)
    journal.subscribe(bridge.on_entry)
    mcp = build_server(commands, queries, journal, settings.server.url, presence, diary)
    server = BackgroundServer(mcp, settings.server.host, settings.server.port)
    return Parley(settings, commands, queries, journal, presence, levels, voice, volume, server, closers, diary)


def stt_engine(settings: Settings) -> str:
    """Кто распознаёт речь: cloud или local (auto — облако, если есть ключ)."""
    engine = settings.transcription.engine.strip().lower()
    if engine not in ("cloud", "local"):
        engine = "cloud" if settings.openrouter.api_key else "local"
    return engine


def transcriber(settings: Settings, openrouter: OpenRouter, models: LocalModels, diary: Diary) -> Transcriber:
    """Облако с подстраховкой встроенной моделью (если она уже скачана) или только встроенная модель."""
    model = settings.transcription.local_model
    if stt_engine(settings) == "local":
        local = LocalTranscriber(models, model, diary)
        local.prepare_in_background()  # скачать (~500 МБ при первом запуске) и загрузить, пока ты не заговорил
        return local
    return FirstThatWorks(openrouter, LocalTranscriber(models, model, diary, download=False))
