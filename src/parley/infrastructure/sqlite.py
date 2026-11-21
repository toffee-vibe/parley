"""Хранилище на SQLite: фразы, ошибки и история фраз пользователя (для метрик прогресса).

Одно соединение на всё приложение под блокировкой: записей мало, а потоков несколько.
Схема создаётся сама; новые колонки добавлять через ALTER в `_migrate`.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ..domain.conversation import Utterance
from ..domain.learning import Mistake, MistakeKind, Phrase, mistake_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS phrases (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    meaning TEXT NOT NULL,
    example TEXT NOT NULL,
    created_at TEXT NOT NULL,
    stage INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    used INTEGER NOT NULL,
    struggled INTEGER NOT NULL,
    missed INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS phrases_text ON phrases (lower(text));

CREATE TABLE IF NOT EXISTS mistakes (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    wrong TEXT NOT NULL,
    right TEXT NOT NULL,
    explanation TEXT NOT NULL,
    count INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS utterances (
    started_at TEXT NOT NULL,
    duration_s REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS utterances_time ON utterances (started_at);
"""


class Database:
    def __init__(self, path: Path | str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(SCHEMA)


def _t(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class SqlitePhrases:
    def __init__(self, db: Database):
        self.db = db

    def add(self, phrase: Phrase) -> None:
        self.save(phrase)

    def save(self, phrase: Phrase) -> None:
        with self.db.lock, self.db.conn:
            self.db.conn.execute(
                "INSERT OR REPLACE INTO phrases VALUES (?,?,?,?,?,?,?,?,?,?)",
                (phrase.id, phrase.text, phrase.meaning, phrase.example, _t(phrase.created_at), phrase.stage,
                 _t(phrase.due_at), phrase.used, phrase.struggled, phrase.missed))

    def get(self, phrase_id: str) -> Phrase | None:
        return self._one("SELECT * FROM phrases WHERE id = ?", phrase_id)

    def find_by_text(self, text: str) -> Phrase | None:
        return self._one("SELECT * FROM phrases WHERE lower(text) = lower(?)", text.strip())

    def due(self, now: datetime, limit: int) -> list[Phrase]:
        # Сравниваем в Python: в базе время с часовым поясом, строковое сравнение ненадёжно.
        return sorted((p for p in self.all() if p.is_due(now)), key=lambda p: (p.stage, p.due_at))[:limit]

    def all(self) -> list[Phrase]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM phrases").fetchall()
        return [self._phrase(r) for r in rows]

    def _one(self, sql: str, *args: object) -> Phrase | None:
        with self.db.lock:
            row = self.db.conn.execute(sql, args).fetchone()
        return self._phrase(row) if row else None

    @staticmethod
    def _phrase(row: sqlite3.Row) -> Phrase:
        return Phrase(id=row["id"], text=row["text"], meaning=row["meaning"], example=row["example"],
                      created_at=_dt(row["created_at"]), stage=row["stage"], due_at=_dt(row["due_at"]),
                      used=row["used"], struggled=row["struggled"], missed=row["missed"])


class SqliteMistakes:
    def __init__(self, db: Database):
        self.db = db

    def by_key(self, key: str) -> Mistake | None:
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM mistakes WHERE key = ?", (key,)).fetchone()
        return self._mistake(row) if row else None

    def save(self, mistake: Mistake) -> None:
        with self.db.lock, self.db.conn:
            self.db.conn.execute(
                "INSERT OR REPLACE INTO mistakes VALUES (?,?,?,?,?,?,?,?,?)",
                (mistake.id, mistake_key(mistake.right), mistake.category.value, mistake.wrong, mistake.right,
                 mistake.explanation, mistake.count, _t(mistake.first_seen), _t(mistake.last_seen)))

    def most_frequent(self, limit: int, since: datetime | None = None) -> list[Mistake]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM mistakes").fetchall()
        mistakes = [self._mistake(r) for r in rows]
        if since:
            mistakes = [m for m in mistakes if m.last_seen and m.last_seen >= since]
        return sorted(mistakes, key=lambda m: m.count, reverse=True)[:limit]

    @staticmethod
    def _mistake(row: sqlite3.Row) -> Mistake:
        return Mistake(id=row["id"], category=MistakeKind(row["category"]), wrong=row["wrong"], right=row["right"],
                       explanation=row["explanation"], count=row["count"], first_seen=_dt(row["first_seen"]),
                       last_seen=_dt(row["last_seen"]))


class SqliteUtterances:
    def __init__(self, db: Database):
        self.db = db

    def append(self, utterance: Utterance) -> None:
        with self.db.lock, self.db.conn:
            self.db.conn.execute("INSERT INTO utterances VALUES (?,?,?)",
                                 (_t(utterance.started_at), utterance.duration_s, utterance.text))

    def since(self, moment: datetime) -> list[Utterance]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT * FROM utterances ORDER BY started_at").fetchall()
        items = [Utterance(r["text"], _dt(r["started_at"]), r["duration_s"]) for r in rows]
        return [u for u in items if u.started_at >= moment]
