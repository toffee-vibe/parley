"""Распознавание: запасная модель при отказе и отсев выдуманных фраз. Без сети и микрофона."""

import numpy as np

from parley.config import OpenRouterSettings
from parley.infrastructure.audio.ears import _imagined
from parley.infrastructure.openrouter import OpenRouter, OpenRouterError


def test_two_words_on_long_noise_are_imagined():
    assert _imagined("Okay.", duration=15.7)          # шум на 15 секунд — это не речь
    assert _imagined("Thank you.", duration=12.9)
    assert _imagined("Продолжение следует...", duration=3)
    assert not _imagined("Right.", duration=1.0)      # короткий настоящий ответ
    assert not _imagined("I worked on data pipelines", duration=3.0)


def test_rate_limit_falls_back_to_second_model(monkeypatch):
    client = OpenRouter(OpenRouterSettings(api_key="k", transcription_model="main", fallback_transcription_model="spare"))
    used = []

    def fake(samples, rate, model):
        used.append(model)
        if model == "main":
            raise OpenRouterError("429", 429)
        return "hello"

    monkeypatch.setattr(client, "_transcribe", fake)
    assert client.transcribe(np.zeros(160, np.float32)) == "hello"
    assert used == ["main", "spare"]


def test_bad_key_is_not_hidden_by_fallback(monkeypatch):
    client = OpenRouter(OpenRouterSettings(api_key="k", transcription_model="main", fallback_transcription_model="spare"))

    def fake(samples, rate, model):
        raise OpenRouterError("401", 401)

    monkeypatch.setattr(client, "_transcribe", fake)
    try:
        client.transcribe(np.zeros(160, np.float32))
    except OpenRouterError as e:
        assert e.status == 401
    else:
        raise AssertionError("ошибка ключа должна дойти до пользователя")
