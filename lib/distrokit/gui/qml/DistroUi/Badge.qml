import QtQuick

// A small pill label. Its text takes the colour that reads on the fill (the matching "on" colour for M3 containers).
Rectangle {
    id: badge
    property alias text: label.text
    color: Theme.tertiaryContainer
    readonly property color content: {
        if (Qt.colorEqual(color, Theme.tertiaryContainer)) return Theme.tertiaryContainerContent
        if (Qt.colorEqual(color, Theme.secondaryContainer)) return Theme.secondaryContainerContent
        if (Qt.colorEqual(color, Theme.primaryContainer)) return Theme.primaryContainerContent
        if (Qt.colorEqual(color, Theme.errorContainer)) return Theme.errorContainerContent
        if (Qt.colorEqual(color, Theme.warningContainer)) return Theme.warningContainerContent
        if (Qt.colorEqual(color, Theme.successContainer)) return Theme.successContainerContent
        // Any other fill: dark or light text, whichever reads.
        return (0.299 * color.r + 0.587 * color.g + 0.114 * color.b) > 0.6 ? "#1A1C22" : "#FFFFFF"
    }
    radius: height / 2
    implicitHeight: label.implicitHeight + 8
    implicitWidth: label.implicitWidth + 20
    Text {
        id: label
        anchors.centerIn: parent
        color: badge.content
        font.family: Theme.font
        font.pixelSize: Theme.labelMedium
        font.weight: Font.DemiBold
    }
}
