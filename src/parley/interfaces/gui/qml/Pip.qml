// Пип — полая капсула: цветное кольцо, внутри «дыра» (сквозь неё виден фон), в дыре — лицо из глифов.
// Форма всегда одна и та же; эмоции и состояния меняют цвет кольца и лицо. Всё плоское, рисуется кодом.
//
// Входы:
//   activity      waiting | idle | hearing | thinking | speaking | deaf
//   mood          neutral | happy | curious | surprised | proud | thoughtful
//   hearingLevel  громкость микрофона (0..~0.3) — кольцо «дышит» твоим голосом
//   voiceLevel    громкость собственного голоса (0..~0.3) — открывает рот
//   lookX, lookY  куда смотреть (-1..1) — лицо сдвигается внутри дыры
//   pointing      смотрит на доску справа
// Методы:
//   startle()     вздрогнуть (резкий звук)
//   nod()         кивнуть (сам кивает, пока слушает: на паузах в твоей речи и когда договорил)
//
// Лица (expression): sleep (ждёт Claude / микрофон выключен), listen («о»), think (глаза вверх, черта),
// neutral (капли и улыбка), happy (^ ^ и рот «D»), surprised (круглые глаза, «О»), curious (один глаз больше).
import QtQuick
import QtQuick.Shapes

Item {
    id: pip

    property string activity: "idle"
    property string mood: "neutral"
    property real hearingLevel: 0
    property real voiceLevel: 0
    property real lookX: 0
    property real lookY: 0
    property bool pointing: false

    readonly property bool asleep: activity === "deaf" || activity === "waiting"
    readonly property real voice: activity === "speaking" ? Math.min(voiceLevel * 9, 1) : 0
    readonly property real ear: activity === "hearing" ? Math.min(hearingLevel * 12, 1) : 0
    readonly property string expression: asleep ? "sleep"
        : activity === "hearing" ? "listen"
        : activity === "thinking" || mood === "thoughtful" ? "think"
        : mood === "happy" || mood === "proud" ? "happy"
        : mood === "surprised" ? "surprised"
        : mood === "curious" ? "curious" : "neutral"

    property color tone: Theme.pipColor(activity, mood)
    Behavior on tone { ColorAnimation { duration: Theme.normal } }

    function startle() { startleAnim.restart() }

    // ================= движение =================
    QtObject {
        id: motion
        property real phase: 0        // покачивание
        property real hop: 0          // прыжок
        property real blink: 0        // 1 — глаза закрыты
        property real glanceX: 0
        property real glanceY: 0
        property real nod: 0          // кивок: 1 — голова внизу
    }
    NumberAnimation { target: motion; property: "phase"; running: true; loops: Animation.Infinite
                      from: 0; to: Math.PI * 2; duration: pip.asleep ? 5200 : 3000 }

    property real gazeX: pip.pointing ? 0.9 : pip.expression === "think" ? -0.5 : pip.lookX * 0.8 + motion.glanceX
    property real gazeY: pip.expression === "think" ? -0.8 : pip.lookY * 0.6 + motion.glanceY
    property real tilt: (pip.mood === "curious" ? -7 : 0) + (pip.expression === "think" ? -4 : 0) + (pip.pointing ? 3 : 0)
                        + (pip.activity === "hearing" ? Math.sin(motion.phase * 3) * pip.ear * 3 : 0)
    Behavior on gazeX { SpringAnimation { spring: 3; damping: 0.35 } }
    Behavior on gazeY { SpringAnimation { spring: 3; damping: 0.35 } }
    Behavior on tilt { SpringAnimation { spring: 2; damping: 0.25 } }

    Timer { // моргание
        interval: 2600 + Math.random() * 3000; running: !pip.asleep; repeat: true
        onTriggered: { interval = 2600 + Math.random() * 3000; blinkAnim.restart() }
    }
    SequentialAnimation {
        id: blinkAnim
        NumberAnimation { target: motion; property: "blink"; to: 1; duration: 70 }
        NumberAnimation { target: motion; property: "blink"; to: 0; duration: 110 }
    }
    Timer { // оглядывается, когда скучно
        interval: 5000 + Math.random() * 5000; repeat: true
        running: pip.activity === "idle" && !pip.pointing
        onTriggered: {
            interval = 5000 + Math.random() * 5000
            motion.glanceX = (Math.random() - 0.5) * 1.4
            motion.glanceY = (Math.random() - 0.5) * 0.6
            glanceBack.restart()
        }
    }
    Timer { id: glanceBack; interval: 1200; onTriggered: { motion.glanceX = 0; motion.glanceY = 0 } }
    SequentialAnimation {
        id: hopAnim
        NumberAnimation { target: motion; property: "hop"; to: 1; duration: 180; easing.type: Easing.OutQuad }
        NumberAnimation { target: motion; property: "hop"; to: 0; duration: 420; easing.type: Easing.OutBounce }
    }
    SequentialAnimation {
        id: startleAnim
        NumberAnimation { target: motion; property: "hop"; to: 0.7; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { target: motion; property: "hop"; to: 0; duration: 520; easing.type: Easing.OutElastic }
    }
    onExpressionChanged: if (expression === "happy" || expression === "surprised") hopAnim.restart()

    // Кивает, пока слушает: на паузах в твоей речи (поговорил хотя бы полсекунды, потом затих)
    // и когда ты договорил. Молча — это живой «угу», который не перебивает.
    SequentialAnimation {
        id: nodAnim
        NumberAnimation { target: motion; property: "nod"; to: 1; duration: 160; easing.type: Easing.OutQuad }
        NumberAnimation { target: motion; property: "nod"; to: 0; duration: 320; easing.type: Easing.InOutQuad }
    }
    QtObject {
        id: listener
        property real loud: 0         // сколько секунд подряд ты говоришь
        property real quiet: 0        // сколько секунд подряд тишина после речи
        property real lastNod: 0
    }
    function nod() {
        if (Date.now() - listener.lastNod < 2200) return
        listener.lastNod = Date.now()
        nodAnim.restart()
    }
    Timer {
        interval: 100; repeat: true; running: pip.activity === "hearing"
        onRunningChanged: { listener.loud = 0; listener.quiet = 0 }
        onTriggered: {
            if (pip.ear > 0.3) { listener.loud += 0.1; listener.quiet = 0 }
            else if (listener.loud > 0.5) {
                listener.quiet += 0.1
                if (listener.quiet >= 0.3) { pip.nod(); listener.loud = 0; listener.quiet = 0 }
            }
        }
    }
    onActivityChanged: if (activity === "thinking") nod()

    // ================= капсула =================
    Item {
        id: body
        width: Math.min(pip.width, pip.height * 1.9)
        height: width * 0.52
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -(Math.sin(motion.phase) * 0.02 + motion.hop * 0.12 - motion.nod * 0.03) * width
        rotation: pip.tilt
        // Говорит — чуть сплющивается в такт голосу; прыгает — вытягивается
        readonly property real squash: 1 + pip.voice * 0.05 * Math.sin(motion.phase * 9) + motion.hop * 0.06
        transform: Scale { origin.x: body.width / 2; origin.y: body.height; xScale: 2 - body.squash; yScale: body.squash }

        // Толщина кольца «дышит» твоим голосом, пока Пип слушает
        readonly property real ring: height * (0.15 - pip.ear * 0.04)

        Rectangle { anchors.fill: parent; radius: height / 2; color: pip.tone }
        Rectangle { // дыра: сквозь неё виден фон
            id: hole
            anchors.fill: parent
            anchors.margins: body.ring
            radius: height / 2
            color: Theme.background
            Behavior on anchors.margins { NumberAnimation { duration: 90 } }

            Item {
                id: face
                width: hole.width * 0.6; height: width * 0.5
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: pip.gazeX * hole.width * 0.12
                anchors.verticalCenterOffset: pip.gazeY * hole.height * 0.12 - height * 0.02 + motion.nod * hole.height * 0.1
                readonly property real u: width
                readonly property color ink: Theme.text

                // ---- глаза ----
                Repeater {
                    model: [-1, 1]
                    Item {
                        required property int modelData
                        readonly property real grow: pip.expression === "curious" ? (modelData > 0 ? 1.25 : 0.85) : 1
                        width: face.u * 0.16; height: face.u * 0.22
                        x: face.u / 2 + modelData * face.u * 0.2 - width / 2
                        y: face.u * 0.02

                        Rectangle { // капля (обычный, слушает, любопытство) — моргает
                            visible: ["neutral", "listen", "curious"].indexOf(pip.expression) >= 0
                            anchors.centerIn: parent
                            width: face.u * (pip.expression === "listen" ? 0.12 : 0.105) * parent.grow
                            height: Math.max(face.u * 0.03, face.u * (pip.expression === "listen" ? 0.2 : 0.17) * parent.grow * (1 - motion.blink * 0.85))
                            radius: width / 2; color: face.ink
                        }
                        Rectangle { // удивление — круг
                            visible: pip.expression === "surprised"
                            anchors.centerIn: parent; width: face.u * 0.15; height: width; radius: width / 2; color: face.ink
                        }
                        Rectangle { // раздумье — приплюснутый глаз
                            visible: pip.expression === "think"
                            anchors.centerIn: parent; width: face.u * 0.12; height: face.u * 0.07; radius: height / 2; color: face.ink
                        }
                        Rectangle { // сон — черта
                            visible: pip.expression === "sleep"
                            anchors.centerIn: parent; anchors.verticalCenterOffset: face.u * 0.03
                            width: face.u * 0.13; height: face.u * 0.04; radius: height / 2; color: face.ink
                        }
                        Shape { // радость — галочка ^
                            visible: pip.expression === "happy"
                            anchors.fill: parent
                            preferredRendererType: Shape.CurveRenderer
                            ShapePath { strokeColor: face.ink; strokeWidth: face.u * 0.05; fillColor: "transparent"
                                capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                                startX: face.u * 0.02; startY: face.u * 0.15
                                PathLine { x: face.u * 0.08; y: face.u * 0.06 } PathLine { x: face.u * 0.14; y: face.u * 0.15 } }
                        }
                    }
                }

                // ---- рот ----
                Item {
                    id: mouth
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: face.u * 0.3
                    width: face.u * 0.24; height: face.u * 0.16
                    readonly property bool open: pip.voice > 0.02 || pip.expression === "happy"

                    Shape { // спокойная улыбка
                        visible: !mouth.open && (pip.expression === "neutral" || pip.expression === "curious")
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath { strokeColor: face.ink; strokeWidth: face.u * 0.04; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            startX: face.u * 0.06; startY: face.u * 0.02
                            PathQuad { x: face.u * 0.18; y: face.u * 0.02; controlX: face.u * 0.12; controlY: face.u * 0.09 } }
                    }
                    Rectangle { // «о» — слушает / удивлён
                        visible: !mouth.open && (pip.expression === "listen" || pip.expression === "surprised")
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: face.u * (pip.expression === "surprised" ? 0.08 : 0.055); height: width * 1.15; radius: width / 2; color: face.ink
                    }
                    Rectangle { // черта — думает / спит
                        visible: !mouth.open && (pip.expression === "think" || pip.expression === "sleep")
                        anchors.horizontalCenter: parent.horizontalCenter; y: face.u * 0.02
                        width: face.u * 0.09; height: face.u * 0.035; radius: height / 2; color: face.ink
                    }
                    Shape { // открытый рот «D»: говорит или радуется
                        id: openMouth
                        visible: mouth.open
                        readonly property real w: face.u * (pip.expression === "happy" ? 0.18 : 0.13)
                        readonly property real h: face.u * (pip.expression === "happy" ? 0.07 + pip.voice * 0.04 : 0.025 + pip.voice * 0.08)
                        x: (mouth.width - w) / 2
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath { fillColor: face.ink; strokeColor: "transparent"
                            startX: 0; startY: 0
                            PathLine { x: openMouth.w; y: 0 }
                            PathQuad { x: 0; y: 0; controlX: openMouth.w / 2; controlY: openMouth.h * 2 } }
                    }
                }
            }
        }
    }

    // ---- «z», когда микрофон выключен ----
    Repeater {
        model: pip.activity === "deaf" ? 3 : 0
        Text {
            required property int index
            readonly property real t: ((motion.phase / (Math.PI * 2)) + index / 3) % 1
            text: "z"
            font.family: Theme.font
            font.weight: Font.Black
            font.pixelSize: body.height * (0.14 + index * 0.04)
            color: Theme.muted
            x: body.x + body.width * 0.9 + t * body.height * 0.4
            y: body.y - t * body.height * 0.6
            opacity: Math.sin(t * Math.PI)
        }
    }
}
