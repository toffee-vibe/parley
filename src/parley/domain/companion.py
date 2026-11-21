"""Компаньон — персонаж на экране. Его состояние и есть то, что видит пользователь.

Состояния:
    waiting   — Claude не подключён: слушать и отвечать некому, микрофон выключен
    idle      — ждёт, уши открыты
    hearing   — пользователь сейчас говорит
    thinking  — фраза услышана, ждём ответа Claude
    speaking  — компаньон говорит
    deaf      — пользователь выключил компаньону слух (например, ушёл в Discord)

Ещё компаньон умеет показывать доску: табличку, правило, пример — и тогда отходит в сторону.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .shared import Aggregate, DomainEvent


class Activity(StrEnum):
    WAITING = "waiting"
    IDLE = "idle"
    HEARING = "hearing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    DEAF = "deaf"


class Mood(StrEnum):
    """Выражение лица. Claude меняет его инструментом `emote`."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    SURPRISED = "surprised"
    PROUD = "proud"
    THOUGHTFUL = "thoughtful"


@dataclass(frozen=True, kw_only=True)
class ActivityChanged(DomainEvent):
    kind = "activity"
    activity: Activity


@dataclass(frozen=True, kw_only=True)
class MoodChanged(DomainEvent):
    kind = "mood"
    mood: Mood


@dataclass(frozen=True, kw_only=True)
class EarsClosed(DomainEvent):
    kind = "ears_closed"


@dataclass(frozen=True, kw_only=True)
class EarsOpened(DomainEvent):
    kind = "ears_opened"


@dataclass(frozen=True, kw_only=True)
class BoardShown(DomainEvent):
    kind = "board_shown"
    title: str
    markdown: str


@dataclass(frozen=True, kw_only=True)
class BoardHidden(DomainEvent):
    kind = "board_hidden"


@dataclass
class Companion(Aggregate):
    activity: Activity = Activity.WAITING
    mood: Mood = Mood.NEUTRAL
    since: datetime | None = None           # когда началось текущее состояние
    voice_ended_at: datetime | None = None  # когда пользователь последний раз замолчал
    board_open: bool = False
    ears_open: bool = True                  # выбор пользователя: кнопка микрофона
    partner_here: bool = False              # подключён ли Claude — тот, кто слушает и отвечает

    @property
    def listening(self) -> bool:
        """Микрофон должен работать: пользователь его не выключал и есть кому слушать."""
        return self.ears_open and self.partner_here

    # --- Claude ---

    def partner_arrived(self, now: datetime) -> None:
        if not self.partner_here:
            self.partner_here = True
            if self.activity is Activity.WAITING:
                self._become(Activity.IDLE, now)

    def partner_left(self, now: datetime) -> None:
        """Ушёл Claude — договорить начатое можно, но слушать и «думать» больше незачем."""
        if self.partner_here:
            self.partner_here = False
            if self.ears_open and self.activity is not Activity.SPEAKING:
                self._become(Activity.WAITING, now)

    # --- слух ---

    def close_ears(self, now: datetime) -> None:
        if self.ears_open:
            self.ears_open = False
            self._become(Activity.DEAF, now)
            self._record(EarsClosed(at=now))

    def open_ears(self, now: datetime) -> None:
        if not self.ears_open:
            self.ears_open = True
            self._become(self._resting(), now)
            self._record(EarsOpened(at=now))

    def user_started_talking(self, now: datetime) -> None:
        if self.listening:
            self._become(Activity.HEARING, now)

    def user_finished_talking(self, now: datetime, said_something: bool) -> None:
        """said_something=False — это был шум или пустая фраза: возвращаемся в покой."""
        if self.activity is Activity.HEARING:
            self.voice_ended_at = now
            self._become(Activity.THINKING if said_something else self._resting(), now)

    def user_is_quiet(self, now: datetime, pause: timedelta) -> bool:
        """Можно говорить, не перебивая: человек не говорит и уже выдержал паузу."""
        if self.activity is Activity.HEARING:
            return False
        return self.voice_ended_at is None or now - self.voice_ended_at >= pause

    def settle(self, now: datetime, patience: timedelta) -> None:
        """Claude решил не отвечать (или не подключён) — не «думаем» вечно."""
        if self.activity is Activity.THINKING and self.since and now - self.since > patience:
            self._become(self._resting(), now)

    # --- речь ---

    def can_speak(self) -> bool:
        """С выключенным слухом компаньон молчит: пользователь занят другим разговором."""
        return self.ears_open

    def started_speaking(self, now: datetime) -> None:
        if self.ears_open and self.activity is not Activity.HEARING:
            self._become(Activity.SPEAKING, now)

    def stopped_speaking(self, now: datetime) -> None:
        if self.activity is Activity.SPEAKING:
            self._become(self._resting(), now)

    # --- лицо и доска ---

    def show(self, mood: Mood, now: datetime) -> None:
        if mood is not self.mood:
            self.mood = mood
            self._record(MoodChanged(at=now, mood=mood))

    def show_board(self, title: str, markdown: str, now: datetime) -> None:
        """Доска с объяснением: таблица времён, правило, примеры. Markdown, таблицы поддерживаются."""
        title, markdown = title.strip(), markdown.strip()
        if not (title or markdown):
            raise ValueError("Пустая доска")
        self.board_open = True
        self._record(BoardShown(at=now, title=title, markdown=markdown))

    def hide_board(self, now: datetime) -> None:
        if self.board_open:
            self.board_open = False
            self._record(BoardHidden(at=now))

    def _resting(self) -> Activity:
        """Состояние, когда ничего не происходит."""
        return Activity.IDLE if self.partner_here else Activity.WAITING

    def _become(self, activity: Activity, now: datetime) -> None:
        if activity is not self.activity:
            self.activity = activity
            self.since = now
            self._record(ActivityChanged(at=now, activity=activity))
