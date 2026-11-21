// Login screen theme for SDDM (Qt 6 greeter, theme API 2.0).
//
//   left    the desktop switcher: each installed desktop (Halcyon, and ML4W, HyDE, SekaiPop when installed) as a
//           preview; scroll the mouse wheel over it (or Up/Down in the password field) to change desktop
//   middle  the clock and the login card
//   right   the system, as fastfetch shows it with the distribution's own config
//
// Colours, the distribution's name and the two data paths come from theme.conf, which the branding generator writes
// from distro.conf. A desktop's preview is a screenshot its own session saves shortly after login
// (<previewDir>/<session file name>.png); until there is one, a card is drawn. The system information is written
// before SDDM starts (<infoFile>, a small QML file); without it the panel shows the distribution's name.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    width: 1920
    height: 1080
    color: "#0B0E1A"

    readonly property color accent: config.accent || "#7C6CFF"
    readonly property color accent2: config.accent2 || "#4FD1C5"
    readonly property color fg: config.fg || "#E8ECF8"
    readonly property color muted: config.muted || "#8A93B2"
    readonly property color surface: config.surface || "#151A2C"
    readonly property color danger: config.danger || "#FF5C7A"
    readonly property string mono: "JetBrains Mono"
    property int sessionIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
    property string errorText: ""

    // hyprland.desktop (and its uwsm twin) starts Halcyon here: say so.
    function desktopName(name, file) {
        const stem = (file || "").split("/").pop().replace(/\.desktop$/, "")
        return stem === "hyprland" || stem === "hyprland-uwsm" ? (config.defaultDesktop || "Halcyon") : (name || "")
    }
    function glass(alpha) { return Qt.rgba(root.surface.r, root.surface.g, root.surface.b, alpha) }

    function doLogin() {
        errorText = ""
        sddm.login(userBox.visible && userBox.currentValue ? userBox.currentValue : userField.text, password.text,
                   root.sessionIndex)
    }
    function stepSession(delta) {
        const n = switcher.count
        if (n > 0)
            root.sessionIndex = (root.sessionIndex + delta + n) % n
    }

    component Field: TextField {
        implicitHeight: 46
        color: root.fg
        placeholderTextColor: root.muted
        selectionColor: root.accent
        font.pixelSize: 15
        leftPadding: 16
        background: Rectangle {
            radius: 14
            color: Qt.rgba(1, 1, 1, 0.07)
            border.width: parent.activeFocus ? 2 : 1
            border.color: parent.activeFocus ? root.accent : Qt.rgba(1, 1, 1, 0.16)
        }
    }

    component Choice: ComboBox {
        id: choice
        implicitHeight: 46
        font.pixelSize: 15
        contentItem: Text {
            leftPadding: 16
            text: choice.displayText
            color: root.fg
            font: choice.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            x: choice.width - width - 14
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: root.muted
            font.pixelSize: 14
        }
        background: Rectangle {
            radius: 14
            color: Qt.rgba(1, 1, 1, 0.07)
            border.width: choice.activeFocus ? 2 : 1
            border.color: choice.activeFocus ? root.accent : Qt.rgba(1, 1, 1, 0.16)
        }
        delegate: ItemDelegate {
            required property int index
            required property var model
            width: choice.width
            highlighted: choice.highlightedIndex === index
            contentItem: Text {
                text: model[choice.textRole]
                color: root.fg
                font.pixelSize: 15
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle { color: highlighted ? Qt.rgba(1, 1, 1, 0.10) : "transparent"; radius: 8 }
        }
        popup.background: Rectangle { color: root.surface; radius: 12; border.color: Qt.rgba(1, 1, 1, 0.16) }
    }

    // A panel of frosted glass.
    component Panel: Rectangle {
        radius: 28
        color: root.glass(0.72)
        border.color: Qt.rgba(1, 1, 1, 0.10)
    }

    // A desktop's preview: its saved screenshot, or a drawn desktop until it has one.
    component Preview: Item {
        id: preview
        property string name: ""
        property string file: ""
        readonly property string title: root.desktopName(name, file)
        readonly property string stem: {
            const base = (file || "").split("/").pop()
            return base.replace(/\.desktop$/, "") || name.toLowerCase().replace(/[^a-z0-9]+/g, "-")
        }
        readonly property var sources: [
            config.previewDir ? "file://" + config.previewDir + "/" + stem + ".png" : "",
            "previews/" + stem + ".png"
        ].filter(s => s !== "")
        property int attempt: 0
        onStemChanged: attempt = 0
        readonly property bool hasShot: shot.status === Image.Ready

        // The drawn desktop: a wallpaper of the theme's colours, a bar, two windows and the desktop's initial.
        Rectangle {
            id: drawn
            anchors.fill: parent
            clip: true
            visible: !preview.hasShot
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0; color: Qt.darker(root.accent, 1.6) }
                GradientStop { position: 1; color: Qt.darker(root.accent2, 2.2) }
            }
            Rectangle { x: 0; y: 0; width: parent.width; height: parent.height * 0.06; color: Qt.rgba(0, 0, 0, 0.35) }
            Rectangle {
                x: parent.width * 0.08; y: parent.height * 0.16; width: parent.width * 0.5; height: parent.height * 0.62
                radius: 10; color: Qt.rgba(1, 1, 1, 0.10); border.color: Qt.rgba(1, 1, 1, 0.18)
            }
            Rectangle {
                x: parent.width * 0.62; y: parent.height * 0.16; width: parent.width * 0.3; height: parent.height * 0.3
                radius: 10; color: Qt.rgba(1, 1, 1, 0.08); border.color: Qt.rgba(1, 1, 1, 0.16)
            }
            Text {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: parent.height * 0.06
                text: (preview.title || "?").charAt(0)
                color: Qt.rgba(1, 1, 1, 0.85)
                font.pixelSize: parent.height * 0.34
                font.weight: Font.Bold
            }
        }
        Item {
            anchors.fill: parent
            clip: true
            Image {
                id: shot
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: false
                source: preview.attempt < preview.sources.length ? preview.sources[preview.attempt] : ""
                onStatusChanged: if (status === Image.Error) preview.attempt += 1
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: 3
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.18)
        }
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.errorText = qsTr("That password didn't work. Try again.")
            password.text = ""
            password.forceActiveFocus()
            shake.start()
        }
    }

    Image {
        anchors.fill: parent
        source: config.background || "background.png"
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.55) }
            GradientStop { position: 0.5; color: Qt.rgba(0, 0, 0, 0.18) }
            GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.55) }
        }
    }

    // Left: the desktop switcher -------------------------------------------------------------------------------------
    Item {
        id: desktops
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: Math.max(28, parent.width * 0.04)
        width: Math.max(260, Math.min(600, (parent.width - card.width) / 2 - anchors.leftMargin - 48))

        readonly property real cardWidth: width
        readonly property real cardHeight: cardWidth * 10 / 16

        Text {
            id: desktopsTitle
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.topMargin: parent.height * 0.10
            text: qsTr("Desktop")
            color: root.muted
            font.pixelSize: 15
            font.letterSpacing: 2
            font.capitalization: Font.AllUppercase
        }

        PathView {
            id: switcher
            objectName: "switcher"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: desktopsTitle.bottom
            anchors.bottom: hint.top
            anchors.topMargin: 12
            anchors.bottomMargin: 12
            model: sessionModel
            pathItemCount: 3
            preferredHighlightBegin: 0.5
            preferredHighlightEnd: 0.5
            highlightRangeMode: PathView.StrictlyEnforceRange
            highlightMoveDuration: 380
            interactive: count > 1
            clip: true
            currentIndex: root.sessionIndex
            onCurrentIndexChanged: if (currentIndex !== root.sessionIndex) root.sessionIndex = currentIndex
            path: Path {
                startX: switcher.width / 2; startY: -desktops.cardHeight * 0.95
                PathAttribute { name: "itemScale"; value: 0.62 }
                PathAttribute { name: "itemOpacity"; value: 0.25 }
                PathAttribute { name: "itemZ"; value: 0 }
                PathLine { x: switcher.width / 2; y: switcher.height / 2 }
                PathAttribute { name: "itemScale"; value: 1.0 }
                PathAttribute { name: "itemOpacity"; value: 1.0 }
                PathAttribute { name: "itemZ"; value: 2 }
                PathLine { x: switcher.width / 2; y: switcher.height + desktops.cardHeight * 0.95 }
                PathAttribute { name: "itemScale"; value: 0.62 }
                PathAttribute { name: "itemOpacity"; value: 0.25 }
                PathAttribute { name: "itemZ"; value: 0 }
            }
            delegate: Item {
                id: desk
                required property int index
                required property var model
                readonly property bool current: PathView.isCurrentItem
                width: desktops.cardWidth
                height: desktops.cardHeight + 74
                scale: PathView.itemScale
                opacity: PathView.itemOpacity
                z: PathView.itemZ

                Preview {
                    id: cardPreview
                    width: desktops.cardWidth
                    height: desktops.cardHeight
                    name: desk.model.name || ""
                    file: desk.model.file || ""
                }
                Column {
                    anchors.top: cardPreview.bottom
                    anchors.topMargin: 14
                    anchors.left: parent.left
                    width: parent.width
                    spacing: 2
                    opacity: desk.current ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                    Text {
                        width: parent.width
                        text: root.desktopName(desk.model.name, desk.model.file)
                        color: root.fg
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: desk.model.comment || ""
                        color: root.muted
                        font.pixelSize: 14
                        elide: Text.ElideRight
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: !desk.current
                    onClicked: root.sessionIndex = desk.index
                }
            }
        }
        // The mouse wheel over the switcher changes desktop, a notch at a time (touchpads add up to a notch).
        WheelHandler {
            id: wheel
            objectName: "desktopWheel"
            target: null
            property real pending: 0
            onWheel: event => {
                pending += event.angleDelta.y !== 0 ? event.angleDelta.y : -event.angleDelta.x
                while (pending <= -120) { pending += 120; root.stepSession(1) }
                while (pending >= 120) { pending -= 120; root.stepSession(-1) }
            }
        }
        // Where you are among the desktops.
        Row {
            anchors.left: desktopsTitle.right
            anchors.leftMargin: 14
            anchors.verticalCenter: desktopsTitle.verticalCenter
            spacing: 6
            visible: switcher.count > 1
            Repeater {
                model: switcher.count
                Rectangle {
                    required property int index
                    height: 6
                    width: index === root.sessionIndex ? 22 : 6
                    radius: 3
                    color: index === root.sessionIndex ? root.accent : Qt.rgba(1, 1, 1, 0.35)
                    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                }
            }
        }
        Text {
            id: hint
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.bottomMargin: parent.height * 0.10
            visible: switcher.count > 1
            text: qsTr("Scroll to change desktop")
            color: root.muted
            font.pixelSize: 13
        }
    }

    // Middle: clock and login ----------------------------------------------------------------------------------------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.13
        spacing: 4
        Text {
            id: clock
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.fg
            font.pixelSize: 96
            font.weight: Font.Light
            text: Qt.formatTime(new Date(), "hh:mm")
        }
        Text {
            id: date
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.muted
            font.pixelSize: 22
            text: Qt.formatDate(new Date(), "dddd, d MMMM")
        }
        Timer {
            interval: 1000; running: true; repeat: true
            onTriggered: { clock.text = Qt.formatTime(new Date(), "hh:mm"); date.text = Qt.formatDate(new Date(), "dddd, d MMMM") }
        }
    }

    Panel {
        id: card
        width: 400
        height: form.implicitHeight + 56
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 70

        SequentialAnimation {
            id: shake
            NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: -12; duration: 50 }
            NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 12; duration: 70 }
            NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 0; duration: 50 }
        }

        ColumnLayout {
            id: form
            anchors.fill: parent
            anchors.margins: 28
            spacing: 14

            Image {
                Layout.alignment: Qt.AlignHCenter
                source: "logo.png"
                sourceSize: Qt.size(64, 64)
            }
            Choice {
                id: userBox
                Layout.fillWidth: true
                visible: userModel.count > 0
                model: userModel
                textRole: "realName"
                valueRole: "name"
                currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0
                displayText: currentText !== "" ? currentText : currentValue
                Accessible.name: qsTr("User")
            }
            Field {
                id: userField
                visible: userModel.count === 0
                Layout.fillWidth: true
                placeholderText: qsTr("User name")
            }
            Field {
                id: password
                objectName: "password"
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: qsTr("Password")
                focus: true
                Accessible.name: qsTr("Password")
                Keys.onReturnPressed: root.doLogin()
                Keys.onEnterPressed: root.doLogin()
                // Up and Down change desktop from the keyboard too.
                Keys.onUpPressed: root.stepSession(-1)
                Keys.onDownPressed: root.stepSession(1)
            }
            Text {
                visible: keyboard.capsLock
                text: qsTr("Caps Lock is on")
                color: root.muted
                font.pixelSize: 13
            }
            Text {
                visible: root.errorText !== ""
                text: root.errorText
                color: root.danger
                font.pixelSize: 14
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Button {
                objectName: "loginButton"
                Layout.fillWidth: true
                text: switcher.currentItem && switcher.currentItem.model && switcher.currentItem.model.name
                      ? qsTr("Log in to %1").arg(root.desktopName(switcher.currentItem.model.name, switcher.currentItem.model.file))
                      : qsTr("Log in")
                onClicked: root.doLogin()
                contentItem: Text { text: parent.text; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { implicitHeight: 46; radius: 14; color: parent.down ? Qt.darker(root.accent, 1.2) : root.accent }
            }
        }
    }

    // Right: the system, as fastfetch shows it ----------------------------------------------------------------------
    Loader {
        id: info
        source: config.infoFile ? "file://" + config.infoFile : ""
    }
    Panel {
        id: system
        objectName: "system"
        anchors.right: parent.right
        anchors.rightMargin: Math.max(28, parent.width * 0.04)
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(300, Math.min(470, (parent.width - card.width) / 2 - anchors.rightMargin - 48))
        height: sysColumn.implicitHeight + 52
        readonly property var rows: info.status === Loader.Ready && info.item ? info.item.rows : []

        ColumnLayout {
            id: sysColumn
            anchors.fill: parent
            anchors.margins: 26
            spacing: 10

            RowLayout {
                spacing: 16
                Image {
                    source: "logo.png"
                    sourceSize: Qt.size(76, 76)
                    Layout.alignment: Qt.AlignTop
                }
                ColumnLayout {
                    spacing: 2
                    Text {
                        text: config.distroName || "Welcome"
                        color: root.accent
                        font.family: root.mono
                        font.pixelSize: 19
                        font.weight: Font.Bold
                    }
                    Text {
                        visible: text !== ""
                        text: info.status === Loader.Ready && info.item ? info.item.host : ""
                        color: root.fg
                        font.family: root.mono
                        font.pixelSize: 14
                    }
                    Rectangle { Layout.topMargin: 4; implicitWidth: 120; implicitHeight: 2; radius: 1; color: root.accent }
                }
            }
            GridLayout {
                columns: 2
                columnSpacing: 14
                rowSpacing: 6
                Layout.fillWidth: true
                Layout.topMargin: 6
                Repeater {
                    model: system.rows.length * 2
                    Text {
                        required property int index
                        readonly property var row: system.rows[Math.floor(index / 2)]
                        readonly property bool isKey: index % 2 === 0
                        Layout.fillWidth: !isKey
                        Layout.alignment: Qt.AlignTop
                        text: row ? row[isKey ? 0 : 1] : ""
                        color: isKey ? root.accent : root.fg
                        font.family: root.mono
                        font.pixelSize: 13
                        font.weight: isKey ? Font.Bold : Font.Normal
                        wrapMode: isKey ? Text.NoWrap : Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }
            }
            Text {
                visible: system.rows.length === 0
                text: qsTr("System information appears here after the next start.")
                color: root.muted
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            // fastfetch's colour blocks, in the theme's colours.
            Row {
                Layout.topMargin: 6
                spacing: 6
                Repeater {
                    model: [root.accent, root.accent2, root.fg, root.muted, root.danger, Qt.lighter(root.surface, 2.2)]
                    Rectangle { required property var modelData; width: 26; height: 14; radius: 4; color: modelData }
                }
            }
        }
    }

    // Power ----------------------------------------------------------------------------------------------------------
    RowLayout {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 28
        spacing: 10
        Repeater {
            model: [
                { label: qsTr("Suspend"), can: sddm.canSuspend, act: function() { sddm.suspend() } },
                { label: qsTr("Restart"), can: sddm.canReboot, act: function() { sddm.reboot() } },
                { label: qsTr("Shut down"), can: sddm.canPowerOff, act: function() { sddm.powerOff() } }
            ]
            Button {
                required property var modelData
                visible: modelData.can
                text: modelData.label
                onClicked: modelData.act()
                contentItem: Text { text: parent.text; color: root.fg; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { implicitHeight: 38; implicitWidth: 110; radius: 10; color: Qt.rgba(1, 1, 1, parent.hovered ? 0.18 : 0.10) }
            }
        }
    }

    Component.onCompleted: password.forceActiveFocus()
}
