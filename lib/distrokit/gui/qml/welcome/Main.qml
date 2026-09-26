import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ApplicationWindow {
    id: win
    width: 1100
    height: 760
    minimumWidth: 680
    minimumHeight: 520
    visible: true
    title: qsTr("Welcome to %1").arg(brandInfo.prettyName)
    color: Theme.bg

    property string section: "home"
    property string themeMode: "system"
    onThemeModeChanged: Theme.mode = themeMode
    readonly property bool wide: width >= 900
    readonly property var sections: [
        { id: "home", title: qsTr("Welcome"), icon: "rocket" },
        { id: "updates", title: qsTr("Updates & drivers"), icon: "refresh" },
        { id: "ai", title: qsTr("AI"), icon: "sparkles" },
        { id: "appearance", title: qsTr("Appearance"), icon: "palette" },
        { id: "apps", title: qsTr("Applications"), icon: "package" },
        { id: "privacy", title: qsTr("Privacy"), icon: "shield" },
        { id: "backup", title: qsTr("Backups"), icon: "backup" },
        { id: "help", title: qsTr("Help"), icon: "help" }
    ]

    Connections {
        target: welcome
        function onLog(line) { logView.append(line) }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: win.wide ? 250 : 72
            Layout.fillHeight: true
            color: Theme.surface
            border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 6
                RowLayout {
                    spacing: 10
                    Layout.bottomMargin: 12
                    Image { source: brandInfo.logo; sourceSize: Qt.size(36, 36) }
                    Text { visible: win.wide; text: brandInfo.name; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.Bold }
                }
                Repeater {
                    model: win.sections
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 42
                        radius: 10
                        color: win.section === modelData.id ? Theme.accentSoft : (navMouse.containsMouse ? Theme.surface2 : "transparent")
                        activeFocusOnTab: true
                        Accessible.role: Accessible.PageTab
                        Accessible.name: modelData.title
                        Keys.onReturnPressed: win.section = modelData.id
                        border.width: activeFocus ? 2 : 0
                        border.color: Theme.focus
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            spacing: 12
                            Icon { name: modelData.icon; size: 20; color: win.section === modelData.id ? Theme.accent : Theme.muted }
                            Text { visible: win.wide; text: modelData.title; color: Theme.fg; font.pixelSize: Theme.text; Layout.fillWidth: true }
                        }
                        MouseArea { id: navMouse; anchors.fill: parent; hoverEnabled: true; onClicked: win.section = modelData.id }
                    }
                }
                Item { Layout.fillHeight: true }
                ThemeSwitch { visible: win.wide }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            ScrollView {
                id: scroller
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                Item {
                    width: scroller.availableWidth
                    implicitHeight: content.implicitHeight + 64
                    ColumnLayout {
                        id: content
                        x: Math.max(24, (parent.width - width) / 2)
                        y: 32
                        width: Math.min(parent.width - 48, 860)
                        spacing: 20

                        // Home ---------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "home"
                            Layout.fillWidth: true
                            spacing: 20
                            PageHeader {
                                Layout.fillWidth: true
                                title: qsTr("Welcome to %1").arg(brandInfo.prettyName)
                                subtitle: qsTr("Let's finish setting up your system.")
                            }
                            Card {
                                Layout.fillWidth: true
                                Repeater {
                                    model: welcome.checklist
                                    RowLayout {
                                        required property var modelData
                                        spacing: 12
                                        Icon { name: modelData.ok ? "check-circle" : "alert"; size: 20; color: modelData.ok ? Theme.success : Theme.warning }
                                        Text { text: modelData.label; color: Theme.fg; font.pixelSize: Theme.textLarge; Layout.fillWidth: true }
                                        AppButton { visible: modelData.id === "tasks"; text: qsTr("Run now"); kind: "primary"; enabled: !welcome.busy; onClicked: welcome.runTasks() }
                                    }
                                }
                            }
                            GridLayout {
                                Layout.fillWidth: true
                                columns: width > 640 ? 2 : 1
                                columnSpacing: Theme.gap
                                rowSpacing: Theme.gap
                                Repeater {
                                    model: [
                                        { s: "updates", icon: "refresh", t: qsTr("System update"), d: qsTr("Install the latest packages, drivers and desktop fixes.") },
                                        { s: "updates", icon: "gpu", t: qsTr("Driver status"), d: qsTr("See which graphics driver runs and what it supports.") },
                                        { s: "ai", icon: "sparkles", t: qsTr("AI configuration"), d: qsTr("Set up your assistants and HyperNix.") },
                                        { s: "ai", icon: "download", t: qsTr("Model download"), d: qsTr("Download a local model sized for this computer.") },
                                        { s: "appearance", icon: "palette", t: qsTr("Appearance"), d: qsTr("Themes, wallpaper colours and effects.") },
                                        { s: "apps", icon: "package", t: qsTr("Applications"), d: qsTr("Add popular apps with one click.") },
                                        { s: "privacy", icon: "shield", t: qsTr("Privacy"), d: qsTr("Firewall, location, MAC randomisation, crash dumps.") },
                                        { s: "backup", icon: "backup", t: qsTr("Backups"), d: qsTr("Snapshots before every update, and on demand.") }
                                    ]
                                    OptionCard {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        radio: false
                                        indicator: "navigate"
                                        Accessible.role: Accessible.Button
                                        iconName: modelData.icon
                                        title: modelData.t
                                        description: modelData.d
                                        onClicked: win.section = modelData.s
                                    }
                                }
                            }
                            RowLayout {
                                Item { Layout.fillWidth: true }
                                AppButton {
                                    kind: "primary"
                                    text: welcome.firstBoot ? qsTr("Done — don't show at login") : qsTr("Close")
                                    iconName: "check"
                                    onClicked: { welcome.finish(); Qt.quit() }
                                }
                            }
                        }

                        // Updates & drivers ------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "updates"
                            Layout.fillWidth: true
                            spacing: 20
                            PageHeader { Layout.fillWidth: true; title: qsTr("Updates & drivers"); subtitle: qsTr("pacman stays in charge; these open the same tools you can run in a terminal.") }
                            RowLayout {
                                spacing: 12
                                AppButton { kind: "primary"; text: qsTr("Open System Update"); iconName: "refresh"; onClicked: launcher.run(brandInfo.id + "-update") }
                                AppButton { text: qsTr("Update in a terminal"); iconName: "terminal"; onClicked: launcher.runInTerminal(brandInfo.cli + " update") }
                            }
                            SectionTitle { text: qsTr("Graphics") }
                            Repeater {
                                model: welcome.gpu
                                Card {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Text { text: modelData.vendor + " " + modelData.model; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold }
                                    Text { text: [qsTr("Driver: ") + modelData.driver, "Vulkan: " + modelData.vulkan, qsTr("Status: ") + modelData.status].join("   ·   "); color: Theme.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Repeater { model: modelData.problems || []; Notice { required property string modelData; Layout.fillWidth: true; kind: "warning"; text: modelData } }
                                }
                            }
                            RowLayout {
                                spacing: 12
                                AppButton { text: qsTr("Reconfigure drivers"); iconName: "wrench"; onClicked: launcher.runInTerminal("sudo " + brandInfo.cli + " gpu configure") }
                                AppButton { text: qsTr("Run the system doctor"); iconName: "heart-pulse"; onClicked: launcher.runInTerminal(brandInfo.cli + " doctor -v") }
                            }
                        }

                        // AI ----------------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "ai"
                            Layout.fillWidth: true
                            spacing: 20
                            PageHeader { Layout.fillWidth: true; title: qsTr("AI"); subtitle: qsTr("Everything installs into your home folder and can be removed at any time.") }
                            Repeater {
                                model: welcome.ai
                                Card {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    RowLayout {
                                        spacing: 14
                                        Icon { name: ({ hypernix: "flame", hermis: "bot", openclaw: "message", "claude-code": "terminal", "local-model": "model" })[modelData.id] || "sparkles"; size: 26; color: Theme.accent }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Text { text: modelData.name; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold }
                                            Text { text: modelData.description; color: Theme.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        }
                                        Badge { text: modelData.installed ? (modelData.configured ? qsTr("Ready") : qsTr("Needs setup")) : qsTr("Not installed")
                                                color: modelData.installed ? (modelData.configured ? Theme.success : Theme.warning) : Theme.surface2 }
                                    }
                                    RowLayout {
                                        spacing: 10
                                        AppButton { kind: "primary"; text: modelData.installed ? (modelData.configured ? qsTr("Open") : qsTr("Set up")) : qsTr("Install")
                                                    onClicked: welcome.launchAi(modelData.id, "run") }
                                        AppButton { visible: modelData.id === "local-model"; text: qsTr("Manage models"); onClicked: launcher.run(brandInfo.id + "-ai --models") }
                                    }
                                }
                            }
                        }

                        // Appearance --------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "appearance"
                            Layout.fillWidth: true
                            spacing: 20
                            PageHeader { Layout.fillWidth: true; title: qsTr("Appearance"); subtitle: qsTr("Colours follow your wallpaper, or pick a hand-made theme. Ctrl+Super+Shift+T opens the theme menu and Ctrl+Super+T the wallpaper picker at any time.") }
                            Repeater {
                                model: welcome.themes
                                OptionCard {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    indicator: "navigate"
                                    iconName: "palette"
                                    title: modelData.name
                                    description: modelData.description
                                    onClicked: welcome.applyTheme(modelData.id)
                                }
                            }
                            RowLayout {
                                spacing: 12
                                AppButton { text: qsTr("Choose a wallpaper"); iconName: "image"; onClicked: launcher.run("hyprctl dispatch global quickshell:wallpaperSelectorToggle") }
                                AppButton { text: qsTr("Shell settings"); iconName: "settings"; onClicked: launcher.run("bash -c 'qs -p ~/.config/quickshell/ii/settings.qml'") }
                            }
                        }

                        // Applications -----------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "apps"
                            Layout.fillWidth: true
                            spacing: 16
                            PageHeader { Layout.fillWidth: true; title: qsTr("Applications"); subtitle: qsTr("Installed from the official repositories with pacman. Anything else: `yay -S <name>` or Flatpak.") }
                            TextInput2 { id: appFilter; Layout.fillWidth: true; placeholder: qsTr("Search applications…") }
                            Repeater {
                                model: welcome.apps.filter(a => appFilter.text === "" || (a.name + a.description + a.category).toLowerCase().indexOf(appFilter.text.toLowerCase()) >= 0)
                                Card {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    padding: 14
                                    RowLayout {
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Text { text: modelData.name + "  ·  " + modelData.category; color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                                            Text { text: modelData.description; color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        }
                                        AppButton { text: modelData.installed ? qsTr("Installed") : qsTr("Install"); enabled: !modelData.installed && !welcome.busy; onClicked: welcome.installApp(modelData.id) }
                                    }
                                }
                            }
                        }

                        // Privacy -------------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "privacy"
                            Layout.fillWidth: true
                            spacing: 16
                            PageHeader { Layout.fillWidth: true; title: qsTr("Privacy"); subtitle: qsTr("%1 collects no telemetry. These settings control what the system itself exposes.").arg(brandInfo.name) }
                            Card {
                                Layout.fillWidth: true
                                ToggleRow { Layout.fillWidth: true; title: qsTr("Firewall"); description: qsTr("Block unsolicited incoming connections (nftables)."); checked: welcome.privacy.firewall; enabled: !welcome.busy; onToggled: (v) => welcome.setPrivacy("firewall", v) }
                                ToggleRow { Layout.fillWidth: true; title: qsTr("Randomise Wi-Fi hardware address"); description: qsTr("A random MAC while scanning, and a different stable MAC for each network."); checked: welcome.privacy.macRandomization; enabled: !welcome.busy; onToggled: (v) => welcome.setPrivacy("macRandomization", v) }
                                ToggleRow { Layout.fillWidth: true; title: qsTr("Location services"); description: qsTr("Used by the shell for weather and night light. Off: nothing on this computer can ask for your location."); checked: welcome.privacy.location; enabled: !welcome.busy; onToggled: (v) => welcome.setPrivacy("location", v) }
                                ToggleRow { Layout.fillWidth: true; title: qsTr("Keep crash dumps"); description: qsTr("Crash dumps help debugging but may contain data from the crashed program."); checked: welcome.privacy.coredumps; enabled: !welcome.busy; onToggled: (v) => welcome.setPrivacy("coredumps", v) }
                            }
                        }

                        // Backups ---------------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "backup"
                            Layout.fillWidth: true
                            spacing: 16
                            PageHeader { Layout.fillWidth: true; title: qsTr("Backups"); subtitle: qsTr("Snapshots protect the system; they are not a backup of your files to another disk.") }
                            Card {
                                Layout.fillWidth: true
                                visible: welcome.backup.snapper
                                Text { text: qsTr("Btrfs snapshots: %1 on this system.").arg(welcome.backup.snapshots); color: Theme.fg; font.pixelSize: Theme.textLarge }
                                Text { text: qsTr("A snapshot is taken before and after every package update, and they appear in the boot menu (GRUB) so you can start an earlier state."); color: Theme.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                ToggleRow { Layout.fillWidth: true; title: qsTr("Hourly snapshots"); description: qsTr("Keeps 5 hourly, 7 daily, 2 weekly and 1 monthly."); checked: welcome.backup.timeline; enabled: !welcome.busy; onToggled: (v) => welcome.setTimeline(v) }
                                AppButton { text: qsTr("Take a snapshot now"); iconName: "backup"; enabled: !welcome.busy; onClicked: welcome.snapshotNow() }
                            }
                            Notice {
                                visible: !welcome.backup.snapper
                                Layout.fillWidth: true
                                text: welcome.backup.filesystem === "btrfs" ? qsTr("Snapshots are not configured. Install snapper and snap-pac to enable them.")
                                                                          : qsTr("This system uses %1. Install Timeshift (Applications) for rsync-based system snapshots.").arg(welcome.backup.filesystem || "ext4")
                            }
                            Notice { Layout.fillWidth: true; kind: "warning"; text: qsTr("Keep copies of important files on another disk or a cloud service as well.") }
                        }

                        // Help ---------------------------------------------------------------------
                        ColumnLayout {
                            visible: win.section === "help"
                            Layout.fillWidth: true
                            spacing: 16
                            PageHeader { Layout.fillWidth: true; title: qsTr("Help"); subtitle: qsTr("Press Super + / on the desktop for every keyboard shortcut.") }
                            RowLayout {
                                spacing: 12
                                AppButton { text: qsTr("Documentation"); iconName: "external"; onClicked: launcher.openUrl(brandInfo.docUrl) }
                                AppButton { text: qsTr("Community"); iconName: "message"; onClicked: launcher.openUrl(brandInfo.supportUrl) }
                                AppButton { text: qsTr("System doctor"); iconName: "heart-pulse"; onClicked: launcher.runInTerminal(brandInfo.cli + " doctor -v") }
                            }
                        }

                        // Pending setup tasks and activity log (all sections).
                        Card {
                            visible: welcome.tasks.length > 0 && (win.section === "home" || win.section === "ai")
                            Layout.fillWidth: true
                            SectionTitle { text: qsTr("Setup tasks") }
                            Repeater {
                                model: welcome.tasks
                                RowLayout {
                                    required property var modelData
                                    spacing: 10
                                    Icon { name: modelData.status === "done" ? "check-circle" : modelData.status === "failed" ? "alert" : "clock"; size: 18
                                           color: modelData.status === "done" ? Theme.success : modelData.status === "failed" ? Theme.danger : Theme.muted }
                                    Text { text: modelData.label + (modelData.size ? "  (" + modelData.size + ")" : "") + (modelData.error ? " — " + modelData.error : ""); color: Theme.fg; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    AppButton { visible: modelData.status === "pending" || modelData.status === "failed"; kind: "ghost"; text: qsTr("Skip"); onClicked: welcome.skipTask(modelData.id) }
                                }
                            }
                            AppButton { kind: "primary"; text: welcome.busy ? qsTr("Working…") : qsTr("Run setup tasks"); enabled: !welcome.busy; onClicked: welcome.runTasks() }
                        }
                        LogView { id: logView; Layout.fillWidth: true; Layout.preferredHeight: 160 }
                    }
                }
            }
        }
    }
}
