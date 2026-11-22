// Главное окно — «белый лист» (или тёмный): плоско, крупный жирный шрифт, никаких теней.
//   шапка: «parley», какой агент на связи (Claude Code, opencode, Codex…), переключатель темы
//   сцена: Пип по центру, над ним твоя фраза серым облачком, под ним его реплика — крупно
//   низ: «пилюли» микрофона и громкости, тоже по центру
// Когда агент показывает доску — всё уезжает влево, доска выезжает справа, Пип смотрит на неё.
// Клавиши: M — микрофон, ↑/↓ — громкость, T — тема, Esc — закрыть доску, Ctrl+Q — выход.
// Данные приходят из Python-объекта `parley` (interfaces/gui/bridge.py).
import QtQuick
import QtQuick.Window

Window {
    id: window
    width: 980
    height: 700
    minimumWidth: 540
    minimumHeight: 560
    visible: true
    title: "Parley"
    color: Theme.background
    Behavior on color { ColorAnimation { duration: Theme.normal } }

    readonly property bool boardOpen: parley.boardOpen
    readonly property bool wide: width >= 800
    readonly property real margin: 32
    readonly property bool centered: !boardOpen   // сбоку ничего нет — Пип и панель по центру

    Binding { target: Theme; property: "dark"; value: parley.darkTheme }

    // ---------- шапка ----------
    Text {
        x: window.margin; y: 24
        text: "parley"
        color: Theme.text
        font.family: Theme.font
        font.pixelSize: Theme.wordmarkSize
        font.weight: Font.Black
    }
    Row {
        anchors { right: parent.right; rightMargin: window.margin }
        y: 22
        spacing: 10
        Rectangle { // Claude на связи?
            anchors.verticalCenter: parent.verticalCenter
            height: 34; radius: 17
            width: claude.implicitWidth + 28
            color: parley.claudeOnline ? Theme.okBg : Theme.surface
            Text {
                id: claude
                anchors.centerIn: parent
                text: parley.claudeOnline ? "● " + parley.agentName + " на связи" : "○ Жду агента"
                color: parley.claudeOnline ? Theme.ok : Theme.textMuted
                font.family: Theme.font
                font.pixelSize: 14
                font.weight: Font.Bold
            }
        }
        Rectangle { // тема
            width: 38; height: 38; radius: 19
            color: themeMouse.containsMouse ? Theme.surfaceHover : Theme.surface
            Icon { anchors.centerIn: parent; path: Theme.dark ? Icons.sun : Icons.moon; size: 18; color: Theme.text }
            MouseArea {
                id: themeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: parley.darkTheme = !parley.darkTheme
            }
        }
    }

    // ---------- сцена ----------
    Item {
        id: stage
        x: window.margin
        y: 84
        width: (window.boardOpen && window.wide ? window.width * 0.42 : window.width) - window.margin * 2
        height: window.height - y - 110
        visible: !(window.boardOpen && !window.wide)
        Behavior on width { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutBack; easing.overshoot: 0.6 } }

        HeardBubble {
            id: bubble
            x: window.centered ? (stage.width - width) / 2 : stage.width - width
            text: parley.heardText
            maxWidth: stage.width * (window.centered ? 0.7 : 0.8)
            maxHeight: Math.max(90, stage.height * 0.22)
            Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
        }

        Pip {
            id: pip
            readonly property real size: window.boardOpen ? 220 : Math.min(280, stage.width * 0.5)
            x: window.centered ? (stage.width - width) / 2 : 0
            y: Math.max(64, bubble.visible ? bubble.height + 20 : 0)
            Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }
            width: size; height: size * 0.62
            Behavior on width { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutBack } }

            activity: parley.activity
            mood: parley.mood
            hearingLevel: parley.hearingLevel
            voiceLevel: parley.voiceLevel
            pointing: window.boardOpen && parley.activity !== "deaf"
            lookX: look.hovered ? Math.max(-1, Math.min(1, (look.point.position.x - pip.x - pip.width / 2) / (window.width / 2))) : 0
            lookY: look.hovered ? Math.max(-1, Math.min(1, (look.point.position.y - stage.y - pip.y - pip.height / 2) / window.height)) : 0

            MouseArea { // клик по Пипу — микрофон вкл/выкл
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: parley.toggleEars()
            }
        }

        Text { // что Пип делает сейчас: по центру — под ним, сбоку — справа от него
            id: stateLabel
            x: window.centered ? (stage.width - width) / 2 : pip.x + pip.width + 16
            y: window.centered ? pip.y + pip.height + 8 : pip.y + (pip.height - height) / 2
            Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
            text: ({ waiting: "жду агента", idle: "готов", hearing: "слушаю…", thinking: "думаю…",
                     speaking: "говорю", deaf: "микрофон выключен" })[parley.activity] || ""
            color: Theme.pipColor(parley.activity, "neutral")
            font.family: Theme.font
            font.pixelSize: Theme.labelSize
            font.weight: Font.Black
            Behavior on color { ColorAnimation { duration: Theme.normal } }
        }

        Subtitles {
            y: (window.centered ? stateLabel.y + stateLabel.height : pip.y + pip.height) + 18
            width: stage.width
            height: stage.height - y
            centered: window.centered
            compact: window.boardOpen
            speech: parley.speechText
            spoken: parley.speechSpoken
            hint: !parley.cloudReady ? "Нет ключа OpenRouter — впиши его в ~/.config/parley/config.toml и перезапусти."
                : parley.activity === "deaf" ? "Микрофон выключен — я тебя не слышу. Нажми M или на меня."
                : parley.activity === "waiting" ? "Жду агента: в папке parley запусти агента (claude, kimi, codex, opencode, agy) и скажи «let's practice English». Пока его нет, микрофон выключен."
                : "Слушаю. Говори по-английски или по-русски."
        }
    }

    // ---------- доска ----------
    Board {
        id: board
        title: parley.boardTitle
        markdown: parley.boardMarkdown
        y: 84
        width: window.wide ? window.width * 0.58 - window.margin : window.width - window.margin * 2
        height: window.height - y - 110
        x: window.boardOpen ? window.width - width - window.margin : window.width + 60
        Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutBack; easing.overshoot: 0.6 } }
        onCloseRequested: parley.hideBoard()
        onContentChanged: (document) => parley.styleBoard(document, {
            text: Theme.text, accent: Theme.speaking, code: Theme.idle, line: Theme.line, muted: Theme.textMuted
        })
    }

    // ---------- управление ----------
    Dock {
        id: dock
        x: window.centered ? (window.width - width) / 2 : window.margin
        anchors { bottom: parent.bottom; bottomMargin: 28 }
        Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
        activity: parley.activity
        volume: parley.volume
        onToggleEars: parley.toggleEars()
        onVolumeMoved: (value) => parley.volume = value
    }

    HoverHandler { id: look }  // Пип смотрит на курсор

    Shortcut { sequence: "M"; onActivated: parley.toggleEars() }
    Shortcut { sequence: "T"; onActivated: parley.darkTheme = !parley.darkTheme }
    Shortcut { sequence: "Up"; onActivated: parley.volume = Math.min(1, parley.volume + 0.05) }
    Shortcut { sequence: "Down"; onActivated: parley.volume = Math.max(0, parley.volume - 0.05) }
    Shortcut { sequence: "Escape"; enabled: window.boardOpen; onActivated: parley.hideBoard() }
    Shortcut { sequences: [StandardKey.Quit, "Ctrl+Q"]; onActivated: Qt.quit() }

    Connections {
        target: parley
        function onSoundHeard() { pip.startle() }
    }
}
