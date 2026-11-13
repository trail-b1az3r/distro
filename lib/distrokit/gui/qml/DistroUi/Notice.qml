import QtQuick
import QtQuick.Layouts

// A tonal message box: info | warning | danger | success, in the matching M3 container colours.
Rectangle {
    id: root
    property string kind: "info"
    property string title: ""
    property string text: ""
    default property alias extra: col.data
    readonly property color container: kind === "danger" ? Theme.errorContainer : kind === "warning" ? Theme.warningContainer
                                      : kind === "success" ? Theme.successContainer : Theme.secondaryContainer
    readonly property color content: kind === "danger" ? Theme.errorContainerContent : kind === "warning" ? Theme.warningContainerContent
                                    : kind === "success" ? Theme.successContainerContent : Theme.secondaryContainerContent
    radius: Theme.shapeLargeIncreased
    color: container
    implicitHeight: row.implicitHeight + 32
    Accessible.role: Accessible.AlertMessage
    Accessible.name: title + " " + text
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 16
        spacing: 14
        Icon {
            Layout.alignment: Qt.AlignTop
            name: root.kind === "danger" ? "alert" : root.kind === "warning" ? "alert" : root.kind === "success" ? "check-circle" : "info"
            size: 22
            color: root.content
        }
        ColumnLayout {
            id: col
            Layout.fillWidth: true
            spacing: 4
            Text { visible: root.title !== ""; text: root.title; color: root.content; font.family: Theme.font; font.pixelSize: Theme.titleSmall; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Text { visible: root.text !== ""; text: root.text; color: root.content; font.family: Theme.font; font.pixelSize: Theme.bodyMedium; wrapMode: Text.WordWrap; Layout.fillWidth: true; textFormat: Text.PlainText }
        }
    }
}
