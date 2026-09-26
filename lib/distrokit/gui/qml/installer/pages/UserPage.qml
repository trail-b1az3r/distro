import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var u: installer.config.user
    property string pw1: ""
    property string pw2: ""
    property bool rootPw: installer.config.user.root_password !== ""
    property string rpw1: ""
    property string rpw2: ""
    readonly property int strength: {
        let s = 0
        if (pw1.length >= 8) s++
        if (pw1.length >= 12) s++
        if (/[A-Z]/.test(pw1) && /[a-z]/.test(pw1)) s++
        if (/[0-9]/.test(pw1)) s++
        if (/[^A-Za-z0-9]/.test(pw1)) s++
        return Math.min(s, 4)
    }

    PageHeader { title: qsTr("User Account"); subtitle: qsTr("Your account can administer the system with sudo.") }
    Card {
        Layout.fillWidth: true
        GridLayout {
            Layout.fillWidth: true
            columns: width > 640 ? 2 : 1
            columnSpacing: Theme.gap
            rowSpacing: Theme.gap
            TextInput2 { Layout.fillWidth: true; label: qsTr("Your name"); placeholder: qsTr("Alex Doe"); text: page.u.fullname; onEdited: (v) => installer.set("user.fullname", v) }
            TextInput2 { Layout.fillWidth: true; label: qsTr("Username"); placeholder: "alex"; text: page.u.username; onEdited: (v) => installer.set("user.username", v)
                         hint: qsTr("Lowercase letters, digits, - and _.") }
            TextInput2 { Layout.fillWidth: true; label: qsTr("Computer name"); placeholder: "my-laptop"; text: installer.config.hostname; onEdited: (v) => installer.set("hostname", v)
                         hint: qsTr("How this computer appears on the network.") }
            Item { Layout.fillWidth: true }
            TextInput2 {
                Layout.fillWidth: true; label: qsTr("Password"); password: true
                onEdited: (v) => { page.pw1 = v; installer.set("user.password", v === page.pw2 ? v : "") }
            }
            TextInput2 {
                Layout.fillWidth: true; label: qsTr("Confirm password"); password: true
                error: page.pw2 !== "" && page.pw1 !== page.pw2 ? qsTr("The passwords do not match.") : ""
                onEdited: (v) => { page.pw2 = v; installer.set("user.password", v === page.pw1 ? v : "") }
            }
        }
        RowLayout {
            visible: page.pw1 !== ""
            spacing: 6
            Repeater {
                model: 4
                Rectangle {
                    required property int index
                    width: 48; height: 6; radius: 3
                    color: index < page.strength ? [Theme.danger, Theme.warning, Theme.accent2, Theme.success][page.strength - 1] : Theme.surface2
                }
            }
            Text { text: [qsTr("Very weak"), qsTr("Weak"), qsTr("Fair"), qsTr("Good"), qsTr("Strong")][page.strength]; color: Theme.muted; font.pixelSize: Theme.textSmall }
        }
    }
    Card {
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: qsTr("Login shell"); color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                Text { text: qsTr("Terminals always open Fish. The login shell is used on the text console and over SSH; Bash is the safe choice for scripts and administration."); color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppCombo {
                Layout.preferredWidth: 180
                options: [{ id: "bash", label: qsTr("Bash (recommended)") }, { id: "fish", label: "Fish" }]
                current: page.u.shell
                onChosen: (id) => installer.set("user.shell", id)
            }
        }
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Set a separate root password")
            description: qsTr("Off: the root account is locked and administration uses sudo with your password (recommended).")
            checked: page.rootPw
            onToggled: (v) => { page.rootPw = v; if (!v) installer.set("user.root_password", "") }
        }
        GridLayout {
            visible: page.rootPw
            Layout.fillWidth: true
            columns: width > 640 ? 2 : 1
            columnSpacing: Theme.gap
            TextInput2 { Layout.fillWidth: true; label: qsTr("Root password"); password: true; onEdited: (v) => { page.rpw1 = v; installer.set("user.root_password", v === page.rpw2 ? v : "") } }
            TextInput2 { Layout.fillWidth: true; label: qsTr("Confirm root password"); password: true
                         error: page.rpw2 !== "" && page.rpw1 !== page.rpw2 ? qsTr("The passwords do not match.") : ""
                         onEdited: (v) => { page.rpw2 = v; installer.set("user.root_password", v === page.rpw1 ? v : "") } }
        }
    }
}
