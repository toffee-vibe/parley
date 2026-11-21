"""OpenRouter: распознавание речи (/audio/transcriptions) и облачный голос (/audio/speech)."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
import numpy as np

from ..application.ports import Recorder
from ..config import OpenRouterSettings
from .audio.pcm import SAMPLE_RATE, to_wav
from .diary import NullDiary

log = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class OpenRouter:
    name = "openrouter"

    def __init__(self, settings: OpenRouterSettings, diary: Recorder | None = None):
        self.settings = settings
        self.diary = diary or NullDiary()
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
        if self.settings.transcription_prompt:
            body["prompt"] = self.settings.transcription_prompt
        note = {"model": model, "audio_s": round(len(samples) / sample_rate, 2)}
        data = self._post("/audio/transcriptions", body, "stt", note).json()
        return (data.get("text") or "").strip()

    def speech(self, text: str, voice_id: str = "") -> bytes:
        """Синтез речи в mp3. voice_id — голос из библиотеки Fish Audio; пусто — голос модели по умолчанию."""
        body: dict[str, Any] = {"model": self.settings.voice_model, "input": text, "response_format": "mp3",
                                "provider": {"sort": "price"}}
        if voice_id:
            body["voice"] = voice_id
        note = {"model": self.settings.voice_model, "voice": voice_id, "chars": len(text)}
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
