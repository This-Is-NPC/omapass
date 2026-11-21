import QtQuick
import qs.Commons
import qs.Ui

// Filter chip and segmented-control option; active uses the accent.
BorderSurface {
  id: pill
  required property var panel
  property string label: ""
  property bool active: false
  property bool hasCursor: false
  property bool borderless: false
  // Hover lights the pill only where nothing else tracks the cursor.
  property bool hoverFollows: false
  signal clicked()
  signal hovered()

  // Read by the tests: the pointer is over this chip.
  readonly property bool pointerOver: pillHover.hovered
  readonly property bool hot: hasCursor || (hoverFollows && pillHover.hovered)
  implicitWidth: pillText.implicitWidth + Style.space(20)
  implicitHeight: pillText.implicitHeight + Style.space(8)
  radius: Style.cornerRadius
  color: active ? Qt.rgba(pill.panel.accentColor.r, pill.panel.accentColor.g, pill.panel.accentColor.b, 0.16)
    : (hot ? Qt.rgba(pill.panel.foreground.r, pill.panel.foreground.g, pill.panel.foreground.b, 0.06) : "transparent")
  borderSpec: active ? Border.flat(pill.panel.accentColor, 1)
    : (borderless ? Border.none()
      : Border.flat(hot ? Qt.rgba(pill.panel.foreground.r, pill.panel.foreground.g, pill.panel.foreground.b, 0.4) : pill.panel.subtleBorder, 1))

  Text {
    id: pillText
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: pill.label
    color: pill.active ? pill.panel.accentColor : (pill.hot ? pill.panel.foreground : pill.panel.dim)
    font.family: pill.panel.contentFontFamily
    font.pixelSize: Style.font.bodySmall
  }

  MouseArea {
    anchors.fill: parent
    onClicked: pill.clicked()
  }

  // A hover handler leaves the event to the panel's pointer tracker, so
  // `hovered` fires on real pointer motion only, never when the pill
  // appears under a pointer at rest.
  HoverHandler {
    id: pillHover
    cursorShape: Qt.PointingHandCursor
  }

  Connections {
    target: pill.panel
    function onPointerMoved() {
      if (pillHover.hovered) pill.hovered()
    }
  }
}
