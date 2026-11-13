import QtQuick
import QtQuick.Layouts

// M3 cards: tonal containers with extra-large corners. Content goes into the column.
//   variant: "filled" (surface container), "elevated" (higher container), "outlined"
Rectangle {
    id: card
    default property alias content: column.data
    property int padding: Theme.pad
    property alias spacing: column.spacing
    property bool highlighted: false
    property color tint: "transparent"
    property string variant: "filled"

    color: tint.a > 0 ? tint
         : highlighted ? Theme.secondaryContainer
         : variant === "outlined" ? Theme.surface
         : variant === "elevated" ? Theme.surfaceContainerHigh
         : Theme.surfaceContainer
    radius: Theme.shapeExtraLarge
    border.width: variant === "outlined" ? 1 : 0
    border.color: Theme.outlineVariant
    implicitHeight: column.implicitHeight + padding * 2
    implicitWidth: column.implicitWidth + padding * 2
    Behavior on color { ColorAnimation { duration: Theme.durationShort } }

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: Theme.gap
    }
}
