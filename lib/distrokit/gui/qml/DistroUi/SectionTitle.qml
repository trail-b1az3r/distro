import QtQuick

// A section's label, in the primary colour (M3's title small, emphasized).
Text {
    color: Theme.primary
    font.family: Theme.font
    font.pixelSize: Theme.titleSmall
    font.weight: Font.Bold
    font.letterSpacing: 0.1
    Accessible.role: Accessible.Heading
}
