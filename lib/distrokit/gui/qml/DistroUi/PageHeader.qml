import QtQuick
import QtQuick.Layouts

// A page's title (M3 Expressive's emphasized headline) and subtitle.
ColumnLayout {
    property string title
    property string subtitle
    spacing: 8
    Text {
        text: parent.title
        color: Theme.surfaceContent
        font.family: Theme.font
        font.pixelSize: Theme.headlineLarge
        font.weight: Theme.emphasized
        font.letterSpacing: -0.25
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }
    Text {
        visible: parent.subtitle !== ""
        text: parent.subtitle
        color: Theme.surfaceVariantContent
        font.family: Theme.font
        font.pixelSize: Theme.bodyLarge
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
}
