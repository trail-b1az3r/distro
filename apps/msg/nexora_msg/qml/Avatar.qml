import QtQuick
import QtQuick.Controls
import QtQuick.Effects

// A person's photo, or their initials on a colour picked from their name.
Item {
    id: root
    property string name: ""
    property string photo: ""
    property bool group: false
    implicitWidth: 44
    implicitHeight: 44

    readonly property var palette: ["#5e81ac", "#bf616a", "#a3be8c", "#d08770", "#b48ead", "#88c0d0", "#ebcb8b"]
    function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return Math.abs(h) }

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: root.palette[root.hash(root.name) % root.palette.length]
        visible: img.status !== Image.Ready
        Label {
            anchors.centerIn: parent
            color: "white"
            font.pixelSize: root.width * 0.38
            font.weight: Font.DemiBold
            visible: !root.group
            // Letters only (a number has no initials): a character with an upper and a lower case.
            text: root.name.split(/\s+/).filter(w => w.length && w[0].toUpperCase() !== w[0].toLowerCase()).slice(0, 2).map(w => w[0].toUpperCase()).join("") || "#"
        }
    }
    Image {
        anchors.centerIn: parent
        width: parent.width * 0.55
        height: width
        visible: root.group && img.status !== Image.Ready
        source: "icons/group.svg"
        sourceSize: Qt.size(width * 2, height * 2)
    }
    Image {
        id: img
        anchors.fill: parent
        source: root.photo ? "file://" + root.photo : ""
        sourceSize: Qt.size(root.width * 2, root.height * 2)
        fillMode: Image.PreserveAspectCrop
        visible: false
        layer.enabled: true
        asynchronous: true
    }
    Rectangle { id: mask; anchors.fill: parent; radius: width / 2; visible: false; layer.enabled: true }
    MultiEffect {
        anchors.fill: parent
        source: img
        visible: img.status === Image.Ready
        maskEnabled: true
        maskSource: mask
        maskThresholdMin: 0.5
        maskSpreadAtMin: 1.0
    }
}
