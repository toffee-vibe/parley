"""Технический дневник: запись, подписка на события, сводка, запись запросов к OpenRouter."""

import json
from datetime import datetime

import httpx
import numpy as np

from parley.application.ports import JournalEntry
from parley.config import OpenRouterSettings
from parley.infrastructure.diary import Diary, summarize
from parley.infrastructure.openrouter import OpenRouter, OpenRouterError


def lines(folder):
    return [json.loads(line) for f in folder.glob("*.jsonl") for line in f.read_text().splitlines()]


def test_records_and_summarizes(tmp_path):
    diary = Diary(tmp_path)
    diary.record("session_start", stt="openai/gpt-4o-mini-transcribe")
    diary.record("stt", model="openai/gpt-4o-mini-transcribe", audio_s=60, ms=900)
    diary.record("stt", model="openai/gpt-4o-mini-transcribe", audio_s=2, ms=400, status=429, error="rate")
    diary.record("stt_discarded", text="Thank you.", audio_s=12.0)
    diary.conversation_event(JournalEntry(1, "heard", datetime.now().astimezone(), {"text": "hello"}))
    diary.conversation_event(JournalEntry(2, "mood", datetime.now().astimezone(), {"mood": "happy"}))
    diary.record("claude_note", problem="Pip cut the user off", context="heard: I was work")

    kinds = [r["kind"] for r in lines(tmp_path)]
    assert "event" in kinds and kinds.count("event") == 1  # mood — шум, не пишется

    report = summarize(tmp_path)
    assert "запросов: 2, ошибок: 1" in report
    assert "1.0 мин" in report and "$0.0019" in report      # минута по ~$0.113/час
    assert "услышано фраз: 1" in report and "«Thank you.»" in report
    assert "Pip cut the user off" in report


def test_openrouter_requests_go_to_diary(tmp_path):
    diary = Diary(tmp_path)
    replies = iter([httpx.Response(200, json={"text": "hi", "usage": {"cost": 0.0001}}),
                    httpx.Response(500, text="boom")])
    client = OpenRouter(OpenRouterSettings(api_key="k", transcription_model="m", fallback_transcription_model=""),
                        diary)
    client.http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(lambda _: next(replies)))

    assert client.transcribe(np.zeros(16000, np.float32)) == "hi"
    try:
        client.transcribe(np.zeros(8000, np.float32))
    except OpenRouterError:
        pass
    stt = [r for r in lines(tmp_path) if r["kind"] == "stt"]
    assert stt[0]["model"] == "m" and stt[0]["audio_s"] == 1.0 and stt[0]["cost"] == 0.0001
    assert stt[1]["status"] == 500 and "boom" in stt[1]["error"]


def test_terminal_errors_reach_the_diary(tmp_path):
    """И то, что пишут C-библиотеки прямо в stderr, и упавшие потоки — в дневнике, а в терминале всё как было."""
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(f"""
        import logging, os, threading, time
        from pathlib import Path
        logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
        from parley.infrastructure.diary import Diary
        diary = Diary(Path({str(tmp_path)!r}))
        diary.capture_warnings()
        diary.capture_stderr()
        os.write(2, b"[W:onnxruntime] Some nodes were not assigned to the preferred execution providers\\n")
        os.write(2, b"12:00:00 WARNING parley.x: own log line\\n")
        t = threading.Thread(target=lambda: 1 / 0, name="worker"); t.start(); t.join()
        time.sleep(0.3)
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert "onnxruntime" in done.stderr                       # в терминале по-прежнему видно
    records = lines(tmp_path)
    stderr = [r["line"] for r in records if r["kind"] == "stderr"]
    assert stderr[0] == "[W:onnxruntime] Some nodes were not assigned to the preferred execution providers"
    assert not any("own log line" in line or line.startswith("  File") for line in stderr)
    crashed = [r for r in records if r["kind"] == "warning" and "worker" in r["message"]]
    assert crashed and "ZeroDivisionError" in crashed[0]["error"]
    assert "Из терминала" in summarize(tmp_path)
