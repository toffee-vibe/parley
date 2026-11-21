// Твоя фраза — серое облачко, как в мессенджере. Растёт по мере того, как распознаётся, и остаётся,
// пока ты не скажешь следующую. Текст целиком: длинный прокручивается, видно всегда последние слова.
import QtQuick

Rectangle {
    id: root
    property string text: ""
    property real maxWidth: 400
    property real maxHeight: 160

    visible: text.length > 0
    width: Math.min(label.implicitWidth + 36, maxWidth)
    height: Math.min(label.implicitHeight + 24, maxHeight)
    radius: Math.min(22, height / 2)
    color: Theme.surface

    Flickable {
        id: scroller
        anchors { fill: parent; leftMargin: 18; rightMargin: 18; topMargin: 12; bottomMargin: 12 }
        clip: true
        contentWidth: width
        contentHeight: label.height
        boundsBehavior: Flickable.StopAtBounds
        // Новые слова — внизу: держим низ в поле зрения
        onContentHeightChanged: contentY = Math.max(0, contentHeight - height)

        Text {
            id: label
            width: Math.min(implicitWidth, root.maxWidth - 36)
            wrapMode: Text.Wrap
            text: root.text
            color: Theme.textMuted
            font.family: Theme.font
            font.pixelSize: Theme.heardSize
            font.weight: Font.Medium
        }
    }
}
