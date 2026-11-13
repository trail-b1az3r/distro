pragma Singleton
import QtQuick

// Material 3 Expressive design tokens shared by every application: colour roles, type, shape and motion.
//
// The colour roles are a tonal palette made from the brand's accent (distro.conf, through the `brandInfo` context
// property): primary from the accent, secondary a quieter version of its hue, tertiary from the second accent, and
// neutral surfaces tinted with the accent's hue, in M3's tones for a dark and a light scheme. The scheme follows the
// system unless the user picks one. The older names (bg, surface, fg, accent...) remain as aliases of the new roles.
QtObject {
    id: theme

    property string mode: "system"   // system | dark | light
    readonly property bool dark: mode === "dark" || (mode === "system" && Qt.styleHints.colorScheme !== Qt.ColorScheme.Light)

    readonly property var brand: (typeof brandInfo !== "undefined" && brandInfo) ? brandInfo : ({})
    readonly property color seed: brand.accent || "#7C6CFF"
    readonly property color seed2: brand.accent2 || "#23D5C4"
    readonly property real hue: Math.max(0, seed.hslHue)
    readonly property real hue2: Math.max(0, seed2.hslHue)
    readonly property real chroma: Math.max(0.45, seed.hslSaturation)

    // A tone of a hue (0-100, as in M3's tonal palettes) at a saturation.
    function tone(h, s, t) { return Qt.hsla(h, s, t / 100, 1) }
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

    // Colour roles ------------------------------------------------------------------------------------------------
    readonly property color primary: dark ? tone(hue, chroma, 80) : tone(hue, chroma * 0.75, 42)
    readonly property color primaryContent: dark ? tone(hue, chroma, 20) : "#FFFFFF"
    readonly property color primaryContainer: dark ? tone(hue, chroma * 0.55, 30) : tone(hue, chroma, 90)
    readonly property color primaryContainerContent: dark ? tone(hue, chroma, 90) : tone(hue, chroma, 15)
    readonly property color secondary: dark ? tone(hue, 0.30, 80) : tone(hue, 0.20, 40)
    readonly property color secondaryContent: dark ? tone(hue, 0.30, 20) : "#FFFFFF"
    readonly property color secondaryContainer: dark ? tone(hue, 0.22, 28) : tone(hue, 0.45, 88)
    readonly property color secondaryContainerContent: dark ? tone(hue, 0.35, 90) : tone(hue, 0.35, 14)
    readonly property color tertiary: dark ? tone(hue2, 0.55, 75) : tone(hue2, 0.70, 32)
    readonly property color tertiaryContent: dark ? tone(hue2, 0.60, 15) : "#FFFFFF"
    readonly property color tertiaryContainer: dark ? tone(hue2, 0.45, 26) : tone(hue2, 0.60, 86)
    readonly property color tertiaryContainerContent: dark ? tone(hue2, 0.55, 88) : tone(hue2, 0.70, 12)
    readonly property color error: dark ? "#FFB4AB" : "#BA1A1A"
    readonly property color errorContent: dark ? "#690005" : "#FFFFFF"
    readonly property color errorContainer: dark ? "#93000A" : "#FFDAD6"
    readonly property color errorContainerContent: dark ? "#FFDAD6" : "#410002"
    readonly property color warning: dark ? "#FFB95C" : "#8A5100"
    readonly property color warningContainer: dark ? "#5C3A00" : "#FFDDB3"
    readonly property color warningContainerContent: dark ? "#FFDDB3" : "#2C1600"
    readonly property color success: dark ? "#7DDBA4" : "#006D3F"
    readonly property color successContainer: dark ? "#00522E" : "#99F6BE"
    readonly property color successContainerContent: dark ? "#99F6BE" : "#002110"

    readonly property real neutral: 0.10
    readonly property color surfaceDim: dark ? tone(hue, neutral, 6) : tone(hue, neutral, 87)
    readonly property color surfaceBright: dark ? tone(hue, neutral, 24) : tone(hue, neutral, 98)
    readonly property color surfaceContainerLowest: dark ? tone(hue, neutral, 4) : "#FFFFFF"
    readonly property color surfaceContainerLow: dark ? tone(hue, neutral, 10) : tone(hue, 0.16, 95)
    readonly property color surfaceContainer: dark ? tone(hue, neutral, 12) : tone(hue, 0.18, 92)
    readonly property color surfaceContainerHigh: dark ? tone(hue, neutral, 17) : tone(hue, 0.18, 89)
    readonly property color surfaceContainerHighest: dark ? tone(hue, neutral, 22) : tone(hue, 0.18, 86)
    readonly property color background: dark ? tone(hue, neutral, 6) : tone(hue, neutral, 98)
    readonly property color surfaceContent: dark ? tone(hue, 0.08, 90) : tone(hue, 0.10, 10)
    readonly property color surfaceVariantContent: dark ? tone(hue, 0.12, 80) : tone(hue, 0.12, 30)
    readonly property color outline: dark ? tone(hue, 0.10, 60) : tone(hue, 0.10, 50)
    readonly property color outlineVariant: dark ? tone(hue, 0.10, 30) : tone(hue, 0.12, 80)
    readonly property color inverseSurface: dark ? tone(hue, 0.08, 90) : tone(hue, 0.10, 20)
    readonly property color inverseSurfaceContent: dark ? tone(hue, 0.10, 20) : tone(hue, 0.08, 95)
    readonly property color scrim: "#000000"

    // State layers (M3: hover 8%, focus and press 10%) of a content colour.
    function hover(c) { return alpha(c, 0.08) }
    function press(c) { return alpha(c, 0.10) }

    // The content colours are named <role>Content (M3's "on" colours: QML reads a property named on<Capital>
    // as a signal handler).
    // The older names, as the roles they stand for.
    readonly property color accent: primary
    readonly property color accent2: tertiary
    readonly property color danger: error
    readonly property color bg: background
    readonly property color surface: surfaceContainerLow
    readonly property color surface2: surfaceContainerHigh
    readonly property color border: outlineVariant
    readonly property color fg: surfaceContent
    readonly property color muted: surfaceVariantContent
    readonly property color textOnAccent: primaryContent
    readonly property color accentSoft: secondaryContainer
    readonly property color dangerSoft: errorContainer
    readonly property color warningSoft: warningContainer
    readonly property color focus: primary

    // Type: Google Sans Flex, M3's scale with emphasized (heavier) display and headline styles -------------------
    readonly property string font: "Google Sans Flex"
    readonly property string mono: "JetBrains Mono"
    readonly property int displayLarge: 57
    readonly property int displayMedium: 45
    readonly property int displaySmall: 36
    readonly property int headlineLarge: 32
    readonly property int headlineMedium: 28
    readonly property int headlineSmall: 24
    readonly property int titleLarge: 22
    readonly property int titleMedium: 16
    readonly property int titleSmall: 14
    readonly property int bodyLarge: 16
    readonly property int bodyMedium: 14
    readonly property int bodySmall: 12
    readonly property int labelLarge: 14
    readonly property int labelMedium: 12
    readonly property int labelSmall: 11
    readonly property int emphasized: Font.DemiBold
    readonly property int textSmall: bodySmall
    readonly property int text: bodyMedium
    readonly property int textLarge: bodyLarge
    readonly property int title: headlineLarge
    readonly property int display: displaySmall

    // Shape: M3 Expressive's corner scale ------------------------------------------------------------------------
    readonly property int shapeExtraSmall: 4
    readonly property int shapeSmall: 8
    readonly property int shapeMedium: 12
    readonly property int shapeLarge: 16
    readonly property int shapeLargeIncreased: 20
    readonly property int shapeExtraLarge: 28
    readonly property int shapeExtraLargeIncreased: 32
    readonly property int shapeExtraExtraLarge: 48
    readonly property int radius: shapeExtraLarge
    readonly property int radiusSmall: shapeLarge

    // Spacing
    readonly property int gap: 12
    readonly property int pad: 24

    // Motion: expressive springs (SpringAnimation) for movement and shape, quick eases for colour ---------------------
    readonly property real springSpatial: 3.4        // position, size, shape: a little overshoot
    readonly property real dampingSpatial: 0.26
    readonly property real springFast: 5.0
    readonly property real dampingFast: 0.38
    readonly property int durationShort: 150
    readonly property int durationMedium: 300
    readonly property int durationLong: 500
    readonly property int animation: durationShort
}
