import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A labelled text field with an error message.
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

    Text { text: root.label; color: Theme.fg; font.pixelSize: Theme.text; font.weight: Font.DemiBold; visible: root.label !== "" }
    TextField {
        id: field
        Layout.fillWidth: true
        placeholderText: root.placeholder
        echoMode: root.password ? TextInput.Password : TextInput.Normal
        color: Theme.fg
        placeholderTextColor: Theme.muted
        font.pixelSize: Theme.text
        selectByMouse: true
        Accessible.name: root.label
        leftPadding: 12; rightPadding: 12; topPadding: 10; bottomPadding: 10
        onTextEdited: root.edited(text)
        background: Rectangle {
            radius: Theme.radiusSmall
            color: Theme.surface2
            border.width: field.activeFocus || root.error !== "" ? 2 : 1
            border.color: root.error !== "" ? Theme.danger : (field.activeFocus ? Theme.focus : Theme.border)
        }
    }
    Text {
        visible: root.error !== "" || root.hint !== ""
        text: root.error !== "" ? root.error : root.hint
        color: root.error !== "" ? Theme.danger : Theme.muted
        font.pixelSize: Theme.textSmall
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
}
