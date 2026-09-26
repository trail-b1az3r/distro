import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    spacing: 24
    PageHeader { title: qsTr("Laptop / Tablet Kernel"); subtitle: qsTr("Optional kernels for specific hardware.") }
    Notice {
        Layout.fillWidth: true
        kind: installer.surfaceInfo.detected ? "success" : "info"
        title: installer.surfaceInfo.detected ? qsTr("Microsoft Surface hardware detected") : ""
        text: installer.surfaceInfo.message
    }
    Card {
        Layout.fillWidth: true
        highlighted: installer.config.surface_kernel
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Install Surface Linux Kernel")
            description: qsTr("The linux-surface kernel with touch and pen support (iptsd), cameras and battery reporting for Microsoft Surface devices. The standard kernel stays installed as a fallback. Needs the internet.")
            badge: installer.surfaceInfo.recommended ? qsTr("Recommended") : ""
            checked: installer.config.surface_kernel
            onToggled: (v) => installer.set("surface_kernel", v)
        }
        Notice {
            visible: installer.config.surface_kernel && !installer.surfaceInfo.detected
            Layout.fillWidth: true
            kind: "warning"
            text: qsTr("This computer was not identified as a Surface. The kernel will be installed as you asked; it only helps on Surface devices.")
        }
    }
    Card {
        Layout.fillWidth: true
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Also install the LTS kernel")
            description: qsTr("A long-term-support kernel as a second boot option, useful if a new kernel ever misbehaves with your hardware.")
            checked: installer.config.kernels.indexOf("linux-lts") >= 0
            onToggled: (v) => installer.setKernel("linux-lts", v)
        }
    }
}
