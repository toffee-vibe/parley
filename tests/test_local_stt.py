"""Встроенное распознавание: выбор облако/локально и подстраховка. Без самой модели (она ~500 МБ)."""

import numpy as np
import pytest

from parley.bootstrap import stt_engine, transcriber
from parley.config import Settings
from parley.infrastructure.audio.local_stt import FirstThatWorks, LocalTranscriber
from parley.infrastructure.audio.models import LocalModels
from parley.infrastructure.diary import NullDiary
from parley.infrastructure.openrouter import OpenRouter


class Fixed:
    def __init__(self, name, text=None):
        self.name, self.text = name, text

    def transcribe(self, samples, sample_rate=16000):
        if self.text is None:
            raise RuntimeError("нет сети")
        return self.text


def test_auto_uses_cloud_only_with_a_key():
    settings = Settings()
    assert stt_engine(settings) == "local"            # без ключа Parley всё равно слышит
    settings.openrouter.api_key = "k"
    assert stt_engine(settings) == "cloud"
    settings.transcription.engine = "local"
    assert stt_engine(settings) == "local"            # можно и с ключом


def test_cloud_failure_falls_back_to_local():
    assert FirstThatWorks(Fixed("cloud"), Fixed("local", "hello")).transcribe(np.zeros(160)) == "hello"
    assert FirstThatWorks(Fixed("cloud", "hi"), Fixed("local", "hello")).transcribe(np.zeros(160)) == "hi"


def test_fallback_never_downloads_mid_conversation(tmp_path):
    local = LocalTranscriber(LocalModels(tmp_path), "parakeet", download=False)
    with pytest.raises(FileNotFoundError):
        local.transcribe(np.zeros(1600, np.float32))
    assert not any(tmp_path.iterdir())                # ничего не скачивалось


def test_cloud_mode_is_backed_by_local_model(tmp_path):
    settings = Settings()
    settings.openrouter.api_key = "k"
    chain = transcriber(settings, OpenRouter(settings.openrouter), LocalModels(tmp_path), NullDiary())
    assert chain.name == "openrouter+local/parakeet"


def test_unknown_local_model_is_explained(tmp_path):
    with pytest.raises(ValueError, match="parakeet"):
        LocalModels(tmp_path).speech_recognizer("vosk")
