// Пип — маленький парящий робот: корпус из тёплого пластика, тёмное стекло лица,
// светящиеся глаза и рот из пяти огоньков. Всё рисуется кодом: любой размер, плавные анимации.
//
// Входы:
//   activity      idle | hearing | thinking | speaking | deaf
//   mood          neutral | happy | curious | surprised | proud | thoughtful
//   hearingLevel  громкость микрофона (0..~0.3)
//   voiceLevel    громкость собственного голоса (0..~0.3)
//   lookX, lookY  куда смотреть (-1..1)
//   pointing      смотрит на доску справа
// Методы:
//   startle()     вздрогнуть (резкий звук)
//
// Язык тела, коротко:
//   глаза     — форма передаёт эмоцию: дуги ^ ^ (радость), круглые (удивление), прищур (раздумье), линии (сон)
//   рот       — пять огоньков: улыбка дугой, эквалайзер, когда говорит, бегущая волна, когда думает
//   уши       — полоски по бокам: светятся, когда слышит, красные, когда слух выключен
//   антенна   — огонёк состояния, пульсирует в такт твоему голосу
import QtQuick
import QtQuick.Effects

Item {
    id: pip

    property string activity: "idle"
    property string mood: "neutral"
    property real hearingLevel: 0
    property real voiceLevel: 0
    property real lookX: 0
    property real lookY: 0
    property bool pointing: false

    readonly property real s: Math.min(width, height)
    readonly property bool deaf: activity === "deaf"
    readonly property bool speaking: activity === "speaking"
    readonly property bool hearing: activity === "hearing"
    readonly property bool thinking: activity === "thinking"
    readonly property bool joyful: !deaf && (mood === "happy" || mood === "proud")
    readonly property bool surprised: !deaf && mood === "surprised"
    readonly property bool pensive: !deaf && (mood === "thoughtful" || thinking)
    readonly property real voice: Math.min(voiceLevel * 9, 1)
    readonly property real ear: Math.min(hearingLevel * 12, 1)

    property color glow: Theme.stateColor(activity)
    Behavior on glow { ColorAnimation { duration: Theme.normal } }

    function startle() { startleAnim.restart() }

    // ================= движение =================
    QtObject {
        id: motion
        property real phase: 0                 // парение
        property real hop: 0                   // прыжок от радости / испуга
        property real glanceX: 0               // случайный взгляд в сторону
        property real glanceY: 0
        property real blink: 0                 // 1 — глаза закрыты
        property real wave: 0                  // бегущая волна огоньков рта
        readonly property real lift: Math.sin(phase) * 0.5 + 0.5
        readonly property real gazeX: pip.pointing ? 0.9 : pip.thinking ? -0.45 : pip.lookX * 0.8 + glanceX
        readonly property real gazeY: pip.thinking ? -0.7 : pip.mood === "thoughtful" ? -0.5 : pip.lookY * 0.7 + glanceY
        readonly property real tilt: (pip.pointing ? 5 : 0) + (pip.mood === "curious" ? -9 : 0)
                                   + (pip.mood === "proud" ? -3 : 0) + (pip.thinking ? -4 : 0)
                                   + gazeX * 3 + (pip.hearing ? Math.sin(phase * 3) * pip.ear * 3 : 0)
    }

    NumberAnimation {
        target: motion; property: "phase"; running: true
        from: 0; to: Math.PI * 2; duration: pip.deaf ? 6400 : 3600; loops: Animation.Infinite
    }
    NumberAnimation {
        target: motion; property: "wave"; running: pip.thinking
        from: 0; to: Math.PI * 2; duration: 1100; loops: Animation.Infinite
    }

    // Плавные версии взгляда и наклона: пружина даёт лёгкий «перелёт», как у живого
    property real gazeX: motion.gazeX
    property real gazeY: motion.gazeY
    property real tilt: motion.tilt
    Behavior on gazeX { SpringAnimation { spring: 3; damping: 0.35 } }
    Behavior on gazeY { SpringAnimation { spring: 3; damping: 0.35 } }
    Behavior on tilt { SpringAnimation { spring: 2; damping: 0.25 } }

    Timer { // моргание
        interval: 2400 + Math.random() * 3200; running: !pip.deaf; repeat: true
        onTriggered: { interval = 2400 + Math.random() * 3200; blinkAnim.restart() }
    }
    SequentialAnimation {
        id: blinkAnim
        NumberAnimation { target: motion; property: "blink"; to: 1; duration: 70; easing.type: Easing.InQuad }
        NumberAnimation { target: motion; property: "blink"; to: 0; duration: 110; easing.type: Easing.OutQuad }
    }

    Timer { // оглядывается, когда скучно
        interval: 5000 + Math.random() * 5000; repeat: true
        running: pip.activity === "idle" && !pip.pointing
        onTriggered: {
            interval = 5000 + Math.random() * 5000
            motion.glanceX = (Math.random() - 0.5) * 1.4
            motion.glanceY = (Math.random() - 0.6) * 0.6
            glanceBack.restart()
        }
    }
    Timer { id: glanceBack; interval: 1300; onTriggered: { motion.glanceX = 0; motion.glanceY = 0 } }

    SequentialAnimation { // прыжок
        id: hopAnim
        NumberAnimation { target: motion; property: "hop"; to: 1; duration: 190; easing.type: Easing.OutQuad }
        NumberAnimation { target: motion; property: "hop"; to: 0; duration: 420; easing.type: Easing.OutBounce }
    }
    SequentialAnimation {
        id: startleAnim
        NumberAnimation { target: motion; property: "hop"; to: 0.7; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { target: motion; property: "hop"; to: 0; duration: 520; easing.type: Easing.OutElastic }
    }
    onJoyfulChanged: if (joyful) hopAnim.restart()
    onSurprisedChanged: if (surprised) startleAnim.restart()

    readonly property real rise: (motion.lift * 0.035 + motion.hop * 0.09) * s * (deaf ? 0.4 : 1)

    // ================= тень на полу =================
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: pip.height / 2 + pip.s * 0.35
        width: pip.s * 0.36 * (1 - motion.lift * 0.12 - motion.hop * 0.3)
        height: pip.s * 0.035
        radius: height / 2
        color: "#000000"
        opacity: 0.5 * (1 - motion.hop * 0.5)
        layer.enabled: true
        layer.effect: MultiEffect { blurEnabled: true; blur: 0.6; blurMax: 24 }
    }

    // ================= туловище: отстаёт от головы — так движение выглядит живым =================
    Item {
        id: torso
        width: pip.s * 0.3
        height: pip.s * 0.15
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.horizontalCenterOffset: pip.gazeX * pip.s * 0.006
        y: pip.height / 2 + pip.s * 0.155 - pip.rise * 0.7
        rotation: pip.tilt * 0.4

        Rectangle {
            anchors.fill: parent
            radius: height / 2
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.shellLight }
                GradientStop { position: 1; color: Theme.shellShade }
            }
        }
        Rectangle { // огонёк на груди
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -parent.height * 0.05
            width: pip.s * 0.03; height: width; radius: width / 2
            color: pip.deaf ? Theme.deaf : pip.glow
            opacity: pip.speaking ? 0.6 + pip.voice * 0.4 : 0.85
            layer.enabled: true
            layer.effect: MultiEffect { shadowEnabled: true; shadowColor: pip.deaf ? Theme.deaf : pip.glow
                                        shadowBlur: 0.8; shadowOpacity: 1
                                        shadowHorizontalOffset: 0; shadowVerticalOffset: 0 }
        }
    }

    // ================= голова =================
    Item {
        id: head
        width: pip.s * 0.62
        height: pip.s * 0.46
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.horizontalCenterOffset: pip.gazeX * pip.s * 0.015
        y: pip.height / 2 - pip.s * 0.33 - pip.rise
        rotation: pip.tilt
        transformOrigin: Item.Bottom
        scale: 1 + motion.hop * 0.03

        // --- антенна ---
        Item {
            id: antenna
            width: pip.s * 0.06
            height: pip.s * 0.12
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.top
            anchors.bottomMargin: -pip.s * 0.01
            transformOrigin: Item.Bottom
            rotation: -pip.tilt * 0.8 + Math.sin(motion.phase * 2) * 3

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                width: pip.s * 0.014; height: parent.height * 0.72; radius: width / 2
                color: Theme.shellShade
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: pip.s * 0.05 * (1 + (pip.hearing ? pip.ear * 0.35 : 0)); height: width; radius: width / 2
                y: pip.s * 0.025 - width / 2
                color: pip.deaf ? Theme.textFaint : pip.glow
                Behavior on width { NumberAnimation { duration: 80 } }
                layer.enabled: !pip.deaf
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: pip.glow; shadowBlur: 1; shadowOpacity: 1
                                            shadowHorizontalOffset: 0; shadowVerticalOffset: 0 }
            }
        }

        // --- уши: полоски света по бокам ---
        Repeater {
            model: [-1, 1]
            Item {
                required property int modelData
                width: pip.s * 0.065
                height: pip.s * 0.2
                x: modelData < 0 ? -width * 0.55 : head.width - width * 0.45
                y: (head.height - height) / 2 + pip.s * 0.01
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    gradient: Gradient {
                        GradientStop { position: 0; color: Theme.shell }
                        GradientStop { position: 1; color: Theme.shellShade }
                    }
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 0.3
                    height: parent.height * (pip.deaf ? 0.62 : 0.4 + (pip.hearing ? pip.ear * 0.28 : 0))
                    radius: width / 2
                    color: pip.deaf ? Theme.deaf : pip.glow
                    opacity: pip.deaf ? 0.95 : pip.hearing ? 0.65 + pip.ear * 0.35 : 0.35
                    Behavior on height { NumberAnimation { duration: 90 } }
                }
            }
        }

        // --- корпус ---
        Rectangle {
            anchors.fill: parent
            radius: height * 0.4
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.shellLight }
                GradientStop { position: 0.55; color: Theme.shell }
                GradientStop { position: 1; color: Theme.shellShade }
            }
        }
        Rectangle { // блик сверху
            x: parent.width * 0.2; y: parent.height * 0.035
            width: parent.width * 0.42; height: parent.height * 0.05; radius: height / 2
            color: "#ffffff"; opacity: 0.75
        }

        // --- стекло лица ---
        Rectangle {
            id: visor
            width: parent.width - pip.s * 0.08
            height: parent.height * 0.7
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height * 0.11
            radius: height * 0.42
            border.width: Math.max(1, pip.s * 0.006)
            border.color: Theme.visorEdge
            gradient: Gradient {
                GradientStop { position: 0; color: "#1d1f26" }
                GradientStop { position: 1; color: Theme.visor }
            }
            clip: true

            Item {
                id: face
                anchors.fill: parent
                opacity: pip.deaf ? 0.6 : 1
                Behavior on opacity { NumberAnimation { duration: Theme.normal } }
                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: !pip.deaf; shadowColor: pip.glow
                    shadowBlur: 0.7; shadowOpacity: 0.9
                    shadowHorizontalOffset: 0; shadowVerticalOffset: 0
                }

                readonly property real eyeX: pip.gazeX * width * 0.07
                readonly property real eyeY: pip.gazeY * height * 0.08

                Eye {
                    side: -1
                    x: face.width / 2 - pip.s * 0.105 - width / 2 + face.eyeX
                    y: face.height * 0.43 - height / 2 + face.eyeY
                }
                Eye {
                    side: 1
                    x: face.width / 2 + pip.s * 0.105 - width / 2 + face.eyeX
                    y: face.height * 0.43 - height / 2 + face.eyeY
                }

                // --- рот: пять огоньков ---
                Repeater {
                    model: 5
                    Rectangle {
                        required property int index
                        readonly property real k: index - 2                        // -2..2 от центра
                        readonly property real dot: pip.s * 0.023
                        property real spread: pip.surprised ? 0.6 : 1
                        property real smile: pip.joyful ? 1 : pip.deaf || pip.pensive ? 0 : 0.35
                        readonly property real bar: pip.speaking
                            ? dot * (1 + pip.voice * 3.2 * (0.55 + 0.45 * Math.sin(motion.phase * 9 + index * 1.7)))
                            : dot
                        readonly property real bob: pip.thinking ? Math.sin(motion.wave - index * 0.9) * dot * 0.6 : 0
                        width: dot
                        height: bar
                        radius: dot / 2
                        color: pip.deaf ? Theme.textMuted : pip.glow
                        opacity: pip.deaf ? 0.6 : pip.speaking ? 1 : 0.85
                        x: face.width / 2 + k * dot * 1.75 * spread - width / 2 + face.eyeX * 0.6
                        y: face.height * 0.75 - height / 2 - smile * (4 - k * k) * dot * 0.22 + bob + face.eyeY * 0.5
                        Behavior on height { NumberAnimation { duration: 60 } }
                        Behavior on spread { NumberAnimation { duration: Theme.normal } }
                        Behavior on smile { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutBack } }
                    }
                }
            }

            Rectangle { // отражение на стекле
                x: parent.width * 0.64; y: -parent.height * 0.2
                width: parent.width * 0.1; height: parent.height * 1.4
                rotation: 24
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "#00ffffff" }
                    GradientStop { position: 0.5; color: "#14ffffff" }
                    GradientStop { position: 1; color: "#00ffffff" }
                }
            }
        }

        // --- «z», когда слух выключен ---
        Repeater {
            model: 3
            Text {
                required property int index
                readonly property real t: ((motion.phase / (Math.PI * 2)) + index / 3) % 1
                visible: pip.deaf
                text: "z"
                font.family: Theme.font
                font.weight: Font.ExtraBold
                font.pixelSize: pip.s * (0.04 + index * 0.012)
                color: Theme.textMuted
                x: head.width * 0.88 + t * pip.s * 0.1
                y: -t * pip.s * 0.2
                opacity: Math.sin(t * Math.PI) * 0.8
            }
        }
    }

    // ================= глаз =================
    component Eye: Item {
        id: eye
        property int side: 1
        // Насколько открыт: сон — щёлочка, раздумье — прищур, удивление — шире
        readonly property real open: pip.deaf ? 0.12
            : (pip.surprised ? 1.1 : pip.pensive ? 0.6 : 1) * (1 - motion.blink * 0.9)
        property real grow: pip.surprised ? 1.3 : pip.mood === "curious" ? (side > 0 ? 1.18 : 0.9)
                          : pip.hearing ? 1.06 + pip.ear * 0.08 : 1
        width: pip.s * 0.07 * grow
        height: pip.s * 0.105 * grow * aspect
        property real aspect: pip.surprised ? 0.72 : 1      // удивление — круглые глаза
        Behavior on aspect { NumberAnimation { duration: Theme.fast } }
        Behavior on grow { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutBack } }

        Rectangle { // обычный глаз — светящаяся «таблетка»
            anchors.centerIn: parent
            width: parent.width
            height: Math.max(parent.height * eye.open, pip.s * 0.012)
            radius: pip.surprised ? width / 2 : width * 0.42
            color: pip.deaf ? Theme.textMuted : pip.glow
            opacity: pip.joyful ? 0 : 1
            Behavior on height { NumberAnimation { duration: 70 } }
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        }

        Item { // радостный глаз — дуга ^ (верхняя половина кольца)
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height * 0.18
            width: eye.width * 1.4
            height: width / 2
            clip: true
            opacity: pip.joyful ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
            Rectangle {
                width: parent.width
                height: width
                radius: width / 2
                color: "transparent"
                border.width: eye.width * 0.4
                border.color: pip.glow
            }
        }
    }
}
