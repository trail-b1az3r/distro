import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 24
    property var warnings: []
    Component.onCompleted: {
        const done = installer.history().filter(e => e.type === "done")
        if (done.length) page.warnings = done[done.length - 1].warnings || []
    }
    ColumnLayout {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 24
        spacing: 12
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 96; height: 96; radius: 48
            color: Qt.rgba(0.2, 0.77, 0.55, 0.18)
            Icon { anchors.centerIn: parent; name: "check"; size: 52; color: Theme.success }
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: qsTr("%1 is installed").arg(brandInfo.prettyName)
            color: Theme.fg; font.pixelSize: Theme.display; font.weight: Font.Bold
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 620
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: qsTr("Restart and remove the installation medium. After you log in, the Welcome app helps you finish: updates, drivers, AI, appearance and backups.")
            color: Theme.muted; font.pixelSize: Theme.textLarge
        }
    }
    Repeater {
        model: page.warnings
        Notice { required property string modelData; Layout.fillWidth: true; kind: "warning"; text: modelData }
    }
    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: 12
        AppButton { text: qsTr("Keep using the live system"); onClicked: Qt.quit() }
        AppButton { kind: "primary"; text: qsTr("Restart now"); iconName: "power"; onClicked: installer.reboot() }
    }
}
