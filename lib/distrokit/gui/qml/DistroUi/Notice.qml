import QtQuick
import QtQuick.Layouts

// Coloured message box: info | warning | danger | success.
Rectangle {
    id: root
    property string kind: "info"
    property string title: ""
    property string text: ""
    default property alias extra: col.data
    readonly property color tone: kind === "danger" ? Theme.danger : kind === "warning" ? Theme.warning : kind === "success" ? Theme.success : Theme.accent
    radius: Theme.radiusSmall
    color: Qt.rgba(tone.r, tone.g, tone.b, Theme.dark ? 0.14 : 0.10)
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.5)
    implicitHeight: row.implicitHeight + 24
    Accessible.role: Accessible.AlertMessage
    Accessible.name: title + " " + text
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12
        Icon {
            Layout.alignment: Qt.AlignTop
            name: root.kind === "danger" ? "alert" : root.kind === "warning" ? "alert" : root.kind === "success" ? "check-circle" : "info"
            size: 20
            color: root.tone
        }
        ColumnLayout {
            id: col
            Layout.fillWidth: true
            spacing: 4
            Text { visible: root.title !== ""; text: root.title; color: Theme.fg; font.pixelSize: Theme.text; font.weight: Font.Bold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Text { visible: root.text !== ""; text: root.text; color: Theme.fg; font.pixelSize: Theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true; textFormat: Text.PlainText }
        }
    }
}
