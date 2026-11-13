import QtQuick
import QtQuick.Layouts

// Icon + label + value, as in the hardware summary. The icon sits in an M3 Expressive rounded tile.
RowLayout {
    id: info
    property string iconName
    property string label
    property string value
    property color iconColor: Theme.primaryContainerContent
    spacing: 16
    Rectangle {
        Layout.preferredWidth: 48; Layout.preferredHeight: 48
        radius: Theme.shapeLarge
        color: Theme.primaryContainer
        Icon { anchors.centerIn: parent; name: info.iconName; size: 24; color: info.iconColor }
    }
    ColumnLayout {
        spacing: 2
        Layout.fillWidth: true
        Text { text: info.label; color: Theme.surfaceVariantContent; font.family: Theme.font; font.pixelSize: Theme.labelMedium; font.weight: Font.Medium }
        Text { text: info.value; color: Theme.surfaceContent; font.family: Theme.font; font.pixelSize: Theme.bodyLarge; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    }
}
