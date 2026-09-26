import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var ai: installer.ai
    readonly property var cfgAi: installer.config.ai
    property string mode: cfgAi.custom_model ? "custom" : (cfgAi.model === "" ? "none" : "category")
    property bool browse: false
    property var hfFiles: []
    property string hfError: ""
    property bool hfBusy: false
    readonly property var custom: cfgAi.custom_model || ({ source: "huggingface", repo: "", file: "", url: "", path: "", hypernix_id: "", context: 8192 })
    readonly property var selectedModel: ai.catalog.find(m => m.id === cfgAi.model)

    function setCustom(key, value) {
        const c = Object.assign({}, page.custom)
        c[key] = value
        installer.set("ai.custom_model", c)
    }
    function human(bytes) {
        if (!bytes) return "0 B"
        const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let v = bytes
        while (v >= 1000 && i < u.length - 1) { v /= 1000; i++ }
        return v.toFixed(v >= 10 || i === 0 ? 0 : 1) + " " + u[i]
    }

    Connections {
        target: installer
        function onHfResult(r) { page.hfBusy = false; page.hfError = r.ok ? "" : r.error; page.hfFiles = r.ok ? r.files : [] }
    }

    PageHeader { title: qsTr("Choose Default AI Model"); subtitle: qsTr("A local model runs entirely on this computer. Sizes are shown before anything is downloaded.") }

    Card {
        Layout.fillWidth: true
        highlighted: true
        RowLayout {
            spacing: 14
            Icon { name: "gauge"; size: 28; color: Theme.accent }
            ColumnLayout {
                Layout.fillWidth: true
                Text { text: page.ai.headline; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Text { text: qsTr("Recommended local models:"); color: Theme.muted; font.pixelSize: Theme.text }
                Repeater {
                    model: page.ai.lines
                    Text { required property string modelData; text: "•  " + modelData; color: Theme.fg; font.pixelSize: Theme.text }
                }
                Text { text: qsTr("This is advice, not a limit: any model can be chosen."); color: Theme.muted; font.pixelSize: Theme.textSmall }
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Theme.gap
        OptionCard {
            Layout.fillWidth: true
            iconName: "x"
            title: qsTr("No model")
            description: qsTr("Download one later from the AI Models app or with `%1 model install`.").arg(brandInfo.cli)
            selected: page.mode === "none"
            onClicked: { page.mode = "none"; installer.set("ai.custom_model", null); installer.set("ai.model", "") }
        }
        Repeater {
            model: page.ai.categories
            OptionCard {
                required property var modelData
                Layout.fillWidth: true
                iconName: ({ lightweight: "zap", general: "message", coding: "code", reasoning: "brain", vision: "eye" })[modelData.id] || "model"
                title: modelData.label
                enabled: modelData.suggested !== null
                description: modelData.suggested
                    ? modelData.suggested.name + "  ·  " + page.human(modelData.suggested.download_bytes) + " download  ·  " + modelData.suggested.note
                    : qsTr("No model in this category fits this machine; pick one from the full list if you want to try.")
                selected: page.mode === "category" && modelData.suggested && page.cfgAi.model === modelData.suggested.id
                onClicked: { page.mode = "category"; installer.set("ai.custom_model", null); installer.set("ai.model", modelData.suggested.id) }
            }
        }
        OptionCard {
            Layout.fillWidth: true
            iconName: "wrench"
            title: qsTr("Custom model")
            description: qsTr("A Hugging Face repository, a download URL, a GGUF file on a disk, or a HyperNix model name.")
            selected: page.mode === "custom"
            onClicked: { page.mode = "custom"; installer.set("ai.model", ""); installer.set("ai.custom_model", page.custom) }
        }
    }

    // Browse the whole catalogue ------------------------------------------------
    AppButton {
        visible: page.mode !== "custom"
        text: page.browse ? qsTr("Hide the full list") : qsTr("Browse all models")
        iconName: "search"
        onClicked: page.browse = !page.browse
    }
    ColumnLayout {
        visible: page.browse && page.mode !== "custom"
        Layout.fillWidth: true
        spacing: 8
        TextInput2 { id: filter; Layout.fillWidth: true; placeholder: qsTr("Search models (name, category, e.g. “coder”)…") }
        Repeater {
            model: page.ai.catalog.filter(m => {
                const q = filter.text.toLowerCase()
                return q === "" || (m.name + " " + m.category + " " + m.description).toLowerCase().indexOf(q) >= 0
            })
            OptionCard {
                required property var modelData
                Layout.fillWidth: true
                title: modelData.name
                description: page.human(modelData.download_bytes) + " download  ·  " + modelData.memory_8k + " memory  ·  " + modelData.license + "\n" + modelData.note
                badge: ({ gpu: qsTr("Fits GPU"), offload: qsTr("GPU + RAM"), cpu: qsTr("CPU"), "too-large": qsTr("Too large") })[modelData.placement]
                badgeColor: modelData.placement === "too-large" ? Theme.danger : modelData.placement === "offload" ? Theme.warning : Theme.accent2
                selected: page.cfgAi.model === modelData.id
                onClicked: { page.mode = "category"; installer.set("ai.custom_model", null); installer.set("ai.model", modelData.id) }
            }
        }
    }

    // Custom model form ------------------------------------------------------------
    Card {
        visible: page.mode === "custom"
        Layout.fillWidth: true
        SectionTitle { text: qsTr("Model source") }
        AppCombo {
            Layout.fillWidth: true
            options: [{ id: "huggingface", label: "Hugging Face" }, { id: "url", label: qsTr("Download URL") },
                      { id: "path", label: qsTr("Local model path / GGUF file") }, { id: "hypernix", label: qsTr("HyperNix model identifier") }]
            current: page.custom.source
            onChosen: (id) => page.setCustom("source", id)
        }
        ColumnLayout {
            visible: page.custom.source === "huggingface"
            Layout.fillWidth: true
            TextInput2 { Layout.fillWidth: true; label: qsTr("Repository"); placeholder: "unsloth/Qwen3-8B-GGUF"; text: page.custom.repo; onEdited: (v) => page.setCustom("repo", v) }
            TextInput2 { Layout.fillWidth: true; label: qsTr("Model file"); placeholder: "Qwen3-8B-Q4_K_M.gguf"; text: page.custom.file; onEdited: (v) => page.setCustom("file", v) }
            RowLayout {
                AppButton { text: page.hfBusy ? qsTr("Checking…") : qsTr("List files and sizes"); iconName: "search"; enabled: !page.hfBusy
                            onClicked: { page.hfBusy = true; installer.hfLookup(page.custom.repo, "") } }
                AppButton { text: qsTr("Check size"); iconName: "download"; enabled: !page.hfBusy && page.custom.file !== ""
                            onClicked: { page.hfBusy = true; installer.hfLookup(page.custom.repo, page.custom.file) } }
            }
            Text { visible: page.hfError !== ""; text: page.hfError; color: Theme.danger; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Repeater {
                model: page.hfFiles
                OptionCard {
                    required property var modelData
                    Layout.fillWidth: true
                    radio: true
                    title: modelData.file
                    description: modelData.sizeText
                    selected: page.custom.file === modelData.file
                    onClicked: { const c = Object.assign({}, page.custom); c.file = modelData.file; c.size_bytes = modelData.size; installer.set("ai.custom_model", c) }
                }
            }
        }
        TextInput2 { visible: page.custom.source === "url"; Layout.fillWidth: true; label: qsTr("URL"); placeholder: "https://…/model.gguf"; text: page.custom.url; onEdited: (v) => page.setCustom("url", v) }
        TextInput2 { visible: page.custom.source === "path"; Layout.fillWidth: true; label: qsTr("GGUF path"); placeholder: "/run/media/…/model.gguf"; text: page.custom.path; onEdited: (v) => page.setCustom("path", v)
                     hint: qsTr("The file is copied to your home folder during installation.") }
        TextInput2 { visible: page.custom.source === "hypernix"; Layout.fillWidth: true; label: qsTr("HyperNix model"); placeholder: "qwen3-8b"; text: page.custom.hypernix_id; onEdited: (v) => page.setCustom("hypernix_id", v) }
        RowLayout {
            Text { text: qsTr("Context"); color: Theme.fg; font.pixelSize: Theme.text; Layout.preferredWidth: 90 }
            AppCombo {
                Layout.preferredWidth: 180
                options: [2048, 4096, 8192, 16384, 32768, 65536, 131072].map(n => ({ id: String(n), label: n.toLocaleString(Qt.locale(), "f", 0) + qsTr(" tokens") }))
                current: String(page.custom.context || 8192)
                onChosen: (id) => page.setCustom("context", parseInt(id))
            }
        }
    }

    // Download timing and storage -----------------------------------------------
    Card {
        visible: page.mode !== "none"
        Layout.fillWidth: true
        SectionTitle { text: qsTr("When to download") }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            OptionCard {
                Layout.fillWidth: true
                title: qsTr("During installation")
                description: qsTr("Ready when you log in; the installation takes longer.")
                selected: page.cfgAi.download === "now"
                onClicked: installer.set("ai.download", "now")
            }
            OptionCard {
                Layout.fillWidth: true
                title: qsTr("After first login")
                description: qsTr("Downloads in the background with progress in the Welcome app.")
                selected: page.cfgAi.download === "first-boot"
                onClicked: installer.set("ai.download", "first-boot")
            }
        }
        Notice {
            visible: page.selectedModel !== undefined
            Layout.fillWidth: true
            kind: page.selectedModel && page.selectedModel.download_bytes * 1.2 > page.ai.targetBytes ? "danger" : "info"
            text: page.selectedModel
                ? qsTr("%1 needs %2 of disk space and about %3 of memory at 8k context. Space on the target: %4.")
                    .arg(page.selectedModel.name).arg(page.human(page.selectedModel.download_bytes)).arg(page.selectedModel.memory_8k).arg(page.human(page.ai.targetBytes))
                : ""
        }
    }
}
