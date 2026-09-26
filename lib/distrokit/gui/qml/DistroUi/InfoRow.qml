import QtQuick
import QtQuick.Layouts

// Icon + label + value, as in the hardware summary.
RowLayout {
    property string iconName
    property string label
    property string value
    property color iconColor: Theme.accent
    spacing: 14
    Rectangle {
        Layout.preferredWidth: 40; Layout.preferredHeight: 40
        radius: 12
        color: Theme.accentSoft
        Icon { anchors.centerIn: parent; name: parent.parent.iconName; size: 22; color: parent.parent.iconColor }
    }
    ColumnLayout {
        spacing: 2
        Layout.fillWidth: true
        Text { text: parent.parent.label; color: Theme.muted; font.pixelSize: Theme.textSmall; font.weight: Font.Bold }
        Text { text: parent.parent.value; color: Theme.fg; font.pixelSize: Theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    }
}
