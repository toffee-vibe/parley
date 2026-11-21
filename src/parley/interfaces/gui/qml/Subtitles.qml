// Реплика Пипа — крупно и жирно. Уже произнесённая часть яркая, ещё не произнесённая — бледная.
// Когда сказать нечего — подсказка обычным шрифтом.
import QtQuick

Item {
    id: root
    property string speech: ""         // реплика Пипа
    property int spoken: 0             // сколько символов реплики уже прозвучало
    property string hint: ""           // подсказка, когда говорить нечего
    property bool compact: false       // открыта доска — шрифт помельче

    implicitHeight: speech.length ? line.implicitHeight : hintText.implicitHeight

    function safe(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;") }

    Text {
        id: line
        width: root.width
        visible: root.speech.length > 0
        wrapMode: Text.Wrap
        maximumLineCount: 5
        elide: Text.ElideRight
        textFormat: Text.StyledText
        text: "<font color='" + Theme.text + "'>" + root.safe(root.speech.slice(0, root.spoken)) + "</font>"
              + "<font color='" + Theme.textFaint + "'>" + root.safe(root.speech.slice(root.spoken)) + "</font>"
        font.family: Theme.font
        font.pixelSize: root.compact ? Theme.speechSizeCompact : Theme.speechSize
        font.weight: Font.Black
        lineHeight: 1.04
    }

    Text {
        id: hintText
        width: root.width
        visible: root.speech.length === 0 && root.hint.length > 0
        wrapMode: Text.Wrap
        text: root.hint
        color: Theme.textMuted
        font.family: Theme.font
        font.pixelSize: 18
        font.weight: Font.Medium
        lineHeight: 1.2
    }
}
