import QtQuick
import QtQuick.Layouts

// M3 Expressive connected button group: segments that touch, with the outer corners round and the inner ones small.
// The chosen segment fills with the secondary container and its corners round fully, with a spring.
//   options: [{id, label, icon}]; current: the chosen id.
Row {
    id: group
    property var options: []
    property string current: ""
    signal chosen(string id)
    spacing: 2
    Accessible.role: Accessible.Grouping

    Repeater {
        model: group.options
        Rectangle {
            id: seg
            required property var modelData
            required property int index
            readonly property bool on: modelData.id === group.current
            readonly property bool first: index === 0
            readonly property bool last: index === group.options.length - 1
            readonly property real outer: height / 2
            readonly property real inner: on ? height / 2 : Theme.shapeSmall
            implicitHeight: 40
            implicitWidth: Math.max(48, content.implicitWidth + 32)
            color: "transparent"
            activeFocusOnTab: true
            Accessible.role: Accessible.RadioButton
            Accessible.name: modelData.label || modelData.icon
            Accessible.checked: on
            Keys.onSpacePressed: group.chosen(modelData.id)
            Keys.onReturnPressed: group.chosen(modelData.id)

            // Corners: four quarter-rounded rectangles would need Shapes; a rounded body with square patches where a
            // corner should be small does the same with plain Rectangles.
            Rectangle {
                id: body
                anchors.fill: parent
                radius: Math.max(seg.first ? seg.outer : seg.inner, seg.last ? seg.outer : seg.inner)
                color: seg.on ? Theme.secondaryContainer : Theme.surfaceContainerHigh
                Behavior on color { ColorAnimation { duration: Theme.durationShort } }
            }
            // Squarer corners on the inner side (until chosen).
            Rectangle {
                visible: !seg.first && !seg.on
                width: parent.width / 2; height: parent.height
                radius: Theme.shapeSmall
                color: body.color
            }
            Rectangle {
                visible: !seg.last && !seg.on
                x: parent.width / 2; width: parent.width / 2; height: parent.height
                radius: Theme.shapeSmall
                color: body.color
            }
            Rectangle {
                anchors.fill: parent
                radius: body.radius
                color: seg.on ? Theme.secondaryContainerContent : Theme.surfaceContent
                opacity: segMouse.pressed ? 0.10 : segMouse.containsMouse ? 0.08 : 0
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: -2
                radius: body.radius + 2
                color: "transparent"
                border.width: 2
                border.color: Theme.secondary
                visible: seg.activeFocus
            }
            Row {
                id: content
                anchors.centerIn: parent
                spacing: 6
                Icon {
                    visible: (seg.modelData.icon || "") !== ""
                    name: seg.modelData.icon || ""
                    size: 18
                    color: seg.on ? Theme.secondaryContainerContent : Theme.surfaceVariantContent
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    visible: (seg.modelData.label || "") !== ""
                    text: seg.modelData.label || ""
                    color: seg.on ? Theme.secondaryContainerContent : Theme.surfaceVariantContent
                    font.family: Theme.font
                    font.pixelSize: Theme.labelLarge
                    font.weight: seg.on ? Font.Bold : Font.Medium
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            MouseArea {
                id: segMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: group.chosen(seg.modelData.id)
            }
        }
    }
}
