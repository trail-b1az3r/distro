import QtQuick

// An icon from the shared set (branding/icons/ui), drawn in `color` by the
// application's "icon" image provider.
Item {
    id: root
    property string name
    property int size: 20
    property color color: Theme.fg
    implicitWidth: size
    implicitHeight: size
    Image {
        anchors.fill: parent
        source: root.name ? "image://icon/" + root.name + "/" + root.color.toString().replace("#", "") : ""
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        smooth: true
        asynchronous: false
        Accessible.ignored: true
    }
}
