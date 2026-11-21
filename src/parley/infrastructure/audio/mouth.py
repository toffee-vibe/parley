"""Рот: очередь реплик, синтез по кускам и воспроизведение с отчётом о прогрессе.

Реплика режется на предложения, а предложения — на куски одного языка (у каждого языка свой голос).
Первый кусок начинает звучать, пока синтезируется второй. Так ответ слышно быстрее,
а при перебивании точнее известно, что человек успел услышать.

Кроме реплик рот умеет короткие отклики «Hmm» (murmurs.py): они идут через ту же очередь,
но не докладываются как реплики — для Claude их нет.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from ...application.ports import SpeechListener
from .murmurs import Murmurs
from .pcm import envelope, normalized
from .pipewire import Playback, Volume
from .voices import Voice, language_runs

log = logging.getLogger(__name__)

TICK_S = 0.05
_MURMUR = "~murmur"  # метка отклика в очереди вместо id реплики
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def pieces(text: str) -> list[tuple[str, str]]:
    """(что синтезировать, этот кусок в исходном тексте) — по предложениям и языкам."""
    result = []
    for sentence in sentences(text):
        result += [(run.text, run.source) for run in language_runs(sentence)] or [(sentence, sentence)]
    return result


class QueuedMouth:
    def __init__(self, voice: Voice, listener: SpeechListener, output: str = "",
                 on_level: Callable[[float], None] = lambda _: None, volume: Volume | None = None,
                 murmurs: Murmurs | None = None):
        self.voice = voice
        self.volume = volume or Volume()
        self.listener = listener
        self.output = output
        self.on_level = on_level
        self.murmurs = murmurs
        self._hushes = 0  # каждый hush() делает все поставленные раньше отклики устаревшими
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._cancelled: set[str] = set()
        self._speaking_id: str | None = None
        self._current: Playback | None = None
        self._synth = ThreadPoolExecutor(max_workers=1, thread_name_prefix="synth")
        threading.Thread(target=self._run, name="mouth", daemon=True).start()

    @property
    def busy(self) -> bool:
        return self._speaking_id is not None or not self._queue.empty()

    def say(self, speech_id: str, text: str) -> None:
        self._queue.put((speech_id, text))

    def murmur(self) -> None:
        if self.murmurs:
            self._queue.put((_MURMUR, str(self._hushes)))

    def hush(self) -> None:
        self._hushes += 1
        if self._speaking_id == _MURMUR and self._current:
            self._current.stop()

    def cancel(self, speech_ids: set[str]) -> None:
        """Не ждёт поток рта: вызывается под блокировкой команд."""
        self._cancelled |= speech_ids
        if self._speaking_id in speech_ids and self._current:
            self._current.stop()

    def close(self) -> None:
        """Выход из программы: замолчать сразу."""
        if self._speaking_id:
            self.cancel({self._speaking_id})

    def _run(self) -> None:
        while True:
            speech_id, text = self._queue.get()
            if speech_id in self._cancelled:
                continue
            if speech_id == _MURMUR:
                if text == str(self._hushes):
                    self._murmur()
                continue
            self._speaking_id = speech_id
            try:
                self._speak(speech_id, text)
            except Exception as e:  # noqa: BLE001
                log.exception("Не удалось озвучить реплику")
                self.listener.broke(speech_id, str(e))
            finally:
                self._speaking_id = None
                self._current = None
                self.on_level(0.0)

    def _murmur(self) -> None:
        clip = self.murmurs.pick() if self.murmurs else None
        if clip is None:
            return
        self._speaking_id = _MURMUR  # busy: уши знают, что это наш собственный голос (эхо)
        try:
            samples = normalized(clip[0])
            levels = envelope(samples, clip[1], TICK_S)
            playback = Playback(samples, clip[1], self.output, self.volume)
            self._current = playback
            while playback.playing:  # громкость нужна защите от эха, иначе свой «Hmm» сочтётся перебиванием
                self.on_level(levels[min(int(playback.elapsed / TICK_S), len(levels) - 1)] if levels else 0.0)
                time.sleep(TICK_S)
            playback.wait()
        except Exception:
            log.exception("Отклик не прозвучал")
        finally:
            self._speaking_id = None
            self._current = None
            self.on_level(0.0)

    def _speak(self, speech_id: str, text: str) -> None:
        parts = pieces(text)
        upcoming: Future = self._synth.submit(self.voice.synthesize, parts[0][0])
        offset = 0  # сколько символов реплики уже прозвучало до текущего куска
        for i, (_, part) in enumerate(parts):
            samples, rate = upcoming.result()
            if i + 1 < len(parts):
                upcoming = self._synth.submit(self.voice.synthesize, parts[i + 1][0])
            if speech_id in self._cancelled:
                return  # отменили, пока синтезировали
            if i == 0:
                self.listener.began(speech_id)
            self._play(speech_id, samples, rate, offset, part)
            if speech_id in self._cancelled:
                return
            offset += len(part) + 1
        self.listener.ended(speech_id)

    def _play(self, speech_id: str, samples, rate: int, offset: int, part: str) -> None:
        samples = normalized(samples)
        levels = envelope(samples, rate, TICK_S)
        playback = Playback(samples, rate, self.output, self.volume)
        self._current = playback
        while playback.playing and speech_id not in self._cancelled:
            elapsed = playback.elapsed
            self.on_level(levels[min(int(elapsed / TICK_S), len(levels) - 1)] if levels else 0.0)
            heard = int(len(part) * elapsed / playback.duration) if playback.duration else len(part)
            self.listener.progressed(speech_id, offset + heard)
            time.sleep(TICK_S)
        playback.stop()
        playback.wait()
