"""Команда `parley`.

    parley                 окно с персонажем + MCP-сервер в фоне
    parley headless        без окна (сервер, микрофон, голос)
    parley ears toggle     выключить/включить слух (для хоткея); также open / close
    parley status          состояние персонажа
    parley report [-d N]   как работало приложение за N дней: распознавание, цена, задержки, сбои, заметки Claude
    parley doctor          система, звук, устройства, Qt, агенты — для отчёта об ошибке
    parley bugreport       один файл для issue: doctor + журналы последних запусков + сводка (без ключей)
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
import sys
import threading
import time
import urllib.request

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
    sub.add_parser("doctor", help="всё о системе для отчёта об ошибке")
    sub.add_parser("bugreport", help="собрать один файл для issue: doctor, журналы запусков, сводка")
    agents = sub.add_parser("agents", help="где подключён Parley (Claude Code, Codex, opencode)")
    agents.add_argument("--clean", action="store_true", help="убрать глобальные регистрации Parley")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):  # консоль Windows в старой кодировке не должна ронять вывод
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    level = logging.DEBUG if args.verbose else logging.INFO
    if args.command in (None, "headless"):
        # Само приложение: журнал запуска ловит всё с этой строки (errorlog.py)
        from .errorlog import ErrorLog
        ErrorLog(config.DATA_DIR / "logs").install(level)
    else:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
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
        case "doctor":
            print(_doctor(settings))
        case "bugreport":
            _bugreport(settings)
        case "agents":
            _agents(clean=args.clean)


def _exit(code: int) -> None:
    """Выход без ожидания фоновых потоков: запрос к облаку может висеть до 30 секунд, а ждать его незачем.
    Всё важное к этому моменту уже остановлено (Parley.stop), база пишется сразу."""
    logging.getLogger("parley").info("Parley завершился (код %s)", code)
    logging.shutdown()  # дописать журнал запуска: os._exit обработчики выхода не вызывает
    sys.stdout.flush()
    sys.stderr.flush()
    time.sleep(0.1)     # поток перехвата stderr успевает переложить последние строки
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


PROJECT = config.PROJECT_DIR


def _agents(clean: bool) -> None:
    from .interfaces.agents import report
    print(report(PROJECT, clean))




def _doctor(settings: config.Settings) -> str:
    """Всё, что нужно для issue. Ключей и фраз здесь нет."""
    import platform
    from importlib.metadata import version

    out = ["Parley doctor"]

    def line(name: str, value: object) -> None:
        out.append(f"  {name:22} {value}")

    line("parley", version("parley"))
    line("система", f"{platform.system()} {platform.release()} ({platform.machine()})")
    line("python", platform.python_version())
    for package in ("pyside6", "sherpa-onnx", "sounddevice", "mcp", "numpy"):
        try:
            line(package, version(package))
        except Exception:  # noqa: BLE001
            line(package, "не установлен")
    line("конфиг", f"{config.CONFIG_FILE} ({'есть' if config.CONFIG_FILE.exists() else 'нет'})")
    line("данные", config.DATA_DIR)
    line("ключ OpenRouter", "задан" if settings.openrouter.api_key else "НЕ задан")
    from .bootstrap import stt_engine
    engine = stt_engine(settings)
    line("распознавание", f"{engine}: " + (settings.openrouter.transcription_model if engine == "cloud"
                                         else f"встроенная {settings.transcription.local_model}"))

    from .infrastructure.audio.devices import backend
    line("звук", backend())
    if backend() == "portaudio":
        try:
            from .infrastructure.audio import portaudio
            sd = portaudio._sd()
            line("PortAudio", sd.get_portaudio_version()[1])
            for kind in ("input", "output"):
                try:
                    line(f"  по умолчанию ({kind})", sd.query_devices(kind=kind)["name"])
                except Exception as e:  # noqa: BLE001
                    line(f"  по умолчанию ({kind})", f"нет: {e}")
        except Exception as e:  # noqa: BLE001
            line("PortAudio", f"ОШИБКА: {e}")
    else:
        line("pw-record / pw-play", f"{shutil.which('pw-record')} / {shutil.which('pw-play')}")
    line("устройства в конфиге", f"вход «{settings.hearing.input}», выход «{settings.voice.output}»")

    try:
        with urllib.request.urlopen(settings.server.url + "/status", timeout=2) as resp:
            line("Parley запущен", f"да, {settings.server.url} → {resp.read().decode()[:80]}")
    except OSError:
        line("Parley запущен", f"нет ({settings.server.url})")
    from .interfaces.agents import AGENTS
    for agent in AGENTS:
        line(agent.title, f"{'установлен' if agent.installed else 'не установлен'}; {agent.project_file}: "
                          f"{'есть' if (PROJECT / agent.project_file).exists() else 'нет'}")
    from .errorlog import latest
    runs = latest(config.DATA_DIR / "logs")
    line("журнал запуска", runs[-1] if runs else "ещё не было")
    return "\n".join(out)


def _bugreport(settings: config.Settings) -> None:
    """Один файл для issue: doctor, журналы двух последних запусков, сводка дневника. Ключ вырезан."""
    import re
    from datetime import datetime

    from .errorlog import latest
    from .infrastructure.diary import summarize

    parts = [_doctor(settings), "", "=" * 80, summarize(settings.diary_dir, days=2)]
    for run in latest(config.DATA_DIR / "logs", count=2):
        lines = run.read_text(encoding="utf-8", errors="replace").splitlines()
        parts += ["", "=" * 80, f"{run.name} (последние {min(len(lines), 3000)} строк)", *lines[-3000:]]
    if settings.feedback_file.exists():
        parts += ["", "=" * 80, "feedback.md", settings.feedback_file.read_text(encoding="utf-8")[-20000:]]
    text = "\n".join(parts)
    if settings.openrouter.api_key:
        text = text.replace(settings.openrouter.api_key, "<ключ OpenRouter>")
    text = re.sub(r"sk-or-[\w-]{10,}", "<ключ>", text)
    target = config.DATA_DIR / f"parley-bugreport-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print(f"Отчёт: {target}\nПриложи этот файл к issue: https://github.com/toffee-vibe/parley/issues/new\n"
          "В нём нет ключей, но есть фрагменты твоих фраз из дневника — посмотри, прежде чем отправлять.")
