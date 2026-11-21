// Панель внизу: микрофон (слышит ли тебя Пип) и громкость его голоса.
// Клавиши: M — микрофон, ↑/↓ — громкость (задаются в Main.qml).
import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: dock

    property string activity: "idle"
    property real volume: 0.6
    signal toggleEars()
    signal volumeMoved(real value)

    readonly property bool deaf: activity === "deaf"
    readonly property color stateColor: Theme.stateColor(activity)

    width: row.implicitWidth + 16
    height: 60
    radius: height / 2
    color: Theme.surface
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 14

        // ---------- микрофон ----------
        Rectangle {
            id: micButton
            width: 44; height: 44; radius: 22
            anchors.verticalCenter: parent.verticalCenter
            color: dock.deaf ? (micMouse.containsMouse ? Theme.dangerHover : Theme.danger)
                             : (micMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceRaised)
            border.color: dock.deaf ? Theme.dangerBorder : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.fast } }

            Icon {
                anchors.centerIn: parent
                path: dock.deaf ? Icons.micOff : Icons.mic
                color: dock.deaf ? Theme.deaf : Theme.text
            }
            MouseArea {
                id: micMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: dock.toggleEars()
            }
            ToolTip.visible: micMouse.containsMouse
            ToolTip.delay: 600
            ToolTip.text: dock.deaf ? "Turn mic on (M)" : "Turn mic off (M) — Pip won't hear you"
        }

        // ---------- состояние ----------
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            width: 166
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 8; height: 8; radius: 4
                color: dock.stateColor
                Behavior on color { ColorAnimation { duration: Theme.normal } }
                SequentialAnimation on opacity {
                    running: dock.activity === "hearing" || dock.activity === "thinking"
                    loops: Animation.Infinite
                    onRunningChanged: if (!running) parent.opacity = 1
                    NumberAnimation { to: 0.35; duration: 520; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1; duration: 520; easing.type: Easing.InOutSine }
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: 150
                elide: Text.ElideRight
                text: ({ waiting: "Waiting for Claude", idle: "Ready", hearing: "Listening", thinking: "Thinking", speaking: "Speaking",
                         deaf: "Mic off" })[dock.activity] || dock.activity
                color: dock.deaf ? Theme.deaf : Theme.textMuted
                font.family: Theme.font
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
        }

        Rectangle { width: 1; height: 26; color: Theme.border; anchors.verticalCenter: parent.verticalCenter }

        // ---------- громкость ----------
        Item {
            width: 30; height: 30
            anchors.verticalCenter: parent.verticalCenter
            Icon {
                anchors.centerIn: parent
                path: dock.volume === 0 ? Icons.speakerOff : dock.volume < 0.5 ? Icons.speakerLow : Icons.speaker
                color: speakerMouse.containsMouse ? Theme.text : Theme.textMuted
            }
            property real remembered: 0.6
            MouseArea { // клик — выключить звук / вернуть как было
                id: speakerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (dock.volume > 0) { parent.remembered = dock.volume; dock.volumeMoved(0) }
                    else dock.volumeMoved(parent.remembered || 0.6)
                }
            }
        }

        Slider {
            id: slider
            anchors.verticalCenter: parent.verticalCenter
            width: 132
            from: 0; to: 1
            value: dock.volume
            onMoved: dock.volumeMoved(value)
            background: Rectangle {
                x: slider.leftPadding
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.availableWidth
                height: 4
                radius: 2
                color: Theme.surfaceHover
                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height
                    radius: 2
                    color: Theme.text
                }
            }
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.pressed ? 18 : 14
                height: width
                radius: width / 2
                color: Theme.text
                Behavior on width { NumberAnimation { duration: Theme.fast } }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            text: Math.round(dock.volume * 100)
            color: Theme.textFaint
            font.family: Theme.font
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
        }
    }
}
