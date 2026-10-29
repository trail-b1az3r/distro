import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Write

// A navigation rail entry: a Material Symbols icon in a pill, its label below.
AbstractButton {
    id: control
    property string symbol
    property bool selected: false
    implicitWidth: 72
    implicitHeight: 60
    hoverEnabled: true
    readonly property bool symbols: Qt.fontFamilies().indexOf("Material Symbols Rounded") >= 0

    contentItem: ColumnLayout {
        spacing: 4
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 56
            implicitHeight: 32
            radius: 16
            color: control.selected ? Theme.c.secondaryContainer : "transparent"
            Behavior on color { ColorAnimation { duration: 150 } }
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: Theme.c.onSurface
                opacity: control.hovered && !control.selected ? 0.08 : 0
            }
            Text {
                anchors.centerIn: parent
                text: control.symbols ? control.symbol : control.text.charAt(0)
                font.family: control.symbols ? "Material Symbols Rounded" : Theme.font
                font.pixelSize: control.symbols ? 22 : 16
                font.bold: !control.symbols
                color: control.selected ? Theme.c.onSecondaryContainer : Theme.c.onSurfaceVariant
            }
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: control.text
            font.family: Theme.font
            font.pixelSize: 12
            font.weight: control.selected ? Font.DemiBold : Font.Normal
            color: control.selected ? Theme.c.onSurface : Theme.c.onSurfaceVariant
        }
    }
}
