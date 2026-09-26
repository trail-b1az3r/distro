import QtQuick

// Cycles system -> dark -> light.
AppButton {
    kind: "ghost"
    iconName: Theme.dark ? "moon" : "sun"
    text: Theme.mode === "system" ? qsTr("Auto") : Theme.mode === "dark" ? qsTr("Dark") : qsTr("Light")
    Accessible.name: qsTr("Colour scheme: ") + text
    onClicked: Theme.mode = Theme.mode === "system" ? "dark" : Theme.mode === "dark" ? "light" : "system"
}
