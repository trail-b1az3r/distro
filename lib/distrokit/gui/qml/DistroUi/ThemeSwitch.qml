import QtQuick

// The colour scheme as a connected button group: Auto, Dark, Light.
ConnectedButtons {
    options: [
        { id: "system", label: qsTr("Auto"), icon: "" },
        { id: "dark", label: "", icon: "moon" },
        { id: "light", label: "", icon: "sun" }
    ]
    current: Theme.mode
    Accessible.name: qsTr("Colour scheme")
    onChosen: (id) => Theme.mode = id
}
