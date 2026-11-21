"""Рот без колонок: настоящая очередь и синтез по предложениям, поддельное воспроизведение."""

import time

import numpy as np

from parley.infrastructure.audio import mouth as mouth_module
from parley.infrastructure.audio.mouth import QueuedMouth, sentences
from parley.infrastructure.audio.voices import language_runs


class FakePlayback:
    def __init__(self, samples, rate, target="", volume=None):
        self.duration = len(samples) / rate
        self._started = time.monotonic()
        self._stopped = False

    @property
    def elapsed(self):
        return min(time.monotonic() - self._started, self.duration)

    @property
    def playing(self):
        return not self._stopped and time.monotonic() - self._started < self.duration

    def stop(self):
        self._stopped = True

    def wait(self):
        pass


class FakeVoice:
    name = "fake"

    def synthesize(self, text):
        return np.zeros(int(16000 * 0.2), np.float32), 16000


class Recorder:
    def __init__(self):
        self.log = []

    def began(self, sid):
        self.log.append(("began", sid))

    def progressed(self, sid, chars):
        self.log.append(("progress", chars))

    def ended(self, sid):
        self.log.append(("ended", sid))

    def broke(self, sid, reason):
        self.log.append(("broke", reason))


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_sentences():
    assert sentences("Hi! How are you? Fine.") == ["Hi!", "How are you?", "Fine."]


def test_speaks_all_sentences_and_reports_progress(monkeypatch):
    monkeypatch.setattr(mouth_module, "Playback", FakePlayback)
    listener = Recorder()
    mouth = QueuedMouth(FakeVoice(), listener)
    mouth.say("s1", "First sentence. Second one.")
    wait_until(lambda: ("ended", "s1") in listener.log)
    assert listener.log[0] == ("began", "s1")
    progress = [c for kind, c in listener.log if kind == "progress"]
    assert progress == sorted(progress) and progress[-1] > len("First sentence.")
    assert not mouth.busy


def test_silence_cuts_speech_without_ending_it(monkeypatch):
    monkeypatch.setattr(mouth_module, "Playback", FakePlayback)
    listener = Recorder()
    mouth = QueuedMouth(FakeVoice(), listener)
    mouth.say("s1", "One. Two. Three. Four.")
    mouth.say("s2", "Queued and dropped.")
    wait_until(lambda: ("began", "s1") in listener.log)
    mouth.cancel({"s1", "s2"})
    time.sleep(0.5)
    assert ("ended", "s1") not in listener.log
    assert ("began", "s2") not in listener.log


def test_phrase_is_split_by_language_so_each_gets_a_native_voice():
    runs = language_runs("[warm] Тут нужен «Present Perfect», потому что ты ещё там работаешь.")
    assert [r.language for r in runs] == ["ru", "en", "ru"]
    assert runs[1].source == "«Present Perfect»,"
    assert all(r.text.startswith("[warm]") for r in runs)  # эмоция действует на всю фразу


def test_english_sentence_stays_whole():
    runs = language_runs("[excited] Oh, nice! So you've been working there for three years?")
    assert len(runs) == 1 and runs[0].language == "en"


def test_mouth_speaks_language_pieces_and_counts_progress_in_original_text(monkeypatch):
    monkeypatch.setattr(mouth_module, "Playback", FakePlayback)
    listener = Recorder()
    text = "[warm] Скажи «I've been working». Отлично!"
    mouth = QueuedMouth(FakeVoice(), listener)
    mouth.say("s1", text)
    wait_until(lambda: ("ended", "s1") in listener.log)
    progress = [c for kind, c in listener.log if kind == "progress"]
    assert progress[-1] <= len(text) + 1


def test_murmurs_are_cached_and_do_not_repeat(tmp_path):
    import numpy as np

    from parley.infrastructure.audio.murmurs import Murmurs

    class CountingVoice:
        name = "fake"
        calls = 0

        def synthesize(self, text):
            CountingVoice.calls += 1
            seconds = 3.0 if text == "Long." else 0.4
            return np.zeros(int(16000 * seconds), np.float32), 16000

    first = Murmurs(CountingVoice(), tmp_path, "v1", texts=("Hmm.", "Right.", "Long."))
    first._prepare()
    assert len(first._clips) == 2                       # длинный «отклик» выброшен
    picks = []
    for _ in range(6):
        first.pick()
        picks.append(first._last)
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))  # подряд не повторяется

    again = Murmurs(CountingVoice(), tmp_path, "v1", texts=("Hmm.", "Right."))
    again._prepare()
    assert CountingVoice.calls == 3                     # второй запуск — с диска, без синтеза
