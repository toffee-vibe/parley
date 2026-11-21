"""Оформление доски. Qt сам разбирает Markdown, но таблицы рисует серой сеткой, а выделения — никак.
Здесь документ доски докрашивается: таблица — строки с тонкими разделителями и шапкой,
**жирное** — яркое, *курсив* (примеры на английском) — акцентным цветом, `код` — моноширинным.
"""

from __future__ import annotations

from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFrame,
    QTextFrameFormat,
    QTextLength,
    QTextTable,
)

CELL_PADDING = 10


def style_board(document: QTextDocument, colors: dict[str, str]) -> None:
    for table in _tables(document.rootFrame()):
        _style_table(table, colors)
    _style_text(document, colors)


def _tables(frame: QTextFrame) -> list[QTextTable]:
    found = []
    for child in frame.childFrames():
        if isinstance(child, QTextTable):
            found.append(child)
        found += _tables(child)
    return found


def _style_table(table: QTextTable, colors: dict[str, str]) -> None:
    fmt = table.format()
    fmt.setBorder(0)
    fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_None)
    fmt.setCellSpacing(0)
    fmt.setCellPadding(CELL_PADDING)
    fmt.setBorderCollapse(True)
    fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
    fmt.setTopMargin(6)
    fmt.setBottomMargin(16)
    table.setFormat(fmt)

    line = QBrush(QColor(colors["line"]))
    for row in range(table.rows()):
        for column in range(table.columns()):
            cell = table.cellAt(row, column)
            cell_fmt = cell.format().toTableCellFormat()
            cell_fmt.setBottomBorder(1)
            cell_fmt.setBottomBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            cell_fmt.setBottomBorderBrush(line)
            for side in ("Top", "Left", "Right"):
                getattr(cell_fmt, f"set{side}Border")(0)
            if row == 0:  # шапка — приглушённая, без заливки (Qt заливает ячейки с зазорами)
                cell_fmt.setForeground(QColor(colors["muted"]))
            cell.setFormat(cell_fmt)


def _style_text(document: QTextDocument, colors: dict[str, str]) -> None:
    """Сначала собираем куски, потом красим: правка во время обхода сбивает итераторы Qt."""
    spans: list[tuple[int, int, QTextCharFormat]] = []
    block = document.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            current = fragment.charFormat()
            fmt = QTextCharFormat()
            if current.fontFixedPitch() or "mono" in (current.fontFamilies() or [""])[0].lower():
                fmt.setForeground(QColor(colors["code"]))
                fmt.setFontFamilies(["monospace"])
            elif current.fontItalic():
                fmt.setForeground(QColor(colors["accent"]))
            elif current.fontWeight() >= QFont.Weight.DemiBold:
                fmt.setForeground(QColor(colors["text"]))
            else:
                it += 1
                continue
            spans.append((fragment.position(), fragment.position() + fragment.length(), fmt))
            it += 1
        block = block.next()

    cursor = QTextCursor(document)
    for start, end, fmt in spans:
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(fmt)
