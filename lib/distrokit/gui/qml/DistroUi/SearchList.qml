import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A searchable list of strings (or {value, label} objects), in an M3 list container.
ColumnLayout {
    id: root
    property var items: []
    property string current: ""
    property string placeholder: qsTr("Search…")
    property int listHeight: 280
    signal picked(string value)
    spacing: 8

    readonly property var filtered: {
        const q = search.text.toLowerCase().trim()
        return items.filter(i => {
            const label = (typeof i === "string") ? i : (i.label + " " + i.value)
            return q === "" || label.toLowerCase().indexOf(q) >= 0
        })
    }

    TextInput2 { id: search; Layout.fillWidth: true; placeholder: root.placeholder }
    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: root.listHeight
        radius: Theme.shapeExtraLarge
        color: Theme.surfaceContainer
        clip: true
        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 8
            spacing: 2
            model: root.filtered
            activeFocusOnTab: true
            keyNavigationEnabled: true
            Accessible.role: Accessible.List
            ScrollBar.vertical: ScrollBar {}
            currentIndex: {
                for (let i = 0; i < root.filtered.length; ++i) {
                    const v = typeof root.filtered[i] === "string" ? root.filtered[i] : root.filtered[i].value
                    if (v === root.current) return i
                }
                return -1
            }
            delegate: Rectangle {
                required property var modelData
                required property int index
                readonly property string value: typeof modelData === "string" ? modelData : modelData.value
                readonly property bool chosen: value === root.current
                width: ListView.view.width
                height: 48
                radius: chosen ? height / 2 : Theme.shapeLarge
                Behavior on radius { SpringAnimation { spring: Theme.springFast; damping: Theme.dampingFast } }
                color: chosen ? Theme.secondaryContainer : (ma.containsMouse ? Theme.alpha(Theme.surfaceContent, 0.08) : "transparent")
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left; anchors.leftMargin: 16
                    text: typeof modelData === "string" ? modelData : modelData.label
                    color: parent.chosen ? Theme.secondaryContainerContent : Theme.surfaceContent
                    font.family: Theme.font
                    font.pixelSize: Theme.bodyLarge
                    font.weight: parent.chosen ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                    width: parent.width - 32
                }
                MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: root.picked(parent.value) }
            }
            Keys.onReturnPressed: if (currentItem) root.picked(currentItem.value)
        }
    }
}
