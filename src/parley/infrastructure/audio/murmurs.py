"""«Hmm», «Right», «I see» — короткие отклики, пока Claude думает над ответом.

Синтезируются один раз тем же английским голосом, что и реплики, и лежат на диске
(~/.local/share/parley/murmurs/), поэтому звучат мгновенно и бесплатно. Готовятся в фоне при запуске:
пока не готовы — Пип просто молчит, как раньше.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
from pathlib import Path

import numpy as np

from .voices import Voice

log = logging.getLogger(__name__)

# Нейтральные: подходят и к шутке, и к грустному рассказу, и к ответу на вопрос собеседования.
MURMURS = ("Hmm.", "Mm-hm.", "Right.", "Okay.", "I see.", "Uh-huh.", "Got it.", "Hmm, okay.")
MAX_S = 1.8  # голос иногда «додумывает» лишнее — длинное не берём


class Murmurs:
    def __init__(self, voice: Voice, folder: Path, voice_key: str, texts: tuple[str, ...] = MURMURS):
        self.voice = voice
        self.folder = folder
        self.voice_key = voice_key  # другой голос в конфиге — другие файлы
        self.texts = texts
        self._clips: list[tuple[np.ndarray, int]] = []
        self._last = -1
        self._lock = threading.Lock()

    def prepare_in_background(self) -> None:
        threading.Thread(target=self._prepare, name="murmurs", daemon=True).start()

    def pick(self) -> tuple[np.ndarray, int] | None:
        """Случайный отклик, но не тот же, что в прошлый раз."""
        with self._lock:
            if not self._clips:
                return None
            choices = [i for i in range(len(self._clips)) if i != self._last] or [0]
            self._last = random.choice(choices)
            return self._clips[self._last]

    def _prepare(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for text in self.texts:
            try:
                clip = self._load(text)
            except Exception as e:  # noqa: BLE001 — без отклика можно жить
                log.info("Отклик «%s» не готов: %s", text, e)
                continue
            if clip is not None:
                with self._lock:
                    self._clips.append(clip)

    def _load(self, text: str) -> tuple[np.ndarray, int] | None:
        path = self.folder / f"{hashlib.sha1(f'{self.voice_key}|{text}'.encode()).hexdigest()[:16]}.npz"
        if path.exists():
            data = np.load(path)
            return data["samples"], int(data["rate"])
        samples, rate = self.voice.synthesize(text)
        if len(samples) / rate > MAX_S:
            log.info("Отклик «%s» вышел длинным (%.1f с) — пропускаю", text, len(samples) / rate)
            return None
        np.savez(path, samples=samples.astype(np.float32), rate=rate)
        return samples, rate
