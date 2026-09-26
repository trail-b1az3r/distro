import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ApplicationWindow {
    id: win
    width: 1040
    height: 740
    minimumWidth: 600
    minimumHeight: 480
    visible: true
    title: qsTr("AI Assistant")
    color: Theme.bg
    property string tab: ai.startTab
    property string themeMode: "system"
    onThemeModeChanged: Theme.mode = themeMode
    property var progress: ({})
    property var hfFiles: []
    property string hfError: ""
    readonly property var icons: ({ hypernix: "flame", hermis: "bot", openclaw: "message", "claude-code": "terminal", "local-model": "model" })

    function human(bytes) {
        if (!bytes) return "0 B"
        const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let v = bytes
        while (v >= 1000 && i < u.length - 1) { v /= 1000; i++ }
        return v.toFixed(v >= 10 || i === 0 ? 0 : 1) + " " + u[i]
    }

    Connections {
        target: ai
        function onLog(line) { log.append(line) }
        function onProgress(id, value) { const p = Object.assign({}, win.progress); p[id] = value; win.progress = p }
        function onHfResult(r) { win.hfError = r.ok ? "" : r.error; win.hfFiles = r.ok ? r.files : [] }
    }
    Shortcut { sequence: "Ctrl+1"; onActivated: win.tab = "launcher" }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.tab = "models" }

    ScrollView {
        id: scroller
        anchors.fill: parent
        contentWidth: availableWidth
        Item {
            width: scroller.availableWidth
            implicitHeight: col.implicitHeight + 48
            ColumnLayout {
                id: col
                x: Math.max(20, (parent.width - width) / 2)
                y: 24
                width: Math.min(parent.width - 40, 940)
                spacing: 18

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Icon { name: "sparkles"; size: 30; color: Theme.accent }
                    Text { text: qsTr("AI"); color: Theme.fg; font.pixelSize: Theme.title; font.weight: Font.Bold; Layout.fillWidth: true }
                    AppButton { kind: win.tab === "launcher" ? "primary" : "secondary"; text: qsTr("Launcher"); onClicked: win.tab = "launcher" }
                    AppButton { kind: win.tab === "models" ? "primary" : "secondary"; text: qsTr("Models"); onClicked: win.tab = "models" }
                    ThemeSwitch {}
                }

                // Launcher ---------------------------------------------------------------
                GridLayout {
                    visible: win.tab === "launcher"
                    Layout.fillWidth: true
                    columns: width > 720 ? 2 : 1
                    columnSpacing: Theme.gap
                    rowSpacing: Theme.gap
                    Repeater {
                        model: ai.entries
                        Card {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            RowLayout {
                                spacing: 14
                                Rectangle {
                                    width: 52; height: 52; radius: 16
                                    gradient: Gradient {
                                        orientation: Gradient.Horizontal
                                        GradientStop { position: 0; color: Theme.accent }
                                        GradientStop { position: 1; color: Theme.accent2 }
                                    }
                                    Icon { anchors.centerIn: parent; name: win.icons[modelData.id] || "sparkles"; size: 28; color: "#FFFFFF" }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text { text: modelData.name; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Badge {
                                        text: modelData.installed ? (modelData.configured ? qsTr("Ready") : qsTr("Needs setup")) : qsTr("Not installed")
                                        color: modelData.installed ? (modelData.configured ? Theme.success : Theme.warning) : Theme.surface2
                                    }
                                }
                            }
                            Text { text: modelData.description; color: Theme.muted; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: Theme.text }
                            Item { Layout.fillHeight: true }
                            RowLayout {
                                spacing: 8
                                AppButton {
                                    kind: "primary"
                                    text: !modelData.installed ? qsTr("Install") : modelData.configured ? qsTr("Open") : qsTr("Set up")
                                    iconName: !modelData.installed ? "download" : "play"
                                    onClicked: modelData.id === "local-model" && !modelData.installed ? win.tab = "models" : ai.launch(modelData.id, "run")
                                }
                                AppButton { visible: modelData.id === "hypernix" && modelData.installed; text: qsTr("Devices"); onClicked: ai.launch("hypernix", "devices") }
                                AppButton { visible: modelData.id === "local-model" && modelData.installed; text: ai.serverRunning ? qsTr("Stop server") : qsTr("Serve")
                                            onClicked: ai.setServer(!ai.serverRunning) }
                                AppButton { visible: modelData.homepage !== ""; kind: "ghost"; iconName: "external"; text: qsTr("Website"); onClicked: launcher.openUrl(modelData.homepage) }
                            }
                        }
                    }
                }
                Notice {
                    visible: win.tab === "launcher"
                    Layout.fillWidth: true
                    text: ai.serverRunning ? qsTr("Your default model is served at %1 (OpenAI-compatible). Point assistants and editors there to use it.").arg(ai.endpoint)
                                           : qsTr("Serve your default model to use it from assistants, editors and scripts through an OpenAI-compatible API.")
                }

                // Models -----------------------------------------------------------------
                ColumnLayout {
                    visible: win.tab === "models"
                    Layout.fillWidth: true
                    spacing: 16
                    Card {
                        Layout.fillWidth: true
                        highlighted: true
                        Text { text: ai.recommendation.headline; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        Text { text: qsTr("Acceleration: %1").arg(ai.recommendation.backend.description); color: Theme.muted }
                        Repeater { model: ai.recommendation.lines; Text { required property string modelData; text: "•  " + modelData; color: Theme.fg } }
                    }
                    SectionTitle { text: qsTr("Installed") }
                    Repeater {
                        model: Object.keys(ai.installed.models)
                        Card {
                            id: mcard
                            required property string modelData
                            readonly property var entry: ai.installed.models[modelData]
                            Layout.fillWidth: true
                            padding: 14
                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Text { text: mcard.entry.name + (ai.installed.default === mcard.modelData ? qsTr("  (default)") : ""); color: Theme.fg; font.weight: Font.DemiBold }
                                    Text { text: mcard.entry.path || mcard.entry.source || ""; color: Theme.muted; font.pixelSize: Theme.textSmall; elide: Text.ElideMiddle; Layout.fillWidth: true }
                                }
                                AppButton { visible: ai.installed.default !== mcard.modelData; text: qsTr("Make default"); onClicked: ai.setDefault(mcard.modelData) }
                                AppButton { kind: "ghost"; iconName: "trash"; text: qsTr("Remove"); onClicked: ai.removeModel(mcard.modelData) }
                            }
                        }
                    }
                    Text { visible: Object.keys(ai.installed.models).length === 0; text: qsTr("No models installed yet."); color: Theme.muted }

                    SectionTitle { text: qsTr("Catalogue") }
                    TextInput2 { id: filter; Layout.fillWidth: true; placeholder: qsTr("Search models…") }
                    Repeater {
                        model: ai.recommendation.fits.filter(m => {
                            const q = filter.text.toLowerCase()
                            return q === "" || (m.name + " " + m.category + " " + m.description).toLowerCase().indexOf(q) >= 0
                        })
                        Card {
                            required property var modelData
                            Layout.fillWidth: true
                            padding: 14
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    RowLayout {
                                        Text { text: modelData.name; color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                                        Badge {
                                            text: ({ gpu: qsTr("Fits GPU"), offload: qsTr("GPU + RAM"), cpu: qsTr("CPU"), "too-large": qsTr("Too large") })[modelData.placement]
                                            color: modelData.placement === "too-large" ? Theme.danger : modelData.placement === "offload" ? Theme.warning : Theme.accent2
                                        }
                                        Badge { visible: ai.recommendation.defaults[modelData.category] === modelData.id; text: qsTr("Suggested") }
                                    }
                                    Text { text: win.human(modelData.download_bytes) + qsTr(" download") + "  ·  " + modelData.memory_8k + qsTr(" memory") + "  ·  " + modelData.license; color: Theme.muted; font.pixelSize: Theme.textSmall }
                                    Text { text: modelData.description; color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    Rectangle {
                                        visible: win.progress[modelData.id] !== undefined && win.progress[modelData.id] < 1
                                        Layout.fillWidth: true; height: 6; radius: 3; color: Theme.surface2
                                        Rectangle { width: parent.width * (win.progress[modelData.id] || 0); height: 6; radius: 3; color: Theme.accent }
                                    }
                                }
                                AppButton {
                                    text: ai.installed.models[modelData.id] ? qsTr("Installed") : qsTr("Download")
                                    iconName: "download"
                                    enabled: !ai.busy && !ai.installed.models[modelData.id]
                                    onClicked: ai.installModel(modelData.id)
                                }
                            }
                        }
                    }

                    SectionTitle { text: qsTr("Add your own") }
                    Card {
                        id: customCard
                        Layout.fillWidth: true
                        property string source: "huggingface"
                        AppCombo {
                            Layout.fillWidth: true
                            options: [{ id: "huggingface", label: "Hugging Face" }, { id: "url", label: qsTr("Download URL") },
                                      { id: "path", label: qsTr("Local GGUF file") }, { id: "hypernix", label: qsTr("HyperNix model identifier") }]
                            current: customCard.source
                            onChosen: (id) => customCard.source = id
                        }
                        TextInput2 { id: repo; visible: customCard.source === "huggingface"; Layout.fillWidth: true; label: qsTr("Repository"); placeholder: "owner/name-GGUF" }
                        TextInput2 { id: file; visible: customCard.source === "huggingface"; Layout.fillWidth: true; label: qsTr("File"); placeholder: "model-Q4_K_M.gguf" }
                        TextInput2 { id: url; visible: customCard.source === "url"; Layout.fillWidth: true; label: qsTr("URL"); placeholder: "https://…/model.gguf" }
                        TextInput2 { id: path; visible: customCard.source === "path"; Layout.fillWidth: true; label: qsTr("Path"); placeholder: "~/Models/model.gguf" }
                        TextInput2 { id: hnx; visible: customCard.source === "hypernix"; Layout.fillWidth: true; label: qsTr("HyperNix model"); placeholder: "qwen3-8b" }
                        Repeater {
                            model: win.hfFiles
                            OptionCard { required property var modelData; Layout.fillWidth: true; title: modelData.file; description: modelData.sizeText; selected: file.text === modelData.file; onClicked: file.text = modelData.file }
                        }
                        Text { visible: win.hfError !== ""; text: win.hfError; color: Theme.danger; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        RowLayout {
                            spacing: 10
                            AppButton { visible: customCard.source === "huggingface"; text: qsTr("List files"); iconName: "search"; onClicked: ai.hfLookup(repo.text.trim(), "") }
                            AppButton {
                                kind: "primary"; text: qsTr("Add model"); iconName: "download"; enabled: !ai.busy
                                onClicked: ai.addCustom({ source: customCard.source, repo: repo.text.trim(), file: file.text.trim(), url: url.text.trim(),
                                                          path: path.text.trim(), hypernix_id: hnx.text.trim(), context: 8192 })
                            }
                        }
                    }
                }
                LogView { id: log; Layout.fillWidth: true; Layout.preferredHeight: 120 }
            }
        }
    }
}
