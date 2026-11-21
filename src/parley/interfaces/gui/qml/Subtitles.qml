// Реплика Пипа — крупно и жирно. Уже произнесённая часть яркая, ещё не произнесённая — бледная.
// Текст всегда целиком: длинная реплика мельче и прокручивается вслед за голосом (колесом — назад).
// Реплика остаётся на экране, пока не начнётся следующая. Когда сказать нечего — подсказка.
import QtQuick

Item {
    id: root
    property string speech: ""         // реплика Пипа
    property int spoken: 0             // сколько символов реплики уже прозвучало
    property string hint: ""           // подсказка, когда говорить нечего
    property bool compact: false       // открыта доска — шрифт помельче
    property bool centered: false      // текст по центру (когда доски нет)

    // Чем длиннее реплика, тем мельче шрифт: короткая — крупно, объяснение на полминуты — читаемо.
    readonly property int size: {
        const base = compact ? Theme.speechSizeCompact : Theme.speechSize
        const n = speech.length
        return n < 90 ? base : n < 180 ? Math.round(base * 0.8) : n < 320 ? Math.round(base * 0.65)
                                                                           : Math.round(base * 0.55)
    }

    function safe(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;") }

    Flickable {
        id: scroller
        anchors.fill: parent
        visible: root.speech.length > 0
        clip: true
        contentWidth: width
        contentHeight: line.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        property bool userScrolled: false   // крутили колесом — не дёргаем текст, пока не начнётся новая реплика

        // Держим в поле зрения произносимое место: доля прозвучавшего ≈ доля высоты текста.
        readonly property real target: {
            if (root.speech.length === 0 || contentHeight <= height) return 0
            const at = contentHeight * root.spoken / root.speech.length
            return Math.max(0, Math.min(contentHeight - height, at - height * 0.45))
        }
        onTargetChanged: if (!userScrolled) contentY = target
        Behavior on contentY { enabled: !scroller.moving; NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }
        onMovingChanged: if (moving) userScrolled = true

        Text {
            id: line
            width: scroller.width
            wrapMode: Text.Wrap
            horizontalAlignment: root.centered ? Text.AlignHCenter : Text.AlignLeft
            textFormat: Text.StyledText
            text: "<font color='" + Theme.text + "'>" + root.safe(root.speech.slice(0, root.spoken)) + "</font>"
                  + "<font color='" + Theme.textFaint + "'>" + root.safe(root.speech.slice(root.spoken)) + "</font>"
            font.family: Theme.font
            font.pixelSize: root.size
            font.weight: Font.Black
            lineHeight: 1.04
            Behavior on font.pixelSize { NumberAnimation { duration: Theme.fast } }
        }
    }
    onSpeechChanged: { scroller.userScrolled = false; scroller.contentY = 0 }

    Text {
        id: hintText
        width: root.width
        visible: root.speech.length === 0 && root.hint.length > 0
        wrapMode: Text.Wrap
        horizontalAlignment: root.centered ? Text.AlignHCenter : Text.AlignLeft
        text: root.hint
        color: Theme.textMuted
        font.family: Theme.font
        font.pixelSize: 18
        font.weight: Font.Medium
        lineHeight: 1.2
    }
}
