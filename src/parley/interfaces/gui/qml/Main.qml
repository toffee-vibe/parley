// Главное окно: Пип, субтитры и панель внизу (микрофон, громкость).
// Когда Claude показывает доску — Пип отходит влево и смотрит на неё.
// Клик по Пипу или клавиша M — микрофон вкл/выкл; ↑/↓ — громкость.
// Данные приходят из Python-объекта `parley` (interfaces/gui/bridge.py).
import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import QtQuick.Window

Window {
    id: window
    width: 980
    height: 700
    minimumWidth: 480
    minimumHeight: 560
    visible: true
    title: "Parley"
    color: Theme.background

    readonly property bool boardOpen: parley.boardOpen
    readonly property bool wide: width >= 800
    readonly property real margin: 28
    readonly property real dockSpace: 104      // место под панелью внизу

    // ---------- фон: мягкий свет в центре и отсвет цвета состояния под Пипом ----------
    Shape {
        anchors.fill: parent
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: pipColumn.x + pipColumn.width / 2; centerY: window.height * 0.34
                focalX: centerX; focalY: centerY
                centerRadius: Math.max(window.width, window.height) * 0.62
                GradientStop { position: 0; color: Theme.backgroundCenter }
                GradientStop { position: 1; color: Theme.background }
            }
            PathRectangle { width: window.width; height: window.height }
        }
    }
    Rectangle {
        id: ambient
        width: pip.size * 0.9; height: width * 0.45; radius: height / 2
        x: pipColumn.x + pip.x + (pip.width - width) / 2
        y: pipColumn.y + pip.y + pip.height * 0.72 - height / 2
        color: Theme.stateColor(parley.activity)
        opacity: parley.activity === "idle" ? 0.04 : 0.08
        Behavior on color { ColorAnimation { duration: Theme.normal } }
        Behavior on opacity { NumberAnimation { duration: Theme.normal } }
        layer.enabled: true
        layer.effect: MultiEffect { blurEnabled: true; blur: 1; blurMax: 64 }
    }

    // ---------- верхняя строка: Claude подключён? ----------
    Row {
        anchors { left: parent.left; top: parent.top; margins: 22 }
        spacing: 8
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 7; height: 7; radius: 3.5
            color: parley.claudeOnline ? Theme.listening : Theme.textFaint
        }
        Text {
            text: parley.claudeOnline ? "Claude connected" : "Waiting for Claude"
            color: Theme.textFaint
            font.family: Theme.font
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }

    // ---------- колонка Пипа: в центре или слева от доски ----------
    Item {
        id: pipColumn
        readonly property bool aside: window.boardOpen && window.wide
        readonly property bool above: window.boardOpen && !window.wide
        x: aside ? window.margin : 0
        y: 0
        width: aside ? window.width * 0.36 : window.width
        height: above ? window.height * 0.32 : window.height - window.dockSpace
        Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.InOutCubic } }
        Behavior on width { NumberAnimation { duration: Theme.slow; easing.type: Easing.InOutCubic } }
        Behavior on height { NumberAnimation { duration: Theme.slow; easing.type: Easing.InOutCubic } }

        Pip {
            id: pip
            readonly property real size: Math.min(pipColumn.width * 0.9, pipColumn.height * (pipColumn.above ? 1 : 0.6), 400)
            width: size
            height: size
            anchors.horizontalCenter: parent.horizontalCenter
            y: pipColumn.above ? 0 : pipColumn.height * 0.37 - size / 2
            Behavior on y { NumberAnimation { duration: Theme.slow; easing.type: Easing.InOutCubic } }

            activity: parley.activity
            mood: parley.mood
            hearingLevel: parley.hearingLevel
            voiceLevel: parley.voiceLevel
            pointing: window.boardOpen && parley.activity !== "deaf"
            lookX: look.hovered ? Math.max(-1, Math.min(1, (look.point.position.x - window.width / 2) / (window.width / 2))) : 0
            lookY: look.hovered ? Math.max(-1, Math.min(1, (look.point.position.y - window.height / 3) / window.height)) : 0

            MouseArea { // клик по Пипу — микрофон вкл/выкл
                anchors.centerIn: parent
                width: parent.size * 0.6; height: parent.size * 0.7
                cursorShape: Qt.PointingHandCursor
                onClicked: parley.toggleEars()
            }
        }

        Subtitles {
            visible: !pipColumn.above
            anchors { top: pip.bottom; topMargin: -pip.size * 0.02; horizontalCenter: parent.horizontalCenter }
            width: Math.min(pipColumn.width * 0.84, 720)
            heard: parley.heardText
            speech: parley.speechText
            spoken: parley.speechSpoken
            hint: parley.activity === "deaf" ? "Mic is off — I can't hear you. Press M or click me."
                : !parley.cloudReady ? "No OpenRouter key — add it to ~/.config/parley/config.toml"
                : !parley.claudeOnline ? "Start claude and say “let's practice English”"
                : "I'm listening. Say anything — English or Russian."
        }
    }

    // ---------- доска ----------
    Board {
        id: board
        title: parley.boardTitle
        markdown: parley.boardMarkdown
        width: window.wide ? window.width * 0.6 - window.margin : window.width - window.margin * 2
        height: window.wide ? window.height - window.margin * 2 - window.dockSpace + 20
                            : window.height * 0.68 - window.margin - window.dockSpace + 20
        y: window.wide ? window.margin : window.height * 0.32
        x: window.boardOpen ? window.width - width - window.margin : window.width + 60
        opacity: window.boardOpen ? 1 : 0
        Behavior on x { NumberAnimation { duration: Theme.slow; easing.type: Easing.InOutCubic } }
        Behavior on opacity { NumberAnimation { duration: Theme.normal } }
        onCloseRequested: parley.hideBoard()
        onContentChanged: (document) => parley.styleBoard(document, {
            text: Theme.text, accent: Theme.speaking, code: Theme.listening,
            line: Theme.border, muted: Theme.textMuted
        })
    }

    // ---------- панель внизу ----------
    Dock {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 26 }
        activity: parley.activity
        volume: parley.volume
        onToggleEars: parley.toggleEars()
        onVolumeMoved: (value) => parley.volume = value
    }

    HoverHandler { id: look }  // глаза Пипа следят за курсором

    Shortcut { sequence: "M"; onActivated: parley.toggleEars() }
    Shortcut { sequence: "Up"; onActivated: parley.volume = Math.min(1, parley.volume + 0.05) }
    Shortcut { sequence: "Down"; onActivated: parley.volume = Math.max(0, parley.volume - 0.05) }
    Shortcut { sequence: "Escape"; enabled: window.boardOpen; onActivated: parley.hideBoard() }
    Shortcut { sequences: [StandardKey.Quit, "Ctrl+Q"]; onActivated: Qt.quit() }

    Connections {
        target: parley
        function onSoundHeard() { pip.startle() }
    }
}
