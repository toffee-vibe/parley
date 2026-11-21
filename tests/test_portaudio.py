"""Звук на Windows/macOS (PortAudio): пересчёт частоты, нарезка микрофона, плеер. Без настоящих устройств."""

import sys
import threading
import time
import types

import numpy as np
import pytest

from parley.infrastructure.audio import devices, portaudio
from parley.infrastructure.audio.devices import CHUNK, Volume
from parley.infrastructure.audio.portaudio import _Resampler


def test_resampler_keeps_length_and_shape_across_blocks():
    rate = 44100                         # некратная частота — самый неудобный случай
    t = np.arange(rate * 2) / rate
    tone = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    resample = _Resampler(rate, 16000)
    pieces = [resample(tone[i:i + 441]) for i in range(0, len(tone), 441)]  # куски по 10 мс
    out = np.concatenate(pieces)
    assert abs(len(out) - 32000) <= 1    # ровно 2 секунды при 16 кГц, без дрейфа
    expected = np.sin(2 * np.pi * 440 * np.arange(len(out)) / 16000)
    assert np.max(np.abs(out - expected)) < 0.05  # без щелчков на стыках кусков


class FakePortAudio(types.SimpleNamespace):
    """Поддельный sounddevice: 16 кГц не умеет, родная частота 48 кГц."""

    class PortAudioError(Exception):
        pass

    class CallbackStop(Exception):
        pass

    def __init__(self):
        super().__init__(opened=[])

    def query_devices(self, device=None, kind=None):
        if device not in (None, "USB headset"):
            raise ValueError(device)
        return {"name": device or "default", "default_samplerate": 48000.0}

    def InputStream(self, samplerate, callback, **kw):  # noqa: N802
        if samplerate != 48000:
            raise self.PortAudioError("Invalid sample rate")
        self.opened.append(("in", samplerate, kw.get("device")))
        fake = self

        class Stream:
            def __enter__(self):
                block = np.full((480, 1), 0.5, np.float32)  # 10 мс при 48 кГц
                for _ in range(20):
                    callback(block, 480, None, None)
                return self

            def __exit__(self, *exc):
                fake.closed = True

        return Stream()

    def OutputStream(self, samplerate, callback, finished_callback, **kw):  # noqa: N802
        if samplerate != 48000:
            raise self.PortAudioError("Invalid sample rate")
        self.opened.append(("out", samplerate, kw.get("device")))
        fake = self

        class Stream:
            def start(self):
                def run():
                    out = np.zeros((1024, 1), np.float32)
                    try:
                        while True:
                            callback(out, 1024, None, None)
                            fake.played.append(out[:, 0].copy())
                    except FakePortAudio.CallbackStop:
                        fake.played.append(out[:, 0].copy())
                    finished_callback()
                threading.Thread(target=run, daemon=True).start()

            def abort(self):
                finished_callback()

            def close(self):
                pass

        self.played = []
        return Stream()


@pytest.fixture
def fake_sd(monkeypatch):
    fake = FakePortAudio()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def test_microphone_falls_back_to_native_rate_and_gives_16k_chunks(fake_sd):
    chunks = []
    mic = portaudio.Microphone("USB headset", chunks.append)
    mic.start()
    deadline = time.monotonic() + 2
    while len(chunks) < 6 and time.monotonic() < deadline:
        time.sleep(0.01)
    mic.stop()
    assert fake_sd.opened[0] == ("in", 48000, "USB headset")
    assert len(chunks) == 6                                   # 200 мс при 16 кГц = 3200 отсчётов = 6 кусков
    assert all(len(c) == CHUNK for c in chunks)
    assert np.allclose(chunks[-1], 0.5, atol=1e-3)


def test_playback_resamples_applies_volume_and_reports_end(fake_sd):
    samples = np.ones(24000, np.float32)                      # 1 с при 24 кГц (как у облачного голоса)
    playback = portaudio.Playback(samples, 24000, "nonexistent device", Volume(0.5))
    playback.wait()
    assert not playback.playing
    assert fake_sd.opened == [("out", 48000, None)]           # нет такого устройства — по умолчанию, 48 кГц
    played = np.concatenate(fake_sd.played)
    assert np.isclose(played[:47000], 0.25).all()             # громкость 0.5 → множитель 0.25
    assert np.count_nonzero(played) in range(47990, 48010)    # ровно секунда звука, дальше тишина


def test_backend_choice(monkeypatch):
    devices.backend.cache_clear()
    monkeypatch.setenv("PARLEY_AUDIO", "portaudio")
    assert devices.backend() == "portaudio"
    devices.backend.cache_clear()
    monkeypatch.delenv("PARLEY_AUDIO")
    monkeypatch.setattr(devices.sys, "platform", "win32")
    assert devices.backend() == "portaudio"
    devices.backend.cache_clear()
