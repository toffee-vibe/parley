"""Агенты, которые умеют разговаривать через Parley, и где у каждого лежит его подключение.

Parley подключается к агентам только в папке проекта: файлы ниже лежат в репозитории, и каждый агент
читает свой, когда запущен здесь. Глобальная регистрация (во всех папках) — плохая идея: к Parley
начинает стучаться любой агент на машине. `parley agents --clean` её убирает.

    Claude Code  .mcp.json                       (спросит разрешение при первом запуске)
    Kimi Code    .mcp.json                       (тот же файл, что у Claude Code)
    Codex        .codex/config.toml              (только если проект отмечен доверенным)
    opencode     opencode.json
    Antigravity  .agents/plugins/parley/         (плагин проекта: plugin.json + mcp_config.json)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess | None:
    """Команда агента из домашней папки (там проектные настройки не действуют — видно только глобальное).
    Полный путь к программе: на Windows агенты стоят как .cmd-обёртки, и без пути их не запустить."""
    try:
        return subprocess.run([shutil.which(command[0]) or command[0], *command[1:]], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60, cwd=Path.home())
    except (OSError, subprocess.TimeoutExpired):
        return None


def _says_parley(command: list[str], need_success: bool = True) -> Callable[[], bool]:
    def check() -> bool:
        done = run(command)
        return bool(done) and (done.returncode == 0 or not need_success) and "parley" in done.stdout
    return check


def _succeeds(command: list[str]) -> Callable[[], bool]:
    def remove() -> bool:
        done = run(command)
        return bool(done) and done.returncode == 0
    return remove


def _json_has_parley(path: Path) -> Callable[[], bool]:
    def check() -> bool:
        try:
            return "parley" in json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
        except (OSError, ValueError, AttributeError):
            return False
    return check


def _json_without_parley(path: Path) -> Callable[[], bool]:
    def remove() -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.get("mcpServers", {}).pop("parley", None)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return True
        except (OSError, ValueError, AttributeError):
            return False
    return remove


@dataclass(frozen=True)
class Agent:
    title: str
    command: str                          # как запускается
    project_file: str                     # что в репозитории его подключает
    registered_globally: Callable[[], bool]
    remove_global: Callable[[], bool] | None  # None — убрать можно только руками
    note: str = ""

    @property
    def installed(self) -> bool:
        return shutil.which(self.command) is not None


AGENTS = [
    Agent("Claude Code", "claude", ".mcp.json", _says_parley(["claude", "mcp", "get", "parley"]),
          _succeeds(["claude", "mcp", "remove", "--scope", "user", "parley"]),
          "при первом запуске в папке спросит, разрешить ли сервер parley"),
    Agent("Kimi Code", "kimi", ".mcp.json", _json_has_parley(Path.home() / ".kimi-code" / "mcp.json"),
          _json_without_parley(Path.home() / ".kimi-code" / "mcp.json")),
    Agent("Codex", "codex", ".codex/config.toml", _says_parley(["codex", "mcp", "get", "parley"]),
          _succeeds(["codex", "mcp", "remove", "parley"]),
          "читает файл, только если проект отмечен доверенным (спросит при первом запуске)"),
    Agent("opencode", "opencode", "opencode.json", _says_parley(["opencode", "mcp", "list"], need_success=False),
          None),
    Agent("Antigravity", "agy", ".agents/plugins/parley/mcp_config.json",
          _json_has_parley(Path.home() / ".gemini" / "config" / "mcp_config.json"),
          _succeeds(["agy", "mcp", "remove", "parley"])),
]


def report(project: Path, clean: bool) -> str:
    lines = [f"Parley подключается к агентам только в {project}", ""]
    notes = []
    for agent in AGENTS:
        here = (project / agent.project_file).exists()
        line = (f"  {agent.title:12} {'установлен' if agent.installed else 'не установлен':14} "
                f"{agent.project_file} {'✓' if here else '✗ нет файла'}")
        if agent.installed and agent.registered_globally():
            line += "  ⚠ зарегистрирован глобально"
            if clean and agent.remove_global:
                line += " → убран" if agent.remove_global() else " → убрать не вышло"
            elif clean:
                line += " → убери вручную из его глобального конфига"
        lines.append(line)
        if agent.note and agent.installed:
            notes.append(f"{agent.title}: {agent.note}.")
    return "\n".join(lines + ([""] + notes if notes else []))
