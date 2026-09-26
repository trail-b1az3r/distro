import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    readonly property var layout: installer.layouts.find(l => l.value === installer.config.keyboard_layout) || ({ variants: [] })
    PageHeader { title: qsTr("Keyboard"); subtitle: qsTr("Used everywhere: the login screen, the desktop and the text console.") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 760 ? 2 : 1
        columnSpacing: 24
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            SectionTitle { text: qsTr("Layout") }
            SearchList {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                items: installer.layouts.map(l => ({ value: l.value, label: l.label }))
                current: installer.config.keyboard_layout
                onPicked: (v) => { installer.set("keyboard_layout", v); installer.set("keyboard_variant", "") }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            SectionTitle { text: qsTr("Variant") }
            SearchList {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                listHeight: 200
                items: [{ value: "", label: qsTr("Default") }].concat(page.layout.variants)
                current: installer.config.keyboard_variant
                onPicked: (v) => installer.set("keyboard_variant", v)
            }
            TextInput2 {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                label: qsTr("Try your keyboard")
                placeholder: qsTr("Type here to test the layout")
                hint: qsTr("The live session keeps its own layout; your choice applies to the installed system.")
            }
        }
    }
}
