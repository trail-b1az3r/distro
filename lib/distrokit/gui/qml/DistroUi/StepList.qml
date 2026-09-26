import QtQuick
import QtQuick.Layouts

// Vertical list of steps with done / current / upcoming states.
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
            required property var modelData
            required property int index
            Layout.fillWidth: true
            implicitHeight: 38
            radius: 10
            color: index === root.current ? Theme.accentSoft : "transparent"
            Accessible.role: Accessible.ListItem
            Accessible.name: modelData.title + (index < root.current ? qsTr(", done") : index === root.current ? qsTr(", current step") : "")
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                spacing: 10
                Rectangle {
                    width: 22; height: 22; radius: 11
                    color: index < root.current ? Theme.accent : "transparent"
                    border.width: 2
                    border.color: index <= root.current ? Theme.accent : Theme.border
                    Icon { anchors.centerIn: parent; visible: index < root.current; name: "check"; size: 12; color: Theme.textOnAccent }
                    Text { anchors.centerIn: parent; visible: index >= root.current; text: index + 1; color: index === root.current ? Theme.accent : Theme.muted; font.pixelSize: 10; font.weight: Font.Bold }
                }
                Text {
                    text: modelData.title
                    color: index === root.current ? Theme.fg : (index < root.current ? Theme.fg : Theme.muted)
                    font.pixelSize: Theme.text
                    font.weight: index === root.current ? Font.DemiBold : Font.Normal
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                anchors.fill: parent
                enabled: index < root.current
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.jump(index)
            }
        }
    }
}
