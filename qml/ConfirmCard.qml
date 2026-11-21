import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Confirm dialog card. Same keys as the shell's ConfirmDialog: Esc
// cancels, Left/Right/Tab switch, Enter runs the selected button.
Item {
  id: dialog
  required property var panel
  property bool opened: false
  property string message: ""
  property string detail: ""
  property string confirmText: "Confirm"
  // Only a Dismiss button: a message to read, not a question.
  property bool alertOnly: false
  property int selectedIndex: 0
  signal canceled()
  signal confirmed()

  onOpenedChanged: {
    if (opened) {
      // Start on Cancel: Enter must never confirm a destructive action.
      selectedIndex = 0
      Qt.callLater(function() { dialog.forceActiveFocus() })
    }
  }

  onCanceled: closeConfirm()
  onConfirmed: handleConfirm()

  Keys.priority: Keys.BeforeItem
  Keys.onPressed: function(event) {
    if (dialog.handleKey(event))
      event.accepted = true
  }

  // Name what Replace overwrites, from the loaded list, and where the item
  // ends up: the helper moves it to the form's folder. A folder is named only
  // when the list shows one; a stale list says nothing about it.
  function askReplace(action, account, folder) {
    var nostr = action === "replaceNostr"
    var held = Model.foldersOf(panel.vault.records, account, nostr ? "nostr" : "")
    var label = function(f) { return f === "" ? "no folder" : f }
    panel.confirmAction = action
    panel.confirmMessage = "Replace " + (nostr ? "the Nostr key " : "the secret for ") + account
      + (held.length > 0 ? " in " + held.map(label).join(", ") : "") + "?"
    var target = label(String(folder || ""))
    var where = held.length === 0 ? "It is stored in " + target + ". "
      : (held.length === 1 && Model.sameName(held[0], folder)) ? "" : "It moves to " + target + ". "
    panel.confirmDetail = where + (nostr ? "The old key is lost for good." : "The old password is lost for good.")
    panel.confirmConfirmText = "Replace"
    panel.confirmOpen = true
  }

  // A write that may have damaged the keyring: a footer flash is too short and
  // too narrow to carry the instructions. Keep the whole text in a dialog until
  // dismissed, and notify too, in case the panel is closed by then.
  function reportDamaged(err, code) {
    if (code !== panel.vault.exitDamaged)
      return false
    var text = err || "The keyring may be damaged. Do not log out or reboot."
    panel.vault.notifyFailure("Keyring may be damaged", text)
    if (panel.opened) {
      panel.confirmAction = "alert"
      panel.confirmMessage = "Keyring may be damaged"
      panel.confirmDetail = text
      panel.confirmOpen = true
    }
    return true
  }

  function closeConfirm() {
    panel.confirmOpen = false
    panel.confirmAction = ""
    panel.confirmMessage = ""
    panel.confirmDetail = "This can't be undone."
    panel.pendingRemoveRecord = null
    // The dialog held focus; give it back or keys are dropped.
    Qt.callLater(function() {
      if (panel.opened && !panel.confirmOpen) panel.focusInput()
    })
  }

  function handleConfirm() {
    if (panel.confirmAction === "remove") {
      var record = panel.pendingRemoveRecord
      var account = record ? record.account : ""
      var kind = record ? record.kind : ""
      var folder = record ? record.folder : ""
      closeConfirm()
      if (!account) return
      panel.vault.remove(account, function(ok, err, code) {
        if (!ok && reportDamaged(err, code))
          return
        panel.flashCopied(ok ? "Removed" : (err || "Could not remove"), ok)
      }, kind, folder)
    } else if (panel.confirmAction === "replaceAccount") {
      closeConfirm()
      panel.saveAdd(true)
    } else if (panel.confirmAction === "replaceNostr") {
      closeConfirm()
      panel.generateNostr(true)
    } else {
      closeConfirm()
    }
  }

  function removeRecord(record) {
    if (!record) return
    panel.confirmAction = "remove"
    panel.pendingRemoveRecord = record
    // Same account in several folders: say which one goes.
    panel.confirmMessage = Model.isDuplicate(panel.duplicateKeys, record)
      ? "Remove " + record.account + " from " + (record.folder || "no folder") + "?"
      : "Remove " + record.account + "?"
    panel.confirmConfirmText = "Remove"
    panel.confirmOpen = true
  }

  function toggleSelection() {
    if (!dialog.alertOnly)
      dialog.selectedIndex = dialog.selectedIndex === 0 ? 1 : 0
  }

  function handleKey(event) {
    if (!dialog.opened) return false
    if (event.key === Qt.Key_Escape) {
      dialog.canceled()
      return true
    } else if (event.key === Qt.Key_Left || event.key === Qt.Key_Right
        || event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
      dialog.toggleSelection()
      return true
    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      if (dialog.selectedIndex === 0) dialog.canceled()
      else dialog.confirmed()
      return true
    }
    return false
  }

  visible: opened

  PointerTracker { panel: dialog.panel }

  Rectangle {
    anchors.fill: parent
    color: Qt.rgba(Color.background.r, Color.background.g, Color.background.b, 0.7)
    MouseArea { anchors.fill: parent; onClicked: dialog.canceled() }
  }

  BorderSurface {
    id: dialogCard
    anchors.centerIn: parent
    width: parent.width - Style.space(32)
    height: dialogColumn.implicitHeight + contentTopInset + contentBottomInset
    color: Color.popups.background
    borderSpec: Border.flat(dialog.panel.subtleBorder, 1)
    radius: Style.cornerRadius
    padding: Style.space(16)

    MouseArea { anchors.fill: parent }

    Column {
      id: dialogColumn
      x: dialogCard.contentLeftInset
      y: dialogCard.contentTopInset
      width: dialogCard.width - dialogCard.contentLeftInset - dialogCard.contentRightInset
      spacing: Style.space(6)

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WrapAnywhere
        textFormat: Text.PlainText
        text: dialog.message
        color: dialog.panel.foreground
        font.family: dialog.panel.contentFontFamily
        font.pixelSize: Style.font.body
        font.bold: true
      }

      Text {
        width: parent.width
        visible: dialog.detail !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: dialog.detail
        color: dialog.panel.dim
        font.family: dialog.panel.contentFontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Item { width: 1; height: Style.space(8) }

      RowLayout {
        width: parent.width
        spacing: Style.space(10)

        SolidButton {
          panel: dialog.panel
          Layout.fillWidth: true
          Layout.preferredWidth: 1
          label: dialog.alertOnly ? "Dismiss" : "Cancel"
          selected: dialog.selectedIndex === 0
          cursorDriven: true
          onHovered: dialog.selectedIndex = 0
          onClicked: dialog.canceled()
        }

        SolidButton {
          panel: dialog.panel
          visible: !dialog.alertOnly
          Layout.fillWidth: true
          Layout.preferredWidth: 1
          label: dialog.confirmText
          danger: true
          selected: dialog.selectedIndex === 1
          cursorDriven: true
          onHovered: dialog.selectedIndex = 1
          onClicked: dialog.confirmed()
        }
      }
    }
  }
}
