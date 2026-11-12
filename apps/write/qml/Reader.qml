import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtWebEngine
import Write

// Full-page EPUB and native MDXL book reader. Visual language is inspired by
// Material 3 Expressive and Loaf's translucent, rounded surface system.
Item {
    id: root
    readonly property bool isMdxlBook: mdxlChapters.length > 0
    readonly property bool hasBook: isMdxlBook || epub.count > 0
    readonly property string bookTitle: isMdxlBook ? mdxlTitle : epub.title
    readonly property int chapterCount: isMdxlBook ? mdxlChapters.length : epub.count
    property real textScale: 1.0
    property bool contents: true
    property bool immersive: false
    property string mdxlBookDir: ""
    property string mdxlTitle: ""
    property var mdxlChapters: []
    property int mdxlCurrent: 0

    function open(path) {
        if (path.toLowerCase().endsWith(".epub")) {
            mdxlBookDir = ""
            mdxlChapters = []
            epub.path = path
            if (epub.count > 0) Files.addRecentBook(path, epub.title)
        } else {
            const list = Files.chapters(path)
            if (list.length) {
                mdxlBookDir = path
                mdxlTitle = Files.baseName(path)
                mdxlChapters = list
                mdxlCurrent = 0
                renderChapter()
                Files.addRecentBook(path, mdxlTitle)
            }
        }
    }
    function renderChapter() {
        if (isMdxlBook && mdxlCurrent >= 0 && mdxlCurrent < mdxlChapters.length)
            mdxlRenderer.render(Files.read(mdxlChapters[mdxlCurrent]), true)
    }
    function moveChapter(delta) {
        if (isMdxlBook) {
            const next = Math.max(0, Math.min(mdxlChapters.length - 1, mdxlCurrent + delta))
            if (next !== mdxlCurrent) { mdxlCurrent = next; renderChapter() }
        } else {
            epub.current = Math.max(0, Math.min(epub.count - 1, epub.current + delta))
        }
    }
    function turnPage(delta) {
        if (!hasBook)
            return
        const direction = delta > 0 ? 1 : -1
        const script = "(function(){const e=document.scrollingElement||document.documentElement;"
            + "if(" + direction + ">0 && e.scrollTop+window.innerHeight>=e.scrollHeight-8)return 'end';"
            + "if(" + direction + "<0 && e.scrollTop<=8)return 'start';"
            + "e.scrollBy({top:" + direction + "*window.innerHeight*0.88,behavior:'smooth'});return 'moved';})()"
        view.runJavaScript(script, function(result) {
            if (result === "end") root.moveChapter(1)
            else if (result === "start") root.moveChapter(-1)
        })
    }
    function restyle() {
        if (isMdxlBook) {
            if (mdxlRenderer.html.length)
                view.loadHtml(mdxlRenderer.html, Files.toUrl(mdxlBookDir + "/"))
            return
        }
        const css = Theme.css(textScale)
            + "html,body{min-height:100%}body{max-width:48em;margin:0 auto!important;padding:clamp(24px,5vw,76px) clamp(22px,5vw,72px)!important;line-height:1.85!important}p{margin:0 0 1.15em}img,svg,video{max-width:100%;height:auto;border-radius:14px}figure{margin:1.5em 0}a{color:" + Theme.c.primary + "!important}"
        view.runJavaScript("(function(){var s=document.getElementById('write-theme')||document.createElement('style');s.id='write-theme';s.textContent="
            + JSON.stringify(css) + ";(document.head||document.documentElement).appendChild(s);})()")
    }

    onTextScaleChanged: restyle()
    Connections { target: Theme; function onChanged() { root.restyle() } }
    Connections {
        target: mdxlRenderer
        function onHtmlChanged() {
            if (root.isMdxlBook && mdxlRenderer.html.length)
                view.loadHtml(mdxlRenderer.html, Files.toUrl(root.mdxlBookDir + "/"))
        }
    }
    EpubBook { id: epub }
    MdxlRenderer {
        id: mdxlRenderer
        css: Theme.css(root.textScale)
            + "body{max-width:48em;margin:0 auto!important;padding:clamp(24px,5vw,76px) clamp(22px,5vw,72px)!important;line-height:1.85!important}"
            + "img,svg,video{max-width:100%;height:auto;border-radius:14px}figure{margin:1.5em 0}"
    }

    Keys.onLeftPressed: root.turnPage(-1)
    Keys.onRightPressed: root.turnPage(1)
    Keys.onEscapePressed: root.immersive = false

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(Qt.color(Theme.c.surface).r, Qt.color(Theme.c.surface).g,
                       Qt.color(Theme.c.surface).b, 0.78)
    }
    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: root.contents && root.hasBook && !root.immersive ? 288 : 0
            Layout.minimumWidth: 0
            clip: true
            color: Qt.rgba(Qt.color(Theme.c.surfaceContainerLow).r,
                           Qt.color(Theme.c.surfaceContainerLow).g,
                           Qt.color(Theme.c.surfaceContainerLow).b, 0.84)
            Behavior on Layout.preferredWidth { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            ColumnLayout {
                width: 288
                anchors.fill: parent
                anchors.margins: 18
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: root.bookTitle
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                        color: Theme.c.onSurface
                    }
                    ToolButton { text: "‹"; onClicked: root.contents = false }
                }
                Label {
                    Layout.fillWidth: true
                    visible: !root.isMdxlBook && epub.author.length > 0
                    text: epub.author
                    color: Theme.c.onSurfaceVariant
                }
                Label {
                    text: qsTr("CONTENTS")
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    color: Theme.c.onSurfaceVariant
                    topPadding: 8
                }
                ListView {
                    id: toc
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: root.isMdxlBook
                        ? root.mdxlChapters.map(path => Files.baseName(path))
                        : epub.chapterTitles
                    currentIndex: root.isMdxlBook ? root.mdxlCurrent : epub.current
                    delegate: ItemDelegate {
                        required property int index
                        required property string modelData
                        width: ListView.view.width
                        text: modelData
                        highlighted: index === toc.currentIndex
                        onClicked: {
                            if (root.isMdxlBook) { root.mdxlCurrent = index; root.renderChapter() }
                            else epub.current = index
                        }
                        background: Rectangle {
                            radius: 12
                            color: parent.highlighted ? Theme.c.secondaryContainer
                                : parent.hovered ? Qt.rgba(Qt.color(Theme.c.onSurface).r,
                                  Qt.color(Theme.c.onSurface).g, Qt.color(Theme.c.onSurface).b, 0.06)
                                : "transparent"
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            Rectangle {
                Layout.fillWidth: true
                Layout.margins: 12
                implicitHeight: 54
                visible: !root.immersive
                radius: 18
                color: Qt.rgba(Qt.color(Theme.c.surfaceContainerHigh).r,
                               Qt.color(Theme.c.surfaceContainerHigh).g,
                               Qt.color(Theme.c.surfaceContainerHigh).b, 0.78)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    ToolButton { text: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? (root.contents ? "menu_open" : "menu") : "☰"; font.family: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "Material Symbols Rounded" : Theme.font; onClicked: root.contents = !root.contents }
                    Label {
                        Layout.fillWidth: true
                        text: root.bookTitle || qsTr("Reading")
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        color: Theme.c.onSurface
                    }
                    ToolButton { text: "A−"; onClicked: root.textScale = Math.max(0.75, root.textScale - 0.1) }
                    Label { text: Math.round(root.textScale * 100) + "%"; color: Theme.c.onSurfaceVariant }
                    ToolButton { text: "A+"; onClicked: root.textScale = Math.min(1.8, root.textScale + 0.1) }
                    ToolButton { text: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? (root.immersive ? "fullscreen_exit" : "fullscreen") : "⛶"; font.family: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "Material Symbols Rounded" : Theme.font; onClicked: root.immersive = !root.immersive }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Layout.bottomMargin: 12
                radius: 24
                clip: true
                color: Qt.rgba(Qt.color(Theme.c.surfaceContainer).r,
                               Qt.color(Theme.c.surfaceContainer).g,
                               Qt.color(Theme.c.surfaceContainer).b, 0.76)
                WebEngineView {
                    id: view
                    anchors.fill: parent
                    anchors.margins: 2
                    visible: root.hasBook
                    backgroundColor: "transparent"
                    url: root.isMdxlBook ? "" : epub.currentUrl
                    onLoadingChanged: function(info) {
                        if (info.status === WebEngineLoadingInfo.LoadSucceededStatus && !root.isMdxlBook)
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
                // Edge-only drag handles keep ordinary text selection intact.
                Item {
                    width: 76; anchors.left: parent.left; anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    DragHandler {
                        target: null
                        xAxis.enabled: true
                        yAxis.enabled: false
                        onActiveChanged: if (!active && translation.x > 80) root.turnPage(-1)
                    }
                }
                Item {
                    width: 76; anchors.right: parent.right; anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    DragHandler {
                        target: null
                        xAxis.enabled: true
                        yAxis.enabled: false
                        onActiveChanged: if (!active && translation.x < -80) root.turnPage(1)
                    }
                }
                Label {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 48, 520)
                    visible: !root.hasBook
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: epub.error || qsTr("Open an EPUB or an MDXL book from Books.")
                    color: epub.error ? Theme.c.error : Theme.c.onSurfaceVariant
                }
                ToolButton {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.hasBook && !root.immersive
                    text: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "chevron_left" : "‹"; font.family: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "Material Symbols Rounded" : Theme.font
                    enabled: root.isMdxlBook ? root.mdxlCurrent > 0 : epub.current > 0
                    onClicked: root.turnPage(-1)
                }
                ToolButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.hasBook && !root.immersive
                    text: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "chevron_right" : "›"; font.family: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0 ? "Material Symbols Rounded" : Theme.font
                    enabled: root.isMdxlBook ? root.mdxlCurrent < root.mdxlChapters.length - 1 : epub.current < epub.count - 1
                    onClicked: root.turnPage(1)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 22
                Layout.rightMargin: 22
                Layout.bottomMargin: 8
                visible: root.hasBook && !root.immersive
                Label {
                    Layout.fillWidth: true
                    text: root.isMdxlBook ? Files.baseName(root.mdxlChapters[root.mdxlCurrent] || "")
                        : (epub.chapterTitles[epub.current] || "")
                    color: Theme.c.onSurfaceVariant
                    elide: Text.ElideRight
                }
                Label {
                    text: (root.isMdxlBook ? root.mdxlCurrent + 1 : epub.current + 1)
                        + " / " + root.chapterCount
                    color: Theme.c.onSurfaceVariant
                }
            }
        }
    }
}
