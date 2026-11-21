"""Снимки окна во всех состояниях — без микрофона, колонок и Claude. Удобно править дизайн.

    QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=opengl uv run python scripts/screenshots.py [папка]
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())    # отдельная пустая база, настоящую не трогаем
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()              # и настройки окна (громкость) тоже

# Порядок важен: этот импорт подготавливает Qt (NixOS-библиотеки, переменные) до импорта PySide6.
from parley.interfaces.gui import app as gui  # noqa: E402,I001
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from parley import config  # noqa: E402
from parley.application.commands import (  # noqa: E402
    CloseEars,
    Emote,
    HideBoard,
    OpenEars,
    PartnerArrived,
    Say,
    ShowBoard,
    SpeechBegan,
    SpeechEnded,
    SpeechProgressed,
    UserFinishedTalking,
    UserPaused,
    UserStartedTalking,
)
from parley.bootstrap import build  # noqa: E402
from parley.domain.companion import Mood  # noqa: E402
from parley.domain.conversation import Utterance  # noqa: E402
from parley.infrastructure.clock import SystemClock  # noqa: E402

TENSES = """\
| Время | Когда | Пример |
|---|---|---|
| **Past Simple** | закончилось, есть время | I *built* the pipeline **in 2023**. |
| **Present Perfect** | результат важен сейчас | *I've built* three pipelines. |
| **Past Continuous** | фон, процесс | I *was migrating* the DB when… |
| **Present Perfect Cont.** | длится до сих пор | *I've been working* there for 2 years. |

На собеседовании про прошлую работу почти всегда — **Past Simple**.
"""


class SilentMouth:
    """Ничего не произносит: снимки делаются без звука."""

    busy = False

    def say(self, speech_id, text):
        pass

    def cancel(self, speech_ids):
        pass

    def murmur(self):
        pass

    def hush(self):
        pass


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    settings = config.Settings()
    settings.server.port = 8798
    settings.openrouter.api_key = "preview"
    settings.conversation.murmur_after_s = 0  # не синтезировать «Hmm» (сеть не нужна)
    settings.conversation.turn_end_s = 0.3    # ход заканчивается быстро — снимки не ждут

    gui.prepare_qt()
    qt = QApplication([])
    gui.load_fonts()

    parley = build(settings, with_microphone=False)
    for handler in parley.commands._handlers.values():  # подменяем рот: снимки без звука
        owner = getattr(handler, "__self__", None)
        if owner is not None and hasattr(owner, "mouth"):
            owner.mouth = SilentMouth()
    parley.start()
    bridge = gui.Bridge(parley)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("parley", bridge)
    engine.addImportPath(str(gui.HERE / "qml"))
    engine.load(gui.HERE / "qml" / "Main.qml")
    window = engine.rootObjects()[0]
    run = parley.commands.execute
    now = SystemClock().now

    def snap(name: str, settle_ms: int = 800) -> None:
        wait(settle_ms)
        window.grabWindow().save(str(out / f"{name}.png"))
        print("saved", out / f"{name}.png")

    snap("01-waiting", 1000)
    parley.presence.touched("claude-code")  # «Claude Code на связи» — как будто он только что вызвал инструмент
    run(PartnerArrived())
    snap("01-ready", 600)

    run(UserStartedTalking())
    run(UserPaused(transcribing=True))
    run(UserFinishedTalking(Utterance("I am work as backend developer", now(), 2)))
    run(UserStartedTalking())  # продолжил мысль после паузы
    parley.levels.hearing = 0.08
    snap("02-hearing")
    parley.levels.hearing = 0.0
    run(UserPaused(transcribing=True))
    run(UserFinishedTalking(Utterance("since three years", now(), 1)))
    snap("03-thinking")  # пульс закончил ход через turn_end_s

    speech = run(Say("Small fix: I've been working as a backend developer for three years.",
                     may_interrupt_user=True))
    run(SpeechBegan(speech))
    run(SpeechProgressed(speech, len("Small fix: I've been working as")))
    parley.levels.voice = 0.05
    snap("04-speaking")
    parley.levels.voice = 0.0
    run(SpeechEnded(speech))

    run(ShowBoard("Времена: что когда", TENSES))
    run(Emote(Mood.HAPPY))
    snap("05-board", 1200)
    run(HideBoard())

    for mood in (Mood.CURIOUS, Mood.SURPRISED, Mood.THOUGHTFUL, Mood.PROUD):
        run(Emote(mood))
        snap(f"06-mood-{mood.value}", 700)

    long = ("Смотри, логика одна на все времена. В обычном предложении вспомогательный глагол спрятан, "
            "а в отрицании и вопросе он выходит наружу, и тогда основной глагол стоит в простой форме. "
            "Поэтому did you work, а не did you worked. В Present Perfect вспомогательный — have, и он есть всегда: "
            "I have worked, have you worked? Скажи по-английски: я работал там два года.")
    speech = run(Say(long, may_interrupt_user=True))
    run(SpeechBegan(speech))
    run(SpeechProgressed(speech, int(len(long) * 0.7)))
    snap("06-long-speech", 900)

    run(CloseEars())
    snap("07-deaf", 900)

    bridge.darkTheme = True  # те же кадры в тёмной теме
    run(OpenEars())
    speech = run(Say("Small fix: I've been working as a backend developer for three years.",
                     may_interrupt_user=True))
    run(SpeechBegan(speech))
    run(SpeechProgressed(speech, len("Small fix: I've been working as")))
    parley.levels.voice = 0.05
    snap("08-dark-speaking")
    run(ShowBoard("Времена: что когда", TENSES))
    run(Emote(Mood.HAPPY))
    snap("09-dark-board", 1200)
    parley.stop()
    qt.quit()


if __name__ == "__main__":
    main()
