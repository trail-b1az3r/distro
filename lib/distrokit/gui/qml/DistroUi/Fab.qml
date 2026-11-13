import QtQuick
import QtQuick.Controls.Basic

// M3 Expressive floating action button: a large rounded square in the primary container; extended (with a label)
// when `text` is set. Its corners morph rounder while pressed.
Button {
    id: fab
    property string iconName: "sparkles"
    property string size: "medium"   // small 40 | medium 56 | large 96
    readonly property int side: size === "large" ? 96 : size === "small" ? 40 : 56
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: text !== "" ? 20 : 0
    rightPadding: text !== "" ? 24 : 0
    topPadding: 0; bottomPadding: 0
    Accessible.role: Accessible.Button
    Accessible.name: text !== "" ? text : iconName
    font.family: Theme.font
    font.pixelSize: Theme.titleMedium
    font.weight: Font.DemiBold
    contentItem: Row {
        spacing: 12
        Icon {
            name: fab.iconName
            size: fab.size === "large" ? 36 : 24
            color: Theme.primaryContainerContent
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: fab.text !== ""
            text: fab.text
            font: fab.font
            color: Theme.primaryContainerContent
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        implicitWidth: fab.side
        implicitHeight: fab.side
        radius: fab.down ? height / 2 : (fab.size === "large" ? Theme.shapeExtraLarge : fab.size === "small" ? Theme.shapeMedium : Theme.shapeLarge)
        Behavior on radius { SpringAnimation { spring: Theme.springFast; damping: Theme.dampingFast } }
        color: Theme.primaryContainer
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.primaryContainerContent
            opacity: fab.down ? 0.12 : fab.hovered || fab.visualFocus ? 0.08 : 0
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.secondary
            visible: fab.visualFocus
        }
    }
}
