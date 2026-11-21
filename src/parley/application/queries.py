"""Запросы — только чтение. Каждый возвращает простые dict/list, готовые к JSON."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from statistics import mean

from ..domain.learning import Phrase
from .ports import Clock, FactRepository, Journal, MistakeRepository, PhraseRepository, UtteranceLog
from .state import LiveState

# То, что важно Claude. Остальное (смена выражения лица, начало реплики) нужно только интерфейсу.
FOR_CLAUDE = frozenset({"heard", "sound", "interrupted", "speech_dropped", "speech_finished", "speech_failed",
                        "ears_closed", "ears_opened"})


@dataclass(frozen=True)
class Listen:
    """Long-poll: новые события после курсора `after`. after=-1 — начать с текущего момента."""

    after: int = -1
    timeout_s: float = 25.0


@dataclass(frozen=True)
class SpeechResult:
    speech_id: str
    wait_s: float = 0.0  # >0 — дождаться конца реплики


@dataclass(frozen=True)
class CompanionStatus:
    pass


@dataclass(frozen=True)
class SpeechNow:
    """Что персонаж говорит прямо сейчас и сколько уже прозвучало — для субтитров."""


@dataclass(frozen=True)
class DuePhrases:
    limit: int = 5


@dataclass(frozen=True)
class Progress:
    days: int = 1


@dataclass(frozen=True)
class Recall:
    """Память о пользователе: факты по темам, свежие сверху. topic="" — все."""

    topic: str = ""


SESSION_NOTES_SHOWN = 5  # итогов прошлых сессий достаточно последних нескольких


def phrase_view(phrase: Phrase) -> dict:
    return {"id": phrase.id, "text": phrase.text, "meaning": phrase.meaning, "example": phrase.example,
            "stage": phrase.stage, "learned": phrase.learned, "used": phrase.used, "missed": phrase.missed}


class QueryHandlers:
    def __init__(self, state: LiveState, journal: Journal, clock: Clock,
                 phrases: PhraseRepository, mistakes: MistakeRepository, utterances: UtteranceLog,
                 facts: FactRepository):
        self.state = state
        self.journal = journal
        self.clock = clock
        self.phrases = phrases
        self.mistakes = mistakes
        self.utterances = utterances
        self.facts = facts

    def routes(self) -> dict[type, object]:
        return {
            Listen: self._listen,
            SpeechResult: self._speech_result,
            CompanionStatus: self._status,
            SpeechNow: self._speech_now,
            DuePhrases: self._due_phrases,
            Progress: self._progress,
            Recall: self._recall,
        }

    def _listen(self, query: Listen) -> dict:
        after = self.journal.last_seq() if query.after < 0 else query.after
        deadline = time.monotonic() + max(query.timeout_s, 0)
        while True:
            entries = [e for e in self.journal.wait(after, deadline - time.monotonic()) if e.kind in FOR_CLAUDE]
            fresh = self.journal.last_seq()
            if entries or time.monotonic() >= deadline:
                return {"cursor": fresh, "events": [e.as_dict() for e in entries]}
            after = fresh  # пришло только служебное — ждём дальше

    def _speech_result(self, query: SpeechResult) -> dict:
        deadline = time.monotonic() + query.wait_s
        while True:
            speech = self.state.speeches.get(query.speech_id)
            if speech is None:
                return {"speech_id": query.speech_id, "status": "unknown"}
            if speech.is_over or time.monotonic() >= deadline:
                return {"speech_id": speech.id, "status": speech.status.value,
                        "heard": speech.heard, "not_heard": speech.not_heard}
            self.journal.wait(self.journal.last_seq(), min(0.5, deadline - time.monotonic()))

    def _status(self, _: CompanionStatus) -> dict:
        companion = self.state.companion
        return {"activity": companion.activity.value, "mood": companion.mood.value,
                "ears_open": companion.ears_open, "board_open": companion.board_open,
                "waiting_to_speak": len(self.state.waiting), "cursor": self.journal.last_seq()}

    def _speech_now(self, _: SpeechNow) -> dict | None:
        speech = self.state.current_speech()
        if speech is None:
            return None
        return {"speech_id": speech.id, "text": speech.clean_text, "heard": len(speech.heard)}

    def _due_phrases(self, query: DuePhrases) -> list[dict]:
        return [phrase_view(p) for p in self.phrases.due(self.clock.now(), query.limit)]

    def _progress(self, query: Progress) -> dict:
        """Метрики считаются из записей, а не со слов модели — их можно проверить."""
        now = self.clock.now()
        since = now - timedelta(days=query.days)
        said = [u for u in self.utterances.since(since) if not u.is_empty]
        total_words = sum(u.words for u in said)
        english_words = sum(u.words * u.english_share for u in said)
        phrases = self.phrases.all()
        return {
            "period_days": query.days,
            "utterances": len(said),
            "words_spoken": total_words,
            "english_share": round(english_words / total_words, 2) if total_words else None,
            "avg_words_per_utterance": round(mean(u.words for u in said), 1) if said else None,
            "speaking_minutes": round(sum(u.duration_s for u in said) / 60, 1),
            "phrases_total": len(phrases),
            "phrases_learned": sum(p.learned for p in phrases),
            "phrases_due": sum(p.is_due(now) for p in phrases),
            "top_mistakes": [
                {"right": m.right, "wrong": m.wrong, "category": m.category.value, "count": m.count}
                for m in self.mistakes.most_frequent(5, since=since)
            ],
        }

    def _recall(self, query: Recall) -> dict:
        topic = query.topic.strip().lower()
        facts = sorted(self.facts.all(), key=lambda f: f.updated_at or f.created_at, reverse=True)
        grouped: dict[str, list[dict]] = {}
        for fact in facts:
            if topic and fact.topic != topic:
                continue
            notes = grouped.setdefault(fact.topic, [])
            if fact.topic == "session" and len(notes) >= SESSION_NOTES_SHOWN:
                continue
            notes.append({"id": fact.id, "text": fact.text,
                          "updated": (fact.updated_at or fact.created_at).date().isoformat()})
        return {"facts": grouped, "total": sum(len(v) for v in grouped.values())}
