import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtWebEngine
import Write

// Book mode: an EPUB, a chapter at a time, in the theme's colours.
Item {
    id: root
    readonly property bool hasBook: book.count > 0
    readonly property string bookTitle: book.title
    readonly property int chapterCount: book.count
    property real textScale: 1.1
    property bool contents: true

    function open(path) {
        book.path = path
        if (book.count > 0)
            Files.addRecentBook(path, book.title)
    }
    function restyle() {
        const css = Theme.css(textScale)
            + "body{max-width:42em;margin:0 auto!important;padding:2.5em 2em!important}"
        view.runJavaScript("(function(){var s=document.getElementById('write-theme')"
            + "||document.createElement('style');s.id='write-theme';s.textContent="
            + JSON.stringify(css) + ";(document.head||document.documentElement).appendChild(s);})()")
    }
    onTextScaleChanged: restyle()
    Connections { target: Theme; function onChanged() { root.restyle() } }

    EpubBook { id: book }

    Keys.onLeftPressed: book.current = book.current - 1
    Keys.onRightPressed: book.current = book.current + 1

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Table of contents
        Rectangle {
            Layout.fillHeight: true
            implicitWidth: 280
            visible: root.contents && root.hasBook
            color: Theme.c.surfaceContainerLow
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 4
                Label {
                    Layout.fillWidth: true
                    text: book.title
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    color: Theme.c.onSurface
                }
                Label {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: book.author
                    color: Theme.c.onSurfaceVariant
                    bottomPadding: 8
                }
                ListView {
                    id: toc
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: book.chapterTitles
                    currentIndex: book.current
                    delegate: ItemDelegate {
                        required property int index
                        required property string modelData
                        width: ListView.view.width
                        text: modelData
                        highlighted: index === book.current
                        onClicked: book.current = index
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            WebEngineView {
                id: view
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.hasBook
                backgroundColor: Theme.c.surface
                url: book.currentUrl
                onLoadingChanged: function(info) {
                    if (info.status === WebEngineLoadingInfo.LoadSucceededStatus)
                        root.restyle()
                }
                onNavigationRequested: function(request) {
                    const u = request.url.toString()
                    if (request.navigationType === WebEngineNavigationRequest.LinkClickedNavigation
                            && (u.startsWith("http:") || u.startsWith("https:"))) {
                        Qt.openUrlExternally(request.url)
                        request.reject()
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !root.hasBook
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: book.error || qsTr("Open an EPUB book from Books.")
                color: book.error ? Theme.c.error : Theme.c.onSurfaceVariant
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 8
                visible: root.hasBook
                spacing: 8
                Button { text: qsTr("Contents"); flat: true; checkable: true; checked: root.contents; onToggled: root.contents = checked }
                Item { Layout.fillWidth: true }
                Button { text: "‹"; flat: true; enabled: book.current > 0; onClicked: book.current = book.current - 1 }
                Label {
                    text: (book.chapterTitles[book.current] || "") + "  ·  " + (book.current + 1) + " / " + book.count
                    color: Theme.c.onSurfaceVariant
                }
                Button { text: "›"; flat: true; enabled: book.current < book.count - 1; onClicked: book.current = book.current + 1 }
                Item { Layout.fillWidth: true }
                Button { text: "A−"; flat: true; onClicked: root.textScale = Math.max(0.7, root.textScale - 0.1) }
                Button { text: "A+"; flat: true; onClicked: root.textScale = Math.min(2.0, root.textScale + 0.1) }
            }
        }
    }
}
