// Вся внешность в одном месте: две палитры (светлая и тёмная), цвета Пипа, шрифт, размеры, анимации.
// Тема переключается свойством `dark` (кнопка в окне, клавиша T); выбор запоминается (bridge.py).
// Стиль: плоский — без градиентов, теней и свечения. Всё держится на цвете, форме и жирном шрифте.
pragma Singleton
import QtQuick

QtObject {
    id: theme
    property bool dark: false

    // --- холст и поверхности ---
    readonly property color background: dark ? "#121212" : "#ffffff"
    readonly property color surface: dark ? "#1f1f1f" : "#f2f0eb"          // доска, громкость, твоя реплика
    readonly property color surfaceHover: dark ? "#2a2a2a" : "#e8e5de"
    readonly property color track: dark ? "#3a3a3a" : "#dedbd3"            // дорожка ползунка

    // --- текст ---
    readonly property color text: dark ? "#ffffff" : "#141414"
    readonly property color textMuted: dark ? "#a3a3a3" : "#55524c"
    readonly property color textFaint: dark ? "#3f3f3f" : "#cfccc5"         // ещё не произнесённая часть реплики
    readonly property color boardText: dark ? "#d4d4d4" : "#3a3833"
    readonly property color line: dark ? "#2e2e2e" : "#e2ded5"
    readonly property color selection: dark ? "#3a3a3a" : "#e2ded5"

    // --- главная кнопка (микрофон): инверсия холста ---
    readonly property color action: dark ? "#ffffff" : "#141414"
    readonly property color actionText: dark ? "#141414" : "#ffffff"

    // --- «Claude на связи» ---
    readonly property color okBg: dark ? "#0f2e25" : "#e7f8f1"
    readonly property color ok: dark ? "#3ee0a8" : "#00a376"

    // --- цвета Пипа: состояние и эмоция. Плоские и насыщенные, одинаковые в обеих темах ---
    readonly property color waiting: dark ? "#4a4d52" : "#c9cdd2"    // Claude не подключён
    readonly property color muted: "#9aa0a6"                         // микрофон выключен
    readonly property color idle: "#2e7dff"                          // спокоен
    readonly property color listening: "#00c08b"                     // слушает тебя
    readonly property color thinking: "#8b5cf6"                      // думает (ждёт Claude)
    readonly property color speaking: "#ff6b2c"                      // говорит
    readonly property color happy: "#ffc21a"
    readonly property color proud: "#ffc21a"
    readonly property color surprised: "#ff4fa0"
    readonly property color curious: "#14b8c4"
    readonly property color thoughtful: "#8b5cf6"
    readonly property color danger: "#ff4d4f"                        // кнопка выключенного микрофона

    // Цвет Пипа: выключенный микрофон и ожидание Claude важнее всего; пока слушает или думает —
    // цвет состояния (иначе не видно, что происходит); в остальное время — цвет эмоции.
    function pipColor(activity, mood) {
        if (activity === "deaf") return muted
        if (activity === "waiting") return waiting
        if (activity === "hearing") return listening
        if (activity === "thinking") return thinking
        const byMood = { happy: happy, proud: proud, surprised: surprised, curious: curious, thoughtful: thoughtful }
        if (byMood[mood] !== undefined) return byMood[mood]
        return activity === "speaking" ? speaking : idle
    }
    function stateColor(activity) { return pipColor(activity, "neutral") }

    // --- шрифт и размеры ---
    // zoom — во сколько раз окно больше обычного (980×700). Во весь экран текст и Пип растут вместе с окном,
    // а не остаются мелкими посреди пустоты. Задаёт Main.qml.
    property real zoom: 1
    function px(size) { return Math.round(size * zoom) }
    readonly property string font: "Rubik"
    readonly property int wordmarkSize: px(26)
    readonly property int heardSize: px(17)        // твоя фраза
    readonly property int speechSize: px(40)       // реплика Пипа
    readonly property int speechSizeCompact: px(28)  // реплика, когда открыта доска
    readonly property int labelSize: px(15)
    readonly property int hintSize: px(18)
    readonly property int chipSize: px(14)
    readonly property int boardTitleSize: px(32)
    readonly property int boardTextSize: px(17)
    readonly property int radius: 32

    // --- анимации (мс) ---
    readonly property int fast: 160
    readonly property int normal: 300
    readonly property int slow: 480
}
