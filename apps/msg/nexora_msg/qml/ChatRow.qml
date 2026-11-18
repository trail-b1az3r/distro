import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ItemDelegate {
    id: row
    property var chat
    property bool selected: false
    height: 68
    highlighted: selected

    function ago(ms) {
        if (!ms) return ""
        const d = new Date(ms), now = new Date()
        if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
        if (now - d < 6 * 864e5) return d.toLocaleDateString(Qt.locale(), "ddd")
        return d.toLocaleDateString(Qt.locale(), Locale.ShortFormat)
    }

    contentItem: RowLayout {
        spacing: 12
        Avatar { name: row.chat.title; photo: row.chat.photo; group: row.chat.group }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Label { text: row.chat.title; font.weight: row.chat.unread > 0 ? Font.Bold : Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                Label { text: row.ago(row.chat.last_ms); font.pixelSize: 11; opacity: 0.6 }
            }
            RowLayout {
                Label {
                    text: (row.chat.last_from_me ? "You: " : "") + row.chat.last_text.replace(/\n/g, " ")
                    elide: Text.ElideRight
                    opacity: row.chat.unread > 0 ? 0.95 : 0.6
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }
                Rectangle {
                    visible: row.chat.unread > 0
                    width: 20; height: 20; radius: 10
                    color: win.accent
                    Label { anchors.centerIn: parent; text: row.chat.unread; color: "white"; font.pixelSize: 11 }
                }
            }
        }
    }
}
