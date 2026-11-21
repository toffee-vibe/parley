"""CQRS: команды меняют состояние, запросы только читают. У каждого сообщения ровно один обработчик.

    commands.execute(Say(text="Hi!"))       # изменить мир
    queries.ask(DuePhrases(limit=5))        # спросить о мире

Команды выполняются под одной блокировкой: события приходят из разных потоков
(микрофон, плеер, MCP, интерфейс), а агрегаты должны меняться по одному.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class UnknownMessage(LookupError):
    pass


class _Bus:
    def __init__(self, serialize: bool):
        self._handlers: dict[type, Callable[[Any], Any]] = {}
        self._lock = threading.RLock() if serialize else None

    def register(self, message_type: type, handler: Callable[[Any], Any]) -> None:
        if message_type in self._handlers:
            raise ValueError(f"У {message_type.__name__} уже есть обработчик")
        self._handlers[message_type] = handler

    def _dispatch(self, message: object) -> Any:
        handler = self._handlers.get(type(message))
        if handler is None:
            raise UnknownMessage(f"Нет обработчика для {type(message).__name__}")
        if self._lock is None:
            return handler(message)
        with self._lock:
            return handler(message)


class CommandBus(_Bus):
    def __init__(self) -> None:
        super().__init__(serialize=True)

    def execute(self, command: object) -> Any:
        """Возвращает только идентификатор созданного объекта (если он есть), не данные."""
        return self._dispatch(command)


class QueryBus(_Bus):
    def __init__(self) -> None:
        super().__init__(serialize=False)

    def ask(self, query: object) -> Any:
        return self._dispatch(query)
