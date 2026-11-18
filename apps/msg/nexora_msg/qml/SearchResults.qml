import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// People, conversations and messages that match, the words found in bold.
ListView {
    id: list
    property var results: ({ messages: [], contacts: [], chats: [] })
    signal openChat(int id)
    signal openContact(string handle)
    clip: true
    ScrollBar.vertical: ScrollBar {}

    function bold(text) {
        const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        return esc.replace(/\u0002/g, "<b>").replace(/\u0003/g, "</b>")
    }

    model: {
        const rows = []
        if (results.contacts.length) rows.push({ kind: "header", text: "People" })
        for (const c of results.contacts) rows.push({ kind: "contact", item: c })
        if (results.chats.length) rows.push({ kind: "header", text: "Conversations" })
        for (const c of results.chats) rows.push({ kind: "chat", item: c })
        if (results.messages.length) rows.push({ kind: "header", text: "Messages" })
        for (const m of results.messages) rows.push({ kind: "message", item: m })
        return rows
    }

    delegate: Loader {
        required property var modelData
        width: list.width
        sourceComponent: modelData.kind === "header" ? header : row
        Component {
            id: header
            Label { text: modelData.text; leftPadding: 16; topPadding: 12; bottomPadding: 4; font.pixelSize: 12; font.weight: Font.DemiBold; color: win.accent }
        }
        Component {
            id: row
            ItemDelegate {
                height: 60
                onClicked: {
                    if (modelData.kind === "contact") list.openContact(modelData.item.handles[0] ?? "")
                    else list.openChat(modelData.kind === "chat" ? modelData.item.id : modelData.item.chat_id)
                }
                contentItem: RowLayout {
                    spacing: 12
                    Avatar {
                        implicitWidth: 36; implicitHeight: 36
                        name: modelData.kind === "message" ? modelData.item.sender : (modelData.item.name ?? modelData.item.title)
                        photo: modelData.item.photo ?? ""
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            font.weight: Font.DemiBold
                            text: modelData.kind === "message" ? modelData.item.sender + "  ·  " + new Date(modelData.item.date_ms).toLocaleDateString(Qt.locale(), Locale.ShortFormat)
                                : (modelData.item.name ?? modelData.item.title)
                        }
                        Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            textFormat: Text.StyledText
                            opacity: 0.75
                            font.pixelSize: 13
                            text: modelData.kind === "message" ? list.bold(modelData.item.snippet)
                                : modelData.kind === "contact" ? modelData.item.handles.join(", ") : modelData.item.last_text
                        }
                    }
                }
            }
        }
    }

    Label {
        anchors.centerIn: parent
        visible: list.count === 0
        text: "Nothing found"
        opacity: 0.6
    }
}
