import QtQuick
import QtQuick.Layouts

// A selectable card: icon, title, description, optional badge. Selected, it fills with the secondary container and
// its corners and icon tile morph (M3 Expressive). Keyboard: Tab to focus, Space/Enter to select.
Rectangle {
    id: root
    property string title
    property string description
    property string iconName: ""
    property string badge: ""
    property color badgeColor: Theme.tertiaryContainer
    property bool selected: false
    property bool radio: true
    // "select": radio/check mark; "navigate": an arrow (the card opens something)
    property string indicator: "select"
    signal clicked()

    activeFocusOnTab: true
    Accessible.role: radio ? Accessible.RadioButton : Accessible.CheckBox
    Accessible.name: title
    Accessible.description: description
    Accessible.checked: selected
    Keys.onSpacePressed: if (enabled) clicked()
    Keys.onReturnPressed: if (enabled) clicked()

    implicitHeight: row.implicitHeight + 40
    implicitWidth: 320
    radius: selected ? Theme.shapeExtraLargeIncreased : Theme.shapeLargeIncreased
    Behavior on radius { SpringAnimation { spring: Theme.springSpatial; damping: Theme.dampingSpatial } }
    color: selected ? Theme.secondaryContainer : Theme.surfaceContainer
    border.width: activeFocus ? 2 : 0
    border.color: Theme.secondary
    opacity: enabled ? 1 : 0.5
    Behavior on color { ColorAnimation { duration: Theme.durationShort } }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: root.selected ? Theme.secondaryContainerContent : Theme.surfaceContent
        opacity: mouse.pressed ? 0.10 : mouse.containsMouse ? 0.08 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durationShort } }
    }

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 20
        spacing: 16
        Rectangle {
            visible: root.iconName !== ""
            Layout.preferredWidth: 48; Layout.preferredHeight: 48
            Layout.alignment: Qt.AlignTop
            // A circle selected, a rounded square otherwise.
            radius: root.selected ? 24 : Theme.shapeLarge
            Behavior on radius { SpringAnimation { spring: Theme.springSpatial; damping: Theme.dampingSpatial } }
            color: root.selected ? Theme.primary : Theme.surfaceContainerHighest
            Icon { anchors.centerIn: parent; name: root.iconName; size: 24; color: root.selected ? Theme.primaryContent : Theme.surfaceVariantContent }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            RowLayout {
                spacing: 8
                Text {
                    text: root.title
                    color: root.selected ? Theme.secondaryContainerContent : Theme.surfaceContent
                    font.family: Theme.font
                    font.pixelSize: Theme.titleMedium
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
                Badge { visible: root.badge !== ""; text: root.badge; color: root.badgeColor }
            }
            Text {
                visible: root.description !== ""
                text: root.description
                color: root.selected ? Theme.secondaryContainerContent : Theme.surfaceVariantContent
                font.family: Theme.font
                font.pixelSize: Theme.bodyMedium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        Icon {
            visible: root.indicator === "navigate"
            Layout.alignment: Qt.AlignVCenter
            name: "arrow-right"
            size: 20
            color: Theme.surfaceVariantContent
        }
        Rectangle {
            visible: root.indicator === "select"
            Layout.alignment: Qt.AlignTop
            width: 24; height: 24
            radius: root.radio ? 12 : 6
            color: root.selected ? Theme.primary : "transparent"
            border.width: 2
            border.color: root.selected ? Theme.primary : Theme.surfaceVariantContent
            Icon { anchors.centerIn: parent; visible: root.selected; name: "check"; size: 16; color: Theme.primaryContent }
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
