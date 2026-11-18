import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1080
    height: 720
    minimumWidth: 420
    minimumHeight: 480
    visible: true
    title: chatView.visible && msg.chatInfo.title ? msg.chatInfo.title + " — Messages" : "Messages"

    // The desktop's colours when Halcyon has some, Material's otherwise.
    readonly property var c: msg.colors
    readonly property color accent: c.primary ?? "#0a84ff"
    readonly property color surface: c.surface ?? (Material.theme === Material.Dark ? "#1c1b1f" : "#fdfbff")
    readonly property color panel: c.surface_container ?? (Material.theme === Material.Dark ? "#25232a" : "#f2eff6")
    readonly property color onSurface: c.on_surface ?? (Material.theme === Material.Dark ? "#e6e1e5" : "#1c1b1f")
    readonly property color dim: c.on_surface_variant ?? "#8e8a94"
    readonly property bool narrow: width < 720
    property bool showList: true

    Material.theme: Material.System
    Material.accent: accent
    Material.primary: accent
    Material.background: surface
    Material.foreground: onSurface
    color: surface

    function openChat(id) {
        msg.openChat(id)
        showList = false
        searchField.text = ""
    }

    Shortcut { sequences: [StandardKey.Find]; onActivated: { showList = true; searchField.forceActiveFocus() } }
    Shortcut { sequence: "Ctrl+N"; onActivated: newDialog.open() }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── the conversations ──
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: win.narrow ? win.width : 340
            visible: !win.narrow || win.showList
            color: win.panel

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    Label { text: "Messages"; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    ToolButton { icon.source: "icons/compose.svg"; onClicked: newDialog.open()
                        ToolTip.visible: hovered; ToolTip.text: "New message (Ctrl+N)" }
                    ToolButton { icon.source: "icons/phone.svg"; onClicked: devices.open()
                        ToolTip.visible: hovered; ToolTip.text: "iPhone: Bluetooth, cable and companion app" }
                }

                TextField {
                    id: searchField
                    objectName: "search"
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    placeholderText: "Search messages, people…"
                    onTextChanged: searchTimer.restart()
                    Keys.onEscapePressed: text = ""
                    Timer { id: searchTimer; interval: 180; onTriggered: msg.search(searchField.text) }
                }

                // Search results, or the conversations.
                ListView {
                    id: chatList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.topMargin: 8
                    clip: true
                    visible: searchField.text.length === 0
                    model: msg.chats
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ChatRow {
                        required property var modelData
                        chat: modelData
                        width: chatList.width
                        selected: msg.currentChat === modelData.id
                        onClicked: win.openChat(modelData.id)
                    }
                    Label {
                        anchors.centerIn: parent
                        width: parent.width - 48
                        visible: chatList.count === 0
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: win.dim
                        text: "No messages yet.\n\nConnect your iPhone: over Bluetooth for new messages, or with its cable for the whole history."
                    }
                }

                SearchResults {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: searchField.text.length > 0
                    results: msg.results
                    onOpenChat: id => win.openChat(id)
                    onOpenContact: handle => { msg.newChat(handle); win.showList = false; searchField.text = "" }
                }

                // Status: syncing, connected, errors.
                Pane {
                    Layout.fillWidth: true
                    visible: msg.busy || msg.status.length > 0
                    padding: 10
                    background: Rectangle { color: "transparent" }
                    ColumnLayout {
                        width: parent.width
                        Label { text: msg.status; wrapMode: Text.Wrap; Layout.fillWidth: true; color: win.dim; font.pixelSize: 12 }
                        ProgressBar {
                            Layout.fillWidth: true
                            visible: msg.busy
                            indeterminate: msg.progress < 0
                            value: msg.progress / 100
                        }
                    }
                }
            }
        }

        // ── the open conversation ──
        Conversation {
            id: chatView
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !win.narrow || !win.showList
            onBack: win.showList = true
        }
    }

    DevicesDialog { id: devices; anchors.centerIn: parent }
    NewMessageDialog { id: newDialog; anchors.centerIn: parent; onChosen: handle => { msg.newChat(handle); win.showList = false } }

    // Short messages at the bottom.
    Connections { target: msg; function onToast(text) { toast.text = text; toast.open(); toastTimer.restart() } }
    Popup {
        id: toast
        property alias text: toastLabel.text
        x: (win.width - width) / 2
        y: win.height - height - 24
        padding: 12
        background: Rectangle { radius: 10; color: win.onSurface; opacity: 0.92 }
        Label { id: toastLabel; color: win.surface; wrapMode: Text.Wrap; width: Math.min(implicitWidth, win.width - 80) }
        Timer { id: toastTimer; interval: 4500; onTriggered: toast.close() }
    }
}
