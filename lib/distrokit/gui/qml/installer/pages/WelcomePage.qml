import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    spacing: 28

    ColumnLayout {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 24
        spacing: 14
        Image {
            Layout.alignment: Qt.AlignHCenter
            source: brandInfo.logo
            sourceSize: Qt.size(120, 120)
            Layout.preferredWidth: 120; Layout.preferredHeight: 120
            Accessible.name: brandInfo.prettyName + qsTr(" logo")
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: qsTr("Welcome to %1").arg(brandInfo.prettyName)
            color: Theme.fg
            font.pixelSize: Theme.display
            font.weight: Font.Bold
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            Accessible.role: Accessible.Heading
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 640
            text: brandInfo.tagline
            color: Theme.muted
            font.pixelSize: Theme.textLarge
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width > 700 ? 3 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        Repeater {
            model: [
                { icon: "gpu", title: qsTr("Hardware-aware"), text: qsTr("Detects your CPU, GPUs, displays and Surface devices, and sets up the right drivers.") },
                { icon: "desktop", title: qsTr("A complete desktop"), text: qsTr("Hyprland with a polished shell, ready on first login: themes, keybinds, apps.") },
                { icon: "sparkles", title: qsTr("Local AI, your way"), text: qsTr("Optional HyperNix, AI assistants and a local model sized for your machine.") }
            ]
            Card {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.preferredHeight: 150
                Icon { name: modelData.icon; size: 28; color: Theme.accent }
                Text { text: modelData.title; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold }
                Text { text: modelData.text; color: Theme.muted; font.pixelSize: Theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }
    }

    Notice {
        Layout.fillWidth: true
        text: qsTr("Nothing on your disks changes until the Summary step, where you review every change and confirm it. You can keep using the live system while you decide.")
    }
    Notice {
        visible: installer.isDemo
        Layout.fillWidth: true
        kind: "warning"
        title: qsTr("Demo mode")
        text: qsTr("The installer walks through every step and simulates the installation. No disk is touched.")
    }
}
