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
    color: Qt.rgba(Qt.color(Theme.c.surface).r, Qt.color(Theme.c.surface).g, Qt.color(Theme.c.surface).b, 0.84)
    font.family: Theme.font

    Material.theme: Theme.dark ? Material.Dark : Material.Light
    Material.accent: Theme.c.primary
    Material.primary: Theme.c.primary
    Material.background: Theme.c.surface
    Material.foreground: Theme.c.onSurface

    // 0 write, 1 notes, 2 books, 3 reader
    property int page: 1

    function openFile(path) {
        if (path.toLowerCase().endsWith(".epub") || path.toLowerCase().endsWith(".epub-mxl")) {
            reader.open(path)
            page = 3
        } else if (path.toLowerCase().endsWith(".docx")) {
            const imported = Files.importDocx(path)
            if (imported.length) {
                const note = Files.newNote(Files.baseName(path))
                Files.write(note, imported)
                editor.open(note)
                page = 0
            }
        } else if (Files.chapters(path).length > 0) {
            reader.open(path)
            page = 3
        } else {
            editor.open(path)
            page = 0
        }
    }

    function movePage(delta) {
        const lastPage = reader.hasBook ? 3 : 2
        page = Math.max(0, Math.min(lastPage, page + delta))
    }

    function togglePreview() {
        editor.viewMode = editor.viewMode === 2 ? 1 : 2
        page = 0
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
        nameFilters: [qsTr("Documents and books (*.mdxl *.md *.txt *.docx *.epub *.epub-mxl)"), qsTr("All files (*)")]
        onAccepted: win.openFile(Files.toPath(selectedFile))
    }
    FileDialog {
        id: pdfExportDialog
        title: qsTr("Export PDF")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "pdf"
        nameFilters: [qsTr("PDF document (*.pdf)")]
        onAccepted: editor.exportPdf(Files.toPath(selectedFile))
    }
    FileDialog {
        id: docxExportDialog
        title: qsTr("Export Word document")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "docx"
        nameFilters: [qsTr("Word document (*.docx)")]
        onAccepted: editor.exportWord(Files.toPath(selectedFile))
    }
    // A book folder to an EPUB-MXL book (an EPUB with its MDXL sources inside).
    property string exportBook: ""
    function exportEpubMxl(bookDir) {
        exportBook = bookDir
        epubMxlDialog.selectedFile = Files.toUrl(Files.dirOf(bookDir) + "/" + Files.baseName(bookDir) + ".epub-mxl")
        epubMxlDialog.open()
    }
    FileDialog {
        id: epubMxlDialog
        title: qsTr("Export EPUB-MXL")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "epub-mxl"
        nameFilters: [qsTr("EPUB-MXL book (*.epub-mxl)"), qsTr("EPUB book (*.epub)")]
        onAccepted: {
            const error = Files.exportEpubMxl(win.exportBook, Files.toPath(selectedFile))
            exportNote.text = error.length ? error : qsTr("Exported %1").arg(Files.baseName(Files.toPath(selectedFile)))
            exportNote.open()
        }
    }
    ToolTip {
        id: exportNote
        timeout: 4000
        x: (win.width - width) / 2
        y: win.height - height - 32
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
    // Documents and editing
    Shortcut { sequence: "Ctrl+1"; onActivated: win.page = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.page = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.page = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: if (reader.hasBook) win.page = 3 }
    Shortcut { sequence: "Ctrl+E"; onActivated: editor.viewMode = (editor.viewMode + 1) % 4 }
    Shortcut { sequence: "Ctrl+Shift+E"; onActivated: win.togglePreview() }
    Shortcut { sequence: "Ctrl+PageDown"; onActivated: win.movePage(1) }
    Shortcut { sequence: "Ctrl+PageUp"; onActivated: win.movePage(-1) }
    Shortcut { sequence: "Left"; enabled: win.page === 3 && reader.hasBook; onActivated: reader.turnPage(-1) }
    Shortcut { sequence: "Right"; enabled: win.page === 3 && reader.hasBook; onActivated: reader.turnPage(1) }

    // Direct navigation aliases for one-handed use.
    Shortcut { sequence: "Ctrl+Alt+1"; onActivated: win.page = 0 }
    Shortcut { sequence: "Ctrl+Alt+2"; onActivated: win.page = 1 }
    Shortcut { sequence: "Ctrl+Alt+3"; onActivated: win.page = 2 }
    Shortcut { sequence: "Ctrl+Alt+4"; onActivated: if (reader.hasBook) win.page = 3 }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Navigation rail
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: 88
            color: Qt.rgba(Qt.color(Theme.c.surfaceContainer).r, Qt.color(Theme.c.surfaceContainer).g, Qt.color(Theme.c.surfaceContainer).b, 0.78)
            ColumnLayout {
                anchors.fill: parent
                anchors.topMargin: 16
                anchors.bottomMargin: 16
                spacing: 8
                RoundButton {
                    Layout.alignment: Qt.AlignHCenter
                    implicitWidth: 56
                    implicitHeight: 56
                    // M3 Expressive FAB: a rounded square that rounds fully while pressed.
                    radius: pressed ? 28 : 16
                    Behavior on radius { SpringAnimation { spring: 5; damping: 0.38 } }
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
            Editor { id: editor; onSaveAsRequested: saveAsDialog.open(); onExportRequested: docxExportDialog.open(); onPdfRequested: pdfExportDialog.open() }
            LibraryView { mode: "notes"; onOpenRequested: path => win.openFile(path) }
            LibraryView { id: books; mode: "books"; onOpenRequested: path => win.openFile(path); onOpenEpubRequested: openDialog.open(); onExportRequested: dir => win.exportEpubMxl(dir) }
            Reader { id: reader; onEditRequested: dir => { books.refresh(); books.selectedBook = dir; win.page = 2 } }
        }
    }
}
