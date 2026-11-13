import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A labelled M3 switch with a description: the thumb grows when on and shows a check.
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
                Text { text: root.title; color: Theme.surfaceContent; font.family: Theme.font; font.pixelSize: Theme.titleMedium; font.weight: Font.Medium }
                Badge { visible: root.badge !== ""; text: root.badge }
            }
            Text {
                visible: root.description !== ""
                text: root.description; color: Theme.surfaceVariantContent; font.family: Theme.font; font.pixelSize: Theme.bodyMedium
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
                implicitWidth: 52; implicitHeight: 32
                x: sw.leftPadding; y: parent.height / 2 - height / 2
                radius: 16
                color: sw.checked ? Theme.primary : Theme.surfaceContainerHighest
                border.width: sw.checked ? 0 : 2
                border.color: Theme.outline
                Behavior on color { ColorAnimation { duration: Theme.durationShort } }
                Rectangle {
                    id: thumb
                    property real thumbSize: sw.pressed ? 28 : sw.checked ? 24 : 16
                    width: thumbSize; height: thumbSize; radius: thumbSize / 2
                    x: sw.checked ? parent.width - width - 4 : (sw.pressed ? 2 : 8)
                    anchors.verticalCenter: parent.verticalCenter
                    color: sw.checked ? Theme.primaryContent : Theme.outline
                    Behavior on x { SpringAnimation { spring: Theme.springSpatial; damping: Theme.dampingSpatial } }
                    Behavior on thumbSize { SpringAnimation { spring: Theme.springFast; damping: Theme.dampingFast } }
                    Icon { anchors.centerIn: parent; visible: sw.checked; name: "check"; size: 16; color: Theme.primaryContainerContent }
                }
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -3
                    radius: parent.radius + 3
                    color: "transparent"
                    border.width: 2
                    border.color: Theme.secondary
                    visible: sw.visualFocus
                }
            }
        }
    }
}
