"""Оформление доски: таблица без сетки, выделения раскрашены. Без окна — только документ Qt."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from parley.interfaces.gui import app as _qt  # noqa: E402,F401,I001  (готовит Qt до импорта PySide6)
from PySide6.QtGui import QColor, QFont, QGuiApplication, QTextDocument, QTextTable  # noqa: E402

from parley.interfaces.gui.board_style import style_board  # noqa: E402

COLORS = {"text": "#ffffff", "accent": "#ffd38a", "code": "#6ff2c4", "line": "#2a2c33", "muted": "#9a9ca6"}
_app = QGuiApplication.instance() or QGuiApplication([])


def styled(markdown: str) -> QTextDocument:
    doc = QTextDocument()
    doc.setMarkdown(markdown)
    style_board(doc, COLORS)
    return doc


def color_of(doc: QTextDocument, word: str) -> str:
    cursor = doc.find(word)
    return cursor.charFormat().foreground().color().name()


def test_table_loses_grid_and_gets_padding():
    doc = styled("| A | B |\n|---|---|\n| x | y |\n")
    table = next(f for f in doc.rootFrame().childFrames() if isinstance(f, QTextTable))
    assert table.format().border() == 0
    assert table.format().cellPadding() > 0


def test_examples_bold_and_code_are_coloured():
    doc = styled("Say *I've been working*, not **I am work**. Use `since`.")
    assert color_of(doc, "been") == QColor(COLORS["accent"]).name()
    assert color_of(doc, "am") == QColor(COLORS["text"]).name()
    assert color_of(doc, "since") == QColor(COLORS["code"]).name()
    assert doc.find("Say").charFormat().fontWeight() < QFont.Weight.DemiBold
