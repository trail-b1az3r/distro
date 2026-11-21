import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

// Connecting the iPhone, three ways.
Dialog {
    id: dlg
    title: "Your iPhone"
    modal: true
    width: Math.min(560, win.width - 32)
    height: Math.min(640, win.height - 32)
    background: Rectangle { color: win.surface; radius: 20; border.color: win.dim; border.width: 0 }
    standardButtons: Dialog.Close
    onOpened: msg.scanBluetooth()

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        ColumnLayout {
            width: parent.width
            spacing: 14

            Label { text: "Bluetooth"; font.weight: Font.DemiBold; font.pixelSize: 16 }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                opacity: 0.75
                text: "New messages as they arrive, replies, and contacts. Pair the iPhone in Bluetooth settings, then on the iPhone tap ⓘ next to this computer and turn on Show Notifications and Sync Contacts."
            }
            Repeater {
                model: msg.devices
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Label { text: modelData.name + (modelData.connected ? "" : "  (not in range)"); Layout.fillWidth: true; elide: Text.ElideRight }
                    Button { text: "Connect"; onClicked: msg.connectBluetooth(modelData.address) }
                }
            }
            RowLayout {
                Label { text: msg.bluetoothState || "Not connected"; opacity: 0.7; Layout.fillWidth: true }
                Button { text: "Look again"; flat: true; onClicked: msg.scanBluetooth() }
            }

            MenuSeparator { Layout.fillWidth: true }
            Label { text: "Cable"; font.weight: Font.DemiBold; font.pixelSize: 16 }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                opacity: 0.75
                text: "Every message, with its pictures, and the contacts: the iPhone makes a local backup (only changes after the first time) that is read here. Unlock it and tap Trust the first time. The backup must not be encrypted."
            }
            Button {
                text: "Sync over the cable"
                enabled: !msg.busy
                onClicked: msg.syncCable()
                Material.foreground: "white"
                background: Rectangle { implicitHeight: 40; radius: 20; color: win.accent; opacity: parent.enabled ? 1 : 0.4 }
                leftPadding: 22
                rightPadding: 22
            }

            MenuSeparator { Layout.fillWidth: true }
            Label { text: "Companion app"; font.weight: Font.DemiBold; font.pixelSize: 16 }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                opacity: 0.75
                text: "Sending pictures, and contacts with their photos. Open Frontline Messages on the iPhone (sideloaded); it stays connected in the background. Over the cable, on the same Wi-Fi, or anywhere over Tailscale (by its Tailscale name or address; with Tailscale on the iPhone it is found by itself)."
            }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: host; placeholderText: "iPhone's address or Tailscale name (empty: find it)"; Layout.fillWidth: true }
                Button { text: "Connect"; enabled: !msg.busy; onClicked: msg.connectCompanion(host.text) }
            }
            Label {
                visible: msg.companionState === "pairing"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Check that the iPhone shows the same code, and tap Pair there:"
            }
            Label {
                visible: msg.pairingCode.length > 0 && msg.companionState === "pairing"
                text: msg.pairingCode.replace(/(\d{3})(\d{3})/, "$1 $2")
                font.pixelSize: 34
                font.letterSpacing: 4
                font.weight: Font.Bold
                color: win.accent
            }
            Label { text: msg.companionState === "connected" ? "Connected" : msg.companionState === "closed" ? "Disconnected" : ""; opacity: 0.7 }

            MenuSeparator { Layout.fillWidth: true }
            Button { text: "Sync contacts now"; flat: true; onClicked: msg.syncContacts() }
            Label { text: "frontline-msg " + msg.version; opacity: 0.4; font.pixelSize: 11 }
        }
    }
}
