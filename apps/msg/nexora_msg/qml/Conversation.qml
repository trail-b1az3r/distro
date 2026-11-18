import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: root
    signal back()
    property string image: ""

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        visible: msg.currentChat > 0

        // Who it is with.
        ToolBar {
            Layout.fillWidth: true
            implicitHeight: 56
            background: Rectangle { color: win.surface; Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: win.dim; opacity: 0.2 } }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                ToolButton { visible: win.narrow; icon.source: "icons/back.svg"; onClicked: root.back() }
                Avatar { implicitWidth: 34; implicitHeight: 34; name: msg.chatInfo.title ?? ""; photo: msg.chatInfo.photo ?? ""; group: msg.chatInfo.group ?? false }
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    Label { text: msg.chatInfo.title ?? ""; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                    Label { text: (msg.chatInfo.handles ?? []).join(", "); font.pixelSize: 11; opacity: 0.6; elide: Text.ElideRight; Layout.fillWidth: true
                            visible: (msg.chatInfo.title ?? "") !== (msg.chatInfo.handles ?? []).join(", ") }
                }
            }
        }

        ListView {
            id: list
            objectName: "messages"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: msg.messages
            verticalLayoutDirection: ListView.TopToBottom
            ScrollBar.vertical: ScrollBar {}
            onCountChanged: if (atYEnd || count < 100) Qt.callLater(positionViewAtEnd)
            onAtYBeginningChanged: if (atYBeginning && count >= 80) msg.loadOlder()
            topMargin: 12
            bottomMargin: 12
            delegate: Bubble {
                required property var modelData
                required property int index
                message: modelData
                width: list.width
                // The sender's name above the first of a run in a group; the time when a gap opens.
                showSender: (msg.chatInfo.group ?? false) && !modelData.from_me && (index === 0 || msg.messages[index - 1].handle !== modelData.handle)
                showTime: index === 0 || modelData.date_ms - msg.messages[index - 1].date_ms > 3600000
            }
        }

        // What to send.
        Pane {
            Layout.fillWidth: true
            padding: 8
            background: Rectangle { color: win.panel }
            ColumnLayout {
                width: parent.width
                Item {
                    visible: root.image.length > 0
                    Layout.preferredHeight: 96
                    Layout.preferredWidth: 140
                    Image { anchors.fill: parent; source: root.image; fillMode: Image.PreserveAspectFit; sourceSize.height: 192 }
                    RoundButton { anchors.right: parent.right; anchors.top: parent.top; width: 28; height: 28; text: "×"; onClicked: root.image = "" }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ToolButton {
                        icon.source: "icons/attach.svg"
                        onClicked: picker.open()
                        ToolTip.visible: hovered
                        ToolTip.text: "Add a picture (sent through the companion app)"
                    }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.maximumHeight: 140
                        TextArea {
                            id: input
                            objectName: "composer"
                            placeholderText: "Text message"
                            wrapMode: TextEdit.Wrap
                            Keys.onReturnPressed: event => {
                                if (event.modifiers & Qt.ShiftModifier) event.accepted = false
                                else root.sendNow()
                            }
                        }
                    }
                    RoundButton {
                        icon.source: "icons/send.svg"
                        icon.color: "white"
                        background: Rectangle { implicitWidth: 44; implicitHeight: 44; radius: 22; color: win.accent; opacity: parent.enabled ? 1 : 0.35 }
                        enabled: (input.text.trim().length > 0 || root.image.length > 0) && !msg.busy
                        onClicked: root.sendNow()
                    }
                }
            }
        }
    }

    function sendNow() {
        if (input.text.trim().length === 0 && image.length === 0) return
        msg.send(input.text.trim(), image)
        input.text = ""
        image = ""
    }

    FileDialog {
        id: picker
        title: "Send a picture"
        nameFilters: ["Pictures (*.jpg *.jpeg *.png *.heic *.gif *.webp)", "All files (*)"]
        onAccepted: root.image = selectedFile.toString()
    }

    Label {
        anchors.centerIn: parent
        visible: msg.currentChat <= 0
        text: "Choose a conversation"
        opacity: 0.5
        font.pixelSize: 16
    }
}
