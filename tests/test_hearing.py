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


def test_prompt_leak_is_not_taken_for_speech():
    from parley.config import OpenRouterSettings
    from parley.infrastructure.openrouter import echoes_prompt

    prompt = OpenRouterSettings().transcription_prompt
    leaks = [  # дословно из дневника: модель вернула подсказку на тишине
        "English speaking practice with Parley (Pip). The speaker is Russian and mixes English and Russian: "
        "keep every word in the language it was spoken, do not translate.",
        "Python, backend, PostgreSQL, FastAPI, Docker, deploy.",
        "English speaking practice with Parley, Pip. The speaker is Russian and mixes English and Russian. "
        "Keep every word in the language it was spoken. Do not translate.",
    ]
    assert all(echoes_prompt(t, prompt) for t in leaks)
    real = ["I worked with Python and PostgreSQL on the backend", "Так, ну, давай начнем с времен на английском.",
            "I made it.", "Do not translate this sentence, just tell me what it means"]
    assert not any(echoes_prompt(t, prompt) for t in real)


def test_rate_limited_free_voice_is_replaced_by_the_same_voice_paid(monkeypatch):
    client = OpenRouter(OpenRouterSettings(api_key="k", voice_model="fish:free", paid_voice_model="fish"))
    used = []

    def fake(text, voice_id, model):
        used.append((model, voice_id))
        if model == "fish:free":
            raise OpenRouterError("429", 429)
        return b"mp3"

    monkeypatch.setattr(client, "_speech", fake)
    assert client.speech("Привет", "ru-voice") == b"mp3"
    assert used == [("fish:free", "ru-voice"), ("fish", "ru-voice")]  # тот же голос, не Piper


def test_without_paid_model_rate_limit_goes_to_piper(monkeypatch):
    client = OpenRouter(OpenRouterSettings(api_key="k", voice_model="fish:free"))
    monkeypatch.setattr(client, "_speech", lambda *a: (_ for _ in ()).throw(OpenRouterError("429", 429)))
    try:
        client.speech("Привет", "ru-voice")
    except OpenRouterError as e:
        assert e.status == 429  # VoiceChain возьмёт Piper
    else:
        raise AssertionError("без платной модели — ошибка, а не тихая трата денег")
