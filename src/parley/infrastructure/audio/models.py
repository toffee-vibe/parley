"""Локальные модели: скачиваются один раз в ~/.local/share/parley/models."""

from __future__ import annotations

import logging
import tarfile
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SOUND_TAGGER = "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"


class LocalModels:
    def __init__(self, directory: Path):
        self.dir = directory

    def silero_vad(self) -> Path:
        path = self.dir / "silero_vad.onnx"
        if not path.exists():
            _download(f"{SHERPA}/asr-models/silero_vad.onnx", path)
        return path

    def sound_tagger(self) -> Path:
        """Классификатор звуков AudioSet (527 классов): смех, кашель, музыка, клавиатура…"""
        return self._archive(SOUND_TAGGER, f"{SHERPA}/audio-tagging-models/{SOUND_TAGGER}.tar.bz2")

    def piper_voice(self, voice: str) -> Path:
        name = f"vits-piper-{voice}"
        return self._archive(name, f"{SHERPA}/tts-models/{name}.tar.bz2")

    def _archive(self, name: str, url: str) -> Path:
        directory = self.dir / name
        if not directory.exists():
            archive = self.dir / f"{name}.tar.bz2"
            _download(url, archive)
            with tarfile.open(archive) as tar:
                tar.extractall(self.dir, filter="data")
            archive.unlink()
        return directory


def _download(url: str, dest: Path) -> None:
    log.info("Скачиваю %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # httpx, а не urllib: у Python от uv на NixOS нет системных сертификатов, а httpx берёт certifi.
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes(1 << 20):
                tmp.write(chunk)
    Path(tmp.name).rename(dest)
