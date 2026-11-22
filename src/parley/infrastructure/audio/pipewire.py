"""Linux: захват и воспроизведение через утилиты PipeWire (pw-record / pw-play). Выбирает devices.py.

Подпроцессы вместо нативных биндингов: ничего не нужно собирать, легко отлаживать
(`pw-record --raw - | ...` можно запустить руками), а оборвать звук — просто terminate().
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable

import numpy as np

from .devices import CHUNK, Volume
from .pcm import SAMPLE_RATE, from_s16, to_s16

log = logging.getLogger(__name__)

_FEED_S = 0.04        # звук отдаётся плееру кусочками: новая громкость слышна почти сразу
_PIPE_BYTES = 4096    # маленький буфер трубы — по той же причине (по умолчанию 64 КБ ≈ 1.3 с)


class Microphone:
    """pw-record в отдельном потоке. Отдаёт куски по CHUNK отсчётов в on_chunk. Перезапускается при падении."""

    def __init__(self, target: str, on_chunk: Callable[[np.ndarray], None]):
        self.target = target
        self.on_chunk = on_chunk
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="microphone", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Не ждёт поток: вызывается под блокировкой команд, а поток сам может ждать её."""
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _command(self) -> list[str]:
        cmd = ["pw-record", "--raw", "--rate", str(SAMPLE_RATE), "--channels", "1", "--format", "s16",
               "-P", "{ node.name = parley-ears, node.description = \"Parley ears\" }"]
        if self.target:
            cmd += ["--target", self.target]
        return [*cmd, "-"]

    def _run(self) -> None:
        size = CHUNK * 2
        while not self._stop.is_set():
            try:
                self._proc = subprocess.Popen(self._command(), stdout=subprocess.PIPE)  # stderr — в журнал запуска
            except FileNotFoundError:
                log.error("pw-record не найден — нужен PipeWire")
                return
            assert self._proc.stdout is not None
            while not self._stop.is_set():
                raw = self._proc.stdout.read(size)
                if len(raw) < size:
                    break
                try:
                    self.on_chunk(from_s16(raw))
                except Exception:
                    log.exception("Ошибка обработки звука с микрофона")
            if self._proc.poll() is None:
                self._proc.terminate()
            self._proc.wait()
            if not self._stop.is_set():
                log.warning("pw-record завершился, перезапуск через секунду")
                time.sleep(1)


class Playback:
    """Одна проигрываемая фраза. Знает, сколько уже прозвучало, и умеет обрываться."""

    def __init__(self, samples: np.ndarray, sample_rate: int, target: str = "", volume: Volume | None = None):
        self.duration = len(samples) / sample_rate
        self._volume = volume or Volume(1.0)
        self._rate = sample_rate
        cmd = ["pw-play", "--raw", "--rate", str(sample_rate), "--channels", "1", "--format", "s16",
               "-P", "{ node.name = parley-voice, node.description = \"Parley voice\" }"]
        if target:
            cmd += ["--target", target]
        self._proc = subprocess.Popen([*cmd, "-"], stdin=subprocess.PIPE)  # stderr — в журнал запуска
        try:
            import fcntl  # только Linux: на других системах этот модуль не используется

            fcntl.fcntl(self._proc.stdin, fcntl.F_SETPIPE_SZ, _PIPE_BYTES)
        except (ImportError, OSError, AttributeError):
            pass
        self._started = time.monotonic()
        threading.Thread(target=self._feed, args=(samples,), daemon=True).start()

    def _feed(self, samples: np.ndarray) -> None:
        assert self._proc.stdin is not None
        step = max(int(self._rate * _FEED_S), 1)
        try:
            for i in range(0, len(samples), step):
                self._proc.stdin.write(to_s16(samples[i:i + step] * self._volume.gain()))
                self._proc.stdin.flush()
            self._proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass  # оборвали — это нормально

    @property
    def elapsed(self) -> float:
        return min(time.monotonic() - self._started, self.duration)

    @property
    def playing(self) -> bool:
        return self._proc.poll() is None

    def stop(self) -> None:
        if self.playing:
            self._proc.terminate()

    def wait(self) -> None:
        self._proc.wait()
