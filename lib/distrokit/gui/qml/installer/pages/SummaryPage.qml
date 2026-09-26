import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 20
    readonly property var s: installer.summary
    property bool understood: false
    property string typed: ""
    property bool showCommands: false
    readonly property bool canInstall: s.ok === true && (!s.needsConfirm || (understood && typed === s.confirmToken))

    PageHeader { title: qsTr("Summary"); subtitle: qsTr("Check everything below. Nothing has been changed yet.") }

    Notice {
        visible: page.s.ok === false
        Layout.fillWidth: true
        kind: "danger"
        title: qsTr("This configuration cannot be installed")
        text: page.s.error || ""
    }

    ColumnLayout {
        visible: page.s.ok === true
        Layout.fillWidth: true
        spacing: 20

        Card {
            Layout.fillWidth: true
            tint: Theme.dangerSoft
            RowLayout {
                spacing: 10
                Icon { name: "alert"; size: 22; color: Theme.danger }
                Text { text: qsTr("Changes to your disks"); color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.Bold }
            }
            Repeater {
                model: page.s.destructive || []
                Text {
                    required property string modelData
                    Layout.fillWidth: true
                    text: modelData
                    color: Theme.fg
                    font.pixelSize: Theme.text
                    font.weight: modelData.startsWith("ERASE") || modelData.startsWith("FORMAT") ? Font.Bold : Font.Normal
                    wrapMode: Text.WordWrap
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width > 700 ? 2 : 1
            columnSpacing: Theme.gap
            rowSpacing: Theme.gap
            Repeater {
                model: [
                    { icon: "globe", label: qsTr("Language & region"), value: (page.s.locale || "") + " · " + (page.s.timezone || "") },
                    { icon: "keyboard", label: qsTr("Keyboard"), value: page.s.keyboard || "" },
                    { icon: "layers", label: qsTr("Profile"), value: (page.s.profile || "") + qsTr(" — %1 packages").arg(page.s.packages || 0) },
                    { icon: "power", label: qsTr("Boot"), value: (page.s.bootloader || "") + " (" + (page.s.firmware || "") + ")" },
                    { icon: "user", label: qsTr("Account"), value: (page.s.user || "") + " @ " + (page.s.hostname || "") },
                    { icon: "network", label: qsTr("Network"), value: page.s.online ? qsTr("Online") : qsTr("Offline: online extras install after first login") },
                    { icon: "tablet", label: qsTr("Surface kernel"), value: page.s.surface ? qsTr("Yes") : qsTr("No") },
                    { icon: "sparkles", label: qsTr("AI"), value: page.s.ai ? [page.s.ai.assistant !== "none" ? qsTr("Assistant: ") + page.s.ai.assistant : qsTr("No assistant"),
                                                                              page.s.ai.hypernix ? "HyperNix" : "", page.s.ai.model ? qsTr("Model: ") + page.s.ai.model : "",
                                                                              page.s.ai.backend].filter(x => x).join(" · ") : "" }
                ]
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
            SectionTitle { text: qsTr("Graphics") }
            Repeater {
                model: page.s.gpu || []
                Text { required property string modelData; text: "•  " + modelData; color: Theme.fg; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: Theme.text }
            }
        }

        Repeater {
            model: page.s.warnings || []
            Notice { required property string modelData; Layout.fillWidth: true; kind: "warning"; text: modelData }
        }

        AppButton {
            text: page.showCommands ? qsTr("Hide the exact commands") : qsTr("Show the exact commands (%1)").arg(installer.commands.length)
            iconName: "terminal"
            onClicked: page.showCommands = !page.showCommands
        }
        Rectangle {
            visible: page.showCommands
            Layout.fillWidth: true
            Layout.preferredHeight: 320
            color: Theme.dark ? "#070910" : "#11131C"
            radius: Theme.radiusSmall
            ScrollView {
                anchors.fill: parent
                anchors.margins: 10
                TextArea {
                    readOnly: true
                    text: installer.commands.join("\n")
                    color: "#C9D1E8"
                    font.family: Theme.mono
                    font.pixelSize: 12
                    wrapMode: TextEdit.WrapAnywhere
                    background: null
                    Accessible.name: qsTr("Commands the installer will run")
                }
            }
        }

        Card {
            visible: page.s.needsConfirm === true
            Layout.fillWidth: true
            highlighted: page.canInstall
            CheckBox {
                id: understand
                text: qsTr("I understand that the changes listed above will be made and data on them will be lost.")
                checked: page.understood
                onToggled: page.understood = checked
                contentItem: Text { leftPadding: understand.indicator.width + 8; text: understand.text; color: Theme.fg; wrapMode: Text.WordWrap; font.pixelSize: Theme.text; verticalAlignment: Text.AlignVCenter }
            }
            TextInput2 {
                Layout.fillWidth: true
                label: qsTr("Type %1 to confirm").arg(page.s.confirmToken || "")
                placeholder: page.s.confirmToken || ""
                onEdited: (v) => page.typed = v.trim()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            AppButton { text: qsTr("Back"); iconName: "arrow-left"; onClicked: win.back() }
            Item { Layout.fillWidth: true }
            AppButton {
                kind: page.s.needsConfirm ? "danger" : "primary"
                text: qsTr("Install now")
                iconName: "download"
                enabled: page.canInstall
                onClicked: { if (installer.install(page.typed)) win.page = win.pageIds.indexOf("install") }
            }
        }
    }
}
