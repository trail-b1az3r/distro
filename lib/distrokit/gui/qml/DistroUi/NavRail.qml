import QtQuick
import QtQuick.Layouts

// M3 Expressive navigation rail. Collapsed: icons with labels under them, the selected one in a pill indicator that
// springs open. Expanded: icon and label side by side in a full-width pill. The header (logo, a FAB) goes on top.
//   items: [{id, title, icon}]; current: the selected id.
Rectangle {
    id: rail
    property var items: []
    property string current: ""
    property bool expanded: true
    default property alias header: headerColumn.data
    property alias footer: footerColumn.data
    signal selected(string id)

    implicitWidth: expanded ? 248 : 96
    Behavior on implicitWidth { SpringAnimation { spring: Theme.springSpatial; damping: 0.4 } }
    color: Theme.surfaceContainer
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 20
        anchors.bottomMargin: 20
        anchors.leftMargin: rail.expanded ? 16 : 12
        anchors.rightMargin: rail.expanded ? 16 : 12
        spacing: 4

        ColumnLayout {
            id: headerColumn
            Layout.fillWidth: true
            Layout.bottomMargin: 16
            spacing: 12
        }

        Repeater {
            model: rail.items
            Item {
                id: navItem
                required property var modelData
                readonly property bool on: rail.current === modelData.id
                Layout.fillWidth: true
                implicitHeight: rail.expanded ? 56 : 68
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.title
                Accessible.selected: on
                Keys.onReturnPressed: rail.selected(modelData.id)
                Keys.onSpacePressed: rail.selected(modelData.id)

                // The indicator: a pill behind the icon (collapsed) or the whole row (expanded).
                Rectangle {
                    id: indicator
                    readonly property real fullWidth: rail.expanded ? navItem.width : 56
                    width: navItem.on || rail.expanded ? fullWidth : 32
                    height: rail.expanded ? 56 : 32
                    x: rail.expanded ? 0 : (navItem.width - width) / 2
                    y: rail.expanded ? 0 : 4
                    radius: height / 2
                    color: navItem.on ? Theme.secondaryContainer
                         : navMouse.containsMouse ? Theme.alpha(Theme.surfaceContent, 0.08) : "transparent"
                    Behavior on width { SpringAnimation { spring: Theme.springSpatial; damping: Theme.dampingSpatial } }
                    Behavior on color { ColorAnimation { duration: Theme.durationShort } }
                    border.width: navItem.activeFocus ? 2 : 0
                    border.color: Theme.secondary
                }
                Icon {
                    id: navIcon
                    name: navItem.modelData.icon
                    size: 24
                    color: navItem.on ? Theme.secondaryContainerContent : Theme.surfaceVariantContent
                    x: rail.expanded ? 16 : (navItem.width - width) / 2
                    y: rail.expanded ? (navItem.height - height) / 2 : 8
                }
                Text {
                    text: navItem.modelData.title
                    color: navItem.on ? (rail.expanded ? Theme.secondaryContainerContent : Theme.surfaceContent) : Theme.surfaceVariantContent
                    font.family: Theme.font
                    font.pixelSize: rail.expanded ? Theme.labelLarge : Theme.labelMedium
                    font.weight: navItem.on ? Font.Bold : Font.Medium
                    elide: Text.ElideRight
                    horizontalAlignment: rail.expanded ? Text.AlignLeft : Text.AlignHCenter
                    x: rail.expanded ? 56 : 0
                    width: rail.expanded ? navItem.width - 68 : navItem.width
                    y: rail.expanded ? (navItem.height - height) / 2 : 40
                    maximumLineCount: 1
                }
                MouseArea {
                    id: navMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: rail.selected(navItem.modelData.id)
                }
            }
        }

        Item { Layout.fillHeight: true }
        ColumnLayout {
            id: footerColumn
            Layout.fillWidth: true
            spacing: 8
        }
    }
}
