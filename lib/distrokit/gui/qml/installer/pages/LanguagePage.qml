import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    spacing: 24
    PageHeader { title: qsTr("Language & Region"); subtitle: qsTr("The language of the system and the time zone of the clock.") }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 760 ? 2 : 1
        columnSpacing: 24
        rowSpacing: 24
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            SectionTitle { text: qsTr("Language") }
            SearchList {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                items: installer.locales
                current: installer.config.locale
                placeholder: qsTr("Search languages (e.g. Deutsch, fr_FR)…")
                onPicked: (v) => installer.set("locale", v)
            }
            Text { text: qsTr("Selected: %1").arg(installer.config.locale); color: Theme.muted; font.pixelSize: Theme.textSmall }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            SectionTitle { text: qsTr("Time zone") }
            SearchList {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                items: installer.timezones
                current: installer.config.timezone
                placeholder: qsTr("Search cities (e.g. Berlin, New_York)…")
                onPicked: (v) => installer.set("timezone", v)
            }
            Text { text: qsTr("Selected: %1").arg(installer.config.timezone); color: Theme.muted; font.pixelSize: Theme.textSmall }
        }
    }
}
