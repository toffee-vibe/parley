"""Мост между приложением и QML: свойства для отображения, сигналы о событиях, слоты для кликов.

Журнал событий пишут разные потоки (микрофон, плеер, MCP). Qt разрешает трогать интерфейс
только из главного потока, поэтому каждое событие сначала пересылается сигналом `_arrived`
(Qt сам доставит его в главный поток), и только там меняются свойства.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ...application.commands import HideBoard, ToggleEars
from ...application.ports import JournalEntry
from ...application.queries import CompanionStatus, SpeechNow
from ...bootstrap import Parley
from .board_style import style_board

FRAME_MS = 33              # ~30 кадров в секунду: громкость и субтитры
SMOOTHING = 0.45           # 0 — без сглаживания, ближе к 1 — плавнее
# Реплики не гаснут по таймеру: длинное объяснение не успеть дочитать. Реплика агента держится
# до следующей, твоя фраза — до следующей твоей.

# Имя агента из рукопожатия MCP → как показать в окне
AGENT_NAMES = {"claude-code": "Claude Code", "claude": "Claude", "opencode": "opencode", "codex": "Codex",
               "cursor": "Cursor", "gemini": "Gemini CLI", "goose": "Goose", "zed": "Zed"}


def agent_name(client: str) -> str:
    client = client.lower()
    for key, name in AGENT_NAMES.items():
        if key in client:
            return name
    return client or "агент"
STARTLING_SOUNDS = ("Bang", "Slam", "Knock", "Clap", "Smash", "Explosion", "Thump", "Door", "Gunshot", "Bark")


class Bridge(QObject):
    _arrived = Signal(object)

    stateChanged = Signal()
    levelsChanged = Signal()
    subtitlesChanged = Signal()
    boardChanged = Signal()
    presenceChanged = Signal()
    volumeChanged = Signal()
    themeChanged = Signal()
    soundHeard = Signal()

    def __init__(self, app: Parley):
        super().__init__()
        self.app = app
        status = app.queries.ask(CompanionStatus())
        self._activity = status["activity"]
        self._mood = status["mood"]
        self._hearing = 0.0
        self._voice = 0.0
        self._heard = ""
        self._speech = ""
        self._spoken = 0
        self._board_open = False
        self._board_title = ""
        self._board_markdown = ""
        self._claude_online = False
        self._agent = ""
        self._prefs = QSettings("parley", "parley")
        app.volume.set(float(self._prefs.value("volume", app.volume.value)))  # type: ignore[arg-type]
        # Тема: выбранная вручную, а если не выбирали — как в системе
        system_dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self._dark = self._prefs.value("dark", system_dark, type=bool)

        self._arrived.connect(self._on_entry)
        app.journal.subscribe(self._arrived.emit)

        self._frames = QTimer(self, interval=FRAME_MS, timeout=self._frame)
        self._frames.start()
        self._presence = QTimer(self, interval=1000, timeout=self._check_presence)
        self._presence.start()

    # ---------- свойства для QML ----------

    @Property(str, notify=stateChanged)
    def activity(self) -> str:
        return self._activity

    @Property(str, notify=stateChanged)
    def mood(self) -> str:
        return self._mood

    @Property(float, notify=levelsChanged)
    def hearingLevel(self) -> float:  # noqa: N802 — имена свойств в стиле QML
        return self._hearing

    @Property(float, notify=levelsChanged)
    def voiceLevel(self) -> float:  # noqa: N802
        return self._voice

    @Property(str, notify=subtitlesChanged)
    def heardText(self) -> str:  # noqa: N802
        return self._heard

    @Property(str, notify=subtitlesChanged)
    def speechText(self) -> str:  # noqa: N802
        return self._speech

    @Property(int, notify=subtitlesChanged)
    def speechSpoken(self) -> int:  # noqa: N802
        return self._spoken

    @Property(bool, notify=boardChanged)
    def boardOpen(self) -> bool:  # noqa: N802
        return self._board_open

    @Property(str, notify=boardChanged)
    def boardTitle(self) -> str:  # noqa: N802
        return self._board_title

    @Property(str, notify=boardChanged)
    def boardMarkdown(self) -> str:  # noqa: N802
        return self._board_markdown

    @Property(bool, notify=presenceChanged)
    def claudeOnline(self) -> bool:  # noqa: N802
        return self._claude_online

    @Property(str, notify=presenceChanged)
    def agentName(self) -> str:  # noqa: N802 — «Claude Code», «opencode», «Codex»…
        return self._agent

    def _get_volume(self) -> float:
        return self.app.volume.value

    def _set_volume(self, value: float) -> None:
        if abs(value - self.app.volume.value) < 1e-3:
            return
        self.app.volume.set(value)
        self._prefs.setValue("volume", self.app.volume.value)
        self.volumeChanged.emit()

    volume = Property(float, _get_volume, _set_volume, notify=volumeChanged)

    def _get_dark(self) -> bool:
        return bool(self._dark)

    def _set_dark(self, value: bool) -> None:
        if value != self._dark:
            self._dark = value
            self._prefs.setValue("dark", value)
            self.themeChanged.emit()

    darkTheme = Property(bool, _get_dark, _set_dark, notify=themeChanged)

    @Property(bool, constant=True)
    def cloudReady(self) -> bool:  # noqa: N802
        return self.app.cloud_ready

    # ---------- действия из QML ----------

    @Slot()
    def toggleEars(self) -> None:  # noqa: N802
        self.app.commands.execute(ToggleEars())

    @Slot()
    def hideBoard(self) -> None:  # noqa: N802
        self.app.commands.execute(HideBoard())

    @Slot(QObject, "QVariantMap")
    def styleBoard(self, document: QObject, colors: dict) -> None:  # noqa: N802
        style_board(document.textDocument(), colors)  # type: ignore[attr-defined]

    # ---------- события ----------

    def _on_entry(self, entry: JournalEntry) -> None:
        data = entry.data
        match entry.kind:
            case "activity":
                self._activity = data["activity"]
                self.stateChanged.emit()
            case "mood":
                self._mood = data["mood"]
                self.stateChanged.emit()
            case "hearing_text" | "heard":  # по ходу речи — распознанное до сих пор, в конце — вся мысль
                self._heard = data["text"]
                self.subtitlesChanged.emit()
            case "speech_started":
                self._speech, self._spoken = data["text"], 0
                self.subtitlesChanged.emit()
            case "speech_finished":
                self._spoken = len(self._speech)
                self.subtitlesChanged.emit()
            case "board_shown":
                self._board_open = True
                self._board_title, self._board_markdown = data["title"], data["markdown"]
                self.boardChanged.emit()
            case "board_hidden":
                self._board_open = False
                self.boardChanged.emit()
            case "sound":
                if any(word in data["label"] for word in STARTLING_SOUNDS):
                    self.soundHeard.emit()

    def _frame(self) -> None:
        hearing = self.app.levels.hearing if self._activity != "deaf" else 0.0
        self._hearing = self._hearing * SMOOTHING + hearing * (1 - SMOOTHING)
        self._voice = self._voice * SMOOTHING + self.app.levels.voice * (1 - SMOOTHING)
        self.levelsChanged.emit()
        now = self.app.queries.ask(SpeechNow())
        if now and now["text"] == self._speech and now["heard"] != self._spoken:
            self._spoken = now["heard"]
            self.subtitlesChanged.emit()

    def _check_presence(self) -> None:
        online = self.app.presence.online
        name = agent_name(self.app.presence.client)
        if online != self._claude_online or name != self._agent:
            self._claude_online, self._agent = online, name
            self.presenceChanged.emit()
