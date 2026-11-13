import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A labelled M3 text field (filled, with an active indicator underline) and an error or hint.
ColumnLayout {
    id: root
    property string label
    property string placeholder
    property alias text: field.text
    property bool password: false
    property string error: ""
    property string hint: ""
    property alias field: field
    signal edited(string value)
    spacing: 6

    Text {
        text: root.label
        color: root.error !== "" ? Theme.error : field.activeFocus ? Theme.primary : Theme.surfaceVariantContent
        font.family: Theme.font
        font.pixelSize: Theme.labelLarge
        font.weight: Font.Medium
        visible: root.label !== ""
    }
    TextField {
        id: field
        Layout.fillWidth: true
        placeholderText: root.placeholder
        echoMode: root.password ? TextInput.Password : TextInput.Normal
        color: Theme.surfaceContent
        placeholderTextColor: Theme.surfaceVariantContent
        selectionColor: Theme.primaryContainer
        selectedTextColor: Theme.primaryContainerContent
        font.family: Theme.font
        font.pixelSize: Theme.bodyLarge
        selectByMouse: true
        Accessible.name: root.label
        leftPadding: 16; rightPadding: 16; topPadding: 14; bottomPadding: 14
        onTextEdited: root.edited(text)
        background: Rectangle {
            implicitHeight: 56
            radius: Theme.shapeLarge
            color: Theme.surfaceContainerHighest
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.leftMargin: Theme.shapeLarge / 2; anchors.rightMargin: Theme.shapeLarge / 2
                height: field.activeFocus || root.error !== "" ? 3 : 1
                radius: height / 2
                color: root.error !== "" ? Theme.error : field.activeFocus ? Theme.primary : Theme.surfaceVariantContent
                Behavior on height { NumberAnimation { duration: Theme.durationShort } }
            }
        }
    }
    Text {
        visible: root.error !== "" || root.hint !== ""
        text: root.error !== "" ? root.error : root.hint
        color: root.error !== "" ? Theme.error : Theme.surfaceVariantContent
        font.family: Theme.font
        font.pixelSize: Theme.bodySmall
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        Layout.leftMargin: 16
    }
}
