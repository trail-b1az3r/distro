import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    spacing: 24
    PageHeader { title: qsTr("Hardware Detected"); subtitle: qsTr("What this computer has, and how it will be set up. You can change the choices on the following pages.") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 760 ? 2 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        Repeater {
            model: installer.hardware.rows
            Card {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                padding: 14
                InfoRow { Layout.fillWidth: true; iconName: modelData.icon; label: modelData.label; value: modelData.value }
            }
        }
    }
    Card {
        Layout.fillWidth: true
        highlighted: true
        SectionTitle { text: qsTr("Recommended configuration") }
        Repeater {
            model: installer.hardware.recommendations
            RowLayout {
                required property string modelData
                spacing: 10
                Icon { name: "check-circle"; size: 18; color: Theme.success }
                Text { text: modelData; color: Theme.fg; font.pixelSize: Theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }
    }
    Notice {
        visible: !installer.hardware.uefi
        Layout.fillWidth: true
        kind: "warning"
        text: qsTr("This computer started in legacy BIOS mode. The system will use GRUB; features that need UEFI (systemd-boot, Secure Boot) are unavailable.")
    }
}
