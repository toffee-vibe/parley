"""Windows, macOS и Linux без PipeWire: микрофон и колонки через PortAudio (библиотека sounddevice).

Выбирает devices.py. На Windows и macOS PortAudio приезжает вместе с sounddevice; на Linux нужен пакет
libportaudio2 (Debian/Ubuntu) или portaudio.

Частота. Детектору речи нужно 16 кГц, а не каждое устройство её умеет. Сначала просим 16 кГц
(MME на Windows и CoreAudio на macOS пересчитывают сами); не вышло — берём родную частоту
устройства и пересчитываем сами (`_Resampler`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from .devices import CHUNK, Volume
from .pcm import SAMPLE_RATE

log = logging.getLogger(__name__)

_RETRY_S = 2.0  # микрофон отвалился (выдернули гарнитуру) — пробуем снова через столько


def _sd() -> Any:
    try:
        import sounddevice
    except OSError as e:  # sounddevice есть, а самой библиотеки PortAudio в системе нет (Linux)
        raise RuntimeError("Не найдена библиотека PortAudio: установи libportaudio2 (Debian/Ubuntu) "
                           "или portaudio (Fedora, Arch, Homebrew)") from e
    return sounddevice


def _device(target: str, kind: str) -> str | None:
    """Устройство по части имени из конфига; не нашлось — по умолчанию (с предупреждением)."""
    if not target:
        return None
    try:
        _sd().query_devices(target, kind)
        return target
    except ValueError:
        log.warning("Нет устройства «%s» (%s) — беру устройство по умолчанию. Список: python -m sounddevice",
                    target, kind)
        return None


def _native_rate(device: str | None, kind: str) -> int:
    return int(_sd().query_devices(device, kind)["default_samplerate"])


class _Resampler:
    """Линейный пересчёт частоты для потока кусков: помнит хвост, поэтому на стыках нет щелчков и дрейфа."""

    def __init__(self, source: int, target: int):
        self.step = source / target
        self.pos = 0.0
        self.tail = np.zeros(0, np.float32)

    def __call__(self, block: np.ndarray) -> np.ndarray:
        if self.step == 1:
            return block
        data = np.concatenate([self.tail, block])
        last = len(data) - 1
        if last < self.pos:
            self.tail = data
            return np.zeros(0, np.float32)
        count = int((last - self.pos) // self.step) + 1
        positions = self.pos + np.arange(count) * self.step
        out = np.interp(positions, np.arange(len(data)), data).astype(np.float32)
        self.pos = self.pos + count * self.step - last  # относительно последнего отсчёта, который оставляем
        self.tail = data[last:]
        return out


class Microphone:
    """Поток ввода PortAudio → очередь → свой поток режет на куски по CHUNK и отдаёт в on_chunk.

    Колбэк PortAudio только кладёт звук в очередь: тяжёлая работа (детектор речи) в нём недопустима.
    """

    def __init__(self, target: str, on_chunk: Callable[[np.ndarray], None]):
        self.target = target
        self.on_chunk = on_chunk
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="microphone", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Не ждёт поток: вызывается под блокировкой команд."""
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._listen()
            except Exception as e:  # noqa: BLE001 — нет устройства, отвалилось, нет PortAudio
                log.error("Микрофон: %s — пробую снова через %.0f с", e, _RETRY_S)
                self._stop.wait(_RETRY_S)

    def _listen(self) -> None:
        sd = _sd()
        device = _device(self.target, "input")
        blocks: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001 — подпись PortAudio
            blocks.put(indata[:, 0].copy())

        rate = SAMPLE_RATE
        try:
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                                    blocksize=CHUNK, callback=callback)
        except sd.PortAudioError:
            rate = _native_rate(device, "input")
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                                    callback=callback)
        resample = _Resampler(rate, SAMPLE_RATE)
        pending = np.zeros(0, np.float32)
        with stream:
            log.info("Микрофон: %s, %d Гц", sd.query_devices(device, "input")["name"], rate)
            while not self._stop.is_set():
                try:
                    block = blocks.get(timeout=0.2)
                except queue.Empty:
                    continue
                pending = np.concatenate([pending, resample(block)])
                while len(pending) >= CHUNK:
                    chunk, pending = pending[:CHUNK], pending[CHUNK:]
                    try:
                        self.on_chunk(chunk)
                    except Exception:
                        log.exception("Ошибка обработки звука с микрофона")


class Playback:
    """Одна фраза через поток вывода PortAudio. Громкость применяется на лету, кусок за куском."""

    def __init__(self, samples: np.ndarray, sample_rate: int, target: str = "", volume: Volume | None = None):
        sd = _sd()
        self.duration = len(samples) / sample_rate
        self._volume = volume or Volume(1.0)
        self._done = threading.Event()
        self._pos = 0
        device = _device(target, "output")
        self._data = samples.astype(np.float32)
        try:
            self._stream = self._open(sd, device, sample_rate)
        except sd.PortAudioError:
            rate = _native_rate(device, "output")
            self._data = _Resampler(sample_rate, rate)(self._data)
            self._stream = self._open(sd, device, rate)
        self._started = time.monotonic()
        self._stream.start()

    def _open(self, sd: Any, device: str | None, rate: int) -> Any:
        return sd.OutputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                               callback=self._fill, finished_callback=self._done.set)

    def _fill(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002 — подпись PortAudio
        chunk = self._data[self._pos:self._pos + frames] * self._volume.gain()
        outdata[:len(chunk), 0] = chunk
        outdata[len(chunk):, 0] = 0
        self._pos += frames
        if len(chunk) < frames:
            raise _sd().CallbackStop  # остаток в буфере доиграет, потом сработает finished_callback

    @property
    def elapsed(self) -> float:
        return min(time.monotonic() - self._started, self.duration)

    @property
    def playing(self) -> bool:
        return not self._done.is_set()

    def stop(self) -> None:
        if self.playing:
            try:
                self._stream.abort()
            except Exception:  # noqa: BLE001 — уже закрыт
                self._done.set()

    def wait(self) -> None:
        self._done.wait(timeout=self.duration + 5)  # устройство зависло — не ждём вечно
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
