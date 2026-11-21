"""NixOS: Qt из колеса PySide6 ищет системные библиотеки, а на NixOS их нет в стандартных путях.

Большую часть даёт nix-ld, но не всё (часто не хватает libgssapi_krb5 и libbrotlidec).
Пробуем загрузить QML; если какой-то библиотеки не хватает — находим её в /nix/store и
загружаем заранее: когда Qt попросит библиотеку с тем же именем, загрузчик возьмёт уже загруженную.

Насовсем это решается добавлением пакетов в programs.nix-ld.libraries (krb5, brotli) в конфигурации NixOS.
"""

from __future__ import annotations

import ctypes
import glob
import importlib
import logging
import os
import re

log = logging.getLogger(__name__)

_MISSING = re.compile(r"(lib[\w.+-]+\.so[\d.]*): cannot open shared object file")


def make_qt_loadable() -> None:
    if not os.path.exists("/etc/NIXOS"):
        return
    for _ in range(12):
        try:
            importlib.import_module("PySide6.QtQml")
            return
        except ImportError as e:
            match = _MISSING.search(str(e))
            if not match or not _preload(match.group(1)):
                raise
    raise ImportError("Не удалось подобрать библиотеки для Qt (см. interfaces/gui/nixos.py)")


def _preload(library: str) -> bool:
    for path in sorted(glob.glob(f"/nix/store/*/lib/{library}"), reverse=True):
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            log.debug("Подгрузил %s", path)
            return True
        except OSError:
            continue
    log.error("Нет %s в /nix/store — добавь пакет с ней в programs.nix-ld.libraries", library)
    return False
