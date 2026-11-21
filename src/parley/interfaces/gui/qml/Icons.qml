// Контуры иконок (SVG, сетка 24×24).
pragma Singleton
import QtQuick

QtObject {
    readonly property string mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z M19 11a7 7 0 0 1-14 0 M12 18v3"
    readonly property string micOff: "M15 9.3V6a3 3 0 0 0-5.7-1.3 M9 9v3a3 3 0 0 0 5.1 2.1 M19 11a7 7 0 0 1-1.2 3.9 M5 11a7 7 0 0 0 11.3 5.5 M12 18v3 M3 3l18 18"
    readonly property string speaker: "M11 5L6 9H3v6h3l5 4z M15.5 8.5a5 5 0 0 1 0 7 M18.5 5.5a9 9 0 0 1 0 13"
    readonly property string speakerLow: "M11 5L6 9H3v6h3l5 4z M15.5 8.5a5 5 0 0 1 0 7"
    readonly property string speakerOff: "M11 5L6 9H3v6h3l5 4z M16 9.5l5 5 M21 9.5l-5 5"
    readonly property string close: "M6 6l12 12 M18 6L6 18"
    readonly property string sun: "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4"
    readonly property string moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"
}
