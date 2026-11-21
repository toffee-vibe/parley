"""Команда `parley`.

    parley                 окно с персонажем + MCP-сервер в фоне
    parley headless        без окна (сервер, микрофон, голос)
    parley ears toggle     выключить/включить слух (для хоткея); также open / close
    parley status          состояние персонажа
    parley report [-d N]   как работало приложение за N дней: распознавание, цена, задержки, сбои, заметки Claude
    parley agents [--clean]  где подключён Parley; --clean — убрать глобальные регистрации

Агенты подключаются к Parley только в папке проекта: .mcp.json (Claude Code), .codex/config.toml (Codex),
opencode.json (opencode). Глобально Parley не регистрируется — иначе к нему стучится каждый агент на машине.
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
from pathlib import Path

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="parley", description="Голосовой компаньон для практики английского")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("headless", help="без окна")
    ears = sub.add_parser("ears", help="слух персонажа")
    ears.add_argument("action", choices=["toggle", "open", "close"])
    sub.add_parser("status", help="состояние персонажа")
    report = sub.add_parser("report", help="сводка технического дневника")
    report.add_argument("-d", "--days", type=int, default=1, help="за сколько дней (по умолчанию — сегодня)")
    agents = sub.add_parser("agents", help="где подключён Parley (Claude Code, Codex, opencode)")
    agents.add_argument("--clean", action="store_true", help="убрать глобальные регистрации Parley")
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
        case "report":
            from .infrastructure.diary import summarize
            print(summarize(settings.diary_dir, args.days))
        case "agents":
            _agents(clean=args.clean)


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


PROJECT = Path(__file__).resolve().parents[2]  # корень репозитория (src/parley/cli.py → ../..)

# Где каждый агент берёт MCP-серверы проекта и как убрать глобальную регистрацию.
AGENTS = {
    "claude": (".mcp.json", ["claude", "mcp", "remove", "--scope", "user", "parley"]),
    "codex": (".codex/config.toml", ["codex", "mcp", "remove", "parley"]),
    "opencode": ("opencode.json", None),
}


def _agents(clean: bool) -> None:
    print(f"Parley подключается к агентам только в {PROJECT}\n")
    for agent, (project_file, remove) in AGENTS.items():
        installed = shutil.which(agent) is not None
        here = (PROJECT / project_file).exists()
        global_ = _registered_globally(agent) if installed else False
        line = f"  {agent:9} {'установлен' if installed else 'не установлен':14} проект: {project_file} {'✓' if here else '✗ нет файла'}"
        if global_:
            line += "  ⚠ зарегистрирован глобально"
            if clean and remove:
                done = subprocess.run(remove, capture_output=True, cwd=Path.home()).returncode == 0
                line += " → убран" if done else " → убрать не вышло"
            elif clean:
                line += " → убери вручную из глобального конфига"
        print(line)
    print("\nClaude Code при первом запуске в папке спросит, разрешить ли сервер parley из .mcp.json.")
    print("Codex читает .codex/config.toml, только если проект отмечен доверенным (спросит при первом запуске).")


def _registered_globally(agent: str) -> bool:
    """Есть ли parley в настройках агента вне этой папки (запускаем агента из домашней папки)."""
    command = {"claude": ["claude", "mcp", "get", "parley"], "codex": ["codex", "mcp", "get", "parley"],
               "opencode": ["opencode", "mcp", "list"]}[agent]
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=Path.home())
    except (OSError, subprocess.TimeoutExpired):
        return False
    if agent == "opencode":
        return "parley" in out.stdout
    return out.returncode == 0 and "parley" in out.stdout
