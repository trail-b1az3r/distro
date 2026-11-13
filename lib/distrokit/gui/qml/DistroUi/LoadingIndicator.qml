import QtQuick

// M3 Expressive loading indicator: a shape that turns and morphs (soft square, circle, flower-ish pill) while work
// runs. `contained` puts it on a primary-container disc.
Item {
    id: root
    property bool running: true
    property bool contained: false
    property int size: 48
    implicitWidth: size
    implicitHeight: size
    visible: running

    Rectangle {
        anchors.fill: parent
        visible: root.contained
        radius: width / 2
        color: Theme.primaryContainer
    }
    Rectangle {
        id: shape
        anchors.centerIn: parent
        property real phase: 0
        width: root.size * (root.contained ? 0.55 : 0.75) * (1 + 0.12 * Math.sin(phase * 2))
        height: width
        radius: width * (0.18 + 0.32 * (0.5 + 0.5 * Math.sin(phase)))
        rotation: phase * 57.3
        color: root.contained ? Theme.primaryContainerContent : Theme.primary
        NumberAnimation on phase {
            running: root.running && root.visible
            from: 0; to: Math.PI * 2
            duration: 1600
            loops: Animation.Infinite
        }
    }
    Accessible.role: Accessible.ProgressBar
    Accessible.name: qsTr("Working")
}
