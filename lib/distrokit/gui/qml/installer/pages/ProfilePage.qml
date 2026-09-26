import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    property bool customise: installer.features.some(f => f.overridden)
    readonly property var groups: {
        const seen = []
        installer.features.forEach(f => { if (seen.indexOf(f.group) < 0) seen.push(f.group) })
        return seen
    }
    readonly property var icons: ({ minimal: "package", standard: "desktop", developer: "code", ai: "sparkles" })

    PageHeader { title: qsTr("Installation Profile"); subtitle: qsTr("A starting point. Every part can be switched on or off below.") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 700 ? 2 : 1
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap
        Repeater {
            model: installer.profiles
            OptionCard {
                required property var modelData
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                iconName: page.icons[modelData.id] || "package"
                title: modelData.name
                description: modelData.summary + "\n" + qsTr("About %1 GB").arg(modelData.approxSizeGb)
                badge: modelData.default ? qsTr("Recommended") : ""
                selected: installer.config.profile === modelData.id
                onClicked: installer.set("profile", modelData.id)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        text: (installer.profiles.find(p => p.id === installer.config.profile) || {}).description || ""
        color: Theme.muted
        wrapMode: Text.WordWrap
        font.pixelSize: Theme.text
    }
    AppButton {
        text: page.customise ? qsTr("Hide customisation") : qsTr("Customise")
        iconName: "settings"
        onClicked: page.customise = !page.customise
    }
    Repeater {
        model: page.customise ? page.groups : []
        ColumnLayout {
            id: grp
            required property string modelData
            Layout.fillWidth: true
            spacing: 8
            SectionTitle { text: grp.modelData }
            Card {
                Layout.fillWidth: true
                spacing: 0
                Repeater {
                    model: installer.features.filter(f => f.group === grp.modelData)
                    Loader {
                        id: row
                        required property var modelData
                        Layout.fillWidth: true
                        sourceComponent: modelData.kind === "bool" ? boolRow : choiceRow
                        Component {
                            id: boolRow
                            ToggleRow {
                                title: row.modelData.label
                                description: row.modelData.description
                                badge: row.modelData.network ? qsTr("needs internet") : ""
                                checked: row.modelData.value === true
                                onToggled: (v) => installer.setFeature(row.modelData.id, v)
                            }
                        }
                        Component {
                            id: choiceRow
                            RowLayout {
                                spacing: 16
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Text { text: row.modelData.label; color: Theme.fg; font.weight: Font.DemiBold; font.pixelSize: Theme.text }
                                    Text { text: row.modelData.description; color: Theme.muted; font.pixelSize: Theme.textSmall; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                }
                                AppCombo {
                                    Layout.preferredWidth: 180
                                    options: row.modelData.choices.map(c => ({ id: c, label: c.charAt(0).toUpperCase() + c.slice(1) }))
                                    current: row.modelData.value
                                    onChosen: (id) => installer.setFeature(row.modelData.id, id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
