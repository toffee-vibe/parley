"""Уши: микрофон → детектор речи → распознавание; параллельно — детектор звуков.

Поток микрофона только режет звук и ничего не ждёт; распознавание идёт в отдельном потоке
строго по очереди, чтобы фразы приходили Claude в том порядке, в котором сказаны.

Защита от эха: пока персонаж говорит в колонки, микрофон слышит его самого. `_EchoGuard` сам
измеряет, насколько громко эхо доходит до микрофона (в первую секунду каждой реплики, когда
человек обычно молчит), и засчитывает «человек заговорил» только если микрофон заметно громче
ожидаемого эха. В наушниках эха нет — перебивание срабатывает от обычного голоса.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
import sherpa_onnx

from ...application.ports import HearingListener
from ...config import HearingSettings
from ...domain.conversation import Utterance
from .models import LocalModels
from .pcm import SAMPLE_RATE, rms
from .pipewire import CHUNK, Microphone

log = logging.getLogger(__name__)

PRE_ROLL_S = 0.3           # детектор срабатывает с опозданием — добавляем звук перед началом фразы
BARGE_IN_S = 0.3           # сколько надо говорить громче эха, чтобы перебить персонажа
LOST_VOICE_S = 1.5         # речь началась, но фразы так и не получилось — считаем шумом
SOUND_WINDOW_S = 1.0
SOUND_EVERY_S = 0.5
SOUND_MIN_RMS = 0.01

# На тишине и шуме распознавание иногда «слышит» дежурные фразы из субтитров.
HALLUCINATIONS = {
    "thank you", "thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.",
    "продолжение следует...", "субтитры сделал dimatorzok", "спасибо за просмотр!", "спасибо.",
}

# Классы AudioSet, о которых Claude знать не нужно: речь распознаётся отдельно, фон — неинтересен.
BORING_SOUNDS = {
    "Speech", "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking",
    "Conversation", "Narration, monologue", "Silence", "Inside, small room", "Inside, large room or hall",
    "Outside, urban or manmade", "Outside, rural or natural", "Static", "Hum", "White noise", "Pink noise",
    "Noise", "Environmental noise", "Mains hum", "Speech synthesizer", "Echo", "Reverberation",
    # слишком общие «родители»: вместо них придёт конкретный класс (Cat, Dog, Car…)
    "Animal", "Domestic animals, pets", "Wild animals", "Vehicle", "Sound effect", "Inside, public space",
}


class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str: ...


class MicrophoneEars:
    def __init__(self, settings: HearingSettings, models: LocalModels, transcriber: Transcriber,
                 listener: HearingListener, companion_speaking: Callable[[], bool],
                 voice_level: Callable[[], float] = lambda: 0.0,
                 on_level: Callable[[float], None] = lambda _: None):
        self.settings = settings
        self.transcriber = transcriber
        self.listener = listener
        self.companion_speaking = companion_speaking
        self.on_level = on_level
        self._echo = _EchoGuard(settings.echo_margin, voice_level)
        self._vad = _SpeechDetector(models.silero_vad(), settings)
        self._sounds = _SoundDetector(models, settings) if settings.sounds else None
        self._microphone = Microphone(settings.input, self._on_chunk)
        self._transcribing = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcribe")
        self._voice_reported = False   # сообщили ли приложению, что пользователь заговорил
        self._voice_since: float | None = None
        self._loud_s = 0.0             # сколько подряд звук громче порога перебивания
        self._last_sound_check = 0.0
        self._recent: deque[np.ndarray] = deque(maxlen=int(SOUND_WINDOW_S * SAMPLE_RATE / CHUNK))

    # --- порт Ears ---

    def open(self) -> None:
        self._vad.reset()
        self._microphone.start()

    def close(self) -> None:
        self._microphone.stop()
        self._voice_reported = False
        self._voice_since = None
        self.on_level(0.0)

    # --- поток микрофона ---

    def _on_chunk(self, chunk: np.ndarray) -> None:
        level = rms(chunk)
        self.on_level(level)
        self._echo.observe(level, self.companion_speaking())
        self._recent.append(chunk)
        speaking_now = self._vad.feed(chunk)
        self._track_voice(speaking_now, level)
        for segment in self._vad.segments():
            self._finish_phrase(segment)
        # Звуки слушаем и во время речи: смех и кашель детектор речи часто принимает за голос.
        self._maybe_notice_sound()

    def _track_voice(self, speaking_now: bool, level: float) -> None:
        now = time.monotonic()
        if not speaking_now:
            self._loud_s = 0.0
            if self._voice_reported and self._voice_since and now - self._voice_since > LOST_VOICE_S \
                    and not self._vad.has_pending():
                self._voice_reported = False
                self.listener.voice_finished(None)
            return
        self._voice_since = now
        if self._voice_reported:
            return
        if self.companion_speaking():
            self._loud_s = self._loud_s + CHUNK / SAMPLE_RATE if self._echo.louder_than_echo(level) else 0.0
            if self._loud_s < BARGE_IN_S:
                return  # скорее всего, это эхо собственного голоса
        self._voice_reported = True
        self.listener.voice_started()

    def _finish_phrase(self, segment: np.ndarray) -> None:
        if not self._voice_reported:
            return  # фраза целиком была эхом или шумом во время речи персонажа
        self._voice_reported = False
        started = datetime.now().astimezone() - timedelta(seconds=len(segment) / SAMPLE_RATE)
        self._transcribing.submit(self._transcribe, segment, started)

    def _transcribe(self, segment: np.ndarray, started: datetime) -> None:
        duration = len(segment) / SAMPLE_RATE
        try:
            text = self.transcriber.transcribe(segment)
        except Exception as e:  # noqa: BLE001
            log.warning("Распознавание не удалось: %s", e)
            self.listener.voice_finished(None)
            return
        if _imagined(text, duration):
            text = ""
        self.listener.voice_finished(Utterance(text, started, duration) if text else None)

    def _maybe_notice_sound(self) -> None:
        now = time.monotonic()
        if not self._sounds or now - self._last_sound_check < SOUND_EVERY_S or self.companion_speaking():
            return
        self._last_sound_check = now
        window = np.concatenate(self._recent) if self._recent else np.zeros(0, np.float32)
        if rms(window) < SOUND_MIN_RMS:
            return
        for label, confidence in self._sounds.detect(window):
            self.listener.sound(label, confidence)


def _imagined(text: str, duration: float) -> bool:
    """Выдуманная фраза: дежурная фраза из субтитров или пара слов на долгом шуме («Okay.» на 15 секундах)."""
    words = len(text.split())
    return text.lower().strip() in HALLUCINATIONS or (0 < words <= 3 and words / max(duration, 0.1) < 0.4)


class _EchoGuard:
    """Сколько собственного голоса персонажа доходит до микрофона (отношение громкостей).

    Меряем в первую секунду каждой реплики: человек обычно ещё молчит. Отношение копится
    плавно между репликами, потому что путь «колонки → микрофон» почти не меняется.
    """

    CALIBRATE_S = 1.0
    MIN_RMS = 0.012  # тише этого голос человека не засчитываем никогда

    def __init__(self, margin: float, voice_level: Callable[[], float]):
        self.margin = margin
        self.voice_level = voice_level
        self.ratio = 0.5           # начальная осторожная догадка: эхо вдвое тише голоса
        self._speaking_since: float | None = None

    def observe(self, mic_level: float, companion_speaking: bool) -> None:
        now = time.monotonic()
        if not companion_speaking:
            self._speaking_since = None
            return
        if self._speaking_since is None:
            self._speaking_since = now
        voice = self.voice_level()
        if now - self._speaking_since < self.CALIBRATE_S and voice > 0.005:
            self.ratio = self.ratio * 0.9 + min(mic_level / voice, 5.0) * 0.1

    def louder_than_echo(self, mic_level: float) -> bool:
        expected_echo = self.ratio * self.voice_level()
        return mic_level >= max(self.MIN_RMS, self.margin * expected_echo)


class _SpeechDetector:
    """Silero VAD через sherpa-onnx: говорит ли человек сейчас и какие фразы закончились."""

    def __init__(self, model_path, settings: HearingSettings):
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(model_path)
        config.silero_vad.threshold = settings.vad_threshold
        config.silero_vad.min_silence_duration = settings.end_of_phrase_s
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.max_speech_duration = 30
        config.sample_rate = SAMPLE_RATE
        self._config = config
        self._history: deque[np.ndarray] = deque(maxlen=int(40 * SAMPLE_RATE / CHUNK))
        self._fed = 0
        self.reset()

    def reset(self) -> None:
        self._vad = sherpa_onnx.VoiceActivityDetector(self._config, buffer_size_in_seconds=40)
        self._history.clear()
        self._fed = 0

    def feed(self, chunk: np.ndarray) -> bool:
        self._vad.accept_waveform(chunk)
        self._history.append(chunk)
        self._fed += len(chunk)
        return bool(self._vad.is_speech_detected())

    def has_pending(self) -> bool:
        return not self._vad.empty()

    def segments(self) -> list[np.ndarray]:
        out = []
        while not self._vad.empty():
            segment = self._vad.front
            out.append(np.concatenate([self._before(segment.start), np.asarray(segment.samples, np.float32)]))
            self._vad.pop()
        return out

    def _before(self, start: int) -> np.ndarray:
        """Кусочек звука перед фразой: детектор «съедает» первый слог."""
        history = np.concatenate(self._history) if self._history else np.zeros(0, np.float32)
        first = self._fed - len(history)  # номер первого отсчёта в истории
        lo = max(start - int(PRE_ROLL_S * SAMPLE_RATE), first)
        return history[lo - first:max(start - first, 0)]


class _SoundDetector:
    """Классификатор звуков AudioSet. Отдаёт только заметные и не повторявшиеся недавно."""

    def __init__(self, models: LocalModels, settings: HearingSettings):
        d = models.sound_tagger()
        self._tagger = sherpa_onnx.AudioTagging(sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(ced=str(d / "model.int8.onnx"), num_threads=1),
            labels=str(d / "class_labels_indices.csv"), top_k=3))
        self._threshold = settings.sound_threshold
        self._cooldown = settings.sound_cooldown_s
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def detect(self, window: np.ndarray) -> list[tuple[str, float]]:
        with self._lock:
            stream = self._tagger.create_stream()
            stream.accept_waveform(SAMPLE_RATE, window)
            events = self._tagger.compute(stream)
        # Берём один самый уверенный класс: иначе на мяуканье придут «Cat», «Animal» и «Meow» разом.
        candidates = [e for e in events if e.prob >= self._threshold and e.name not in BORING_SOUNDS]
        if not candidates:
            return []
        best = max(candidates, key=lambda e: e.prob)
        now = time.monotonic()
        if now - self._last_seen.get(best.name, -1e9) < self._cooldown:
            return []
        self._last_seen[best.name] = now
        return [(best.name, float(best.prob))]
