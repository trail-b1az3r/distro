import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A labelled switch with a description.
Item {
    id: root
    property string title
    property string description
    property bool checked: false
    property string badge: ""
    signal toggled(bool value)

    implicitHeight: layout.implicitHeight + 16
    implicitWidth: 400
    opacity: enabled ? 1 : 0.5

    RowLayout {
        id: layout
        anchors.fill: parent
        anchors.topMargin: 8; anchors.bottomMargin: 8
        spacing: 16
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                spacing: 8
                Text { text: root.title; color: Theme.fg; font.pixelSize: Theme.text; font.weight: Font.DemiBold }
                Badge { visible: root.badge !== ""; text: root.badge }
            }
            Text {
                visible: root.description !== ""
                text: root.description; color: Theme.muted; font.pixelSize: Theme.textSmall
                wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
        }
        Switch {
            id: sw
            checked: root.checked
            enabled: root.enabled
            Accessible.name: root.title
            onToggled: root.toggled(checked)
            indicator: Rectangle {
                implicitWidth: 46; implicitHeight: 26
                x: sw.leftPadding; y: parent.height / 2 - height / 2
                radius: 13
                color: sw.checked ? Theme.accent : Theme.surface2
                border.color: sw.visualFocus ? Theme.focus : Theme.border
                border.width: sw.visualFocus ? 2 : 1
                Rectangle {
                    x: sw.checked ? parent.width - width - 3 : 3
                    anchors.verticalCenter: parent.verticalCenter
                    width: 20; height: 20; radius: 10
                    color: "#FFFFFF"
                    Behavior on x { NumberAnimation { duration: Theme.animation } }
                }
            }
        }
    }
}
