import QtQuick
import qs.Commons
import qs.Ui

// Full-width action button; primary is filled with the accent.
BorderSurface {
  id: solid
  required property var panel
  property string label: ""
  property bool primary: false
  // Destructive: filled with the theme's urgent color.
  property bool danger: false
  // Dimmed, still clickable (for example to show why it cannot run).
  property bool muted: false
  property bool selected: false
  // Where the parent tracks the cursor, only `selected` lights the button.
  property bool cursorDriven: false
  signal clicked()
  signal hovered()

  readonly property color fillColor: danger ? solid.panel.urgentColor : solid.panel.accentColor
  readonly property bool filled: primary || danger
  readonly property bool pointerOver: solidHover.hovered
  readonly property bool hot: selected || (!cursorDriven && solidHover.hovered)
  opacity: muted ? 0.45 : 1
  implicitWidth: solidText.implicitWidth + Style.space(24)
  implicitHeight: solidText.implicitHeight + Style.space(14)
  radius: Style.cornerRadius
  color: filled
    ? (hot ? Qt.lighter(fillColor, 1.15) : fillColor)
    : Qt.rgba(solid.panel.foreground.r, solid.panel.foreground.g, solid.panel.foreground.b, hot ? 0.12 : 0.05)
  borderSpec: filled ? (selected ? Border.flat(solid.panel.foreground, 1) : Border.none())
    : Border.flat(selected ? solid.panel.foreground : solid.panel.subtleBorder, 1)

  Text {
    id: solidText
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: solid.label
    color: solid.filled ? Color.background : solid.panel.foreground
    font.family: solid.panel.contentFontFamily
    font.pixelSize: Style.font.body
    font.bold: solid.filled
  }

  MouseArea {
    anchors.fill: parent
    onClicked: solid.clicked()
  }

  // A hover handler, not MouseArea hover: it leaves the event to the
  // panel's pointer tracker.
  HoverHandler {
    id: solidHover
    cursorShape: Qt.PointingHandCursor
  }

  // Select on real pointer motion only, never because the button appeared
  // under a pointer at rest.
  Connections {
    target: solid.panel
    function onPointerMoved() {
      if (solidHover.hovered) solid.hovered()
    }
  }
}
