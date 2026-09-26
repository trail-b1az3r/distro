import QtQuick
import QtQuick.Controls.Basic

// Styled combo box. `options` is [{id, label}]; `current` is the selected id.
ComboBox {
    id: control
    property var options: []
    property string current: ""
    signal chosen(string id)
    model: options
    textRole: "label"
    valueRole: "id"
    currentIndex: Math.max(0, options.findIndex(o => o.id === current))
    font.pixelSize: Theme.text
    implicitHeight: 42
    Accessible.role: Accessible.ComboBox
    onActivated: (index) => chosen(options[index].id)
    contentItem: Text {
        leftPadding: 12
        rightPadding: 30
        text: control.displayText
        color: Theme.fg
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Icon {
        x: control.width - width - 10
        y: (control.height - height) / 2
        name: "arrow-right"
        rotation: 90
        size: 16
        color: Theme.muted
    }
    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.surface2
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? Theme.focus : Theme.border
    }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width
        highlighted: control.highlightedIndex === index
        contentItem: Text { text: modelData.label; color: Theme.fg; font.pixelSize: Theme.text; elide: Text.ElideRight }
        background: Rectangle { color: highlighted ? Theme.accentSoft : Theme.surface }
    }
    popup.background: Rectangle { color: Theme.surface; border.color: Theme.border; radius: Theme.radiusSmall }
}
