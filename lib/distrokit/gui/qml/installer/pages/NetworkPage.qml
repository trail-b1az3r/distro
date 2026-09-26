import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    spacing: 24
    PageHeader { title: qsTr("Internet"); subtitle: qsTr("An internet connection is recommended, but not required.") }
    Card {
        Layout.fillWidth: true
        highlighted: installer.online
        RowLayout {
            spacing: 16
            Rectangle {
                width: 56; height: 56; radius: 16
                color: installer.online ? Qt.rgba(0.2, 0.77, 0.55, 0.18) : Theme.warningSoft
                Icon { anchors.centerIn: parent; name: installer.online ? "wifi" : "alert"; size: 28; color: installer.online ? Theme.success : Theme.warning }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Text {
                    text: installer.online ? qsTr("Connected to the internet") : qsTr("Not connected")
                    color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    color: Theme.muted
                    text: installer.online
                        ? qsTr("Packages come from the newest mirrors, and online-only extras (AI tools, Claude Code, the Surface kernel) can be installed now.")
                        : installer.offlineCapable
                            ? qsTr("The base system installs from this medium. AI tools, models, the Surface kernel and some drivers will be installed after the first login, once you are online.")
                            : qsTr("This medium downloads most packages during installation. Connect to a wired or wireless network to continue.")
                }
            }
        }
        RowLayout {
            spacing: 12
            AppButton { text: qsTr("Network settings"); iconName: "settings"; onClicked: installer.openNetworkSettings() }
            AppButton { text: qsTr("Check again"); iconName: "refresh"; onClicked: installer.checkNetwork() }
        }
    }
    ToggleRow {
        Layout.fillWidth: true
        visible: installer.offlineCapable
        title: qsTr("Install without the internet")
        description: qsTr("Use only the packages on this medium, even if a connection is available.")
        checked: installer.config.offline
        onToggled: (v) => installer.set("offline", v)
    }
    Notice {
        Layout.fillWidth: true
        kind: "info"
        text: qsTr("No data about you or your hardware is sent anywhere. The installer only contacts package mirrors and, if you choose AI tools or models, their official download sources.")
    }
}
