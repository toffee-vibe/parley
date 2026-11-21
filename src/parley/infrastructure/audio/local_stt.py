"""Встроенное распознавание речи: модель на этом компьютере, без сети и бесплатно (sherpa-onnx).

По умолчанию — Parakeet TDT 0.6b v3 (NVIDIA): 25 европейских языков, в том числе русский и английский,
сам определяет язык и расставляет знаки препинания. На тестовых записях с русским акцентом и смешанной
речью: 14% ошибок в словах, ~0.3 с на фразу на обычном процессоре. Для сравнения: облачный
gpt-4o-mini-transcribe — 6–8%, облачный whisper turbo — 15–19%, локальный whisper turbo — 17% и 2.5 с.

Модель (~500 МБ) скачивается один раз в ~/.local/share/parley/models.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Protocol

import numpy as np
import sherpa_onnx

from ...application.ports import Recorder
from ..diary import NullDiary
from .models import LocalModels
from .pcm import SAMPLE_RATE

log = logging.getLogger(__name__)


class Transcriber(Protocol):
    name: str

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str: ...


class LocalTranscriber:
    def __init__(self, models: LocalModels, model: str = "parakeet", diary: Recorder | None = None,
                 download: bool = True):
        self.models = models
        self.model = model
        self.download = download  # False — запасной вариант: работает, только если модель уже скачана
        self.name = f"local/{model}"
        self.diary = diary or NullDiary()
        self._recognizer: Any = None
        self._lock = threading.Lock()

    def prepare_in_background(self) -> None:
        """Скачать и загрузить модель заранее, чтобы первая фраза не ждала загрузки 500 МБ."""
        threading.Thread(target=self._safe_load, name="local-stt", daemon=True).start()

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        recognizer = self._load()
        started = time.monotonic()
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        self.diary.record("stt", model=self.name, audio_s=round(len(samples) / sample_rate, 2),
                          ms=round((time.monotonic() - started) * 1000), cost=0)
        return text

    def _safe_load(self) -> None:
        try:
            self._load()
        except Exception as e:  # noqa: BLE001 — не вышло заранее, попробуем при первой фразе
            log.warning("Встроенное распознавание не готово: %s", e)

    def _load(self) -> Any:
        with self._lock:
            if self._recognizer is None:
                directory = self.models.speech_recognizer(self.model, download=self.download)
                threads = max(1, min(4, (os.cpu_count() or 2) // 2))
                if self.model.startswith("whisper"):
                    size = self.model.removeprefix("whisper-")
                    self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                        encoder=str(directory / f"{size}-encoder.int8.onnx"),
                        decoder=str(directory / f"{size}-decoder.int8.onnx"),
                        tokens=str(directory / f"{size}-tokens.txt"),
                        language="", task="transcribe", num_threads=threads)
                else:
                    self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                        encoder=str(directory / "encoder.int8.onnx"), decoder=str(directory / "decoder.int8.onnx"),
                        joiner=str(directory / "joiner.int8.onnx"), tokens=str(directory / "tokens.txt"),
                        model_type="nemo_transducer", num_threads=threads)
                log.info("Встроенное распознавание готово: %s", self.model)
            return self._recognizer


class FirstThatWorks:
    """Сначала основное распознавание, а если оно упало (нет сети, кончились деньги) — запасное."""

    def __init__(self, primary: Transcriber, fallback: Transcriber):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        try:
            return self.primary.transcribe(samples, sample_rate)
        except Exception as e:  # noqa: BLE001
            log.warning("Распознавание %s не сработало (%s) — беру %s", self.primary.name, e, self.fallback.name)
            return self.fallback.transcribe(samples, sample_rate)
