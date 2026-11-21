"""Присланные тексты: ссылки в тексте и событие для Claude."""

from datetime import datetime

import pytest

from parley.domain.reading import Article, Intent, links_in, shared


def test_links_are_found_once_and_without_trailing_punctuation():
    text = "Глянь https://reddit.com/r/python/comments/abc/x/. И ещё https://x.com/a/status/1, https://x.com/a/status/1"
    assert links_in(text) == ["https://reddit.com/r/python/comments/abc/x/", "https://x.com/a/status/1"]


def test_shared_event_carries_text_intent_and_articles():
    article = Article("https://x.com/a/status/1", "x", author="a", text="ship it")
    event = shared("  проверь мой перевод: ship it = отправь  ", Intent.CHECK_TRANSLATION, [article], [],
                   datetime.now().astimezone())
    assert event.kind == "shared" and event.text.startswith("проверь")
    assert event.links[0]["text"] == "ship it" and "comments" not in event.links[0]
    with pytest.raises(ValueError):
        shared("   ", Intent.EXPLAIN, [], [], datetime.now().astimezone())
