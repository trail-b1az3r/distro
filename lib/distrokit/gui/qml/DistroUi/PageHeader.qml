import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property string title
    property string subtitle
    spacing: 6
    Text {
        text: parent.title
        color: Theme.fg
        font.pixelSize: Theme.title
        font.weight: Font.Bold
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }
    Text {
        visible: parent.subtitle !== ""
        text: parent.subtitle
        color: Theme.muted
        font.pixelSize: Theme.textLarge
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
}
