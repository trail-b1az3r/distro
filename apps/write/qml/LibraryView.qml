import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import Qt.labs.folderlistmodel
import Write

// Tile-based Notes and Books library.
Item {
    id: root
    property string mode: "notes"
    signal openRequested(string path)
    signal openEpubRequested()
    signal exportRequested(string bookDir)
    property var bookDirs: Files.books()
    property string selectedBook: ""
    property var chapterList: selectedBook ? Files.chapters(selectedBook) : []
    function refresh() {
        bookDirs = Files.books()
        chapterList = selectedBook ? Files.chapters(selectedBook) : []
    }
    onVisibleChanged: if (visible) refresh()

    component Tile: Rectangle {
        id: tile
        property string heading
        property string detail
        property bool selected: false
        property string glyph: "▤"
        signal clicked()
        implicitHeight: 116
        radius: 22
        color: selected ? Theme.c.secondaryContainer
            : Qt.rgba(Qt.color(Theme.c.surfaceContainerLow).r,
                      Qt.color(Theme.c.surfaceContainerLow).g,
                      Qt.color(Theme.c.surfaceContainerLow).b, 0.82)
        border.width: selected ? 1 : 0
        border.color: Theme.c.primary
        Behavior on color { ColorAnimation { duration: 160 } }
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.c.onSurface
            opacity: mouse.containsMouse && !tile.selected ? 0.055 : 0
        }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8
            Label {
                text: tile.glyph
                font.pixelSize: 23
                color: tile.selected ? Theme.c.onSecondaryContainer : Theme.c.primary
            }
            Label {
                Layout.fillWidth: true
                text: tile.heading
                font.pixelSize: 15
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                color: tile.selected ? Theme.c.onSecondaryContainer : Theme.c.onSurface
            }
            Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: tile.detail
                font.pixelSize: 11
                elide: Text.ElideRight
                color: Theme.c.onSurfaceVariant
            }
        }
        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tile.clicked()
        }
    }

    component Heading: Label {
        font.pixelSize: 28
        font.weight: Font.DemiBold
        color: Theme.c.onSurface
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16
        visible: root.mode === "notes"
        RowLayout {
            Layout.fillWidth: true
            Heading { Layout.fillWidth: true; text: qsTr("Notes") }
            TextField { id: search; Layout.preferredWidth: 280; placeholderText: qsTr("Search notes") }
            Button {
                text: qsTr("New note")
                highlighted: true
                onClicked: root.openRequested(Files.newNote(search.text || qsTr("New note")))
            }
        }
        GridView {
            id: notes
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            cellWidth: 252
            cellHeight: 132
            model: FolderListModel {
                folder: Files.toUrl(Files.notesDir)
                nameFilters: ["*.mdxl", "*.md", "*.txt"]
                sortField: FolderListModel.Time
                showDirs: false
            }
            delegate: Tile {
                required property string fileName
                required property string filePath
                required property date fileModified
                readonly property bool match: search.text === ""
                    || fileName.toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                width: notes.cellWidth - 12
                height: match ? 116 : 0
                visible: match
                heading: Files.baseName(fileName)
                detail: Qt.formatDateTime(fileModified, "d MMM yyyy, hh:mm")
                glyph: "▤"
                onClicked: root.openRequested(filePath)
            }
            Label {
                anchors.centerIn: parent
                visible: notes.count === 0
                text: qsTr("No notes yet. Create one to get started.")
                color: Theme.c.onSurfaceVariant
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 20
        visible: root.mode === "books"

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 3
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { Layout.fillWidth: true; text: qsTr("Your books") }
                TextField { id: bookTitle; Layout.preferredWidth: 210; placeholderText: qsTr("New book title") }
                Button {
                    text: qsTr("Create")
                    highlighted: true
                    onClicked: {
                        root.selectedBook = Files.newBook(bookTitle.text || qsTr("Untitled book"))
                        bookTitle.text = ""
                        root.refresh()
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14
                GridView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    cellWidth: 232
                    cellHeight: 132
                    clip: true
                    model: root.bookDirs
                    delegate: Tile {
                        required property string modelData
                        width: parent ? 220 : 220
                        heading: Files.baseName(modelData)
                        detail: qsTr("%n chapter(s)", "", Files.chapters(modelData).length)
                        glyph: "▣"
                        selected: root.selectedBook === modelData
                        onClicked: root.selectedBook = modelData
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: root.bookDirs.length === 0
                        text: qsTr("Your MDXL books will appear here.")
                        color: Theme.c.onSurfaceVariant
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 240
                    Layout.fillHeight: true
                    visible: root.selectedBook !== ""
                    spacing: 8
                    Label {
                        Layout.fillWidth: true
                        text: Files.baseName(root.selectedBook)
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                        color: Theme.c.onSurface
                        elide: Text.ElideRight
                    }
                    Button {
                        Layout.fillWidth: true
                        text: qsTr("Read book")
                        highlighted: true
                        onClicked: root.openRequested(root.selectedBook)
                    }
                    Button {
                        Layout.fillWidth: true
                        text: qsTr("Export EPUB-MXL…")
                        ToolTip.visible: hovered
                        ToolTip.text: qsTr("An EPUB any reader opens, with the MDXL chapters inside so Write can edit it again")
                        onClicked: root.exportRequested(root.selectedBook)
                    }
                    Button {
                        Layout.fillWidth: true
                        text: qsTr("New chapter")
                        onClicked: {
                            const p = Files.newChapter(root.selectedBook, qsTr("New chapter"))
                            root.refresh()
                            root.openRequested(p)
                        }
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 4
                        model: root.chapterList
                        delegate: ItemDelegate {
                            required property string modelData
                            width: ListView.view.width
                            text: Files.baseName(modelData)
                            onClicked: root.openRequested(modelData)
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 2
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { Layout.fillWidth: true; text: qsTr("Continue reading") }
                Button { text: qsTr("Open EPUB…"); onClicked: root.openEpubRequested() }
            }
            GridView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                cellWidth: 232
                cellHeight: 132
                model: Files.recentBooks
                delegate: Tile {
                    required property var modelData
                    width: 220
                    heading: modelData.title
                    detail: Files.baseName(modelData.path)
                    glyph: "▣"
                    onClicked: root.openRequested(modelData.path)
                }
                Label {
                    anchors.centerIn: parent
                    visible: Files.recentBooks.length === 0
                    text: qsTr("Recently opened books appear here.")
                    color: Theme.c.onSurfaceVariant
                }
            }
        }
    }
}
