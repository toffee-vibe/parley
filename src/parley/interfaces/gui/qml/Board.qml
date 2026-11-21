// Доска с объяснением: заголовок + Markdown (таблицы, списки, жирный, код).
// Закрывается крестиком или когда Claude вызывает hide_board.
// Таблицы и выделения раскрашивает Python (bridge.styleBoard): у Qt свой Markdown выглядит слишком сыро.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects

Item {
    id: root

    property string title: ""
    property string markdown: ""
    signal closeRequested()
    signal contentChanged(var document)   // документ готов к раскраске
    // Не по textChanged: раскраска сама меняет документ, и вышел бы бесконечный цикл
    onMarkdownChanged: Qt.callLater(() => root.contentChanged(content.textDocument))

    RectangularShadow {
        anchors.fill: panel
        offset.y: 16
        blur: 48
        radius: panel.radius
        color: Theme.shadow
    }

    Rectangle {
        id: panel
        anchors.fill: parent
        radius: Theme.radius + 4
        color: Theme.surface
        border.color: Theme.border

        Text {
            id: label
            anchors { left: parent.left; top: parent.top; leftMargin: 32; topMargin: 28 }
            text: "BOARD"
            color: Theme.speaking
            font.family: Theme.font
            font.pixelSize: Theme.labelSize
            font.weight: Font.ExtraBold
            font.letterSpacing: 1.6
        }

        Text {
            id: heading
            anchors { left: parent.left; right: close.left; top: label.bottom; leftMargin: 32; rightMargin: 12; topMargin: 6 }
            text: root.title
            wrapMode: Text.Wrap
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.boardTitleSize
            font.weight: Font.ExtraBold
            font.letterSpacing: -0.3
        }

        Rectangle { // крестик
            id: close
            width: 36; height: 36; radius: 18
            anchors { right: parent.right; top: parent.top; margins: 20 }
            color: closeMouse.containsMouse ? Theme.surfaceHover : "transparent"
            Icon { anchors.centerIn: parent; path: Icons.close; size: 18; color: Theme.textMuted }
            MouseArea {
                id: closeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.closeRequested()
            }
        }

        ScrollView {
            id: scroll
            anchors { left: parent.left; right: parent.right; top: heading.bottom; bottom: parent.bottom
                      leftMargin: 32; rightMargin: 24; topMargin: 18; bottomMargin: 24 }
            clip: true
            contentWidth: availableWidth

            TextEdit {
                id: content
                width: scroll.availableWidth - 8
                readOnly: true
                selectByMouse: true
                textFormat: TextEdit.MarkdownText
                text: root.markdown
                wrapMode: TextEdit.Wrap
                color: Theme.boardText
                selectionColor: Theme.selection
                font.family: Theme.font
                font.pixelSize: Theme.boardTextSize
                font.weight: Font.Medium
            }
        }
    }
}
