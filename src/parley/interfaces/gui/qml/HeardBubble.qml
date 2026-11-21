// Твоя последняя фраза — серое облачко, как в мессенджере. Исчезает, когда сказать нечего.
import QtQuick

Rectangle {
    id: root
    property string text: ""
    property real maxWidth: 400

    visible: text.length > 0
    width: Math.min(label.implicitWidth + 36, maxWidth)
    height: label.implicitHeight + 24
    radius: Math.min(22, height / 2)
    color: Theme.surface

    Text {
        id: label
        x: 18; y: 12
        width: Math.min(implicitWidth, root.maxWidth - 36)
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideLeft
        text: root.text
        color: Theme.textMuted
        font.family: Theme.font
        font.pixelSize: Theme.heardSize
        font.weight: Font.Medium
    }
}
