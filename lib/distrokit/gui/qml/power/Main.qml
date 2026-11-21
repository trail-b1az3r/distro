import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

// The power menu: the screen dimmed, a row of round buttons in the middle. Arrow keys or Tab move, Enter or a click
// chooses, Escape or a click outside closes.
ApplicationWindow {
    id: win
    objectName: "powerMenu"
    visible: true
    visibility: Window.FullScreen
    flags: Qt.FramelessWindowHint
    title: qsTr("Power")
    color: Theme.alpha(Theme.background, 0.78)
    font.family: Theme.font
    property int current: Math.max(0, power.actions.findIndex(a => a.id === "poweroff"))

    function choose(i) {
        if (i >= 0 && i < power.actions.length)
            power.perform(power.actions[i].id)
    }

    MouseArea {
        anchors.fill: parent
        onClicked: Qt.quit()
    }

    Item {
        focus: true
        anchors.fill: parent
        Keys.onEscapePressed: Qt.quit()
        Keys.onLeftPressed: win.current = (win.current + power.actions.length - 1) % power.actions.length
        Keys.onRightPressed: win.current = (win.current + 1) % power.actions.length
        Keys.onTabPressed: win.current = (win.current + 1) % power.actions.length
        Keys.onBacktabPressed: win.current = (win.current + power.actions.length - 1) % power.actions.length
        Keys.onReturnPressed: win.choose(win.current)
        Keys.onEnterPressed: win.choose(win.current)
        Keys.onSpacePressed: win.choose(win.current)
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 28

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: power.userName ? qsTr("Goodbye for now, %1").arg(power.userName) : qsTr("Power")
            color: Theme.surfaceContent
            font.pixelSize: 26
            font.weight: Font.DemiBold
        }

        RowLayout {
            objectName: "actions"
            Layout.alignment: Qt.AlignHCenter
            spacing: 18

            Repeater {
                model: power.actions
                delegate: ColumnLayout {
                    id: cell
                    required property var modelData
                    required property int index
                    readonly property bool active: win.current === index || area.containsMouse
                    Layout.alignment: Qt.AlignTop
                    spacing: 10

                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 84
                        height: 84
                        radius: cell.active ? 28 : 42
                        color: cell.active
                            ? (cell.modelData.danger ? Theme.errorContainer : Theme.primaryContainer)
                            : Theme.surfaceContainerHigh
                        Behavior on radius { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 160 } }
                        Icon {
                            anchors.centerIn: parent
                            name: cell.modelData.icon
                            size: 32
                            color: cell.active
                                ? (cell.modelData.danger ? Theme.errorContainerContent : Theme.primaryContainerContent)
                                : Theme.surfaceContent
                        }
                        MouseArea {
                            id: area
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: win.current = cell.index
                            onClicked: win.choose(cell.index)
                        }
                        Accessible.role: Accessible.Button
                        Accessible.name: cell.modelData.label
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 110
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: cell.modelData.label
                        color: cell.active ? Theme.surfaceContent : Theme.alpha(Theme.surfaceContent, 0.7)
                        font.pixelSize: 14
                    }
                }
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: qsTr("Esc to cancel")
            color: Theme.alpha(Theme.surfaceContent, 0.55)
            font.pixelSize: 12
        }
    }
}
