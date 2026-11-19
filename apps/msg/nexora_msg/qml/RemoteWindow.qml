import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Nexora.Remote

// Another computer's desktop: its own window, with the keyboard and mouse going to it while it has focus.
ApplicationWindow {
    id: rw
    property string host
    property string code
    width: 1280
    height: 800
    visible: true
    title: (view.title || host) + " — Remote desktop"
    color: "black"
    Component.onCompleted: view.open(host, code)
    onClosing: view.close()

    header: ToolBar {
        visible: !rw.fullScreen
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 6
            Label {
                text: view.status.startsWith("connected") ? view.title + (view.status.length > 9 ? view.status.slice(9) : "")
                      : view.status === "connecting" ? "Connecting to " + rw.host + "…" : view.status.replace(/^(error|closed): /, "")
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Label { text: "Quality"; opacity: 0.7 }
            Slider { from: 30; to: 95; value: 70; stepSize: 5; Layout.preferredWidth: 120; onMoved: view.setQuality(value) }
            ToolButton { text: "Full screen"; onClicked: rw.visibility = Window.FullScreen }
            ToolButton { text: "Disconnect"; onClicked: { view.close(); rw.close() } }
        }
    }
    readonly property bool fullScreen: visibility === Window.FullScreen
    Shortcut { sequence: "Ctrl+Alt+Return"; onActivated: rw.visibility = rw.fullScreen ? Window.Windowed : Window.FullScreen }

    RemoteView {
        id: view
        objectName: "remoteView"
        anchors.fill: parent
        focus: true
    }
    Label {
        anchors.centerIn: parent
        visible: !view.status.startsWith("connected")
        width: Math.min(parent.width - 60, 520)
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        color: "white"
        font.pixelSize: 16
        text: view.status === "connecting" ? "Connecting…" : view.status.replace(/^(error|closed): /, "")
    }
}
