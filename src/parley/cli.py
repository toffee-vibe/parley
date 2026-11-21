"""Команда `parley`.

    parley                 окно с персонажем + MCP-сервер в фоне
    parley headless        без окна (сервер, микрофон, голос)
    parley ears toggle     выключить/включить слух (для хоткея); также open / close
    parley status          состояние персонажа
    parley connect-claude  зарегистрировать MCP-сервер в Claude Code (user scope)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import urllib.request

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="parley", description="Голосовой компаньон для практики английского")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("headless", help="без окна")
    ears = sub.add_parser("ears", help="слух персонажа")
    ears.add_argument("action", choices=["toggle", "open", "close"])
    sub.add_parser("status", help="состояние персонажа")
    sub.add_parser("connect-claude", help="подключить к Claude Code")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if not args.verbose:  # каждый HTTP-запрос и служебные сообщения MCP в терминале не нужны
        for noisy in ("httpx", "mcp", "uvicorn"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = config.load()

    match args.command:
        case None:
            from .interfaces.gui.app import run
            _exit(run(settings))
        case "headless":
            _headless(settings)
            _exit(0)
        case "ears":
            print(_request(settings, f"/ears/{args.action}", method="POST"))
        case "status":
            print(_request(settings, "/status"))
        case "connect-claude":
            _connect_claude(settings)


def _exit(code: int) -> None:
    """Выход без ожидания фоновых потоков: запрос к облаку может висеть до 30 секунд, а ждать его незачем.
    Всё важное к этому моменту уже остановлено (Parley.stop), база пишется сразу."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _headless(settings: config.Settings) -> None:
    from .bootstrap import build

    app = build(settings)
    app.start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    app.stop()


def _request(settings: config.Settings, path: str, method: str = "GET") -> str:
    request = urllib.request.Request(settings.server.url + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return json.dumps(json.loads(resp.read()), ensure_ascii=False)
    except OSError as e:
        sys.exit(f"Parley не запущен ({e})")


def _connect_claude(settings: config.Settings) -> None:
    if not shutil.which("claude"):
        sys.exit("Не найден claude (Claude Code)")
    url = f"{settings.server.url}/mcp"
    subprocess.run(["claude", "mcp", "remove", "--scope", "user", "parley"], capture_output=True)
    subprocess.run(["claude", "mcp", "add", "--scope", "user", "--transport", "http", "parley", url], check=True)
    print(f"Готово: Claude Code будет подключаться к {url}. Перезапусти сессию claude.")
