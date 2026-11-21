"""Запуск окна: шрифт, стиль, иконка в трее, QML."""

from __future__ import annotations

import os
import signal
from pathlib import Path

from .nixos import make_qt_loadable

# Системные настройки Qt рассчитаны на системный Qt, а не на Qt из колеса PySide6:
# чужие плагины и стиль «adwaita-dark» ломают загрузку QML. Убираем до импорта PySide6.
for _name in ("QT_PLUGIN_PATH", "QT_STYLE_OVERRIDE", "QT_QPA_PLATFORMTHEME", "QT_QUICK_CONTROLS_STYLE"):
    os.environ.pop(_name, None)
# Безвредный шум Wayland и порталов в терминале не нужен.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false;qt.qpa.services=false")
make_qt_loadable()

from PySide6.QtCore import QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction, QColor, QFontDatabase, QIcon, QLinearGradient, QPainter, QPixmap, QSurfaceFormat  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from ...application.commands import ToggleEars  # noqa: E402
from ...bootstrap import build  # noqa: E402
from ...config import Settings  # noqa: E402
from .bridge import Bridge  # noqa: E402

HERE = Path(__file__).parent


def prepare_qt() -> None:
    """До создания QApplication: стиль контролов и сглаживание (MSAA) для круглых форм Пипа."""
    QQuickStyle.setStyle("Basic")
    surface = QSurfaceFormat.defaultFormat()
    surface.setSamples(4)
    QSurfaceFormat.setDefaultFormat(surface)


def load_fonts() -> None:
    for font in sorted((HERE / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font))


def quit_on_signals(qt: QApplication) -> QTimer:
    """Ctrl+C и kill завершают программу. Пока крутится цикл Qt, Python не видит сигналы —
    таймер раз в 200 мс отдаёт ему управление, чтобы обработчик успел сработать."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: qt.quit())
    timer = QTimer(interval=200, timeout=lambda: None)
    timer.start()
    return timer


def run(settings: Settings) -> int:
    prepare_qt()
    qt = QApplication([])
    qt.setApplicationName("Parley")
    qt.setDesktopFileName("parley")
    qt.setWindowIcon(_icon())
    load_fonts()
    signals = quit_on_signals(qt)

    app = build(settings)
    app.start()
    bridge = Bridge(app)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("parley", bridge)
    engine.addImportPath(str(HERE / "qml"))
    engine.load(HERE / "qml" / "Main.qml")
    if not engine.rootObjects():
        app.stop()
        return 1
    window = engine.rootObjects()[0]

    tray = _tray(qt, app, window) if QSystemTrayIcon.isSystemTrayAvailable() else None
    qt.setQuitOnLastWindowClosed(True)  # закрыл окно — программа завершилась

    code = qt.exec()
    app.stop()
    del engine, bridge, tray, signals
    return code


def _tray(qt: QApplication, app, window) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_icon(), qt)
    tray.setToolTip("Parley")
    menu = QMenu()
    show = QAction("Show Parley", menu, triggered=lambda: (window.show(), window.raise_(), window.requestActivate()))
    ears = QAction("Mic on / off", menu, triggered=lambda: app.commands.execute(ToggleEars()))
    quit_ = QAction("Quit", menu, triggered=qt.quit)
    menu.addActions([show, ears])
    menu.addSeparator()
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window.setVisible(not window.isVisible())
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    tray.setProperty("menu", menu)  # меню должно жить столько же, сколько иконка
    return tray


def _icon() -> QIcon:
    """Иконка — голова Пипа, нарисованная кодом (без файлов-картинок)."""
    size = 128
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    shell = QLinearGradient(0, 14, 0, 116)
    shell.setColorAt(0, QColor("#fbf9f4"))
    shell.setColorAt(1, QColor("#bdb6a8"))
    p.setBrush(shell)
    p.drawRoundedRect(QRectF(6, 20, 116, 90), 36, 36)
    p.setBrush(QColor("#121318"))
    p.drawRoundedRect(QRectF(18, 32, 92, 64), 27, 27)
    p.setBrush(QColor("#8ee9ff"))
    p.drawRoundedRect(QRectF(40, 46, 14, 22), 6, 6)
    p.drawRoundedRect(QRectF(74, 46, 14, 22), 6, 6)
    for i in range(5):
        p.drawEllipse(QRectF(51 + i * 6.5 - 2, 80 - (4 - (i - 2) ** 2) * 0.6, 4, 4))
    p.end()
    return QIcon(pixmap)
