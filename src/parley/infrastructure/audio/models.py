"""Локальные модели: скачиваются один раз в ~/.local/share/parley/models."""

from __future__ import annotations

import logging
import tarfile
import tempfile
import threading
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SOUND_TAGGER = "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
# Встроенное распознавание речи (local_stt.py): имя в конфиге → архив sherpa-onnx
SPEECH_MODELS = {
    "parakeet": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    "whisper-turbo": "sherpa-onnx-whisper-turbo",
}


class LocalModels:
    def __init__(self, directory: Path):
        self.dir = directory
        self._lock = threading.RLock()

    def silero_vad(self) -> Path:
        path = self.dir / "silero_vad.onnx"
        if not path.exists():
            _download(f"{SHERPA}/asr-models/silero_vad.onnx", path)
        return path

    def sound_tagger(self) -> Path:
        """Классификатор звуков AudioSet (527 классов): смех, кашель, музыка, клавиатура…"""
        return self._archive(SOUND_TAGGER, f"{SHERPA}/audio-tagging-models/{SOUND_TAGGER}.tar.bz2")

    def speech_recognizer(self, name: str, download: bool = True) -> Path:
        """Модель распознавания речи (~500 МБ): parakeet или whisper-turbo.
        download=False — только если уже скачана (запасной вариант не должен качать посреди разговора)."""
        if name not in SPEECH_MODELS:
            raise ValueError(f"Нет встроенной модели «{name}»; есть: {', '.join(SPEECH_MODELS)}")
        archive = SPEECH_MODELS[name]
        if not download and not (self.dir / archive).exists():
            raise FileNotFoundError(f"встроенная модель {name} не скачана")
        return self._archive(archive, f"{SHERPA}/asr-models/{archive}.tar.bz2")

    def piper_voice(self, voice: str) -> Path:
        name = f"vits-piper-{voice}"
        return self._archive(name, f"{SHERPA}/tts-models/{name}.tar.bz2")

    def _archive(self, name: str, url: str) -> Path:
        """Скачать и распаковать один раз. Под блокировкой: модель могут попросить два потока сразу.
        Распаковка — во временную папку: прерванная загрузка не оставит полупустую модель."""
        directory = self.dir / name
        with self._lock:
            if not directory.exists():
                archive = self.dir / f"{name}.tar.bz2"
                _download(url, archive)
                with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
                    with tarfile.open(archive) as tar:
                        tar.extractall(tmp, filter="data")
                    (Path(tmp) / name).rename(directory)
                archive.unlink()
        return directory


def _download(url: str, dest: Path) -> None:
    log.info("Скачиваю %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # httpx, а не urllib: у Python от uv на NixOS нет системных сертификатов, а httpx берёт certifi.
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(1 << 20):
                    tmp.write(chunk)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)  # оборванная загрузка не должна копиться на диске
            raise
    Path(tmp.name).rename(dest)
