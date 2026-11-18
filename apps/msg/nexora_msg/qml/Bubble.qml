import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One message: blue (iMessage) or green (SMS) on the right when it is yours, grey on the left otherwise.
Item {
    id: root
    property var message
    property bool showSender: false
    property bool showTime: false
    readonly property bool mine: message.from_me
    readonly property color tint: !mine ? (Qt.colorEqual(win.surface, "#fdfbff") ? "#e9e9eb" : "#3a3a3c")
                                       : (message.service === "SMS" ? "#34c759" : win.accent)
    implicitHeight: col.implicitHeight + 4

    ColumnLayout {
        id: col
        width: parent.width
        spacing: 2
        Label {
            visible: root.showTime
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            font.pixelSize: 11
            opacity: 0.55
            text: new Date(root.message.date_ms).toLocaleString(Qt.locale(), Locale.ShortFormat)
        }
        Label {
            visible: root.showSender
            text: root.message.sender
            font.pixelSize: 11
            opacity: 0.6
            Layout.leftMargin: 26
        }
        Repeater {
            model: root.message.attachments
            delegate: Image {
                required property var modelData
                Layout.alignment: root.mine ? Qt.AlignRight : Qt.AlignLeft
                Layout.leftMargin: 16
                Layout.rightMargin: 16
                Layout.preferredWidth: Math.min(260, root.width * 0.6)
                Layout.preferredHeight: status === Image.Ready ? Layout.preferredWidth * implicitHeight / Math.max(1, implicitWidth) : 40
                visible: modelData.path.length > 0
                source: modelData.path ? "file://" + modelData.path : ""
                sourceSize.width: 520
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                Label {
                    anchors.centerIn: parent
                    visible: parent.status === Image.Error
                    text: "📎 " + (modelData.name || "attachment")
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(parent.source) }
            }
        }
        Rectangle {
            visible: root.message.text.length > 0
            Layout.alignment: root.mine ? Qt.AlignRight : Qt.AlignLeft
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            Layout.maximumWidth: root.width * 0.72
            implicitWidth: Math.min(text.implicitWidth + 28, root.width * 0.72)
            implicitHeight: text.implicitHeight + 16
            radius: 18
            color: root.tint
            TextEdit {
                id: text
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                anchors.topMargin: 8
                anchors.bottomMargin: 8
                text: root.message.text
                wrapMode: Text.Wrap
                readOnly: true
                selectByMouse: true
                color: root.mine ? "white" : win.onSurface
                font.pixelSize: 14
                textFormat: TextEdit.PlainText
            }
        }
    }
}
