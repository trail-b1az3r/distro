import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import Qt.labs.folderlistmodel
import Write

// Notes (a folder of MDXL files) or Books (book folders to write, EPUBs to read).
Item {
    id: root
    property string mode: "notes"
    signal openRequested(string path)
    signal openEpubRequested()

    property var bookDirs: Files.books()
    property string selectedBook: ""
    property var chapterList: selectedBook ? Files.chapters(selectedBook) : []
    function refresh() {
        bookDirs = Files.books()
        chapterList = selectedBook ? Files.chapters(selectedBook) : []
    }
    onVisibleChanged: if (visible) refresh()

    component Card: Rectangle {
        id: card
        property string heading
        property string detail
        property bool selected: false
        signal clicked()
        implicitHeight: 64
        radius: 16
        color: selected ? Theme.c.secondaryContainer : Theme.c.surfaceContainerLow
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.c.onSurface
            opacity: mouse.containsMouse && !card.selected ? 0.06 : 0
        }
        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: 2
            Label {
                Layout.fillWidth: true
                text: card.heading
                font.pixelSize: 16
                font.weight: Font.Medium
                elide: Text.ElideRight
                color: card.selected ? Theme.c.onSecondaryContainer : Theme.c.onSurface
            }
            Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: card.detail
                font.pixelSize: 12
                elide: Text.ElideRight
                color: Theme.c.onSurfaceVariant
            }
        }
        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: card.clicked()
        }
    }

    component Heading: Label {
        font.pixelSize: 26
        font.weight: Font.DemiBold
        color: Theme.c.onSurface
    }

    // ---- Notes -------------------------------------------------------------
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16
        visible: root.mode === "notes"

        RowLayout {
            Layout.fillWidth: true
            Heading { Layout.fillWidth: true; text: qsTr("Notes") }
            TextField {
                id: search
                Layout.preferredWidth: 280
                placeholderText: qsTr("Search notes")
            }
            Button {
                text: qsTr("New note")
                highlighted: true
                onClicked: root.openRequested(Files.newNote(search.text || qsTr("New note")))
            }
        }
        ListView {
            id: notes
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: FolderListModel {
                folder: Files.toUrl(Files.notesDir)
                nameFilters: ["*.mdxl", "*.md", "*.txt"]
                sortField: FolderListModel.Time
                showDirs: false
            }
            delegate: Card {
                required property string fileName
                required property string filePath
                required property date fileModified
                readonly property bool match: search.text === ""
                    || fileName.toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                width: ListView.view.width
                visible: match
                height: match ? implicitHeight : 0
                heading: Files.baseName(fileName)
                detail: Qt.formatDateTime(fileModified, "d MMM yyyy, hh:mm")
                onClicked: root.openRequested(filePath)
            }
            Label {
                anchors.centerIn: parent
                visible: notes.count === 0
                text: qsTr("No notes yet. They are kept in %1.").arg(Files.notesDir)
                color: Theme.c.onSurfaceVariant
            }
        }
    }

    // ---- Books -------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 24
        visible: root.mode === "books"

        // Books being written
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 3
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { Layout.fillWidth: true; text: qsTr("Writing") }
                TextField { id: bookTitle; Layout.preferredWidth: 220; placeholderText: qsTr("New book title") }
                Button {
                    text: qsTr("New book")
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
                spacing: 16
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: root.bookDirs
                    delegate: Card {
                        required property string modelData
                        width: ListView.view.width
                        heading: Files.baseName(modelData)
                        detail: qsTr("%n chapter(s)", "", Files.chapters(modelData).length)
                        selected: root.selectedBook === modelData
                        onClicked: root.selectedBook = modelData
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: root.bookDirs.length === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("A book is a folder of MDXL chapters in %1.").arg(Files.booksDir)
                        color: Theme.c.onSurfaceVariant
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: root.selectedBook !== ""
                    spacing: 8
                    RowLayout {
                        Label {
                            Layout.fillWidth: true
                            text: Files.baseName(root.selectedBook)
                            font.pixelSize: 18
                            font.weight: Font.Medium
                            elide: Text.ElideRight
                            color: Theme.c.onSurface
                        }
                        Button {
                            text: qsTr("New chapter")
                            flat: true
                            onClicked: {
                                const p = Files.newChapter(root.selectedBook, qsTr("New chapter"))
                                root.refresh()
                                root.openRequested(p)
                            }
                        }
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: root.chapterList
                        delegate: Card {
                            required property string modelData
                            width: ListView.view.width
                            implicitHeight: 48
                            heading: Files.baseName(modelData)
                            onClicked: root.openRequested(modelData)
                        }
                    }
                }
            }
        }

        // Books to read
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 2
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { Layout.fillWidth: true; text: qsTr("Reading") }
                Button { text: qsTr("Open EPUB…"); onClicked: root.openEpubRequested() }
            }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: Files.recentBooks
                delegate: Card {
                    required property var modelData
                    width: ListView.view.width
                    heading: modelData.title
                    detail: Files.baseName(modelData.path)
                    onClicked: root.openRequested(modelData.path)
                }
                Label {
                    anchors.centerIn: parent
                    visible: Files.recentBooks.length === 0
                    text: qsTr("EPUB books you open appear here.")
                    color: Theme.c.onSurfaceVariant
                }
            }
        }
    }
}
