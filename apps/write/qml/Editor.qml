import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtWebEngine
import Write

// MDXL editor with a Material-inspired command ribbon and page preview.
Item {
    id: root
    property string path: ""
    property bool modified: false
    property int viewMode: 1   // 0 edit, 1 both, 2 preview, 3 document page
    property bool loading: false
    readonly property bool documentMode: viewMode === 3
    readonly property int renderedLength: renderer.html.length
    readonly property string syntax: highlighter.definition
    readonly property string renderError: renderer.error
    signal saveAsRequested()
    signal exportRequested()
    signal pdfRequested()

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

    function exportWord(p) {
        exportError.text = Files.exportDocx(p, area.text)
                    ? qsTr("Exported Word document.")
                    : qsTr("Could not export this document.")
    }

    function exportPdf(p) {
        preview.printToPdf(p)
        exportError.text = qsTr("PDF export started.")
    }

    function sendEmail() {
        const url = "mailto:" + emailTo.text.trim()
            + "?subject=" + encodeURIComponent(emailSubject.text)
            + "&body=" + encodeURIComponent(emailBody.text)
        Qt.openUrlExternally(url)
        emailDialog.close()
    }

    function acceptChanges() {
        area.text = area.text.replace(/<ins>([\s\S]*?)<\/ins>/g, "$1")
                             .replace(/<del>[\s\S]*?<\/del>/g, "")
    }

    function rejectChanges() {
        area.text = area.text.replace(/<del>([\s\S]*?)<\/del>/g, "$1")
                             .replace(/<ins>[\s\S]*?<\/ins>/g, "")
    }

    function addComment(value) {
        const start = area.selectionStart >= 0 ? area.selectionStart : area.cursorPosition
        const end = area.selectionStart >= 0 ? area.selectionEnd : start
        if (end > start) {
            const selected = area.text.slice(start, end)
            area.remove(start, end)
            area.insert(start, "<mark>" + selected + "</mark>")
        }
        area.insert(area.text.length, "\n<!-- WRITE_COMMENT:" + value.replace(/-->/g, "") + " -->\n")
        area.forceActiveFocus()
    }

    function wrapSelection(before, after) {
        const start = area.selectionStart >= 0 ? area.selectionStart : area.cursorPosition
        const end = area.selectionStart >= 0 ? area.selectionEnd : start
        const selected = area.selectedText || qsTr("text")
        area.remove(start, end)
        area.insert(start, before + selected + after)
        area.select(start + before.length, start + before.length + selected.length)
        area.forceActiveFocus()
    }

    function prefixLine(prefix) {
        const lineStart = area.text.lastIndexOf("\n", Math.max(0, area.cursorPosition - 1)) + 1
        area.insert(lineStart, prefix)
        area.forceActiveFocus()
    }

    function insertAtCursor(value) {
        area.insert(area.cursorPosition, value)
        area.forceActiveFocus()
    }

    onDocumentModeChanged: renderer.render(area.text, true)

    Timer { id: autosave; interval: 1500; onTriggered: root.saveNow() }

    Dialog {
        id: headerDialog
        title: qsTr("Document header")
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: TextField { id: headerText; placeholderText: qsTr("Text shown at the top of the document") }
        onAccepted: root.insertAtCursor("\n<!-- WRITE_HEADER:" + headerText.text.replace(/-->/g, "") + " -->\n")
    }
    Dialog {
        id: footerDialog
        title: qsTr("Document footer")
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: TextField { id: footerText; placeholderText: qsTr("Text shown at the bottom of the document") }
        onAccepted: root.insertAtCursor("\n<!-- WRITE_FOOTER:" + footerText.text.replace(/-->/g, "") + " -->\n")
    }
    Dialog {
        id: commentDialog
        title: qsTr("Add comment")
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: TextField { id: commentText; placeholderText: qsTr("Write a review comment") }
        onAccepted: if (commentText.text.trim().length)
                        root.insertAtCursor("\n<!-- WRITE_COMMENT:" + commentText.text.replace(/-->/g, "") + " -->\n")
    }
    Dialog {
        id: emailDialog
        title: qsTr("Send document by email")
        standardButtons: Dialog.Cancel
        modal: true
        contentItem: ColumnLayout {
            width: 420
            TextField { id: emailTo; Layout.fillWidth: true; placeholderText: qsTr("Recipient email address") }
            TextField { id: emailSubject; Layout.fillWidth: true; text: root.path ? Files.baseName(root.path) : ""; placeholderText: qsTr("Subject") }
            TextArea { id: emailBody; Layout.fillWidth: true; Layout.preferredHeight: 140; wrapMode: TextEdit.Wrap; text: qsTr("Please find the document below.\n\n") + area.text }
            Button {
                Layout.alignment: Qt.AlignRight
                text: qsTr("Send with Betterbird")
                enabled: Files.betterbirdInstalled() && emailTo.text.trim().length > 0
                onClicked: root.sendEmail()
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: Files.betterbirdInstalled() ? qsTr("Opens a message in Betterbird; review and send it there.")
                                                  : qsTr("Install Betterbird to enable email sending.")
                color: Theme.c.onSurfaceVariant
            }
        }
    }

    Highlighter {
        id: highlighter
        document: area.textDocument
        dark: Theme.dark
        fileName: root.path
    }

    MdxlRenderer {
        id: renderer
        css: root.documentMode
             ? Theme.css(1.0) + "@page{size:A4;margin:0}body{box-sizing:border-box!important;width:794px!important;min-height:1123px!important;margin:28px auto!important;padding:76px 82px!important;background:#fff!important;color:#202124!important;box-shadow:0 8px 36px #0003!important;line-height:1.75!important}.write-page-break{break-before:page;page-break-before:always;height:1px}body a{color:#315fba!important}@media(max-width:900px){body{padding:32px 24px!important;margin:8px!important}}"
             : Theme.css(1.0)
        onHtmlChanged: if (html) preview.loadHtml(html, Files.toUrl(Files.dirOf(root.path) + "/"))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 12
            Layout.leftMargin: 20
            spacing: 8
            Label {
                Layout.fillWidth: true
                text: root.path ? Files.baseName(root.path) : qsTr("Nothing open")
                font.pixelSize: 22
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                color: Theme.c.onSurface
            }
            Repeater {
                model: [qsTr("Edit"), qsTr("Both"), qsTr("Preview"), qsTr("Document")]
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
                text: qsTr("Export PDF")
                flat: true
                enabled: root.path !== ""
                onClicked: root.pdfRequested()
            }
            Button {
                text: qsTr("Export DOCX")
                flat: true
                enabled: root.path !== ""
                onClicked: root.exportRequested()
            }
            Button {
                text: qsTr("Save")
                flat: true
                enabled: root.path !== ""
                onClicked: root.saveNow()
            }
            Button {
                text: qsTr("Save as…")
                flat: true
                enabled: root.path !== ""
                onClicked: root.saveAsRequested()
            }
        }

        // Formatting commands use MDXL, so documents remain portable and
        // render identically in the MDXL previewer and other compatible apps.
        Flickable {
            Layout.fillWidth: true
            implicitHeight: 48
            contentWidth: ribbon.implicitWidth
            clip: true
            visible: root.path !== "" && root.viewMode !== 2 && root.viewMode !== 3
            RowLayout {
                id: ribbon
                height: 44
                spacing: 2
                ToolButton { text: qsTr("Heading"); onClicked: root.prefixLine("## ") }
                ToolButton { text: qsTr("Bold"); onClicked: root.wrapSelection("**", "**") }
                ToolButton { text: qsTr("Italic"); onClicked: root.wrapSelection("*", "*") }
                ToolButton { text: qsTr("Strike"); onClicked: root.wrapSelection("~~", "~~") }
                ToolButton { text: qsTr("Link"); onClicked: root.wrapSelection("[", "](https://)") }
                ToolButton { text: qsTr("Image"); enabled: root.path !== ""; onClicked: imageDialog.open() }
                ToolButton { text: qsTr("Color"); onClicked: root.insertAtCursor("/col//Colored text /col#B7F77A//") }
                ToolButton { text: qsTr("Quote"); onClicked: root.prefixLine("> ") }
                ToolButton { text: qsTr("Bullets"); onClicked: root.prefixLine("- ") }
                ToolButton { text: qsTr("Numbered"); onClicked: root.prefixLine("1. ") }
                ToolButton { text: qsTr("Checklist"); onClicked: root.prefixLine("- [ ] ") }
                ToolButton { text: qsTr("Inline code"); onClicked: root.wrapSelection("`", "`") }
                ToolButton { text: qsTr("Code block"); onClicked: root.insertAtCursor("\n\n```\n\n```\n") }
                ToolButton { text: qsTr("Table"); onClicked: root.insertAtCursor("\n| Column 1 | Column 2 |\n| --- | --- |\n| | |\n") }
                ToolButton { text: qsTr("Page break"); onClicked: root.insertAtCursor("\n\n<!-- WRITE_PAGE_BREAK -->\n\n") }
                ToolButton { text: qsTr("Header"); onClicked: headerDialog.open() }
                ToolButton { text: qsTr("Footer"); onClicked: footerDialog.open() }
                ToolButton { text: qsTr("Comment"); onClicked: commentDialog.open() }
                ToolButton { text: qsTr("Track insertion"); onClicked: root.wrapSelection("<ins>", "</ins>") }
                ToolButton { text: qsTr("Track deletion"); onClicked: root.wrapSelection("<del>", "</del>") }
                ToolButton { text: qsTr("Accept changes"); onClicked: root.acceptChanges() }
                ToolButton { text: qsTr("Reject changes"); onClicked: root.rejectChanges() }
                ToolButton { text: qsTr("Email"); enabled: Files.betterbirdInstalled(); onClicked: emailDialog.open() }
                ToolButton { text: qsTr("Undo"); onClicked: area.undo() }
                ToolButton { text: qsTr("Redo"); onClicked: area.redo() }
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.path !== ""

            Rectangle {
                SplitView.fillWidth: root.viewMode === 0
                SplitView.preferredWidth: parent.width / 2
                visible: root.viewMode !== 2 && root.viewMode !== 3
                color: Qt.rgba(Qt.color(Theme.c.surfaceContainerLow).r, Qt.color(Theme.c.surfaceContainerLow).g, Qt.color(Theme.c.surfaceContainerLow).b, 0.80)
                radius: 28
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
                color: Qt.rgba(Qt.color(root.documentMode ? Theme.c.surfaceContainer : Theme.c.surface).r, Qt.color(root.documentMode ? Theme.c.surfaceContainer : Theme.c.surface).g, Qt.color(root.documentMode ? Theme.c.surfaceContainer : Theme.c.surface).b, 0.78)
                radius: 28
                clip: true
                WebEngineView {
                    id: preview
                    anchors.fill: parent
                    anchors.margins: 4
                    backgroundColor: Theme.c.surface
                    onNavigationRequested: function(request) {
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
            Label { text: root.documentMode ? qsTr("Document layout") : ""; color: Theme.c.onSurfaceVariant }
            Label {
                id: exportError
                text: ""
                color: Theme.c.primary
            }
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
