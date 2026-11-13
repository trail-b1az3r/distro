import QtQuick
import QtQuick.Controls.Basic

// M3 Expressive buttons: a pill whose corners morph squarer while pressed, with a spring.
//   kind: "primary" (filled), "tonal" (secondary container), "secondary" (outlined), "ghost" (text), "danger"
//   size: "small" (40), "medium" (56), "large" (96)
Button {
    id: control
    property string kind: "secondary"
    property string size: "small"
    property string iconName: ""
    readonly property int baseHeight: size === "large" ? 96 : size === "medium" ? 56 : 40
    font.family: Theme.font
    font.pixelSize: size === "large" ? Theme.headlineSmall : size === "medium" ? Theme.titleMedium : Theme.labelLarge
    font.weight: Font.DemiBold
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: size === "large" ? 48 : size === "medium" ? 28 : 18
    rightPadding: leftPadding
    topPadding: 0; bottomPadding: 0
    Accessible.role: Accessible.Button
    Accessible.name: text

    readonly property color containerColor: {
        if (!enabled) return Theme.alpha(Theme.surfaceContent, kind === "ghost" || kind === "secondary" ? 0 : 0.12)
        if (kind === "primary") return Theme.primary
        if (kind === "tonal") return Theme.secondaryContainer
        if (kind === "danger") return Theme.error
        return "transparent"
    }
    readonly property color contentColor: {
        if (!enabled) return Theme.alpha(Theme.surfaceContent, 0.38)
        if (kind === "primary") return Theme.primaryContent
        if (kind === "tonal") return Theme.secondaryContainerContent
        if (kind === "danger") return Theme.errorContent
        if (kind === "ghost") return Theme.primary
        return Theme.surfaceVariantContent
    }

    contentItem: Row {
        spacing: 8
        Icon {
            visible: control.iconName !== ""
            name: control.iconName
            size: control.size === "large" ? 32 : control.size === "medium" ? 24 : 18
            color: control.contentColor
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: control.text
            font: control.font
            color: control.contentColor
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        implicitHeight: control.baseHeight
        implicitWidth: control.baseHeight
        // Pill at rest; pressed, the corners pull in (M3 Expressive's shape morph).
        radius: control.down ? Math.min(height / 2, control.size === "small" ? Theme.shapeMedium : Theme.shapeLarge) : height / 2
        Behavior on radius { SpringAnimation { spring: Theme.springFast; damping: Theme.dampingFast } }
        color: control.containerColor
        border.width: control.kind === "secondary" ? 1 : 0
        border.color: control.enabled ? Theme.outlineVariant : Theme.alpha(Theme.surfaceContent, 0.12)
        Behavior on color { ColorAnimation { duration: Theme.durationShort } }
        // State layer
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: control.contentColor
            opacity: !control.enabled ? 0 : control.down ? 0.12 : control.hovered || control.visualFocus ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durationShort } }
        }
        // Focus ring
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.secondary
            visible: control.visualFocus
        }
    }
}
