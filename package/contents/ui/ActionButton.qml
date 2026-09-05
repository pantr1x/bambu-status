import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

// Flat coloured pill in the macOS vein: soft tint, hairline border, icon plus
// label. Plasma's Button paints itself from the theme, so per-action colour
// means drawing it by hand.
Rectangle {
    id: btn

    property color accent: "#00ae42"
    property string label: ""
    property string confirmLabel: ""
    property string iconName: ""
    property bool needsConfirm: false
    property bool armed: false

    signal activated()

    implicitHeight: Math.round(Kirigami.Units.gridUnit * 1.75)
    radius: Kirigami.Units.gridUnit * 0.5
    opacity: enabled ? 1 : 0.3

    color: !enabled ? Qt.rgba(1, 1, 1, 0.05)
         : armed ? accent
         : area.containsMouse ? Qt.rgba(accent.r, accent.g, accent.b, 0.28)
         : Qt.rgba(accent.r, accent.g, accent.b, 0.14)

    border.width: 1
    border.color: armed ? accent : Qt.rgba(accent.r, accent.g, accent.b, 0.4)

    Behavior on color { ColorAnimation { duration: 120 } }
    scale: area.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 90 } }

    readonly property color contentColor: armed ? "#0b0b0b"
                                        : enabled ? accent
                                        : Kirigami.Theme.textColor

    RowLayout {
        anchors.centerIn: parent
        spacing: Kirigami.Units.smallSpacing * 0.8

        Kirigami.Icon {
            visible: btn.iconName !== ""
            source: btn.iconName
            implicitWidth: Kirigami.Units.gridUnit * 0.85
            implicitHeight: implicitWidth
            color: btn.contentColor
            isMask: true
        }

        PlasmaComponents.Label {
            text: btn.armed && btn.confirmLabel ? btn.confirmLabel : btn.label
            font.family: "Noto Sans"
            font.pixelSize: Kirigami.Units.gridUnit * 0.68
            font.weight: Font.DemiBold
            color: btn.contentColor
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: btn.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        enabled: btn.enabled
        onClicked: {
            if (!btn.needsConfirm) { btn.activated(); return }
            // destructive actions take two clicks
            if (btn.armed) { btn.armed = false; btn.activated() }
            else btn.armed = true
        }
    }

    Timer {
        interval: 5000
        running: btn.armed
        onTriggered: btn.armed = false
    }
}
