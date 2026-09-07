import QtQuick
import QtQuick.Effects
import Qt.labs.platform as Platform
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    readonly property string uiFont: "Noto Sans"
    readonly property color green: "#00ae42"      // Bambu brand green
    readonly property color paused: "#e0a458"
    readonly property color failed: "#e05252"
    readonly property color track: Qt.rgba(1, 1, 1, 0.14)

    property string name: ""
    property string label: "—"
    property string state_: ""
    property int percent: 0
    property int remainingMin: 0
    property int curLayer: 0
    property int totalLayers: 0
    property real nozzle: 0
    property real bed: 0
    property string model: "Bambu"
    property bool printing: false
    property bool connected: false
    property string error: ""
    property double updated: 0
    property double clock: Date.now() / 1000
    readonly property string homeDir: Platform.StandardPaths
        .writableLocation(Platform.StandardPaths.HomeLocation).toString().replace("file://", "")
    // 90 s mirrors STALE_AFTER in bin/bambu-monitor; QML cannot read the
    // monitor's constant, so change both or neither
    readonly property bool stale: connected && updated > 0 && (clock - updated) > 90

    readonly property color barColor: state_ === "FAILED" ? failed
                                    : state_ === "PAUSE" ? paused
                                    : green

    function fmtEta(min) {
        if (min <= 0) return "—"
        var h = Math.floor(min / 60)
        var m = min % 60
        return h > 0 ? h + "h " + m + "m" : m + "m"
    }

    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: function (source, data) {
            disconnectSource(source)
            var out = (data["stdout"] || "").trim()
            if (!out) {
                root.connected = false
                root.error = "monitor not running"
                return
            }
            try {
                var j = JSON.parse(out)
                root.name = j.name || ""
                root.label = j.label || "—"
                root.state_ = j.state || ""
                root.percent = j.percent || 0
                root.remainingMin = j.remainingMin || 0
                root.curLayer = j.layer || 0
                root.totalLayers = j.totalLayers || 0
                root.nozzle = j.nozzle || 0
                root.bed = j.bed || 0
                root.model = j.model || "Bambu"
                root.printing = !!j.printing
                root.connected = !!j.connected
                root.error = j.error || ""
                root.updated = j.updated || 0
            } catch (e) {
                root.connected = false
                root.error = "malformed data"
            }
        }
    }

    function refresh() {
        runner.connectSource("cat $HOME/.cache/bambu-status.json 2>/dev/null")
    }

    // the monitor watches this file and forwards the verb over MQTT
    function send(verb) {
        runner.connectSource("printf %s " + verb + " > $HOME/.cache/bambu-command")
    }

    property int frameTick: 0
    Timer {
        interval: 1000
        running: root.expanded
        repeat: true
        onTriggered: root.frameTick++
    }

    Component.onCompleted: refresh()

    Timer {
        interval: 5000
        running: true
        repeat: true
        onTriggered: root.refresh()
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: root.clock = Date.now() / 1000
    }

    preferredRepresentation: compactRepresentation

    // ---------------------------------------------------------------- panel
    compactRepresentation: MouseArea {
        Layout.minimumWidth: row.implicitWidth + Kirigami.Units.largeSpacing
        Layout.preferredWidth: Layout.minimumWidth
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded

        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            Image {
                Layout.alignment: Qt.AlignVCenter
                source: Qt.resolvedUrl("bambu.svg")
                sourceSize.width: Kirigami.Units.gridUnit * 1.5
                sourceSize.height: Kirigami.Units.gridUnit * 1.5
                width: Math.round(Kirigami.Units.gridUnit * 0.72)
                height: width
                smooth: true
                opacity: root.connected ? 1.0 : 0.45
            }

            PlasmaComponents.Label {
                visible: !root.connected
                text: "offline"
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.5
            }

            PlasmaComponents.Label {
                visible: root.connected
                text: root.model
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.9
            }

            PlasmaComponents.Label {
                visible: root.connected && root.printing && root.remainingMin > 0
                text: "·"
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.35
            }

            PlasmaComponents.Label {
                visible: root.connected && root.printing && root.remainingMin > 0
                Layout.rightMargin: Kirigami.Units.smallSpacing / 2
                text: root.fmtEta(root.remainingMin)
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.75
            }

            // percent rides inside the bar; the fill acts as its background
            Rectangle {
                id: bar
                Layout.alignment: Qt.AlignVCenter
                visible: root.connected && root.printing
                implicitWidth: Kirigami.Units.gridUnit * 7
                implicitHeight: Math.round(Kirigami.Units.gridUnit * 0.95)
                radius: height / 2
                color: root.track

                Rectangle {
                    id: fill
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(height, parent.width * Math.min(root.percent, 100) / 100)
                    height: parent.height
                    radius: height / 2
                    color: root.barColor
                    Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
                }

                PlasmaComponents.Label {
                    anchors.centerIn: parent
                    text: root.percent + "%"
                    font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.62
                    font.weight: Font.Bold
                    // dark once the fill has reached the label, light before that
                    color: fill.width >= parent.width / 2 + implicitWidth / 2
                           ? "#0b0b0b" : Kirigami.Theme.textColor
                }
            }

            // the monitor writes a timestamp on every report; if it goes quiet
            // the numbers on screen are lying
            PlasmaComponents.Label {
                visible: root.connected && root.stale
                text: "!"
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.7
                font.weight: Font.Bold
                color: root.failed
            }

            PlasmaComponents.Label {
                visible: root.connected && !root.printing
                text: root.label
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.7
            }
        }
    }

    // ---------------------------------------------------------------- popup
    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 21
        Layout.preferredWidth: Kirigami.Units.gridUnit * 21
        Layout.minimumHeight: Kirigami.Units.gridUnit * 26

        Rectangle {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            radius: Kirigami.Units.gridUnit * 0.9
            color: Qt.rgba(1, 1, 1, 0.05)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.09)
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing * 1.2
            spacing: Kirigami.Units.largeSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Image {
                    source: Qt.resolvedUrl("bambu.svg")
                    sourceSize.width: Kirigami.Units.iconSizes.smallMedium * 2
                    sourceSize.height: Kirigami.Units.iconSizes.smallMedium * 2
                    width: Kirigami.Units.iconSizes.smallMedium
                    height: width
                    smooth: true
                }
                ColumnLayout {
                    spacing: 0
                    PlasmaComponents.Label {
                        text: root.model
                        font.family: root.uiFont
                        font.weight: Font.Bold
                        font.pixelSize: Kirigami.Units.gridUnit * 0.95
                    }
                    PlasmaComponents.Label {
                        text: root.connected ? root.label : "offline"
                        font.family: root.uiFont
                        font.pixelSize: Kirigami.Units.gridUnit * 0.7
                        color: root.connected ? root.barColor : Kirigami.Theme.textColor
                        opacity: root.connected ? 1 : 0.5
                    }
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.Label {
                    visible: root.connected && root.printing
                    text: root.percent + "%"
                    font.family: root.uiFont
                    font.weight: Font.Bold
                    font.pixelSize: Kirigami.Units.gridUnit * 1.5
                    color: root.barColor
                }
            }

            PlasmaComponents.Label {
                Layout.fillWidth: true
                visible: root.name !== ""
                text: root.name
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.85
                elide: Text.ElideMiddle
            }

            Rectangle {
                Layout.fillWidth: true
                visible: root.connected
                implicitHeight: Kirigami.Units.gridUnit * 0.5
                radius: height / 2
                color: root.track

                Rectangle {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width * Math.min(root.percent, 100) / 100
                    height: parent.height
                    radius: height / 2
                    color: root.barColor
                    Behavior on width { NumberAnimation { duration: 400 } }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                visible: root.connected
                columns: 2
                rowSpacing: Kirigami.Units.smallSpacing
                columnSpacing: Kirigami.Units.largeSpacing

                PlasmaComponents.Label {
                    text: "Remaining"; opacity: 0.55; font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }
                PlasmaComponents.Label {
                    Layout.alignment: Qt.AlignRight
                    text: root.fmtEta(root.remainingMin)
                    font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }

                PlasmaComponents.Label {
                    text: "Layer"; opacity: 0.55; font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }
                PlasmaComponents.Label {
                    Layout.alignment: Qt.AlignRight
                    text: root.totalLayers > 0 ? root.curLayer + " / " + root.totalLayers : "—"
                    font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }

                PlasmaComponents.Label {
                    text: "Nozzle / bed"; opacity: 0.55; font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }
                PlasmaComponents.Label {
                    Layout.alignment: Qt.AlignRight
                    text: Math.round(root.nozzle) + "° / " + Math.round(root.bed) + "°"
                    font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.75
                }
            }

            // camera: the monitor drops the newest JPEG on disk, the query
            // string is what forces QML to drop its cached copy.
            // clip:true only clips to the bounding box, so the rounded corners
            // need an actual mask.
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: width * 0.52

                Rectangle {
                    id: camMask
                    anchors.fill: parent
                    radius: Kirigami.Units.gridUnit * 0.7
                    visible: false
                    layer.enabled: true
                }

                Item {
                    id: camBody
                    anchors.fill: parent
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        maskEnabled: true
                        maskSource: camMask
                        maskThresholdMin: 0.5
                        maskSpreadAtMin: 1.0
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: Qt.rgba(0, 0, 0, 0.35)
                    }

                    // double buffered: a single Image blanks itself while
                    // decoding the next frame, which reads as flicker
                    Item {
                        id: cam
                        anchors.fill: parent
                        property bool showA: true
                        property bool everLoaded: false

                        function load(tick) {
                            var target = showA ? imgB : imgA
                            target.source = "file://" + root.homeDir
                                            + "/.cache/bambu-frame.jpg?t=" + tick
                        }

                        Image {
                            id: imgA
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectCrop
                            cache: false
                            asynchronous: true
                            opacity: cam.showA ? 1 : 0
                            onStatusChanged: if (status === Image.Ready && !cam.showA) {
                                cam.showA = true; cam.everLoaded = true
                            }
                        }

                        Image {
                            id: imgB
                            anchors.fill: parent
                            fillMode: Image.PreserveAspectCrop
                            cache: false
                            asynchronous: true
                            opacity: cam.showA ? 0 : 1
                            onStatusChanged: if (status === Image.Ready && cam.showA) {
                                cam.showA = false; cam.everLoaded = true
                            }
                        }

                        Connections {
                            target: root
                            function onFrameTickChanged() { cam.load(root.frameTick) }
                        }

                        Component.onCompleted: load(0)
                    }
                }

                PlasmaComponents.Label {
                    anchors.centerIn: parent
                    visible: !cam.everLoaded
                    text: "camera…"
                    font.family: root.uiFont
                    font.pixelSize: Kirigami.Units.gridUnit * 0.7
                    opacity: 0.5
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                ActionButton {
                    Layout.fillWidth: true
                    accent: root.paused
                    label: "Pause"
                    iconName: "media-playback-pause"
                    enabled: root.connected && root.state_ === "RUNNING"
                    onActivated: root.send("pause")
                }
                ActionButton {
                    Layout.fillWidth: true
                    accent: root.green
                    label: "Resume"
                    iconName: "media-playback-start"
                    enabled: root.connected && root.state_ === "PAUSE"
                    onActivated: root.send("resume")
                }
                ActionButton {
                    Layout.fillWidth: true
                    accent: root.failed
                    label: "Stop"
                    iconName: "media-playback-stop"
                    confirmLabel: "Sure?"
                    needsConfirm: true
                    enabled: root.connected && root.printing
                    onActivated: root.send("stop")
                }
            }

            ActionButton {
                Layout.fillWidth: true
                accent: "#4a8cf7"
                label: "Print again"
                iconName: "media-playlist-repeat"
                confirmLabel: "Start print?"
                needsConfirm: true
                enabled: root.connected && !root.printing && root.name !== ""
                onActivated: root.send("reprint")
            }

            Item { Layout.fillHeight: true }

            PlasmaComponents.Label {
                Layout.fillWidth: true
                visible: !root.connected && root.error !== ""
                text: root.error
                wrapMode: Text.WordWrap
                font.family: root.uiFont
                font.pixelSize: Kirigami.Units.gridUnit * 0.65
                opacity: 0.55
            }
        }
    }

    toolTipMainText: root.connected ? (root.model + " · " + root.label) : "Bambu — offline"
    toolTipSubText: root.printing
        ? root.name + "\n" + root.percent + "% · " + root.fmtEta(root.remainingMin) + " left"
        : (root.error || "")
}
