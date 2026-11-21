"""Тексты, которые пользователь присылает через окно: пост с Reddit, твит, статья, свой перевод.

Пользователь вставляет текст или ссылку и выбирает, что с ним делать (`Intent`). Ссылки Parley сам
открывает и достаёт текст (infrastructure/links.py), а Claude получает событие `shared`
со всем сразу: что прислали, что просили и что было по ссылке.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .shared import DomainEvent

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
MAX_SHARED_CHARS = 8000   # больше разбирать вслух бессмысленно, да и Claude не нужно
MAX_LINKS = 3


class Intent(StrEnum):
    EXPLAIN = "explain"              # разобрать язык: слова, идиомы, сленг, тон
    CHECK_TRANSLATION = "check_translation"  # проверить мой перевод: точность и естественность
    DISCUSS = "discuss"              # поговорить о содержании по-английски


@dataclass(frozen=True)
class Comment:
    author: str
    text: str
    score: int | None = None


@dataclass(frozen=True)
class Article:
    """То, что нашлось по ссылке."""

    url: str
    site: str                 # reddit | x | web
    title: str = ""
    author: str = ""
    text: str = ""
    comments: tuple[Comment, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        data: dict = {"url": self.url, "site": self.site, "title": self.title, "author": self.author,
                      "text": self.text}
        if self.comments:
            data["comments"] = [{"author": c.author, "text": c.text, "score": c.score} for c in self.comments]
        return data


def links_in(text: str) -> list[str]:
    found: list[str] = []
    for url in _URL.findall(text):
        url = url.rstrip(".,;:!?")
        if url not in found:
            found.append(url)
    return found[:MAX_LINKS]


@dataclass(frozen=True, kw_only=True)
class TextShared(DomainEvent):
    kind = "shared"
    text: str                 # что вставил пользователь (с его пометками, своим переводом и т.п.)
    intent: Intent
    links: list[dict]         # Article.as_dict() для каждой открытой ссылки
    failed_links: list[str]   # ссылки, которые открыть не удалось — Claude может попробовать сам


def shared(text: str, intent: Intent, articles: list[Article], failed: list[str], now) -> TextShared:
    text = text.strip()
    if not text:
        raise ValueError("Пустой текст")
    return TextShared(at=now, text=text[:MAX_SHARED_CHARS], intent=intent,
                      links=[a.as_dict() for a in articles], failed_links=failed)
