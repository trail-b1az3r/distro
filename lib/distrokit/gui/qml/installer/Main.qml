import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ApplicationWindow {
    id: win
    width: 1180
    height: 800
    minimumWidth: 720
    minimumHeight: 560
    visible: true
    title: qsTr("Install %1").arg(brandInfo.prettyName)
    color: Theme.bg

    property int page: 0
    property var issues: []
    property string toast: ""
    // Lets tests and command-line options pick the colour scheme.
    property string themeMode: "system"
    onThemeModeChanged: Theme.mode = themeMode
    readonly property var pageIds: installer.pages
    readonly property string pageId: pageIds[page]
    readonly property bool wide: width >= 980
    readonly property bool locked: pageId === "install" || pageId === "done"
    readonly property var titles: ({
        welcome: qsTr("Welcome"), language: qsTr("Language & Region"), keyboard: qsTr("Keyboard"),
        network: qsTr("Internet"), hardware: qsTr("Hardware"), disk: qsTr("Disk"),
        profile: qsTr("Installation Profile"), desktop: qsTr("Desktop"), gpu: qsTr("Graphics"),
        kernel: qsTr("Laptop / Tablet Kernel"), ai: qsTr("AI Assistant"), model: qsTr("AI Model"),
        user: qsTr("User Account"), summary: qsTr("Summary"), install: qsTr("Install"), done: qsTr("Finished")
    })
    readonly property var stepModel: pageIds.map(id => ({ title: titles[id] }))

    function validateCurrent() {
        issues = installer.validate(pageId)
        return issues.filter(i => i.severity === "error").length === 0
    }
    function next() {
        if (locked) return
        if (!validateCurrent()) return
        if (pageIds[page + 1] === "summary") installer.prepareSummary()
        if (page < pageIds.length - 1) { page += 1; issues = [] }
    }
    function back() {
        if (locked || page === 0) return
        page -= 1
        issues = []
    }
    function goTo(index) { if (!locked && index < page) { page = index; issues = [] } }

    Shortcut { sequences: ["Alt+Right", "Ctrl+Return"]; onActivated: win.next() }
    Shortcut { sequence: "Alt+Left"; onActivated: win.back() }

    Connections {
        target: installer
        function onMessage(text) { win.toast = text; toastTimer.restart() }
        function onEngineEvent(e) { if (e.type === "done") win.page = win.pageIds.indexOf("done") }
    }
    Timer { id: toastTimer; interval: 5000; onTriggered: win.toast = "" }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Sidebar ---------------------------------------------------------
        Rectangle {
            visible: win.wide
            Layout.preferredWidth: 272
            Layout.fillHeight: true
            color: Theme.surface
            border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 18
                RowLayout {
                    spacing: 12
                    Image { source: brandInfo.logo; sourceSize: Qt.size(40, 40); Layout.preferredWidth: 40; Layout.preferredHeight: 40 }
                    ColumnLayout {
                        spacing: 0
                        Text { text: brandInfo.prettyName; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.Bold }
                        Text { text: qsTr("Installer"); color: Theme.muted; font.pixelSize: Theme.textSmall }
                    }
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    StepList {
                        width: 232
                        steps: win.stepModel
                        current: win.page
                        onJump: (i) => win.goTo(i)
                    }
                }
                ThemeSwitch { Layout.alignment: Qt.AlignLeft }
            }
        }

        // Main area -------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Compact progress header for narrow windows.
            Rectangle {
                visible: !win.wide
                Layout.fillWidth: true
                implicitHeight: 64
                color: Theme.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    Image { source: brandInfo.logo; sourceSize: Qt.size(28, 28) }
                    Text {
                        text: qsTr("Step %1 of %2 — %3").arg(win.page + 1).arg(win.pageIds.length).arg(win.titles[win.pageId])
                        color: Theme.fg; font.pixelSize: Theme.text; font.weight: Font.DemiBold
                        Layout.fillWidth: true; elide: Text.ElideRight
                    }
                    ThemeSwitch {}
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    height: 3
                    width: parent.width * (win.page + 1) / win.pageIds.length
                    color: Theme.accent
                    Behavior on width { NumberAnimation { duration: Theme.animation } }
                }
            }

            ScrollView {
                id: scroller
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                Item {
                    width: scroller.availableWidth
                    implicitHeight: pageLoader.implicitHeight + 64
                    Loader {
                        id: pageLoader
                        x: Math.max(24, (parent.width - width) / 2)
                        y: 32
                        width: Math.min(parent.width - 48, 920)
                        source: "pages/" + win.pageId.charAt(0).toUpperCase() + win.pageId.slice(1) + "Page.qml"
                        onLoaded: scroller.ScrollBar.vertical.position = 0
                    }
                }
            }

            // Validation messages
            ColumnLayout {
                visible: win.issues.length > 0
                Layout.fillWidth: true
                Layout.leftMargin: 24; Layout.rightMargin: 24
                spacing: 6
                Repeater {
                    model: win.issues
                    Notice {
                        required property var modelData
                        Layout.fillWidth: true
                        kind: modelData.severity === "error" ? "danger" : "warning"
                        text: modelData.message
                    }
                }
            }
            Notice {
                visible: win.toast !== ""
                Layout.fillWidth: true
                Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.topMargin: 6
                text: win.toast
            }

            // Navigation bar
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 76
                color: Theme.surface
                border.color: Theme.border
                visible: !win.locked
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 24; anchors.rightMargin: 24
                    spacing: 12
                    AppButton {
                        text: qsTr("Back")
                        iconName: "arrow-left"
                        enabled: win.page > 0
                        onClicked: win.back()
                    }
                    Item { Layout.fillWidth: true }
                    Badge { visible: installer.isDemo; text: qsTr("DEMO — disks are never changed"); color: Theme.warning }
                    AppButton {
                        visible: win.pageId !== "summary"
                        kind: "primary"
                        text: qsTr("Next")
                        iconName: "arrow-right"
                        onClicked: win.next()
                    }
                }
            }
        }
    }
}
