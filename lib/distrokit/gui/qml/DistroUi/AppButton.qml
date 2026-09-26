import QtQuick
import QtQuick.Controls.Basic

// Buttons in three weights: primary (accent), secondary (outlined), danger.
Button {
    id: control
    property string kind: "secondary"   // primary | secondary | danger | ghost
    property string iconName: ""
    font.pixelSize: Theme.text
    font.weight: Font.DemiBold
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: 18; rightPadding: 18; topPadding: 10; bottomPadding: 10
    Accessible.role: Accessible.Button
    Accessible.name: text

    contentItem: Row {
        spacing: 8
        Icon {
            visible: control.iconName !== ""
            name: control.iconName
            size: 18
            color: label.color
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: label
            text: control.text
            font: control.font
            color: control.kind === "primary" || control.kind === "danger" ? Theme.textOnAccent
                 : (control.enabled ? Theme.fg : Theme.muted)
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        implicitHeight: 42
        radius: Theme.radiusSmall
        color: {
            if (!control.enabled) return Theme.surface2
            if (control.kind === "primary") return control.down ? Qt.darker(Theme.accent, 1.2) : control.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
            if (control.kind === "danger") return control.down ? Qt.darker(Theme.danger, 1.2) : Theme.danger
            if (control.kind === "ghost") return control.hovered ? Theme.surface2 : "transparent"
            return control.hovered ? Theme.surface2 : Theme.surface
        }
        border.width: control.kind === "secondary" ? 1 : 0
        border.color: Theme.border
        opacity: control.enabled ? 1 : 0.6
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.focus
            visible: control.visualFocus
        }
    }
}
