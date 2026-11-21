// Субтитры под Пипом: что он услышал от тебя и что говорит сейчас.
// Уже произнесённая часть реплики яркая, ещё не произнесённая — приглушённая.
import QtQuick

Column {
    id: root

    property string heard: ""          // последняя фраза пользователя
    property string speech: ""         // реплика Пипа
    property int spoken: 0             // сколько символов реплики уже прозвучало
    property string hint: ""           // подсказка, когда говорить нечего

    spacing: 16

    function safe(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;") }

    Text { // ты
        width: root.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideLeft
        textFormat: Text.StyledText
        visible: root.heard.length > 0
        text: "<font color='" + Theme.textFaint + "'>YOU&nbsp;&nbsp;</font>" + root.safe(root.heard)
        font.family: Theme.font
        font.pixelSize: Theme.heardSize
        font.weight: Font.Medium
        color: Theme.textMuted
    }

    Text { // Пип
        width: root.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        maximumLineCount: 5
        elide: Text.ElideRight
        textFormat: Text.StyledText
        visible: root.speech.length > 0
        text: "<font color='" + Theme.text + "'>" + root.safe(root.speech.slice(0, root.spoken)) + "</font>"
              + "<font color='" + Theme.textFaint + "'>" + root.safe(root.speech.slice(root.spoken)) + "</font>"
        font.family: Theme.font
        font.pixelSize: Theme.speechSize
        font.weight: Font.DemiBold
        font.letterSpacing: -0.2
        lineHeight: 1.2
    }

    Text { // подсказка
        width: root.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        visible: root.hint.length > 0 && root.heard.length === 0 && root.speech.length === 0
        text: root.hint
        font.family: Theme.font
        font.pixelSize: Theme.heardSize
        font.weight: Font.Medium
        color: Theme.textMuted
    }
}
