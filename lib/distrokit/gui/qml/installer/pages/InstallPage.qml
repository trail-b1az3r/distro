import QtQuick
import QtQuick.Layouts
import DistroUi

ColumnLayout {
    id: page
    spacing: 20
    property real progress: 0
    property string current: qsTr("Preparing…")
    property var steps: []
    property var states: ({})
    property string error: ""
    property var warnings: []
    property bool showLog: false
    property string download: ""

    function handle(e) {
            if (e.type === "plan") { page.steps = e.steps }
            else if (e.type === "step") { page.current = e.label; const s = Object.assign({}, page.states); s[e.id] = "running"; page.states = s }
            else if (e.type === "step-done") { const s = Object.assign({}, page.states); s[e.id] = s[e.id] === "warning" ? "warning" : "done"; page.states = s }
            else if (e.type === "progress") { page.progress = e.value }
            else if (e.type === "log") { log.append(e.line) }
            else if (e.type === "warning") { page.warnings = page.warnings.concat([e.message]); const s = Object.assign({}, page.states); s[e.step] = "warning"; page.states = s }
            else if (e.type === "download") { page.download = e.total ? (Math.round(e.done / e.total * 100) + "%") : "" }
            else if (e.type === "error") { page.error = e.label + ": " + e.message; const s = Object.assign({}, page.states); s[e.step] = "failed"; page.states = s; page.showLog = true }
            else if (e.type === "exit" && page.error === "") { page.error = qsTr("The installer stopped unexpectedly (code %1).").arg(e.code); page.showLog = true }
    }
    Component.onCompleted: installer.history().forEach(e => handle(e))
    Connections {
        target: installer
        function onEngineEvent(e) { page.handle(e) }
    }

    PageHeader {
        title: page.error ? qsTr("Installation failed") : qsTr("Installing %1").arg(brandInfo.prettyName)
        subtitle: page.error ? qsTr("Nothing else will be changed. The log below shows what happened.") : qsTr("This takes a while. You can keep using the live system.")
    }

    Card {
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            Text { text: page.current + (page.download ? "  " + page.download : ""); color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
            Text { text: Math.round(page.progress * 100) + "%"; color: Theme.accent; font.pixelSize: Theme.textLarge; font.weight: Font.Bold }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 10
            radius: 5
            color: Theme.surface2
            Accessible.role: Accessible.ProgressBar
            Accessible.name: qsTr("Installation progress")
            Rectangle {
                width: parent.width * page.progress
                height: parent.height
                radius: 5
                color: page.error ? Theme.danger : Theme.accent
                Behavior on width { NumberAnimation { duration: 300 } }
            }
        }
    }

    Notice { visible: page.error !== ""; Layout.fillWidth: true; kind: "danger"; title: qsTr("Error"); text: page.error }

    Card {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: page.steps
            RowLayout {
                required property var modelData
                readonly property string st: page.states[modelData.id] || "pending"
                spacing: 10
                Icon {
                    name: st === "done" ? "check-circle" : st === "failed" ? "x" : st === "warning" ? "alert" : st === "running" ? "refresh" : "clock"
                    size: 18
                    color: st === "done" ? Theme.success : st === "failed" ? Theme.danger : st === "warning" ? Theme.warning : st === "running" ? Theme.accent : Theme.muted
                    RotationAnimation on rotation { running: st === "running"; from: 0; to: 360; duration: 1200; loops: Animation.Infinite }
                }
                Text { text: modelData.label; color: st === "pending" ? Theme.muted : Theme.fg; font.pixelSize: Theme.text; font.weight: st === "running" ? Font.DemiBold : Font.Normal }
            }
        }
    }

    AppButton { text: page.showLog ? qsTr("Hide details") : qsTr("Show details"); iconName: "terminal"; onClicked: page.showLog = !page.showLog }
    LogView { id: log; visible: page.showLog; Layout.fillWidth: true; Layout.preferredHeight: 360 }
}
