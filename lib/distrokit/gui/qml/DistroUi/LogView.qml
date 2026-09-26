import QtQuick
import QtQuick.Controls.Basic

// Scrolling monospace log that follows new lines unless scrolled up.
Rectangle {
    id: root
    property var lines: []
    property int maxLines: 4000
    color: Theme.dark ? "#070910" : "#11131C"
    radius: Theme.radiusSmall
    border.color: Theme.border
    function append(line) {
        model.append({ text: line })
        if (model.count > maxLines) model.remove(0, model.count - maxLines)
        if (follow) list.positionViewAtEnd()
    }
    function clear() { model.clear() }
    property bool follow: true
    ListModel { id: model }
    ListView {
        id: list
        anchors.fill: parent
        anchors.margins: 10
        clip: true
        model: model
        ScrollBar.vertical: ScrollBar {}
        onMovementEnded: root.follow = atYEnd
        Accessible.role: Accessible.StaticText
        Accessible.name: qsTr("Installation log")
        delegate: Text {
            required property string text
            width: ListView.view.width
            text: text
            color: text.startsWith("$ ") ? "#8FD3FF" : (text.startsWith("✗") || text.indexOf("error") === 0 ? "#FF8FA3" : "#C9D1E8")
            font.family: Theme.mono
            font.pixelSize: 12
            wrapMode: Text.WrapAnywhere
        }
    }
}
