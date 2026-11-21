import QtQuick
import qs.Commons
import qs.Ui

// Text field whose focus ring uses the accent color.
TextField {
  id: field
  required property var panel
  foreground: field.panel.foreground
  font.family: field.panel.contentFontFamily
  background: BorderSurface {
    color: Qt.rgba(field.panel.foreground.r, field.panel.foreground.g, field.panel.foreground.b, field.activeFocus ? 0.05 : 0.03)
    borderSpec: Border.flat(field.activeFocus ? field.panel.accentColor
      : (field.hovered || field.hasCursor ? Qt.rgba(field.panel.foreground.r, field.panel.foreground.g, field.panel.foreground.b, 0.35)
        : field.panel.subtleBorder), 1)
    radius: Style.cornerRadius
  }
}
