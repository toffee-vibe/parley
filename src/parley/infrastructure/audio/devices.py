"""Микрофон и колонки на любой системе.

    Linux с PipeWire  → pipewire.py (утилиты pw-record / pw-play: свои узлы «Parley ears» / «Parley voice»)
    Windows, macOS, Linux без PipeWire → portaudio.py (библиотека sounddevice)

Выбрать вручную: переменная окружения PARLEY_AUDIO=pipewire | portaudio.
Остальной код работает с `Microphone` и `Playback` отсюда и не знает, какая система под ними.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from functools import cache
from typing import Protocol

import numpy as np

CHUNK = 512  # 32 мс при 16 кГц — ровно окно детектора речи Silero


class Volume:
    """Громкость голоса 0..1. Меняет интерфейс, читает плеер прямо во время фразы."""

    def __init__(self, value: float = 0.6):
        self.value = value

    def set(self, value: float) -> None:
        self.value = min(max(value, 0.0), 1.0)

    def gain(self) -> float:
        return self.value ** 2  # слух воспринимает громкость нелинейно: так ползунок ощущается ровным


class MicrophonePort(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PlaybackPort(Protocol):
    duration: float

    @property
    def elapsed(self) -> float: ...
    @property
    def playing(self) -> bool: ...
    def stop(self) -> None: ...
    def wait(self) -> None: ...


@cache
def backend() -> str:
    chosen = os.environ.get("PARLEY_AUDIO", "").strip().lower()
    if chosen in ("pipewire", "portaudio"):
        return chosen
    if sys.platform.startswith("linux") and shutil.which("pw-record") and shutil.which("pw-play"):
        return "pipewire"
    return "portaudio"


def Microphone(target: str, on_chunk: Callable[[np.ndarray], None]) -> MicrophonePort:  # noqa: N802 — как класс
    """Куски по CHUNK отсчётов, 16 кГц, моно, float32. target — устройство ("" — по умолчанию)."""
    if backend() == "pipewire":
        from . import pipewire
        return pipewire.Microphone(target, on_chunk)
    from . import portaudio
    return portaudio.Microphone(target, on_chunk)


def Playback(samples: np.ndarray, sample_rate: int, target: str = "",  # noqa: N802 — как класс
             volume: Volume | None = None) -> PlaybackPort:
    """Одна фраза: начинает звучать сразу, знает, сколько прозвучало, умеет обрываться."""
    if backend() == "pipewire":
        from . import pipewire
        return pipewire.Playback(samples, sample_rate, target, volume)
    from . import portaudio
    return portaudio.Playback(samples, sample_rate, target, volume)
