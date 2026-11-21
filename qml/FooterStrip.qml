import QtQuick
import qs.Commons
import qs.Ui

// Fixed strip under the list: key hints at rest, status after an action.
Item {
  id: footer
  required property var panel
  readonly property bool statusOk: !footer.panel.showListError && (footer.panel.savedFlash || footer.panel.flashOk)
  visible: footer.panel.view === "list"
  anchors.left: parent.left
  anchors.right: parent.right
  anchors.bottom: parent.bottom
  height: footer.panel.footerHeight

  Text {
    visible: !footer.panel.toastVisible
    anchors.fill: parent
    anchors.leftMargin: Style.space(8)
    anchors.rightMargin: Style.space(8)
    verticalAlignment: Text.AlignVCenter
    horizontalAlignment: Text.AlignHCenter
    textFormat: Text.PlainText
    elide: Text.ElideRight
    text: "↵ Copy   ·   ⇧↵ Type   ·   + Add   ·   ⋯ More"
    color: footer.panel.dim
    font.family: footer.panel.contentFontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    visible: footer.panel.toastVisible
    anchors.centerIn: parent
    spacing: Style.space(8)

    Text {
      text: footer.statusOk ? "󰄬" : "󰀦"
      color: footer.statusOk ? footer.panel.accentColor : footer.panel.urgentColor
      font.family: footer.panel.contentFontFamily
      font.pixelSize: Style.font.body
    }

    Text {
      width: Math.min(implicitWidth, footer.width - Style.space(48))
      textFormat: Text.PlainText
      elide: Text.ElideRight
      text: footer.panel.showListError ? footer.panel.listError : (footer.panel.savedFlash ? "Saved" : footer.panel.copyFlashText)
      color: footer.statusOk ? footer.panel.foreground : footer.panel.urgentColor
      font.family: footer.panel.contentFontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }
}
