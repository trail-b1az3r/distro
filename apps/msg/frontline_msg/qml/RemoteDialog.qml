import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Connect to another computer's desktop (its rdp-express server): on this network, or anywhere on Tailscale.
Dialog {
    id: dlg
    title: "Remote desktop"
    modal: true
    width: Math.min(520, win.width - 32)
    height: Math.min(560, win.height - 32)
    background: Rectangle { color: win.surface; radius: 20 }
    standardButtons: Dialog.Close
    onOpened: msg.findRemotes()

    function go(host) {
        if (!host) return
        const w = Qt.createComponent("RemoteWindow.qml").createObject(null, { host: host, code: code.text })
        if (w) { code.text = ""; dlg.close() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.75
            text: "The other computer runs rdp-express (package frontline-rdp-express). The first time, run `rdp-express pair` there and enter the code it shows."
        }
        Label { text: "On your tailnet"; font.weight: Font.DemiBold; visible: msg.remotes.length > 0 }
        Repeater {
            model: msg.remotes
            delegate: ItemDelegate {
                required property var modelData
                Layout.fillWidth: true
                text: modelData.name + "  ·  " + (modelData.dns || modelData.host)
                onClicked: host.text = modelData.host
            }
        }
        Label { text: msg.findingRemotes ? "Looking on Tailscale…" : (msg.remotes.length ? "" : "No computer sharing its desktop found on Tailscale."); opacity: 0.6; visible: text.length > 0 }
        TextField { id: host; objectName: "remoteHost"; Layout.fillWidth: true; placeholderText: "Computer (name, address, or a Tailscale name)"; onAccepted: dlg.go(text.trim()) }
        TextField { id: code; Layout.fillWidth: true; placeholderText: "Pairing code (only the first time)"; inputMethodHints: Qt.ImhDigitsOnly }
        Button {
            text: "Connect"
            enabled: host.text.trim().length > 0
            onClicked: dlg.go(host.text.trim())
            background: Rectangle { implicitHeight: 40; radius: 20; color: win.accent; opacity: parent.enabled ? 1 : 0.4 }
            contentItem: Label { text: parent.text; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            leftPadding: 22; rightPadding: 22
        }
        Item { Layout.fillHeight: true }
    }
}
