"""Голоса — превращают текст в звук. Рот (mouth.py) берёт их по цепочке: облачный → локальный.

Один голос — один язык. Иначе русский голос говорит по-английски с акцентом и наоборот.
`Bilingual` режет фразу на английские и русские куски и отдаёт каждый носителю языка:
«Тут нужен | Present Perfect, | потому что…» — три куска, два голоса, без акцента.

Свой голос — класс с методом `synthesize(text) -> (samples, sample_rate)`; подставить в bootstrap.py.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import sherpa_onnx

from ...domain.speech import without_tags
from ..openrouter import OpenRouter
from .models import LocalModels
from .pcm import decode, resample

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"(?P<tag>\[[^\]]*\])|(?P<en>[A-Za-z]+(?:'[A-Za-z]+)?)|(?P<ru>[А-Яа-яЁё]+)")
_GAP_S = 0.06  # пауза на стыке языков


class Voice(Protocol):
    name: str

    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...


@dataclass(frozen=True)
class Run:
    """Кусок фразы на одном языке. `text` — что синтезировать, `source` — этот кусок в исходной фразе."""

    language: str
    text: str
    source: str


def language_runs(text: str) -> list[Run]:
    """Режет текст на куски одного языка: «Тут нужен» (ru), «Present Perfect,» (en), «потому что…» (ru).

    Знаки препинания остаются с предыдущим куском, открывающие кавычки и теги эмоций — со следующим.
    Тег эмоции продолжает действовать и в следующих кусках.
    """
    runs: list[tuple[str, str]] = []
    language, start, word_end, cut, mood = "", 0, 0, None, ""
    for token in _TOKEN.finditer(text):
        if token["tag"]:
            if cut is None:
                cut = token.start()
            continue
        here = "en" if token["en"] else "ru"
        if language and here != language:
            boundary = cut if cut is not None else _before_prefix(text, word_end, token.start())
            runs.append((language, text[start:boundary].strip()))
            start = boundary
        language, word_end, cut = here, token.end(), None
    runs.append((language or "en", text[start:].strip()))

    result = []
    for lang, part in runs:
        tags = re.findall(r"\[[^\]]*\]", part)
        spoken = f"{mood} {part}" if mood and not part.startswith("[") else part
        mood = tags[-1] if tags else mood
        if without_tags(part).strip():
            result.append(Run(lang, spoken, part))
    return result


def _before_prefix(text: str, previous_end: int, word_start: int) -> int:
    """Начало слова вместе с прилипшими к нему открывающими знаками («, ", ( …)."""
    cut = word_start
    while cut > previous_end and not text[cut - 1].isspace():
        cut -= 1
    return cut


class Bilingual:
    """Отдаёт каждый кусок фразы голосу его языка и склеивает результат. Куски синтезируются параллельно."""

    def __init__(self, name: str, english: Voice, russian: Voice):
        self.name = name
        self.voices = {"en": english, "ru": russian}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"{name}-voice")

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        runs = language_runs(text) or [Run("en", text, text)]
        if len(runs) == 1:
            return self.voices[runs[0].language].synthesize(runs[0].text)
        results = list(self._pool.map(lambda run: self.voices[run.language].synthesize(run.text), runs))
        rate = results[0][1]
        gap = np.zeros(int(rate * _GAP_S), dtype=np.float32)
        pieces: list[np.ndarray] = []
        for samples, sample_rate in results:
            pieces += [resample(samples, sample_rate, rate), gap]
        return np.concatenate(pieces[:-1]), rate


class CloudVoice:
    """Облачный голос OpenRouter (Fish Audio). Понимает теги эмоций: «[excited] Wow!».

    voice_id — голос из библиотеки Fish Audio (fish.audio → Voice Library).
    """

    def __init__(self, client: OpenRouter, voice_id: str, name: str = "cloud"):
        self.client = client
        self.voice_id = voice_id
        self.name = name

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return decode(self.client.speech(text, self.voice_id))


class PiperVoice:
    """Локальный голос на случай, если облако недоступно: быстрый и бесплатный, но без эмоций."""

    def __init__(self, models: LocalModels, voice: str):
        self.models = models
        self.voice = voice
        self.name = f"piper-{voice}"
        self._engine: sherpa_onnx.OfflineTts | None = None
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        text = without_tags(text)  # Piper теги эмоций прочитал бы вслух
        with self._lock:
            audio = self._load().generate(text, sid=0, speed=1.0)
        samples = np.asarray(audio.samples, dtype=np.float32)
        if samples.size == 0:
            raise RuntimeError("Piper вернул тишину (нужен sherpa-onnx<2)")
        return samples, int(audio.sample_rate)

    def _load(self) -> sherpa_onnx.OfflineTts:
        if self._engine is None:
            d = self.models.piper_voice(self.voice)
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(d / f"{self.voice}.onnx"), tokens=str(d / "tokens.txt"),
                        data_dir=str(d / "espeak-ng-data")),
                    num_threads=2))
            self._engine = sherpa_onnx.OfflineTts(config)
        return self._engine


class VoiceChain:
    """Пробует голоса по порядку. Упавший голос отдыхает `cooldown_s` (лимиты бесплатной модели)."""

    def __init__(self, *voices: Voice, cooldown_s: float = 60.0):
        self.voices = voices
        self.cooldown_s = cooldown_s
        self._resting_until: dict[str, float] = {}
        self.last_used = ""

    @property
    def name(self) -> str:
        return "+".join(v.name for v in self.voices)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        errors = []
        for voice in self.voices:
            if time.monotonic() < self._resting_until.get(voice.name, 0):
                continue
            try:
                result = voice.synthesize(text)
                self.last_used = voice.name
                return result
            except Exception as e:  # noqa: BLE001 — любой сбой голоса = пробуем следующий
                log.warning("Голос %s не сработал: %s", voice.name, e)
                errors.append(f"{voice.name}: {e}")
                self._resting_until[voice.name] = time.monotonic() + self.cooldown_s
        raise RuntimeError("; ".join(errors) or "нет доступных голосов")
