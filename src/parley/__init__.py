"""Parley — голосовой компаньон: Claude слышит тебя и отвечает вслух, помогая разговориться на английском.

Слои (Clean Architecture, зависимости только внутрь):
    domain/          правила: персонаж, реплики, фразы, ошибки — без внешних библиотек
    application/     команды и запросы (CQRS), порты для внешнего мира
    infrastructure/  PipeWire, sherpa-onnx, OpenRouter, SQLite — реализации портов
    interfaces/      MCP-сервер для Claude и окно на Qt
    bootstrap.py     сборка всего вместе
"""


def main() -> None:
    from .cli import main as cli_main

    cli_main()
