pragma Singleton
import QtQuick

// Colours, type and spacing shared by every application. Brand colours come
// from distro.conf through the `brandInfo` context property; dark and light
// palettes follow the system unless the user picks one.
QtObject {
    id: theme

    property string mode: "system"   // system | dark | light
    readonly property bool dark: mode === "dark" || (mode === "system" && Qt.styleHints.colorScheme !== Qt.ColorScheme.Light)

    readonly property var brand: (typeof brandInfo !== "undefined" && brandInfo) ? brandInfo : ({})
    readonly property color accent: brand.accent || "#7C6CFF"
    readonly property color accent2: brand.accent2 || "#23D5C4"
    readonly property color warning: brand.warning || "#FFB547"
    readonly property color danger: brand.danger || "#FF5C7A"
    readonly property color success: "#35C48B"

    readonly property color bg: dark ? (brand.bg || "#0B0E1A") : "#F4F5FA"
    readonly property color surface: dark ? (brand.surface || "#151A2C") : "#FFFFFF"
    readonly property color surface2: dark ? Qt.lighter(surface, 1.25) : "#ECEEF6"
    readonly property color border: dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(0, 0, 0, 0.10)
    readonly property color fg: dark ? (brand.fg || "#E8ECF8") : "#161A2B"
    readonly property color muted: dark ? (brand.muted || "#8A93B2") : "#5B6380"
    readonly property color textOnAccent: "#FFFFFF"
    readonly property color accentSoft: Qt.rgba(accent.r, accent.g, accent.b, dark ? 0.18 : 0.12)
    readonly property color dangerSoft: Qt.rgba(danger.r, danger.g, danger.b, dark ? 0.16 : 0.10)
    readonly property color warningSoft: Qt.rgba(warning.r, warning.g, warning.b, dark ? 0.16 : 0.14)
    readonly property color focus: accent2

    readonly property string font: "Inter, Rubik, Noto Sans, sans-serif"
    readonly property string mono: "JetBrains Mono, monospace"
    readonly property int textSmall: 12
    readonly property int text: 14
    readonly property int textLarge: 17
    readonly property int title: 26
    readonly property int display: 38

    readonly property int radius: 16
    readonly property int radiusSmall: 10
    readonly property int gap: 12
    readonly property int pad: 20
    readonly property int animation: 160
}
