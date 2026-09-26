import QtQuick

Rectangle {
    property alias text: label.text
    color: Theme.accent2
    radius: height / 2
    implicitHeight: label.implicitHeight + 6
    implicitWidth: label.implicitWidth + 16
    Text {
        id: label
        anchors.centerIn: parent
        color: "#06121A"
        font.pixelSize: 11
        font.weight: Font.Bold
    }
}
