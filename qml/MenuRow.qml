import QtQuick
import qs.Commons
import qs.Ui

CursorSurface {
  id: menuRow
  required property var panel
  signal chosen()
  signal hovered()
  property string label: ""
  property bool selected: false
  property bool danger: false
  property string hint: ""
  property bool divider: false

  visible: enabled
  foreground: menuRow.panel.foreground
  hasCursor: selected
  implicitHeight: Style.space(32)
  fill: danger ? Style.hoverFillFor(menuRow.panel.urgentColor, menuRow.panel.urgentColor) : Style.hoverFillFor(foreground, Color.accent)
  radius: Style.cornerRadius

  MouseArea {
    anchors.fill: parent
    onClicked: menuRow.chosen()
  }

  // Select on real pointer motion only: the menu opens under a pointer at
  // rest, and Enter must run the option the keyboard chose.
  readonly property bool pointerOver: menuHover.hovered
  HoverHandler {
    id: menuHover
    cursorShape: Qt.PointingHandCursor
  }

  Connections {
    target: menuRow.panel
    function onPointerMoved() {
      if (menuHover.hovered) menuRow.hovered()
    }
  }

  Rectangle {
    visible: menuRow.divider
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    height: 1
    color: Qt.rgba(menuRow.panel.foreground.r, menuRow.panel.foreground.g, menuRow.panel.foreground.b, 0.08)
  }

  Text {
    id: menuHint
    anchors.right: parent.right
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: menuRow.hint
    color: menuRow.panel.dim
    font.family: menuRow.panel.contentFontFamily
    font.pixelSize: Style.font.caption
  }

  Text {
    anchors.left: parent.left
    anchors.right: menuHint.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(8)
    verticalAlignment: Text.AlignVCenter
    textFormat: Text.PlainText
    text: menuRow.label
    color: menuRow.danger ? menuRow.panel.urgentColor : menuRow.panel.foreground
    font.family: menuRow.panel.contentFontFamily
    font.pixelSize: Style.font.body
    elide: Text.ElideRight
  }
}
