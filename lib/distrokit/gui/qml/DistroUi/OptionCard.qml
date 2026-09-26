import QtQuick
import QtQuick.Layouts

// A selectable card: icon, title, description, optional badge.
// Keyboard: Tab to focus, Space/Enter to select.
Rectangle {
    id: root
    property string title
    property string description
    property string iconName: ""
    property string badge: ""
    property color badgeColor: Theme.accent2
    property bool selected: false
    property bool radio: true
    signal clicked()

    activeFocusOnTab: true
    Accessible.role: radio ? Accessible.RadioButton : Accessible.CheckBox
    Accessible.name: title
    Accessible.description: description
    Accessible.checked: selected
    Keys.onSpacePressed: if (enabled) clicked()
    Keys.onReturnPressed: if (enabled) clicked()

    implicitHeight: row.implicitHeight + 32
    implicitWidth: 320
    radius: Theme.radius
    color: selected ? Theme.accentSoft : (mouse.containsMouse ? Theme.surface2 : Theme.surface)
    border.width: selected || activeFocus ? 2 : 1
    border.color: activeFocus ? Theme.focus : (selected ? Theme.accent : Theme.border)
    opacity: enabled ? 1 : 0.5
    Behavior on color { ColorAnimation { duration: Theme.animation } }

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 16
        spacing: 14
        Rectangle {
            visible: root.iconName !== ""
            Layout.preferredWidth: 44; Layout.preferredHeight: 44
            Layout.alignment: Qt.AlignTop
            radius: 12
            color: root.selected ? Theme.accent : Theme.surface2
            Icon { anchors.centerIn: parent; name: root.iconName; size: 24; color: root.selected ? Theme.textOnAccent : Theme.fg }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            RowLayout {
                spacing: 8
                Text {
                    text: root.title
                    color: Theme.fg
                    font.pixelSize: Theme.textLarge
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
                Badge { visible: root.badge !== ""; text: root.badge; color: root.badgeColor }
            }
            Text {
                visible: root.description !== ""
                text: root.description
                color: Theme.muted
                font.pixelSize: Theme.text
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        Rectangle {
            Layout.alignment: Qt.AlignTop
            width: 22; height: 22
            radius: root.radio ? 11 : 6
            color: root.selected ? Theme.accent : "transparent"
            border.width: 2
            border.color: root.selected ? Theme.accent : Theme.muted
            Icon { anchors.centerIn: parent; visible: root.selected; name: "check"; size: 14; color: Theme.textOnAccent }
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: { if (root.enabled) { root.forceActiveFocus(); root.clicked() } }
    }
}
