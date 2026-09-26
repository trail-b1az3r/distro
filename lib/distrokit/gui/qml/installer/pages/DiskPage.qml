import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var cfg: installer.config.disk
    readonly property var installable: installer.disks.filter(d => d.installable)
    readonly property bool anyFree: installable.some(d => d.largest_free_bytes >= 40 * 1024 * 1024 * 1024)
    readonly property var chosen: installer.disks.find(d => d.path === cfg.disk)
    property string pass2: ""

    PageHeader {
        title: qsTr("Disk")
        subtitle: qsTr("Where to install. Nothing is written until you confirm on the Summary page.")
    }

    // Mode ------------------------------------------------------------------
    SectionTitle { text: qsTr("Installation type") }
    ColumnLayout {
        Layout.fillWidth: true
        spacing: Theme.gap
        OptionCard {
            Layout.fillWidth: true
            iconName: "storage"
            title: qsTr("Erase a disk and install")
            description: qsTr("Uses a whole disk. Everything on it is deleted.")
            badge: qsTr("Deletes data"); badgeColor: Theme.danger
            selected: page.cfg.mode === "erase"
            onClicked: installer.set("disk.mode", "erase")
        }
        OptionCard {
            Layout.fillWidth: true
            iconName: "layers"
            title: qsTr("Install alongside other systems")
            description: page.anyFree ? qsTr("Uses unallocated space and keeps existing partitions (e.g. Windows) untouched. A boot menu lets you choose at start-up.")
                                      : qsTr("Needs at least 40 GB of unallocated space. Shrink a partition first (e.g. in Windows Disk Management or the partition editor).")
            enabled: page.anyFree
            badge: qsTr("Keeps data")
            selected: page.cfg.mode === "free-space"
            onClicked: installer.set("disk.mode", "free-space")
        }
        OptionCard {
            Layout.fillWidth: true
            iconName: "wrench"
            title: qsTr("Manual partitioning")
            description: qsTr("Choose partitions and mount points yourself. For advanced users.")
            selected: page.cfg.mode === "manual"
            onClicked: installer.set("disk.mode", "manual")
        }
    }

    // Disk choice -------------------------------------------------------------
    ColumnLayout {
        visible: page.cfg.mode !== "manual"
        Layout.fillWidth: true
        spacing: Theme.gap
        SectionTitle { text: qsTr("Disk") }
        Repeater {
            model: page.installable
            OptionCard {
                required property var modelData
                Layout.fillWidth: true
                iconName: modelData.transport === "usb" ? "plug" : "storage"
                title: modelData.label
                description: [modelData.path,
                              modelData.existing_systems.length ? qsTr("Contains: %1").arg(modelData.existing_systems.join(", ")) : qsTr("No operating system found"),
                              modelData.freeText].join("  ·  ")
                enabled: page.cfg.mode !== "free-space" || modelData.largest_free_bytes >= 40 * 1024 * 1024 * 1024
                selected: page.cfg.disk === modelData.path
                onClicked: installer.set("disk.disk", modelData.path)
            }
        }
        Notice {
            visible: page.installable.length === 0
            Layout.fillWidth: true
            kind: "danger"
            text: qsTr("No disk large enough (16 GB or more) was found. The installation medium itself cannot be used.")
        }
        Notice {
            visible: page.cfg.mode === "erase" && page.chosen !== undefined && page.chosen.partitions.length > 0
            Layout.fillWidth: true
            kind: "danger"
            title: qsTr("All data on this disk will be erased")
            text: page.chosen ? page.chosen.partitions.map(p => "• " + p.path + "  " + p.size + "  " + p.role + (p.label ? "  “" + p.label + "”" : "")).join("\n") : ""
        }
        RowLayout {
            AppButton { text: qsTr("Rescan disks"); iconName: "refresh"; onClicked: installer.rescanDisks() }
        }
    }

    // Manual ------------------------------------------------------------------
    ColumnLayout {
        visible: page.cfg.mode === "manual"
        Layout.fillWidth: true
        spacing: Theme.gap
        Notice {
            Layout.fillWidth: true
            text: qsTr("Create partitions with the partition editor, then assign mount points here. You need / (root) and, on UEFI, the EFI system partition at /boot (or /efi plus a /boot partition). Partitions marked “Format” are erased.")
        }
        RowLayout {
            spacing: 12
            AppButton { text: qsTr("Open partition editor"); iconName: "wrench"; onClicked: installer.openPartitionEditor() }
            AppButton { text: qsTr("Rescan"); iconName: "refresh"; onClicked: installer.rescanDisks() }
        }
        Repeater {
            model: installer.disks.filter(d => !d.live_medium)
            Card {
                id: diskCard
                required property var modelData
                Layout.fillWidth: true
                Text { text: modelData.label + "  (" + modelData.path + ")"; color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                Repeater {
                    model: diskCard.modelData.partitions
                    RowLayout {
                        id: prow
                        required property var modelData
                        readonly property var mount: (page.cfg.mounts || []).find(m => m.device === modelData.path)
                        Layout.fillWidth: true
                        spacing: 12
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Text { text: prow.modelData.path + "  ·  " + prow.modelData.size; color: Theme.fg; font.pixelSize: Theme.text }
                            Text { text: prow.modelData.role + (prow.modelData.label ? "  “" + prow.modelData.label + "”" : ""); color: Theme.muted; font.pixelSize: Theme.textSmall }
                        }
                        AppCombo {
                            Layout.preferredWidth: 160
                            options: [{ id: "", label: qsTr("Do not use") }, { id: "/", label: "/" }, { id: "/home", label: "/home" },
                                      { id: "/boot", label: "/boot" }, { id: "/efi", label: "/efi" }, { id: "swap", label: "swap" }]
                            current: prow.mount ? prow.mount.mountpoint : ""
                            onChosen: (id) => installer.setMount(prow.modelData.path, id, prow.mount ? prow.mount.format : id !== "/boot" && id !== "/efi")
                        }
                        CheckBox {
                            text: qsTr("Format")
                            enabled: prow.mount !== undefined
                            checked: prow.mount ? prow.mount.format : false
                            onToggled: installer.setMount(prow.modelData.path, prow.mount.mountpoint, checked)
                            palette.windowText: Theme.fg
                        }
                    }
                }
                Text { visible: diskCard.modelData.partitions.length === 0; text: qsTr("No partitions"); color: Theme.muted }
            }
        }
    }

    // Options -----------------------------------------------------------------
    SectionTitle { text: qsTr("File system and security") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 700 ? 2 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        OptionCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            title: "Btrfs"
            description: qsTr("Compression and automatic snapshots before every update, bootable from the boot menu.")
            badge: qsTr("Recommended")
            selected: page.cfg.filesystem === "btrfs"
            onClicked: installer.set("disk.filesystem", "btrfs")
        }
        OptionCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            title: "ext4"
            description: qsTr("The classic, simple Linux file system.")
            selected: page.cfg.filesystem === "ext4"
            onClicked: installer.set("disk.filesystem", "ext4")
        }
    }
    Card {
        Layout.fillWidth: true
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Encrypt the system (LUKS2)")
            description: qsTr("Protects your files if the computer is lost or stolen. You type the passphrase at every start.")
            checked: page.cfg.encrypt
            enabled: page.cfg.mode !== "manual"
            onToggled: (v) => installer.set("disk.encrypt", v)
        }
        GridLayout {
            visible: page.cfg.encrypt
            Layout.fillWidth: true
            columns: width > 600 ? 2 : 1
            columnSpacing: Theme.gap
            TextInput2 {
                id: pass1
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: qsTr("Passphrase")
                password: true
                hint: qsTr("At least 8 characters. There is no way to recover it.")
                onEdited: (v) => installer.set("disk.passphrase", v === page.pass2 ? v : "")
            }
            TextInput2 {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: qsTr("Confirm passphrase")
                password: true
                error: page.pass2 !== "" && page.pass2 !== pass1.text ? qsTr("The passphrases do not match.") : ""
                onEdited: (v) => { page.pass2 = v; installer.set("disk.passphrase", v === pass1.text ? v : "") }
            }
        }
    }
    Card {
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: qsTr("Swap"); color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                Text { text: qsTr("Compressed RAM (zram) is fast and needs no disk space; hibernation needs a swap partition or file."); color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppCombo {
                Layout.preferredWidth: 220
                options: [{ id: "zram", label: qsTr("zram (recommended)") }, { id: "partition", label: qsTr("Swap partition") },
                          { id: "file", label: qsTr("Swap file") }, { id: "none", label: qsTr("No swap") }]
                current: page.cfg.swap
                onChosen: (id) => installer.set("disk.swap", id)
            }
        }
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Hibernation")
            description: qsTr("Save the session to disk and power off. The swap space is sized to your RAM.")
            checked: page.cfg.hibernation
            enabled: page.cfg.swap === "partition" || page.cfg.swap === "file"
            onToggled: (v) => installer.set("disk.hibernation", v)
        }
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Separate /home partition")
            description: qsTr("Keeps your files on their own partition, so the system can be reinstalled without touching them.")
            checked: page.cfg.separate_home
            enabled: page.cfg.mode === "erase"
            onToggled: (v) => installer.set("disk.separate_home", v)
        }
    }

    SectionTitle { text: qsTr("Boot") }
    Card {
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: qsTr("Boot loader"); color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                Text { text: qsTr("systemd-boot is simple and fast; GRUB can boot snapshots and works on BIOS computers."); color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            AppCombo {
                Layout.preferredWidth: 240
                options: installer.hardware.uefi
                    ? [{ id: "auto", label: qsTr("Automatic (systemd-boot)") }, { id: "systemd-boot", label: "systemd-boot" }, { id: "grub", label: "GRUB" }]
                    : [{ id: "auto", label: qsTr("Automatic (GRUB)") }, { id: "grub", label: "GRUB" }]
                current: installer.config.bootloader
                onChosen: (id) => installer.set("bootloader", id)
            }
        }
        ToggleRow {
            visible: installer.hardware.uefi
            Layout.fillWidth: true
            title: qsTr("Secure Boot with your own keys (sbctl)")
            description: installer.hardware.setupMode
                ? qsTr("The firmware is in Setup Mode: keys are created and enrolled (keeping Microsoft's), and the boot loader and kernels are signed.")
                : qsTr("Keys are created and everything is signed, but enrolling them needs the firmware in Setup Mode. Leave this off unless you know you need it.")
            badge: installer.hardware.secureBoot ? qsTr("Secure Boot is on") : ""
            checked: installer.config.secure_boot === "sbctl"
            enabled: installer.config.bootloader !== "grub"
            onToggled: (v) => installer.set("secure_boot", v ? "sbctl" : "off")
        }
        Notice {
            visible: installer.hardware.secureBoot === true && installer.config.secure_boot !== "sbctl"
            Layout.fillWidth: true
            kind: "warning"
            text: qsTr("Secure Boot is enabled in the firmware. Either enable the option above, or turn Secure Boot off in the firmware settings before restarting.")
        }
    }
}
