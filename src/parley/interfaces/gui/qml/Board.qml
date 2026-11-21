// Доска с объяснением: заголовок + Markdown (таблицы, списки, жирный, код). Плоская карточка без теней.
// Закрывается крестиком, клавишей Esc или когда Claude вызывает hide_board.
// Таблицы и выделения докрашивает Python (bridge.styleBoard): у Qt свой Markdown выглядит слишком сыро.
import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root

    property string title: ""
    property string markdown: ""
    signal closeRequested()
    signal contentChanged(var document)   // документ готов к раскраске
    // Не по textChanged: раскраска сама меняет документ, и вышел бы бесконечный цикл.
    // Смена темы тоже перекрашивает доску.
    onMarkdownChanged: Qt.callLater(() => root.contentChanged(content.textDocument))
    Connections { target: Theme; function onDarkChanged() { Qt.callLater(() => root.contentChanged(content.textDocument)) } }

    radius: Theme.radius
    color: Theme.surface

    Text {
        id: heading
        anchors { left: parent.left; right: close.left; top: parent.top; leftMargin: 28; rightMargin: 12; topMargin: 24 }
        text: root.title
        wrapMode: Text.Wrap
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.boardTitleSize
        font.weight: Font.Black
        lineHeight: 0.95
    }

    Rectangle { // крестик
        id: close
        width: 40; height: 40; radius: 20
        anchors { right: parent.right; top: parent.top; margins: 20 }
        color: closeMouse.containsMouse ? Theme.surfaceHover : "transparent"
        Icon { anchors.centerIn: parent; path: Icons.close; size: 20; color: Theme.text }
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
                  leftMargin: 28; rightMargin: 20; topMargin: 18; bottomMargin: 24 }
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
            selectedTextColor: Theme.text
            font.family: Theme.font
            font.pixelSize: Theme.boardTextSize
        }
    }
}
