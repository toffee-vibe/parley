"""Технический дневник — чтобы потом понять, что в Parley улучшить.

Пишет по файлу в день: ~/.local/share/parley/diary/2026-11-21.jsonl, одна JSON-строка на запись.
Это не учебная статистика (она в parley.db), а то, как работает само приложение:

    session_start / session_end   версия моделей, сколько длилась сессия
    stt                           запрос распознавания: модель, длина звука, задержка, цена, ошибка
    tts                           запрос облачного голоса: длина текста, задержка, ошибка
    stt_discarded                 распознавание выдумало фразу на шуме — выброшено
    voice_lost                    детектор речи сработал, а фразы не получилось
    barge_in                      пользователь перебил Пипа (и насколько громким было эхо)
    event                         события разговора: услышано, сказано, перебито, доска, микрофон…
    warning                       любое предупреждение или ошибка из логов
    claude_note                   заметка Claude: что в разговоре пошло не так (инструмент note_for_developer)

Сводка: `parley report` (summarize ниже). Старше KEEP_DAYS дней — удаляется при запуске.
Всё остаётся на этом компьютере.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..application.ports import JournalEntry

KEEP_DAYS = 60

# Примерная цена распознавания за час звука ($), если OpenRouter не вернул точную стоимость.
STT_PRICE_PER_HOUR = {
    "openai/gpt-4o-mini-transcribe": 0.113,
    "openai/whisper-large-v3-turbo": 0.012,
}

# События разговора, которые в дневник не нужны: их слишком много, а смысла мало.
QUIET_EVENTS = {"mood"}


class Diary:
    def __init__(self, folder: Path):
        self.folder = folder
        self._lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        self._forget_old()

    def record(self, kind: str, **data: Any) -> None:
        now = datetime.now().astimezone()
        line = json.dumps({"at": now.isoformat(timespec="milliseconds"), "kind": kind, **data},
                          ensure_ascii=False, default=str)
        try:
            with self._lock, open(self.folder / f"{now.date()}.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass  # дневник не должен ронять приложение

    def conversation_event(self, entry: JournalEntry) -> None:
        """Подписчик журнала событий."""
        if entry.kind not in QUIET_EVENTS:
            self.record("event", event=entry.kind, **entry.data)

    def capture_warnings(self) -> None:
        """Все WARNING и ERROR из логов приложения тоже попадают в дневник."""
        handler = _DiaryHandler(self)
        handler.setLevel(logging.WARNING)
        logging.getLogger("parley").addHandler(handler)

    def _forget_old(self) -> None:
        oldest = date.today() - timedelta(days=KEEP_DAYS)
        for file in self.folder.glob("*.jsonl"):
            try:
                if date.fromisoformat(file.stem) < oldest:
                    file.unlink()
            except ValueError:
                continue


class _DiaryHandler(logging.Handler):
    def __init__(self, diary: Diary):
        super().__init__()
        self.diary = diary

    def emit(self, record: logging.LogRecord) -> None:
        data: dict[str, Any] = {"level": record.levelname, "where": record.name, "message": record.getMessage()}
        if record.exc_info and record.exc_info[1]:
            data["error"] = repr(record.exc_info[1])
        self.diary.record("warning", **data)


class NullDiary:
    """Дневник, который ничего не пишет (тесты, утилиты)."""

    def record(self, kind: str, **data: Any) -> None:
        pass


# ---------------- сводка ----------------


def read(folder: Path, days: int) -> Iterator[dict[str, Any]]:
    first = date.today() - timedelta(days=days - 1)
    for file in sorted(folder.glob("*.jsonl")):
        try:
            if date.fromisoformat(file.stem) < first:
                continue
        except ValueError:
            continue
        for line in file.read_text(encoding="utf-8").splitlines():
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def summarize(folder: Path, days: int = 1) -> str:
    records = list(read(folder, days))
    if not records:
        return f"За {days} дн. записей нет ({folder})."
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r)
    events = Counter(r.get("event") for r in by_kind.get("event", []))
    out = [f"Parley за {days} дн. ({folder})", ""]

    sessions = by_kind.get("session_start", [])
    out.append(f"Сессий: {len(sessions)}")

    stt = by_kind.get("stt", [])
    if stt:
        ok = [r for r in stt if not r.get("error")]
        audio = sum(r.get("audio_s", 0) for r in ok)
        cost = sum(_stt_cost(r) for r in ok)
        latency = sorted(r["ms"] for r in ok if "ms" in r)
        models = Counter(r.get("model") for r in ok)
        out += ["", "Распознавание",
                f"  запросов: {len(stt)}, ошибок: {len(stt) - len(ok)}",
                f"  звука: {audio / 60:.1f} мин, стоимость ≈ ${cost:.4f} (≈ ${cost / max(audio, 1) * 3600:.3f}/час)",
                f"  задержка: медиана {_pct(latency, 50)} мс, 90% {_pct(latency, 90)} мс",
                "  модели: " + ", ".join(f"{m} ×{n}" for m, n in models.most_common())]
        errors = Counter(str(r.get("status") or r.get("error"))[:60] for r in stt if r.get("error"))
        if errors:
            out.append("  ошибки: " + ", ".join(f"{e} ×{n}" for e, n in errors.most_common(5)))

    tts = by_kind.get("tts", [])
    if tts:
        ok = [r for r in tts if not r.get("error")]
        latency = sorted(r["ms"] for r in ok if "ms" in r)
        out += ["", "Облачный голос",
                f"  запросов: {len(tts)}, ошибок: {len(tts) - len(ok)}, символов: {sum(r.get('chars', 0) for r in ok)}",
                f"  задержка: медиана {_pct(latency, 50)} мс, 90% {_pct(latency, 90)} мс"]

    out += ["", "Разговор",
            f"  услышано фраз: {events['heard']}, выброшено как шум/выдумка: {len(by_kind.get('stt_discarded', []))},"
            f" сорвалось (речь без фразы): {len(by_kind.get('voice_lost', []))}",
            f"  реплик Пипа: {events['speech_started']}, перебито: {events['interrupted']},"
            f" сбоев озвучки: {events['speech_failed']}, выброшено из очереди: {events['speech_dropped']}",
            f"  доска: {events['board_shown']}, микрофон выключали: {events['ears_closed']},"
            f" звуки: {events['sound']}"]

    discarded = by_kind.get("stt_discarded", [])
    if discarded:
        out.append("  выброшенные: " + "; ".join(f"«{r.get('text')}» ({r.get('audio_s', 0):.1f} с)"
                                                 for r in discarded[-5:]))

    warnings = Counter(f"{r.get('where')}: {str(r.get('message'))[:90]}" for r in by_kind.get("warning", []))
    if warnings:
        out += ["", f"Предупреждения ({sum(warnings.values())})"]
        out += [f"  ×{n} {w}" for w, n in warnings.most_common(8)]

    notes = by_kind.get("claude_note", [])
    if notes:
        out += ["", f"Заметки Claude ({len(notes)})"]
        out += [f"  [{r['at'][:16]}] {r.get('problem')}" + (f" — {r['context']}" if r.get("context") else "")
                for r in notes[-15:]]
    return "\n".join(out)


def _stt_cost(r: dict[str, Any]) -> float:
    if isinstance(r.get("cost"), int | float):
        return float(r["cost"])
    return r.get("audio_s", 0) / 3600 * STT_PRICE_PER_HOUR.get(r.get("model", ""), 0.113)


def _pct(values: list[float], p: int) -> str:
    if not values:
        return "—"
    return str(round(values[min(len(values) - 1, len(values) * p // 100)]))
