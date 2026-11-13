import QtQuick
import QtQuick.Layouts

// Vertical list of steps (done / current / upcoming). The current step sits in a pill of the secondary container;
// its number grows into a filled circle, done steps show a check.
ColumnLayout {
    id: root
    property var steps: []          // [{title}]
    property int current: 0
    property bool compact: false
    signal jump(int index)
    spacing: 2
    Repeater {
        model: root.steps
        delegate: Rectangle {
            id: step
            required property var modelData
            required property int index
            readonly property bool done: index < root.current
            readonly property bool active: index === root.current
            Layout.fillWidth: true
            implicitHeight: 48
            radius: height / 2
            color: active ? Theme.secondaryContainer : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.durationShort } }
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData.title + (done ? qsTr(", done") : active ? qsTr(", current step") : "")
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: Theme.surfaceContent
                opacity: stepMouse.containsMouse && step.done ? 0.08 : 0
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                spacing: 12
                Rectangle {
                    width: 28; height: 28
                    radius: step.active ? 14 : step.done ? 14 : 9
                    Behavior on radius { SpringAnimation { spring: Theme.springSpatial; damping: Theme.dampingSpatial } }
                    color: step.done || step.active ? Theme.primary : "transparent"
                    border.width: step.done || step.active ? 0 : 2
                    border.color: Theme.outlineVariant
                    Icon { anchors.centerIn: parent; visible: step.done; name: "check"; size: 14; color: Theme.primaryContent }
                    Text {
                        anchors.centerIn: parent
                        visible: !step.done
                        text: step.index + 1
                        color: step.active ? Theme.primaryContent : Theme.surfaceVariantContent
                        font.family: Theme.font; font.pixelSize: Theme.labelMedium; font.weight: Font.Bold
                    }
                }
                Text {
                    text: step.modelData.title
                    color: step.active ? Theme.secondaryContainerContent : step.done ? Theme.surfaceContent : Theme.surfaceVariantContent
                    font.family: Theme.font
                    font.pixelSize: Theme.labelLarge
                    font.weight: step.active ? Font.Bold : Font.Medium
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                id: stepMouse
                anchors.fill: parent
                hoverEnabled: true
                enabled: step.done
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.jump(step.index)
            }
        }
    }
}
