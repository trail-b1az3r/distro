import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    function feature(id) { return installer.features.find(f => f.id === id) || ({ value: false }) }
    readonly property string assistant: feature("assistant").value || "none"

    PageHeader { title: qsTr("AI Assistant"); subtitle: qsTr("Choose assistants to install for your account. Everything here is optional and installs into your home folder, so it can never stop the system from working.") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 700 ? 2 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        Repeater {
            model: [
                { id: "none", icon: "x", title: qsTr("None"), text: qsTr("No assistant. You can add one later with `%1 ai install`.").arg(brandInfo.cli) },
                { id: "hermis", icon: "bot", title: "Hermis", text: qsTr("Hermes Agent by Nous Research: a self-improving agent that learns skills as you use it. Works with local models or cloud providers.") },
                { id: "openclaw", icon: "message", title: "OpenClaw", text: qsTr("A personal assistant with a local gateway, chat channels and a web dashboard.") },
                { id: "both", icon: "sparkles", title: qsTr("Both"), text: qsTr("Install Hermis and OpenClaw side by side.") }
            ]
            OptionCard {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                iconName: modelData.icon
                title: modelData.title
                description: modelData.text
                selected: page.assistant === modelData.id
                onClicked: installer.setFeature("assistant", modelData.id)
            }
        }
    }
    SectionTitle { text: "HyperNix" }
    Card {
        Layout.fillWidth: true
        highlighted: page.feature("hypernix").value === true
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("Install HyperNix")
            description: qsTr("Chat with local models, convert and quantise them to GGUF, fine-tune and monitor training. PyTorch is installed for %1.").arg(installer.gpuInfo.backend)
            badge: qsTr("needs internet")
            checked: page.feature("hypernix").value === true
            onToggled: (v) => installer.setFeature("hypernix", v)
        }
    }
    SectionTitle { text: qsTr("Developer tools") }
    Card {
        Layout.fillWidth: true
        ToggleRow {
            Layout.fillWidth: true
            title: "Claude Code"
            description: qsTr("Anthropic's coding agent. Runs as `claude` in any terminal, with no shell setup needed.")
            badge: qsTr("needs internet")
            checked: page.feature("claude_code").value === true
            onToggled: (v) => installer.setFeature("claude_code", v)
        }
    }
    Notice {
        visible: !installer.online && (page.assistant !== "none" || page.feature("hypernix").value || page.feature("claude_code").value)
        Layout.fillWidth: true
        kind: "warning"
        text: qsTr("You are offline: these will be installed automatically the first time you log in with an internet connection.")
    }
}
