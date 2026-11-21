"""Преобразования звука: float32 ⇄ WAV/PCM, декодирование чего угодно через ffmpeg."""

from __future__ import annotations

import io
import subprocess
import wave

import numpy as np

SAMPLE_RATE = 16000  # микрофон, детектор речи и распознавание работают на 16 кГц


def to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(to_s16(samples))
    return buf.getvalue()


def to_s16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()


def from_s16(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def decode(data: bytes, sample_rate: int = 24000) -> tuple[np.ndarray, int]:
    """WAV читаем сами, остальное (mp3, ogg, …) — через ffmpeg."""
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data)) as w:
            raw = w.readframes(w.getnframes())
            samples = from_s16(raw)
            if w.getnchannels() > 1:
                samples = samples.reshape(-1, w.getnchannels()).mean(axis=1)
            return samples, w.getframerate()
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "pipe:1"],
        input=data, capture_output=True, check=True)
    return from_s16(result.stdout), sample_rate


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0


def envelope(samples: np.ndarray, sample_rate: int, step_s: float = 0.05) -> list[float]:
    """Громкость по кусочкам — чтобы персонаж открывал рот в такт речи."""
    step = max(int(sample_rate * step_s), 1)
    return [rms(samples[i:i + step]) for i in range(0, len(samples), step)]


def resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    """Линейная интерполяция — для склейки кусков речи достаточно."""
    if rate == target or samples.size == 0:
        return samples
    positions = np.arange(int(len(samples) * target / rate)) * rate / target
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


def normalized(samples: np.ndarray, target_rms: float = 0.07, peak: float = 0.95) -> np.ndarray:
    """Одинаковая громкость у всех голосов: разные модели и голоса звучат очень по-разному."""
    level = rms(samples)
    if level < 1e-4:
        return samples
    gain = min(target_rms / level, peak / float(np.max(np.abs(samples))))
    return (samples * gain).astype(np.float32)
