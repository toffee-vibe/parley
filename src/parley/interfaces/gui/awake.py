"""Пока идёт разговор, экран не гаснет и не блокируется — как при просмотре видео.

Ты говоришь, а не двигаешь мышью, и система думает, что за компьютером никого нет.
    Linux   — D-Bus org.freedesktop.ScreenSaver.Inhibit (hypridle, KDE, GNOME, XFCE…). Запрет держится
              на своём соединении с D-Bus и снимается его закрытием: так требует спецификация, и так
              не нужен UnInhibit с номером uint32, который PySide6 передать не умеет.
    Windows — SetThreadExecutionState (как видеоплееры)
    macOS   — caffeinate, пока жив Parley
Запрет снимается, как только разговор кончился (агент ушёл, микрофон выключен), и при выходе.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)

REASON = "Голосовой разговор с Parley"


class StayAwake:
    def __init__(self) -> None:
        self.active = False
        self._bus = ""           # имя отдельного соединения с D-Bus, на котором держится запрет
        self._count = 0
        self._caffeinate: subprocess.Popen | None = None

    def set(self, on: bool) -> None:
        if on == self.active:
            return
        try:
            self._inhibit() if on else self._release()
            self.active = on
        except Exception as e:  # noqa: BLE001 — нет D-Bus, нет сервиса: экран просто будет гаснуть, как раньше
            log.warning("Не удалось %s блокировку экрана: %s", "запретить" if on else "вернуть", e)
            self.active = on

    def _inhibit(self) -> None:
        if sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        elif sys.platform == "darwin":
            self._caffeinate = subprocess.Popen(["caffeinate", "-d", "-i", "-w", str(os.getpid())])
        else:
            self._count += 1
            self._bus = f"parley-awake-{self._count}"
            _dbus_inhibit(self._bus)

    def _release(self) -> None:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        elif sys.platform == "darwin":
            if self._caffeinate:
                self._caffeinate.terminate()
                self._caffeinate = None
        elif self._bus:
            from PySide6.QtDBus import QDBusConnection
            QDBusConnection.disconnectFromBus(self._bus)  # соединение закрыто — запрет снят
            self._bus = ""


def _dbus_inhibit(bus: str) -> None:
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    connection = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, bus)
    if not connection.isConnected():
        raise RuntimeError("нет сессионной шины D-Bus")
    errors = []
    for path in ("/org/freedesktop/ScreenSaver", "/ScreenSaver"):  # разные реализации — разный путь
        reply = QDBusInterface("org.freedesktop.ScreenSaver", path, "org.freedesktop.ScreenSaver",
                               connection).call("Inhibit", "Parley", REASON)
        if reply.arguments() and reply.errorName() == "":
            log.info("Экран не погаснет, пока идёт разговор")
            return
        errors.append(f"{path}: {reply.errorMessage() or 'нет ответа'}")
    QDBusConnection.disconnectFromBus(bus)
    raise RuntimeError("; ".join(errors))
