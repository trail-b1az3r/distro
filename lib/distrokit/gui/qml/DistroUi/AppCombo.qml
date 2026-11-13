import QtQuick
import QtQuick.Controls.Basic

// An M3 exposed dropdown menu. `options` is [{id, label}]; `current` is the selected id.
ComboBox {
    id: control
    property var options: []
    property string current: ""
    signal chosen(string id)
    model: options
    textRole: "label"
    valueRole: "id"
    currentIndex: Math.max(0, options.findIndex(o => o.id === current))
    font.family: Theme.font
    font.pixelSize: Theme.bodyLarge
    implicitHeight: 56
    Accessible.role: Accessible.ComboBox
    onActivated: (index) => chosen(options[index].id)
    contentItem: Text {
        leftPadding: 16
        rightPadding: 40
        text: control.displayText
        color: Theme.surfaceContent
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Icon {
        x: control.width - width - 16
        y: (control.height - height) / 2
        name: "arrow-right"
        rotation: control.popup.visible ? -90 : 90
        Behavior on rotation { SpringAnimation { spring: Theme.springFast; damping: Theme.dampingFast } }
        size: 18
        color: Theme.surfaceVariantContent
    }
    background: Rectangle {
        radius: Theme.shapeLarge
        color: Theme.surfaceContainerHighest
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.primary
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.surfaceContent
            opacity: control.hovered ? 0.08 : 0
        }
    }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width - 16
        x: 8
        height: 48
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            leftPadding: 4
            text: modelData.label; color: control.currentIndex === index ? Theme.secondaryContainerContent : Theme.surfaceContent
            font.family: Theme.font; font.pixelSize: Theme.bodyLarge; elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: Theme.shapeMedium
            color: control.currentIndex === index ? Theme.secondaryContainer
                 : highlighted ? Theme.alpha(Theme.surfaceContent, 0.08) : "transparent"
        }
    }
    popup.topPadding: 8
    popup.bottomPadding: 8
    popup.background: Rectangle { color: Theme.surfaceContainer; radius: Theme.shapeLarge }
}
