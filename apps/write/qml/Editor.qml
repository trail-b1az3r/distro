import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtWebEngine
import Write

// The writing view: the MDXL source with syntax colours, and its live
// preview rendered by MDXL itself. Saved automatically while typing.
Item {
    id: root
    property string path: ""
    property bool modified: false
    property int viewMode: 1   // 0 edit, 1 edit and preview, 2 preview
    property bool loading: false
    readonly property int renderedLength: renderer.html.length
    readonly property string syntax: highlighter.definition
    readonly property string renderError: renderer.error
    signal saveAsRequested()

    function open(p) {
        saveNow()
        loading = true
        path = p
        area.text = Files.read(p)
        area.cursorPosition = 0
        loading = false
        modified = false
        renderer.render(area.text, true)
        area.forceActiveFocus()
    }
    function saveNow() {
        if (path && modified && Files.write(path, area.text))
            modified = false
    }
    function saveAs(p) {
        if (Files.write(p, area.text)) {
            path = p
            modified = false
        }
    }

    Timer { id: autosave; interval: 1500; onTriggered: root.saveNow() }

    Highlighter {
        id: highlighter
        document: area.textDocument
        dark: Theme.dark
        fileName: root.path
    }
    MdxlRenderer {
        id: renderer
        css: Theme.css(1.0)
        onHtmlChanged: if (html) preview.loadHtml(html, Files.toUrl(Files.dirOf(root.path) + "/"))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Title and view mode
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            Layout.leftMargin: 20
            spacing: 12
            Label {
                Layout.fillWidth: true
                text: root.path ? Files.baseName(root.path) : qsTr("Nothing open")
                font.pixelSize: 22
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                color: Theme.c.onSurface
            }
            Repeater {
                model: [qsTr("Edit"), qsTr("Both"), qsTr("Preview")]
                delegate: Button {
                    required property int index
                    required property string modelData
                    text: modelData
                    flat: root.viewMode !== index
                    highlighted: root.viewMode === index
                    onClicked: root.viewMode = index
                }
            }
            Button {
                text: qsTr("Save as…")
                flat: true
                enabled: root.path !== ""
                onClicked: root.saveAsRequested()
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.path !== ""

            Rectangle {
                SplitView.fillWidth: root.viewMode === 0
                SplitView.preferredWidth: parent.width / 2
                visible: root.viewMode !== 2
                color: Theme.c.surfaceContainerLow
                radius: 16
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 4
                    TextArea {
                        id: area
                        wrapMode: TextArea.Wrap
                        textFormat: TextEdit.PlainText
                        font.family: Theme.mono
                        font.pixelSize: 15
                        color: Theme.c.onSurface
                        selectionColor: Theme.c.primaryContainer
                        selectedTextColor: Theme.c.onPrimaryContainer
                        leftPadding: 24
                        rightPadding: 24
                        topPadding: 20
                        bottomPadding: 20
                        background: null
                        placeholderText: qsTr("Write in MDXL…")
                        onTextChanged: {
                            if (root.loading)
                                return
                            root.modified = true
                            autosave.restart()
                            renderer.render(text)
                        }
                    }
                }
            }

            Rectangle {
                SplitView.fillWidth: true
                visible: root.viewMode !== 0
                color: Theme.c.surface
                radius: 16
                clip: true
                WebEngineView {
                    id: preview
                    anchors.fill: parent
                    anchors.margins: 4
                    backgroundColor: Theme.c.surface
                    onNavigationRequested: function(request) {
                        // Links leave for the browser; the preview stays put.
                        if (request.navigationType === WebEngineNavigationRequest.LinkClickedNavigation) {
                            Qt.openUrlExternally(request.url)
                            request.reject()
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.path === ""
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: qsTr("Start a note with the pencil button, or open one from Notes or Books.")
            color: Theme.c.onSurfaceVariant
        }

        // Status bar
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.topMargin: 6
            Layout.bottomMargin: 8
            spacing: 18
            visible: root.path !== ""
            Label { text: qsTr("%1 words").arg(Files.words(area.text)); color: Theme.c.onSurfaceVariant }
            Label { text: qsTr("%1 characters").arg(area.length); color: Theme.c.onSurfaceVariant }
            Label { text: highlighter.definition; color: Theme.c.onSurfaceVariant }
            Label {
                Layout.fillWidth: true
                text: renderer.error
                color: Theme.c.error
                elide: Text.ElideRight
            }
            Label { text: root.modified ? qsTr("Saving…") : qsTr("Saved"); color: Theme.c.onSurfaceVariant }
        }
    }
}
