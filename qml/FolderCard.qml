import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// A folder as a card: header with name and count, then its logins.
BorderSurface {
  id: card
  required property var panel
  required property var listView
  property string title: ""
  property var records: []
  property bool showHeader: true

  height: visible ? cardColumn.implicitHeight + contentTopInset + contentBottomInset : 0
  color: card.panel.cardFill
  borderSpec: Border.flat(card.panel.cardBorder, 1)
  radius: Style.cornerRadius
  bottomPadding: Style.space(4)

  Column {
    id: cardColumn
    x: card.contentLeftInset
    y: card.contentTopInset
    width: card.width - card.contentLeftInset - card.contentRightInset

    RowLayout {
      visible: card.showHeader
      width: parent.width
      height: card.panel.headerHeight + Style.space(8)
      spacing: Style.space(6)

      Text {
        Layout.fillWidth: true
        Layout.leftMargin: Style.space(12)
        text: card.title.toUpperCase()
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: card.panel.dim
        font.family: card.panel.contentFontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1
        font.bold: true
      }

      BorderSurface {
        Layout.rightMargin: Style.space(12)
        implicitWidth: Math.max(implicitHeight, countText.implicitWidth + Style.space(12))
        implicitHeight: countText.implicitHeight + Style.space(4)
        color: Qt.rgba(card.panel.foreground.r, card.panel.foreground.g, card.panel.foreground.b, 0.08)
        radius: Style.cornerRadius

        Text {
          id: countText
          anchors.centerIn: parent
          text: String(card.records.length)
          textFormat: Text.PlainText
          color: card.panel.dim
          font.family: card.panel.contentFontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    Repeater {
      model: card.records

      LoginRow {
        panel: card.panel
        listView: card.listView
        required property var modelData
        required property int index
        width: cardColumn.width
        record: modelData
        rowIndex: card.panel.indexOfRecord(modelData)
        separator: index < card.records.length - 1
      }
    }
  }
}
