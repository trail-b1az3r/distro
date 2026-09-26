// Login screen theme for SDDM (Qt 6 greeter, theme API 2.0).
// Colours and the distribution name come from theme.conf, which the branding
// generator writes from distro.conf.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    width: 1920
    height: 1080
    color: "#0B0E1A"

    readonly property color accent: config.accent || "#7C6CFF"
    readonly property color fg: config.fg || "#E8ECF8"
    readonly property color muted: config.muted || "#8A93B2"
    readonly property color surface: config.surface || "#151A2C"
    readonly property color danger: config.danger || "#FF5C7A"
    property int sessionIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
    property string errorText: ""

    component Field: TextField {
        implicitHeight: 44
        color: root.fg
        placeholderTextColor: root.muted
        selectionColor: root.accent
        font.pixelSize: 15
        leftPadding: 14
        background: Rectangle {
            radius: 12
            color: Qt.rgba(1, 1, 1, 0.07)
            border.width: parent.activeFocus ? 2 : 1
            border.color: parent.activeFocus ? root.accent : Qt.rgba(1, 1, 1, 0.16)
        }
    }

    component Choice: ComboBox {
        id: choice
        implicitHeight: 44
        font.pixelSize: 15
        contentItem: Text {
            leftPadding: 14
            text: choice.displayText
            color: root.fg
            font: choice.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            x: choice.width - width - 14
            anchors.verticalCenter: parent.verticalCenter
            text: "\u25BE"
            color: root.muted
            font.pixelSize: 14
        }
        background: Rectangle {
            radius: 12
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

    function doLogin() {
        errorText = ""
        sddm.login(userBox.currentText !== "" ? userBox.currentValue : userField.text, password.text, root.sessionIndex)
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
    Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.25 }

    // Clock ----------------------------------------------------------------------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.14
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

    // Login card -----------------------------------------------------------------
    Rectangle {
        id: card
        width: 420
        height: form.implicitHeight + 56
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 80
        radius: 24
        color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, 0.82)
        border.color: Qt.rgba(1, 1, 1, 0.12)

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
                sourceSize: Qt.size(72, 72)
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: config.distroName || "Welcome"
                color: root.fg
                font.pixelSize: 20
                font.weight: Font.DemiBold
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
                Layout.fillWidth: true
                text: qsTr("Log in")
                onClicked: root.doLogin()
                contentItem: Text { text: parent.text; color: "#FFFFFF"; font.pixelSize: 16; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { implicitHeight: 44; radius: 12; color: parent.down ? Qt.darker(root.accent, 1.2) : root.accent }
            }
        }
    }

    // Session and power ------------------------------------------------------------
    RowLayout {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 28
        spacing: 10
        Text { text: qsTr("Session"); color: root.muted; font.pixelSize: 14 }
        Choice {
            id: sessionBox
            model: sessionModel
            textRole: "name"
            currentIndex: root.sessionIndex
            onActivated: (index) => root.sessionIndex = index
            implicitWidth: 240
            Accessible.name: qsTr("Session")
        }
    }
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
