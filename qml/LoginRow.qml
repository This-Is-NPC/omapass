import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

CursorSurface {
  id: row
  required property var panel
  required property var listView
  property var record: null
  property int rowIndex: -1
  property bool actionsMenuOpen: false
  property int menuIndex: 0
  property bool separator: false

  // No row stays lit while the keyboard cursor is on the folder chips:
  // Enter acts on the chip there.
  readonly property bool selected: rowIndex === row.panel.listIndex && row.panel.focusSection !== "folders"
  readonly property bool nostr: Model.isNostr(record)
  readonly property bool copied: row.panel.copiedFlash && row.panel.flashOk && record !== null
    && row.panel.lastCopiedAccount === String(record.account || "")
    && row.panel.lastCopiedKind === String(record.kind || "")
    && row.panel.lastCopiedFolder === String(record.folder || "")
  readonly property var menuOptions: [
    { id: "copyAccount", label: "Copy account", hint: "u" },
    { id: "typePassword", label: nostr ? "Type key" : "Type password", hint: "⇧↵" },
    { id: "remove", label: "Remove", hint: "Del" }
  ]

  hasCursor: row.panel.focusSection === "list" && row.panel.listIndex === rowIndex && rowIndex >= 0
  current: selected
  foreground: row.panel.foreground
  implicitHeight: row.panel.rowHeight

  // Below the button when it fits, else above it without covering the
  // search area. A short list has neither: reserve room and open below.
  function placeActionsMenu() {
    var gap = Style.space(4)
    var top = moreButton.mapToItem(row.listView, 0, 0).y
    var h = actionsPopup.implicitHeight
    var below = top + moreButton.height + gap
    var wanted = below
    if (!row.panel.menuRoom) {
      if (below + h <= row.listView.height)
        wanted = below
      else if (top - h - gap >= row.listView.listArea.y)
        wanted = top - h - gap
      else
        row.panel.menuRoom = true
    }
    var py = Math.max(gap, Math.min(wanted, row.listView.height - h - gap))
    actionsPopup.y = py - actionsPopup.parent.mapToItem(row.listView, 0, 0).y
  }

  function openActionsMenu() {
    menuIndex = 0
    placeActionsMenu()
    actionsPopup.open()
  }

  function scrollIntoView() {
    if (row.rowIndex !== row.panel.listIndex) return
    row.listView.ensureVisible(row)
  }

  function moveMenuCursor(delta) {
    if (menuOptions.length === 0) return
    menuIndex = (menuIndex + delta + menuOptions.length) % menuOptions.length
  }

  function activateMenuOption() {
    if (menuIndex < 0 || menuIndex >= menuOptions.length) return
    var id = menuOptions[menuIndex].id
    // Close first so the menu is not left drawn over a confirm dialog.
    actionsPopup.close()
    runMenuAction(id)
  }

  function runMenuAction(actionId) {
    if (!row.record) return
    if (actionId === "copyAccount")
      row.panel.copyAccount(row.record)
    else if (actionId === "typePassword")
      row.panel.typeRecord(row.record)
    else if (actionId === "remove")
      row.panel.confirmCard.removeRecord(row.record)
  }

  readonly property bool pointerOver: rowHover.hovered
  HoverHandler {
    id: rowHover
    cursorShape: Qt.PointingHandCursor
  }

  // Select on real pointer motion only: Qt re-delivers hover when rows move
  // under a pointer at rest (search, open), which must not steer the keys.
  Connections {
    target: row.panel
    function onPointerMoved() {
      if (rowHover.hovered && row.rowIndex >= 0)
        row.panel.setListCursor(row.rowIndex)
    }
  }

  // The panel grew to make room for the menu: place it again.
  Connections {
    target: row.listView
    function onHeightChanged() {
      if (actionsPopup.opened) row.placeActionsMenu()
    }
  }

  Connections {
    target: row.panel
    function onListIndexChanged() {
      if (row.rowIndex === row.panel.listIndex)
        Qt.callLater(row.scrollIntoView)
    }
    function onOpenOverflowForRow(idx) {
      if (idx === row.rowIndex)
        row.openActionsMenu()
    }
  }

  Rectangle {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(12)
    height: 1
    visible: row.separator && !row.selected
    color: Qt.rgba(row.panel.foreground.r, row.panel.foreground.g, row.panel.foreground.b, 0.07)
  }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(8)
    spacing: Style.space(10)

    BorderSurface {
      Layout.alignment: Qt.AlignVCenter
      implicitWidth: Style.space(22)
      implicitHeight: Style.space(22)
      color: Qt.rgba(row.panel.foreground.r, row.panel.foreground.g, row.panel.foreground.b, 0.08)
      radius: Style.cornerRadius

      Text {
        anchors.centerIn: parent
        text: row.nostr ? "󰌆" : (row.record ? String(row.record.account || "?").charAt(0).toUpperCase() : "")
        textFormat: Text.PlainText
        color: row.nostr ? (row.selected ? row.panel.accentColor : row.panel.dim)
          : (row.selected ? row.panel.selectedText : row.panel.dim)
        font.family: row.panel.contentFontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Item {
      Layout.fillWidth: true
      Layout.fillHeight: true

      TapHandler {
        acceptedButtons: Qt.LeftButton
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: row.panel.copyRecord(row.record)
      }

      // The name takes its own width, the tag sits right after it.
      Row {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)

        Text {
          width: Math.min(implicitWidth, Math.max(0, parent.parent.width
            - (row.nostr ? nsecBadge.width + parent.spacing : 0)
            - (warnGlyph.visible ? warnGlyph.width + parent.spacing : 0)))
          textFormat: Text.PlainText
          text: row.record ? row.record.account : ""
          color: row.selected ? row.panel.selectedText : row.panel.foreground
          font.family: row.panel.contentFontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        // The helper flags names with control or invisible characters, and
        // the panel flags the same account in several folders.
        Text {
          id: warnGlyph
          visible: row.record !== null && (String(row.record.warn || "") !== ""
                   || Model.isDuplicate(row.panel.duplicateKeys, row.record))
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: "⚠"
          color: row.panel.urgentColor
          font.family: row.panel.contentFontFamily
          font.pixelSize: Style.font.body
        }

        BorderSurface {
          id: nsecBadge
          visible: row.nostr
          anchors.verticalCenter: parent.verticalCenter
          implicitWidth: nsecText.implicitWidth + Style.space(10)
          implicitHeight: nsecText.implicitHeight + Style.space(2)
          color: Qt.rgba(row.panel.foreground.r, row.panel.foreground.g, row.panel.foreground.b, 0.06)
          radius: Style.cornerRadius

          Text {
            id: nsecText
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: "nsec"
            color: row.panel.dim
            font.family: row.panel.contentFontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }

    PanelActionButton {
      id: copyButton
      // Actions show on the selected (or hovered) row only.
      visible: row.selected || row.actionsMenuOpen
      iconText: row.copied ? "󰄬" : "󰆏"
      tooltipText: row.nostr ? "Copy key" : "Copy password"
      foreground: row.copied ? row.panel.accentColor : row.panel.foreground
      fontFamily: row.panel.contentFontFamily
      Layout.alignment: Qt.AlignVCenter
      onClicked: row.panel.copyRecord(row.record)
    }

    PanelActionButton {
      id: moreButton
      visible: row.selected || row.actionsMenuOpen
      iconText: "󰇘"
      tooltipText: "More"
      foreground: row.panel.foreground
      fontFamily: row.panel.contentFontFamily
      Layout.alignment: Qt.AlignVCenter
      onClicked: row.openActionsMenu()
    }

    // The menu follows the panel's flag: close() and a popout switch
    // clear it without a click in the popup.
    Connections {
      target: row.panel
      function onActionsMenuOpenChanged() {
        if (!row.panel.actionsMenuOpen && actionsPopup.opened) actionsPopup.close()
      }
    }

    // The list rebuilt this row while its menu was open: the popup is gone
    // without its closing signal, so clear the flag and return the keys.
    Component.onDestruction: if (row.actionsMenuOpen) {
      row.panel.actionsMenuOpen = false
      Qt.callLater(row.panel.refocusCatcher)
    }

    Popup {
      id: actionsPopup
      x: moreButton.x + moreButton.width - width
      y: moreButton.y + moreButton.height + Style.space(4)
      width: Style.space(190)
      padding: 0
      modal: false
      focus: true
      closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

      function handleKey(event) {
        if (event.key === Qt.Key_Escape) {
          close()
          event.accepted = true
          return
        }
        if (event.key === Qt.Key_Down || event.text === "j") {
          row.moveMenuCursor(1)
          event.accepted = true
          return
        }
        if (event.key === Qt.Key_Up || event.text === "k") {
          row.moveMenuCursor(-1)
          event.accepted = true
          return
        }
        // The hints shown in the menu work while it is open.
        var action = ""
        if (event.key === Qt.Key_Delete || event.text === "x" || event.text === "X")
          action = "remove"
        else if (event.text === "u" || event.text === "U")
          action = "copyAccount"
        else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
            && (event.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)))
          action = "typePassword"
        if (action !== "") {
          close()
          row.runMenuAction(action)
          event.accepted = true
          return
        }
        // Enter or a click runs an option. Space does nothing here: it must
        // never type a secret.
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          row.activateMenuOption()
          event.accepted = true
        } else if (event.key === Qt.Key_Space) {
          event.accepted = true
        }
      }

      onOpenedChanged: {
        row.actionsMenuOpen = opened
        row.panel.actionsMenuOpen = opened
        if (!opened) row.panel.menuRoom = false
        if (opened) {
          row.menuIndex = 0
          Qt.callLater(function() { actionsPopupContent.forceActiveFocus() })
        } else if (row.panel.opened) {
          Qt.callLater(row.panel.refocusCatcher)
        }
      }

      background: BorderSurface {
        color: Color.background
        borderSpec: Border.flat(row.panel.dim, 1)
        radius: Style.cornerRadius
      }

      contentItem: Column {
        id: actionsPopupContent
        width: parent.width
        focus: true
        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) { actionsPopup.handleKey(event) }

        // The popup sits above the key catcher, which then gets no hover.
        PointerTracker { panel: row.panel }

        Repeater {
          model: row.menuOptions

          MenuRow {
            panel: row.panel
            required property var modelData
            required property int index
            width: parent.width
            label: String(modelData.label || "")
            hint: String(modelData.hint || "")
            danger: modelData.id === "remove"
            divider: modelData.id === "remove"
            selected: row.menuIndex === index
            onHovered: row.menuIndex = index
            onChosen: {
              var id = String(modelData.id || "")
              actionsPopup.close()
              row.runMenuAction(id)
            }
          }
        }
      }
    }
  }
}
