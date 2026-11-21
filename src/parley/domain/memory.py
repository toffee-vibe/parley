"""Память о пользователе между сессиями: чтобы каждый разговор не начинался с «Tell me about yourself».

Факт — одна короткая запись о человеке или о прошлом разговоре: «Работает бэкендером в банке, 2 года»,
«Собеседование в Яндекс 5 декабря», «Вчера рассказывал про race condition в FastAPI — спросить, чем кончилось».
Claude записывает факты сам (`remember`) и читает их в начале сессии (`recall`).

Темы (`topic`) помогают читать память по частям:
    profile    — кто он: имя, где живёт, чем занят
    work       — работа, стек, обязанности
    projects   — пет-проекты и то, что он сейчас делает
    interview  — к чему готовится: компании, даты, вакансии
    life       — увлечения, планы, то, о чём ему интересно говорить
    style      — как с ним лучше разговаривать (что раздражает, что нравится)
    session    — итог прошлой сессии и незакрытые темы («спросить, чем кончилось …»)
Тема — свободная строка, список выше — подсказка.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .shared import new_id

TOPICS = ("profile", "work", "projects", "interview", "life", "style", "session")
MAX_FACT_CHARS = 300


@dataclass
class Fact:
    text: str
    topic: str
    created_at: datetime
    id: str = field(default_factory=new_id)
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        self.text = " ".join(self.text.split())
        self.topic = (self.topic or "profile").strip().lower()
        if not self.text:
            raise ValueError("Пустой факт")
        if len(self.text) > MAX_FACT_CHARS:
            raise ValueError(f"Факт длиннее {MAX_FACT_CHARS} символов — запиши короче или разбей на несколько")
        self.updated_at = self.updated_at or self.created_at

    def rewrite(self, text: str, topic: str, now: datetime) -> None:
        """Факт устарел («перешёл в другую компанию») — заменяем, а не копим противоречия."""
        replacement = Fact(text, topic or self.topic, self.created_at)
        self.text, self.topic, self.updated_at = replacement.text, replacement.topic, now
