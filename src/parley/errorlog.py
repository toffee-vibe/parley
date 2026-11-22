"""Журнал запуска: всё, что может пойти не так, — с первой строки программы и у любого пользователя.

Включается первым делом в `parley` (cli.main), раньше Qt, моделей и сервера. Каждый запуск пишет свой файл
~/.local/share/parley/logs/parley-ГГГГММДД-ЧЧММСС.log (хранятся последние KEEP запусков). В него попадает:

    записи лога (INFO и выше; с -v — всё)               logging
    всё, что пишется в stderr, — в том числе             перехват файлового дескриптора 2:
      C-библиотеками (Qt до своего обработчика,            иначе то, что пишут мимо Python,
      onnxruntime, PortAudio) и дочерними процессами       не поймать
    падение программы                                    sys.excepthook
    падение фонового потока                              threading.excepthook
    «Exception ignored in …»                             sys.unraisablehook
    предупреждения Python (DeprecationWarning и т.п.)    logging.captureWarnings
    падение в C-коде (segfault, abort)                   faulthandler — пишет трассировку прямо в файл

В терминале всё выглядит как раньше. Ошибки и предупреждения вдобавок уходят в технический дневник
(`parley report`), а `parley bugreport` собирает журнал последнего запуска в один файл для issue.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO

KEEP = 20
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
STDERR_LOGGER = "parley.stderr"   # строки, пришедшие в stderr мимо логов

log = logging.getLogger("parley")

# Строки, которые наш же консольный лог уже показал (наш формат и формат rich у MCP), и строки трассировок —
# сама ошибка уже записана вместе с трассировкой через excepthook.
_ALREADY_LOGGED = re.compile(r"^(\d\d:\d\d:\d\d (DEBUG|INFO|WARNING|ERROR|CRITICAL) "
                             r"|\[\d\d/\d\d/\d\d \d\d:\d\d:\d\d\] |\s|Traceback \(most recent call last\))")


class ErrorLog:
    def __init__(self, folder: Path, keep: int = KEEP):
        self.folder = folder
        self.keep = keep
        self.path = folder / f"parley-{datetime.now():%Y%m%d-%H%M%S}.log"
        self._fault_file: TextIO | None = None

    def install(self, level: int = logging.INFO) -> ErrorLog:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._forget_old()
        console = self._capture_stderr()  # консоль — исходный stderr: перехват не должен ловить сам себя

        root = logging.getLogger()
        root.setLevel(level)
        for handler in list(root.handlers):
            root.removeHandler(handler)
        to_file = logging.FileHandler(self.path, encoding="utf-8")
        to_file.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s %(name)s: "
                                               "%(message)s", "%H:%M:%S"))
        to_console = logging.StreamHandler(console)
        to_console.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
        to_console.addFilter(lambda r: r.name != STDERR_LOGGER)  # эти строки терминал уже видел как есть
        root.addHandler(to_file)
        root.addHandler(to_console)

        logging.captureWarnings(True)
        sys.excepthook = _uncaught
        threading.excepthook = _thread_crashed
        sys.unraisablehook = _unraisable
        self._fault_file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115 — живёт до выхода
        faulthandler.enable(self._fault_file, all_threads=True)
        log.info("Журнал запуска: %s", self.path)
        return self

    def _capture_stderr(self) -> TextIO:
        """fd 2 → труба; поток читает её, показывает в терминале как есть и пишет строки в лог."""
        try:
            original = os.dup(2)
            read_end, write_end = os.pipe()
            os.dup2(write_end, 2)
            os.close(write_end)
        except OSError:  # нет stderr (pythonw на Windows) — ловим только то, что идёт через Python
            return sys.stderr
        threading.Thread(target=_pump, args=(read_end, original), name="stderr", daemon=True).start()
        return os.fdopen(os.dup(original), "w", encoding="utf-8", errors="replace", buffering=1)

    def _forget_old(self) -> None:
        old = sorted(self.folder.glob("parley-*.log"))[: -(self.keep - 1) or None]
        for file in old:
            file.unlink(missing_ok=True)


def latest(folder: Path, count: int = 1) -> list[Path]:
    return sorted(folder.glob("parley-*.log"))[-count:]


def _pump(read_end: int, original: int) -> None:
    stderr_log = logging.getLogger(STDERR_LOGGER)
    buffer = b""
    while chunk := os.read(read_end, 4096):
        os.write(original, chunk)                   # в терминале всё как было
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", "replace").rstrip()
            if line and not _ALREADY_LOGGED.match(line):
                stderr_log.warning("%s", line[:1000])


def _uncaught(kind, value, tb) -> None:  # noqa: ANN001 — сигнатура sys.excepthook
    if issubclass(kind, KeyboardInterrupt):
        return sys.__excepthook__(kind, value, tb)
    log.critical("Parley упал", exc_info=(kind, value, tb))


def _thread_crashed(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    log.error("Поток %s упал", args.thread.name if args.thread else "?",
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _unraisable(args) -> None:  # noqa: ANN001 — sys.UnraisableHookArgs
    log.error("Ошибка, которую Python проигнорировал: %s %s", args.err_msg or "", repr(args.object)[:200],
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback) if args.exc_value else None)
