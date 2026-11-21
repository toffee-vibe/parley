// Управление внизу: «пилюля» микрофона (слышит ли тебя Пип) и «пилюля» громкости его голоса.
// Клавиши: M — микрофон, ↑/↓ — громкость (задаются в Main.qml).
import QtQuick
import QtQuick.Controls.Basic

Row {
    id: dock

    property string activity: "idle"
    property real volume: 0.6
    signal toggleEars()
    signal volumeMoved(real value)

    readonly property bool deaf: activity === "deaf"
    spacing: 12

    // ---------- микрофон ----------
    Rectangle {
        height: 52; radius: 26
        width: micRow.implicitWidth + 40
        color: dock.deaf ? Theme.danger : Theme.action
        opacity: micMouse.containsMouse ? 0.88 : 1
        Behavior on color { ColorAnimation { duration: Theme.fast } }

        Row {
            id: micRow
            anchors.centerIn: parent
            spacing: 10
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                path: dock.deaf ? Icons.micOff : Icons.mic
                color: dock.deaf ? "#ffffff" : Theme.actionText
            }
            Text {
                text: dock.deaf ? "Микрофон выкл." : "Микрофон вкл."
                color: dock.deaf ? "#ffffff" : Theme.actionText
                font.family: Theme.font
                font.pixelSize: 16
                font.weight: Font.Bold
            }
        }
        MouseArea {
            id: micMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: dock.toggleEars()
        }
        ToolTip.visible: micMouse.containsMouse
        ToolTip.delay: 700
        ToolTip.text: dock.deaf ? "Включить микрофон (M)" : "Выключить микрофон (M) — Пип тебя не услышит"
    }

    // ---------- громкость ----------
    Rectangle {
        height: 52; radius: 26
        width: 300
        color: Theme.surface

        Item { // динамик: клик — без звука / вернуть как было
            id: speakerButton
            x: 12; width: 32; height: 32
            anchors.verticalCenter: parent.verticalCenter
            property real remembered: 0.6
            Icon {
                anchors.centerIn: parent
                path: dock.volume === 0 ? Icons.speakerOff : dock.volume < 0.5 ? Icons.speakerLow : Icons.speaker
                color: Theme.text
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (dock.volume > 0) { speakerButton.remembered = dock.volume; dock.volumeMoved(0) }
                    else dock.volumeMoved(speakerButton.remembered || 0.6)
                }
            }
        }

        Slider {
            id: slider
            x: 52; width: 190
            anchors.verticalCenter: parent.verticalCenter
            from: 0; to: 1
            value: dock.volume
            onMoved: dock.volumeMoved(value)
            background: Rectangle {
                x: slider.leftPadding
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.availableWidth
                height: 12; radius: 6
                color: Theme.track
                Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: 6; color: Theme.action }
            }
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.pressed ? 28 : 24; height: width; radius: width / 2
                color: Theme.action
                Behavior on width { NumberAnimation { duration: Theme.fast } }
            }
        }

        Text {
            anchors { right: parent.right; rightMargin: 18; verticalCenter: parent.verticalCenter }
            text: Math.round(dock.volume * 100)
            color: Theme.text
            font.family: Theme.font
            font.pixelSize: 16
            font.weight: Font.Black
            font.features: { "tnum": 1 }
        }
    }
}
