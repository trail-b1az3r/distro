import QtQuick
import QtQuick.Layouts

// A rounded panel. Content goes into `default` children via the column.
Rectangle {
    id: card
    default property alias content: column.data
    property int padding: Theme.pad
    property alias spacing: column.spacing
    property bool highlighted: false
    property color tint: "transparent"

    color: tint !== "transparent" ? tint : Theme.surface
    radius: Theme.radius
    border.width: highlighted ? 2 : 1
    border.color: highlighted ? Theme.accent : Theme.border
    implicitHeight: column.implicitHeight + padding * 2
    implicitWidth: column.implicitWidth + padding * 2
    Behavior on border.color { ColorAnimation { duration: Theme.animation } }

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: Theme.gap
    }
}
