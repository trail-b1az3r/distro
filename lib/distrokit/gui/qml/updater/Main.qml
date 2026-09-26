import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import DistroUi

ApplicationWindow {
    id: win
    width: 900
    height: 720
    minimumWidth: 560
    minimumHeight: 480
    visible: true
    title: qsTr("System Update")
    color: Theme.bg
    property string themeMode: "system"
    onThemeModeChanged: Theme.mode = themeMode
    property var selected: ["packages", "aur", "flatpak", "desktop", "ai"]

    Connections {
        target: updater
        function onLog(line) { log.append(line) }
    }

    ScrollView {
        id: scroller
        anchors.fill: parent
        contentWidth: availableWidth
        Item {
            width: scroller.availableWidth
            implicitHeight: col.implicitHeight + 48
            ColumnLayout {
                id: col
                x: Math.max(20, (parent.width - width) / 2)
                y: 24
                width: Math.min(parent.width - 40, 820)
                spacing: 18

                RowLayout {
                    Layout.fillWidth: true
                    PageHeader {
                        Layout.fillWidth: true
                        title: qsTr("System Update")
                        subtitle: !updater.checked ? qsTr("Checking for updates…")
                                 : updater.total ? qsTr("%1 updates available").arg(updater.total) : qsTr("Everything is up to date.")
                    }
                    ThemeSwitch {}
                }

                Repeater {
                    model: updater.news
                    Notice {
                        required property var modelData
                        Layout.fillWidth: true
                        kind: "warning"
                        title: qsTr("Arch Linux news (%1): %2").arg(modelData.date).arg(modelData.title)
                        text: qsTr("News posts can require manual steps. Read it before updating.")
                        AppButton { text: qsTr("Read"); iconName: "external"; onClicked: launcher.openUrl(modelData.link) }
                    }
                }

                Repeater {
                    model: updater.sources
                    Card {
                        id: srcCard
                        required property var modelData
                        property bool open: false
                        Layout.fillWidth: true
                        visible: modelData.available || modelData.error !== ""
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            CheckBox {
                                enabled: modelData.count > 0 && !updater.busy
                                checked: modelData.count > 0 && win.selected.indexOf(modelData.id) >= 0
                                onToggled: win.selected = checked ? win.selected.concat([modelData.id]) : win.selected.filter(x => x !== modelData.id)
                                Accessible.name: modelData.label
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text { text: modelData.label; color: Theme.fg; font.pixelSize: Theme.textLarge; font.weight: Font.DemiBold }
                                Text {
                                    text: modelData.error ? modelData.error : (modelData.count ? qsTr("%1 update(s)").arg(modelData.count) : qsTr("Up to date"))
                                    color: modelData.error ? Theme.warning : Theme.muted
                                    font.pixelSize: Theme.textSmall
                                }
                            }
                            Text { visible: modelData.command.length > 0; text: modelData.command.join(" "); color: Theme.muted; font.family: Theme.mono; font.pixelSize: 12 }
                            AppButton { visible: modelData.count > 0; kind: "ghost"; text: srcCard.open ? qsTr("Hide") : qsTr("Details"); onClicked: srcCard.open = !srcCard.open }
                        }
                        Repeater {
                            model: srcCard.open ? modelData.items : []
                            Text {
                                required property var modelData
                                text: modelData.name + "  " + modelData.current + (modelData.new ? "  →  " + modelData.new : "")
                                color: Theme.fg; font.family: Theme.mono; font.pixelSize: 12
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    AppButton { text: qsTr("Check again"); iconName: "refresh"; enabled: !updater.busy; onClicked: updater.check() }
                    AppButton { text: qsTr("Update in a terminal"); iconName: "terminal"; onClicked: updater.openTerminal() }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        kind: "primary"
                        text: updater.busy ? qsTr("Working…") : qsTr("Install updates")
                        iconName: "download"
                        enabled: !updater.busy && updater.total > 0
                        onClicked: updater.apply(win.selected)
                    }
                }
                LogView { id: log; Layout.fillWidth: true; Layout.preferredHeight: 260 }
            }
        }
    }
}
