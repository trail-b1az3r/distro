import QtQuick
import QtQuick.Controls.Basic

// Scrolling monospace log that follows new lines unless scrolled up, in the lowest surface container.
Rectangle {
    id: root
    property var lines: []
    property int maxLines: 4000
    color: Theme.surfaceContainerLowest
    radius: Theme.shapeExtraLarge
    function append(line) {
        model.append({ line: line })
        if (model.count > maxLines) model.remove(0, model.count - maxLines)
        if (follow) list.positionViewAtEnd()
    }
    function clear() { model.clear() }
    property bool follow: true
    ListModel { id: model }
    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 18
        clip: true
        model: model
        ScrollBar.vertical: ScrollBar {}
        onMovementEnded: root.follow = atYEnd
        Accessible.role: Accessible.StaticText
        Accessible.name: qsTr("Installation log")
        delegate: Text {
            required property string line
            width: ListView.view.width
            text: line
            color: line.startsWith("$ ") ? Theme.primary : (line.startsWith("✗") || line.indexOf("error") === 0 ? Theme.error : Theme.surfaceVariantContent)
            font.family: Theme.mono
            font.pixelSize: 12
            wrapMode: Text.WrapAnywhere
        }
    }
}
