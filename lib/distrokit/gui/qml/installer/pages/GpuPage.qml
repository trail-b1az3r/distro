import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var compute: installer.features.find(f => f.id === "gpu_compute")

    PageHeader { title: qsTr("Graphics"); subtitle: qsTr("The recommended driver is chosen for each GPU. Change it only if you know you need a different one.") }
    Notice {
        visible: installer.gpuInfo.mode === "hybrid"
        Layout.fillWidth: true
        title: qsTr("Hybrid graphics")
        text: qsTr("The integrated GPU drives the display and saves power; the discrete GPU renders games and AI work on demand.")
    }
    Repeater {
        model: installer.gpuCards
        Card {
            required property var modelData
            Layout.fillWidth: true
            highlighted: modelData.stack !== modelData.recommended
            RowLayout {
                spacing: 14
                Rectangle {
                    width: 48; height: 48; radius: 14; color: Theme.accentSoft
                    Icon { anchors.centerIn: parent; name: "gpu"; size: 26; color: Theme.accent }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text { text: modelData.name; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    Text {
                        text: [modelData.kind, modelData.architecture, modelData.vram, modelData.role !== "only" ? modelData.role : ""].filter(x => x).join("  ·  ")
                        color: Theme.muted; font.pixelSize: Theme.textSmall
                    }
                }
            }
            Text { text: modelData.reason; color: Theme.fg; font.pixelSize: Theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Text { text: qsTr("Driver"); color: Theme.muted; font.pixelSize: Theme.text; Layout.preferredWidth: 80 }
                AppCombo {
                    Layout.fillWidth: true
                    options: modelData.options.map(o => ({ id: o.id, label: o.label + (o.id === modelData.recommended ? qsTr("  (recommended)") : "") }))
                    current: modelData.stack
                    onChosen: (id) => installer.setGpuDriver(modelData.slot, id)
                }
            }
            RowLayout {
                spacing: 8
                Badge { text: "Vulkan: " + modelData.vulkan; color: Theme.surface2 }
                Badge { text: "Wayland: " + modelData.wayland; color: Theme.surface2 }
                Badge { visible: modelData.vendor === "nvidia"; text: "CUDA: " + modelData.cuda; color: Theme.surface2 }
            }
        }
    }
    Notice {
        visible: installer.gpuCards.length === 0
        Layout.fillWidth: true
        text: qsTr("No GPU was detected; the generic Mesa drivers are installed.")
    }
    Repeater {
        model: installer.gpuInfo.notes
        Notice { required property string modelData; Layout.fillWidth: true; text: modelData }
    }
    Card {
        Layout.fillWidth: true
        ToggleRow {
            Layout.fillWidth: true
            title: page.compute ? page.compute.label : ""
            description: (page.compute ? page.compute.description : "") + (installer.gpuInfo.computePackages.length ? "\n" + installer.gpuInfo.computePackages.join(", ") : "")
            checked: page.compute ? page.compute.value === true : false
            onToggled: (v) => installer.setFeature("gpu_compute", v)
        }
        ToggleRow {
            Layout.fillWidth: true
            title: qsTr("32-bit graphics libraries")
            description: qsTr("Needed by Steam, Wine and other 32-bit programs (enables the multilib repository).")
            checked: installer.config.multilib
            onToggled: (v) => installer.set("multilib", v)
        }
    }
}
