import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var plasma: installer.features.find(f => f.id === "plasma_fallback")

    PageHeader { title: qsTr("Desktop"); subtitle: qsTr("Hyprland with the Halcyon shell: Wayland-first, keyboard- and touch-friendly, with Material You colours from your wallpaper.") }

    Card {
        Layout.fillWidth: true
        padding: 0
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            radius: Theme.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.bg }
                GradientStop { position: 0.55; color: Qt.darker(Theme.accent, 2.4) }
                GradientStop { position: 1.0; color: Qt.darker(Theme.accent2, 2.6) }
            }
            // A sketch of the desktop: top bar, two windows, a dock.
            Rectangle { x: 16; y: 14; width: parent.width - 32; height: 22; radius: 11; color: Qt.rgba(1, 1, 1, 0.10) }
            Rectangle { x: 34; y: 56; width: parent.width * 0.52; height: 150; radius: 14; color: Qt.rgba(1, 1, 1, 0.12); border.color: Qt.rgba(1, 1, 1, 0.2)
                Text { anchors.centerIn: parent; text: "konsole — fish"; color: "#E8ECF8"; font.family: Theme.mono } }
            Rectangle { x: parent.width * 0.52 + 50; y: 56; width: parent.width * 0.48 - 84; height: 150; radius: 14; color: Qt.rgba(1, 1, 1, 0.08); border.color: Qt.rgba(1, 1, 1, 0.2)
                Text { anchors.centerIn: parent; text: "Dolphin"; color: "#E8ECF8" } }
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 218; width: 220; height: 28; radius: 14; color: Qt.rgba(1, 1, 1, 0.12) }
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width > 700 ? 2 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        Repeater {
            model: [
                { k: "Super + Enter", v: qsTr("Terminal (Konsole, Fish)") },
                { k: "Super + E", v: qsTr("Files (Dolphin)") },
                { k: "Super", v: qsTr("Search and launch apps") },
                { k: "Super + /", v: qsTr("All keyboard shortcuts") },
                { k: "Ctrl + Super + A", v: qsTr("AI launcher") },
                { k: "Super + Shift + U", v: qsTr("System update") }
            ]
            RowLayout {
                required property var modelData
                spacing: 12
                Rectangle {
                    implicitWidth: keyText.implicitWidth + 20; implicitHeight: 30; radius: 8
                    color: Theme.surface2; border.color: Theme.border
                    Text { id: keyText; anchors.centerIn: parent; text: modelData.k; color: Theme.fg; font.family: Theme.mono; font.pixelSize: 12 }
                }
                Text { text: modelData.v; color: Theme.muted; font.pixelSize: Theme.text }
            }
        }
    }

    SectionTitle { text: qsTr("Displays") }
    Card {
        Layout.fillWidth: true
        Repeater {
            model: installer.hardware.displays
            RowLayout {
                required property var modelData
                spacing: 12
                Icon { name: modelData.internal ? "laptop" : "display"; size: 22; color: Theme.accent }
                Text {
                    Layout.fillWidth: true
                    text: (modelData.internal ? qsTr("Built-in display") : modelData.name + " (" + modelData.connector + ")") + "  ·  " + modelData.resolution
                          + (modelData.diagonal_inches ? "  ·  " + modelData.diagonal_inches + "\"" : "")
                    color: Theme.fg; font.pixelSize: Theme.text; wrapMode: Text.WordWrap
                }
                Badge { text: qsTr("Scale %1×").arg(modelData.recommended_scale); color: modelData.hidpi ? Theme.accent2 : Theme.surface2 }
            }
        }
        Text {
            visible: installer.hardware.displays.length === 0
            text: qsTr("No display information available; the desktop picks sensible defaults.")
            color: Theme.muted
        }
        Text {
            Layout.fillWidth: true
            text: qsTr("Scaling is set per display from its pixel density; change it later in ~/.config/hypr/custom/general.lua or the settings app.")
            color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap
        }
    }

    Card {
        Layout.fillWidth: true
        ToggleRow {
            Layout.fillWidth: true
            title: page.plasma ? page.plasma.label : ""
            description: page.plasma ? page.plasma.description : ""
            checked: page.plasma ? page.plasma.value === true : false
            onToggled: (v) => installer.setFeature("plasma_fallback", v)
        }
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Log in automatically")
            description: installer.config.disk.encrypt ? qsTr("Your disk passphrase still protects the computer at start-up.")
                                                       : qsTr("Anyone who turns on the computer gets your desktop. Not recommended for laptops.")
            checked: installer.config.user.autologin
            onToggled: (v) => installer.set("user.autologin", v)
        }
    }
}
