"""Настоящий pw-play (только где он есть): оборванная фраза не оставляет ошибок. Громкость 0 — не слышно."""

import gc
import shutil
import sys
import time

import numpy as np
import pytest

from parley.infrastructure.audio.devices import Volume

pytestmark = pytest.mark.skipif(not shutil.which("pw-play"), reason="нужен PipeWire")


def test_interrupted_phrase_leaves_no_broken_pipe(monkeypatch):
    from parley.infrastructure.audio.pipewire import Playback

    errors = []
    monkeypatch.setattr(sys, "unraisablehook", lambda args: errors.append(args.exc_value))
    for _ in range(3):
        playback = Playback(np.random.uniform(-0.1, 0.1, 24000 * 3).astype(np.float32), 24000, volume=Volume(0.0))
        time.sleep(0.3)
        playback.stop()      # ты перебил Пипа
        playback.wait()
        del playback
        gc.collect()
    assert errors == []
