import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// To whom: a contact (searched) or a number or address typed in.
Dialog {
    id: dlg
    signal chosen(string handle)
    title: "New message"
    modal: true
    width: Math.min(440, win.width - 32)
    height: Math.min(560, win.height - 32)
    background: Rectangle { color: win.surface; radius: 20; border.color: win.dim; border.width: 0 }
    standardButtons: Dialog.Cancel
    onOpened: { to.text = ""; to.forceActiveFocus() }

    function pick(handle) { if (handle) { dlg.chosen(handle); dlg.close() } }

    ColumnLayout {
        anchors.fill: parent
        TextField {
            id: to
            Layout.fillWidth: true
            placeholderText: "Name, number or email"
            onAccepted: dlg.pick(people.count > 0 && !/^[+\d(][\d\s()+-]{4,}$|@/.test(text) ? people.model[0].handles[0] : text.trim())
        }
        ListView {
            id: people
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: msg.contacts.filter(c => to.text.length === 0 || (c.name + " " + c.handles.join(" ")).toLowerCase().includes(to.text.toLowerCase())).slice(0, 200)
            delegate: ItemDelegate {
                required property var modelData
                width: people.width
                contentItem: RowLayout {
                    spacing: 10
                    Avatar { implicitWidth: 32; implicitHeight: 32; name: modelData.name; photo: modelData.photo }
                    ColumnLayout {
                        spacing: 0
                        Label { text: modelData.name; font.weight: Font.DemiBold }
                        Label { text: modelData.handles.join(", "); opacity: 0.6; font.pixelSize: 12; elide: Text.ElideRight; Layout.maximumWidth: people.width - 80 }
                    }
                }
                onClicked: dlg.pick(modelData.handles[0] ?? "")
            }
        }
    }
}
