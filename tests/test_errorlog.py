"""Журнал запуска ловит все виды ошибок — каждую проверяем в отдельном процессе, как у живого пользователя."""

import subprocess
import sys
import textwrap

import pytest

from parley.errorlog import latest

PRELUDE = """
import logging, os, sys, threading, time
from pathlib import Path
from parley.errorlog import ErrorLog
ErrorLog(Path({folder!r})).install()
"""

CASES = {
    "запись лога": ("logging.getLogger('parley.x').error('broken pipe in mouth')", "broken pipe in mouth"),
    "C-библиотека пишет в stderr": (
        "os.write(2, b'[W:onnxruntime:, graph.cc:3490] Removing initializer\\n')", "Removing initializer"),
    "дочерний процесс": (
        "import subprocess; subprocess.run([sys.executable, '-c', 'import sys; sys.stderr.write(\"pw-play: no target\\\\n\")'])",
        "pw-play: no target"),
    "warnings": ("import warnings; warnings.warn('old API', DeprecationWarning, stacklevel=1)", "old API"),
    "упавший поток": ("t = threading.Thread(target=lambda: 1 / 0, name='mouth'); t.start(); t.join()",
                      "ZeroDivisionError"),
    "Exception ignored": (
        "class A:\n    def __del__(self): raise ValueError('in __del__')\nA()", "in __del__"),
    "asyncio": (
        "import asyncio\nasync def boom(): raise RuntimeError('lost task')\n"
        "async def main():\n    asyncio.get_running_loop().create_task(boom()); await asyncio.sleep(0.1)\n"
        "asyncio.run(main()); import gc; gc.collect()", "lost task"),
    "падение программы": ("raise KeyError('crash at startup')", "crash at startup"),
    # Linux/macOS: «Fatal Python error: Segmentation fault», Windows: «Windows fatal exception: access violation»
    "segfault": ("import ctypes; ctypes.string_at(0)", "atal"),
}


@pytest.mark.parametrize("case", CASES)
def test_every_kind_of_error_ends_up_in_the_log(case, tmp_path):
    code, expected = CASES[case]
    script = PRELUDE.format(folder=str(tmp_path)) + code + "\ntime.sleep(0.3)\n"
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
    log = latest(tmp_path)[0].read_text(encoding="utf-8", errors="replace")
    assert expected in log, f"{case}: нет в журнале\n{log}\n--- stderr ---\n{done.stderr}"
    if case not in ("segfault",):
        assert expected in done.stderr or case == "запись лога" and "broken pipe" in done.stderr  # и терминал видит


def test_qt_messages_go_to_the_log(tmp_path):
    script = PRELUDE.format(folder=str(tmp_path)) + textwrap.dedent("""
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from parley.interfaces.gui import app
        app.log_qt_messages()
        from PySide6.QtCore import qWarning
        qWarning("QML: Cannot assign to non-existent property")
        time.sleep(0.2)
    """)
    subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
    assert "Cannot assign to non-existent property" in latest(tmp_path)[0].read_text(encoding="utf-8")


def test_old_logs_are_removed(tmp_path):
    for i in range(25):
        (tmp_path / f"parley-20260101-0000{i:02d}.log").write_text("x")
    from parley.errorlog import ErrorLog
    log = ErrorLog(tmp_path, keep=5)
    log._forget_old()
    assert len(list(tmp_path.glob("parley-*.log"))) == 4  # + текущий = 5
