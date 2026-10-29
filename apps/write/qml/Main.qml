import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import Write

ApplicationWindow {
    id: win
    width: 1280
    height: 820
    minimumWidth: 720
    minimumHeight: 480
    visible: true
    title: (page === 3 && reader.bookTitle ? reader.bookTitle
            : editor.path ? Files.baseName(editor.path) + (editor.modified ? " •" : "") : "") + " — " + appName
    color: Theme.c.surface
    font.family: Theme.font

    Material.theme: Theme.dark ? Material.Dark : Material.Light
    Material.accent: Theme.c.primary
    Material.primary: Theme.c.primary
    Material.background: Theme.c.surface
    Material.foreground: Theme.c.onSurface

    // 0 write, 1 notes, 2 books, 3 reader
    property int page: 1

    function openFile(path) {
        if (path.toLowerCase().endsWith(".epub")) {
            reader.open(path)
            page = 3
        } else {
            editor.open(path)
            page = 0
        }
    }

    Component.onCompleted: {
        for (const f of startupFiles)
            openFile(f)
    }
    onClosing: editor.saveNow()

    Timer {
        running: selfTest
        interval: 4000
        onTriggered: {
            console.log("SELFTEST " + JSON.stringify({
                theme: Theme.fromDesktop ? "desktop" : "fallback",
                book: reader.bookTitle, chapters: reader.chapterCount,
                document: editor.path, syntax: editor.syntax,
                rendered: editor.renderedLength, renderError: editor.renderError
            }))
            Qt.exit(0)
        }
    }

    FileDialog {
        id: openDialog
        title: qsTr("Open")
        nameFilters: [qsTr("Documents and books (*.mdxl *.md *.txt *.epub)"), qsTr("All files (*)")]
        onAccepted: win.openFile(Files.toPath(selectedFile))
    }
    FileDialog {
        id: saveAsDialog
        title: qsTr("Save as")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "mdxl"
        nameFilters: [qsTr("MDXL (*.mdxl)"), qsTr("Markdown (*.md)"), qsTr("Text (*.txt)")]
        onAccepted: editor.saveAs(Files.toPath(selectedFile))
    }

    Shortcut { sequences: [StandardKey.Open]; onActivated: openDialog.open() }
    Shortcut { sequences: [StandardKey.Save]; onActivated: editor.saveNow() }
    Shortcut { sequences: [StandardKey.SaveAs]; onActivated: saveAsDialog.open() }
    Shortcut { sequences: [StandardKey.New]; onActivated: win.openFile(Files.newNote(qsTr("New note"))) }
    Shortcut { sequence: "Ctrl+1"; onActivated: win.page = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.page = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.page = 2 }
    Shortcut { sequence: "Ctrl+E"; onActivated: editor.viewMode = (editor.viewMode + 1) % 3 }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Navigation rail
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: 88
            color: Theme.c.surfaceContainer
            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 16
                anchors.bottomMargin: 16
                spacing: 8
                RoundButton {
                    Layout.alignment: Qt.AlignHCenter
                    implicitWidth: 56
                    implicitHeight: 56
                    radius: 16
                    text: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "edit_square" : "+"
                    font.family: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "Material Symbols Rounded" : Theme.font
                    font.pixelSize: 24
                    Material.background: Theme.c.primaryContainer
                    Material.foreground: Theme.c.onPrimaryContainer
                    ToolTip.visible: hovered
                    ToolTip.text: qsTr("New note (Ctrl+N)")
                    onClicked: win.openFile(Files.newNote(qsTr("New note")))
                }
                Item { implicitHeight: 12 }
                RailButton { Layout.alignment: Qt.AlignHCenter; text: qsTr("Write"); symbol: "edit_note"; selected: win.page === 0; onClicked: win.page = 0 }
                RailButton { Layout.alignment: Qt.AlignHCenter; text: qsTr("Notes"); symbol: "sticky_note_2"; selected: win.page === 1; onClicked: win.page = 1 }
                RailButton { Layout.alignment: Qt.AlignHCenter; text: qsTr("Books"); symbol: "auto_stories"; selected: win.page === 2; onClicked: win.page = 2 }
                RailButton {
                    Layout.alignment: Qt.AlignHCenter
                    visible: reader.hasBook
                    text: qsTr("Reading")
                    symbol: "menu_book"
                    selected: win.page === 3
                    onClicked: win.page = 3
                }
                Item { Layout.fillHeight: true }
                RailButton { Layout.alignment: Qt.AlignHCenter; text: qsTr("Open"); symbol: "folder_open"; onClicked: openDialog.open() }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: win.page
            Editor { id: editor; onSaveAsRequested: saveAsDialog.open() }
            LibraryView { mode: "notes"; onOpenRequested: path => win.openFile(path) }
            LibraryView { mode: "books"; onOpenRequested: path => win.openFile(path); onOpenEpubRequested: openDialog.open() }
            Reader { id: reader }
        }
    }
}
