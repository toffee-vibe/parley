"""OpenRouter: распознавание речи (/audio/transcriptions) и облачный голос (/audio/speech)."""

from __future__ import annotations

import base64
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import numpy as np

from ..application.ports import Recorder
from ..config import OpenRouterSettings
from ..domain.hearing import RecognitionHints
from .audio.pcm import SAMPLE_RATE, to_wav
from .diary import NullDiary

log = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenRouter:
    name = "openrouter"

    def __init__(self, settings: OpenRouterSettings, diary: Recorder | None = None,
                 hints: Callable[[], RecognitionHints] | None = None):
        self.settings = settings
        self.diary = diary or NullDiary()
        self.hints = hints  # что подсказать распознаванию: выученные слова, последняя реплика Пипа, доска
        self.http = httpx.Client(
            base_url=settings.base_url,
            timeout=httpx.Timeout(30, connect=5),
            headers={"Authorization": f"Bearer {settings.api_key}", "X-Title": "Parley"},
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.api_key)

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        """Основная модель, а если она отказала (лимит запросов, сбой провайдера) — запасная."""
        try:
            return self._transcribe(samples, sample_rate, self.settings.transcription_model)
        except OpenRouterError as e:
            fallback = self.settings.fallback_transcription_model
            if not fallback or fallback == self.settings.transcription_model or e.status in (None, 401, 402):
                raise
            log.info("Распознавание: %s отказала (%s), беру %s", self.settings.transcription_model, e.status, fallback)
            return self._transcribe(samples, sample_rate, fallback)

    def _transcribe(self, samples: np.ndarray, sample_rate: int, model: str) -> str:
        body: dict[str, Any] = {
            "model": model,
            "input_audio": {"data": base64.b64encode(to_wav(samples, sample_rate)).decode(), "format": "wav"},
            "provider": {"sort": "price"},  # одна модель у разных провайдеров стоит по-разному (до ×3)
        }
        static, prompt = self._prompt()
        if prompt:
            body["prompt"] = prompt
        note = {"model": model, "audio_s": round(len(samples) / sample_rate, 2)}
        data = self._post("/audio/transcriptions", body, "stt", note).json()
        text = (data.get("text") or "").strip()
        # Утечку проверяем по постоянной части подсказки: реплику Пипа человек вправе повторить слово в слово
        if static and echoes_prompt(text, static):
            # На тишине и шуме модель иногда возвращает саму подсказку — это не речь человека
            self.diary.record("stt_discarded", text=text[:200], audio_s=note["audio_s"], reason="prompt")
            return ""
        return text

    def _prompt(self) -> tuple[str, str]:
        """(постоянная часть подсказки, вся подсказка). Постоянная — словарь из конфига и выученные слова."""
        base = self.settings.transcription_prompt
        hints = self.hints() if self.hints else None
        if not hints:
            return base, base
        static = "\n".join(p for p in (base, hints.vocabulary()) if p)
        return static, "\n".join(p for p in (static, hints.recent()) if p)[:PROMPT_CHARS]

    def speech(self, text: str, voice_id: str = "") -> bytes:
        """Синтез речи в mp3. voice_id — голос из библиотеки Fish Audio; пусто — голос модели по умолчанию.

        Бесплатная модель даёт 20 запросов в минуту, а смешанная речь — это много коротких кусков. Упёрлись
        в лимит и задана paid_voice_model — тот же кусок тем же голосом платной моделью; иначе Parley уходит
        на минуту на запасной Piper (другой голос)."""
        try:
            return self._speech(text, voice_id, self.settings.voice_model)
        except OpenRouterError as e:
            paid = self.settings.paid_voice_model
            if e.status != 429 or not paid or paid == self.settings.voice_model:
                raise
            log.info("Бесплатный голос упёрся в лимит — этот кусок озвучит %s", paid)
            return self._speech(text, voice_id, paid)

    def _speech(self, text: str, voice_id: str, model: str) -> bytes:
        body: dict[str, Any] = {"model": model, "input": text, "response_format": "mp3", "provider": {"sort": "price"}}
        if voice_id:
            body["voice"] = voice_id
        note = {"model": model, "voice": voice_id, "chars": len(text)}
        return self._post("/audio/speech", body, "tts", note).content

    def _post(self, path: str, body: dict[str, Any], kind: str, note: dict[str, Any]) -> httpx.Response:
        """Запрос + запись в дневник: задержка, цена (если OpenRouter её вернул), ошибка."""
        if not self.configured:
            raise OpenRouterError("Не задан ключ OpenRouter (config.toml или OPENROUTER_API_KEY)")
        started = time.monotonic()
        try:
            resp = self.http.post(path, json=body)
        except httpx.HTTPError as e:
            self.diary.record(kind, **note, ms=_ms(started), error=f"сеть: {e!r}")
            raise OpenRouterError(f"сеть: {e!r}") from e
        if resp.status_code != 200:
            self.diary.record(kind, **note, ms=_ms(started), status=resp.status_code, error=resp.text[:300])
            raise OpenRouterError(f"{path} → {resp.status_code}: {resp.text[:300]}", resp.status_code)
        self.diary.record(kind, **note, ms=_ms(started), provider=resp.headers.get("x-openrouter-provider"),
                          **_usage(resp))
        return resp


PROMPT_CHARS = 1500  # длиннее подсказку модель всё равно обрежет

_WORD = re.compile(r"[\w'-]+")


def echoes_prompt(text: str, prompt: str, n: int = 4) -> bool:
    """Распознанное — пересказ подсказки: больше половины слов идут подряд кусками по n слов из неё."""
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < n:
        return False
    source = [w.lower() for w in _WORD.findall(prompt)]
    grams = {tuple(source[i:i + n]) for i in range(len(source) - n + 1)}
    covered: set[int] = set()
    for i in range(len(words) - n + 1):
        if tuple(words[i:i + n]) in grams:
            covered.update(range(i, i + n))
    return len(covered) >= len(words) / 2


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _usage(resp: httpx.Response) -> dict[str, Any]:
    """Стоимость и токены, если OpenRouter их прислал (у распознавания — в JSON, у голоса — нет)."""
    if not resp.headers.get("content-type", "").startswith("application/json"):
        return {}
    try:
        usage = resp.json().get("usage") or {}
    except ValueError:
        return {}
    return {"cost": usage.get("cost"), "usage": usage} if usage else {}
