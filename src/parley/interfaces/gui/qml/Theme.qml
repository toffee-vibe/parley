// Вся внешность в одном месте: цвета, шрифты, размеры, скорость анимаций.
// Хочешь другой вид — правь только этот файл.
pragma Singleton
import QtQuick

QtObject {
    // --- фон: тёплый графит, в центре чуть светлее ---
    readonly property color background: "#0e0f12"
    readonly property color backgroundCenter: "#1b1d22"

    // --- поверхности (доска, панель управления) ---
    readonly property color surface: "#17181c"
    readonly property color surfaceRaised: "#222329"
    readonly property color surfaceHover: "#2b2d34"
    readonly property color border: "#2a2c33"

    // --- текст ---
    readonly property color text: "#f4f3ef"
    readonly property color textMuted: "#9a9ca6"
    readonly property color textFaint: "#5c5f69"

    // --- состояния: этим цветом светятся глаза, антенна и индикаторы ---
    readonly property color idle: "#8ee9ff"        // ледяной голубой — спокоен
    readonly property color listening: "#6ff2c4"   // мятный — слышит тебя
    readonly property color thinking: "#b9a3ff"    // сиреневый — думает (ждёт Claude)
    readonly property color speaking: "#ffd38a"    // тёплый янтарь — говорит
    readonly property color deaf: "#ff6b6b"        // красный — слух выключен
    function stateColor(activity) {
        return activity === "hearing" ? listening : activity === "thinking" ? thinking
             : activity === "speaking" ? speaking : activity === "deaf" ? deaf : idle
    }

    // --- Пип: корпус из тёплого белого пластика, тёмное стекло лица ---
    readonly property color shellLight: "#fbf9f4"
    readonly property color shell: "#e9e5dc"
    readonly property color shellShade: "#bdb6a8"
    readonly property color visor: "#121318"
    readonly property color visorEdge: "#2b2d35"

    // --- шрифт и размеры ---
    readonly property string font: "Manrope"
    readonly property int heardSize: 15        // твоя фраза
    readonly property int speechSize: 24       // реплика Пипа
    readonly property int labelSize: 11        // подписи капсом
    readonly property int boardTitleSize: 24
    readonly property int boardTextSize: 16
    readonly property int radius: 20

    // --- анимации (мс) ---
    readonly property int fast: 160
    readonly property int normal: 300
    readonly property int slow: 560
}
