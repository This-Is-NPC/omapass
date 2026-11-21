import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.this-is-npc.omapass"
  ipcTarget: "io.github.this-is-npc.omapass"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  property string searchText: ""
  // The selected row is kept by identity (account, kind, folder), never by
  // position: a list refresh may move rows, and Enter must act on the item
  // the user saw selected. Empty or gone: the first row.
  property string selectedId: ""
  readonly property int listIndex: Math.max(0, Model.indexOfIdentity(visibleRecords, selectedId))
  property bool copiedFlash: false
  property string copyFlashText: ""
  property bool flashOk: true
  property string view: "list"
  property string folderFilter: Model.ALL_FOLDERS
  property int folderIndex: 0
  property bool actionsMenuOpen: false
  property string focusSection: "search"
  property string addFolder: ""
  property string addAccount: ""
  property string addPassword: ""
  property string addError: ""
  property string addKind: "account"
  property bool addPasswordVisible: false
  // True while the password field holds the generated one; never the secret.
  property bool addPasswordGenerated: false
  // Set while the row menu needs more list height than a short list has.
  property bool menuRoom: false
  property bool confirmOpen: false
  property string confirmMessage: ""
  property string confirmConfirmText: "Confirm"
  property string confirmDetail: "This can't be undone."
  property string confirmAction: ""
  property var pendingRemoveRecord: null
  property var focusSnapshot: null
  // Bumped by close(): an open() still waiting for the focus snapshot then
  // shows nothing. `opening` is true during that wait.
  property int openToken: 0
  property bool opening: false
  // Last pointer position seen over the panel, null until the first one.
  property var lastPointer: null
  // The pointer really moved (not just re-delivered hover) and every
  // hover state has caught up with it.
  signal pointerMoved()
  property bool popoutSwitchClosing: false
  // Where the panel opens: centered on the bar (default) or under the icon.
  // Stored in shell.json as this widget's "centerPanel" setting.
  readonly property bool centerPanel: setting("centerPanel", true) === true

  // Bumped whenever the form's secrets are wiped or the form is reset, so a
  // late helper reply (save, generate) can't put a secret back.
  property int formToken: 0
  property bool activateByReturn: false
  property bool modifiedReturn: false

  function wipeSensitiveState() {
    formToken++
    vault.forgetSecrets()
    addPassword = ""
    addPasswordVisible = false
    addPasswordGenerated = false
    addForm.clearPasswordField()
  }

  signal openOverflowForRow(int rowIndex)

  property bool savedFlash: false
  // Which row the last successful copy came from; never the secret itself.
  property string lastCopiedAccount: ""
  property string lastCopiedKind: ""
  property string lastCopiedFolder: ""

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color selectedText: Color.menu.selectedText
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  // Window border from the user's Hyprland config; null until read (or on
  // other compositors), which keeps the shell's default panel border.
  readonly property var frameBorderSpec: hypr.border
    ? {
        color: hypr.border.colors[0],
        widths: { top: hypr.border.width, right: hypr.border.width, bottom: hypr.border.width, left: hypr.border.width },
        gradient: { colors: hypr.border.colors, angle: hypr.border.angle, enabled: hypr.border.colors.length > 1 },
      }
    : Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
  readonly property color cardFill: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.03)
  readonly property color cardBorder: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.12)
  readonly property color accentColor: Color.accent
  readonly property color urgentColor: Color.urgent
  readonly property bool canSubmitAdd: addKind === "nostr"
    ? String(addAccount || "").trim() !== ""
    : (String(addFolder || "").trim() !== "" && String(addAccount || "").trim() !== "" && String(addPassword || "") !== "")
  readonly property color subtleBorder: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.18)

  readonly property int rowHeight: Style.space(36)
  // The panel is as tall as its content; the list scrolls past the cap.
  readonly property bool showListError: vault.listError !== "" && visibleRecords.length > 0
  readonly property bool toastVisible: showListError || copiedFlash || savedFlash
  // The footer strip is always there (hints or status), so the panel never
  // changes height for a toast or the actions menu.
  readonly property real footerHeight: Style.space(26)
  readonly property real footerReserve: footerHeight + Style.space(4)
  readonly property real desiredContentHeight: (view === "list" ? listView.chromeHeight : addForm.implicitHeight)
    + (view === "list"
      ? Style.space(8) + footerReserve
        + (visibleRecords.length === 0 ? Style.space(140)
          : Math.max(Math.min(listView.listContentHeight, listBudget), menuRoom ? Style.space(140) : 0))
      : 0)
  readonly property int headerHeight: Style.space(20)
  readonly property var filteredRecords: Model.filterByFolder(Model.searchBy(vault.records, searchText), folderFilter)
  readonly property var groups: folderFilter === Model.ALL_FOLDERS ? Model.groupByFolder(filteredRecords) : []
  // Keyboard order is screen order: in "All" the folder cards, row by row.
  readonly property var visibleRecords: folderFilter === Model.ALL_FOLDERS ? Model.flattenGroups(groups) : filteredRecords
  // Account+kind pairs that exist in more than one folder.
  readonly property var duplicateKeys: Model.duplicateKeys(vault.records)
  readonly property var folderChipIds: {
    var chips = [{ id: Model.ALL_FOLDERS, name: "All" }]
    var all = Model.groupByFolder(vault.records)
    for (var i = 0; i < all.length; i++)
      chips.push({ id: all[i].name, name: all[i].name + " " + all[i].total })
    return chips
  }
  readonly property int maxListBodyHeight: rowHeight * 8
  // In "All" the card headers are extra: up to three of them fit on top of
  // the eight rows, so a few folders do not cut the last card.
  readonly property int listBudget: maxListBodyHeight
    + (folderFilter === Model.ALL_FOLDERS ? Math.min(groups.length, 3) * (headerHeight + Style.space(14)) : 0)

  Component.onCompleted: hypr.refresh()

  // A summon while the panel is open takes the keyboard back: a
  // notification, an overlay or the lock may have taken it, and the panel
  // stays open without it. KeyboardPanel primes Exclusive focus again.
  function retakeKeyboard() {
    if (!opened) return
    panel.focusPrimed = false
    panel.beginFocusPrime()
  }

  // A list refresh rebuilds the rows, and with them an open row menu, so a
  // summon refreshes after the dialog or menu is gone.
  property bool refreshAfterModal: false
  onModalOpenChanged: {
    if (modalOpen || !refreshAfterModal) return
    refreshAfterModal = false
    if (opened) vault.refresh()
  }

  function open() {
    // A summon while a dialog or the row menu is open keeps it, and its
    // focus, as it is. Moving focus to the search field would let the next
    // Enter copy or type a secret behind it.
    if (opened && modalOpen) {
      refreshAfterModal = true
      retakeKeyboard()
      return
    }
    lastPointer = null
    modifiedReturn = false
    hypr.refresh()
    vault.cancelType()
    var token = ++openToken
    opening = true
    vault.captureFocus(function(snap) {
      // A close (or a newer open) since: the user gave up on this one.
      if (token !== root.openToken)
        return
      opening = false
      root.focusSnapshot = snap
      vault.refresh()
      root.controller.show()
      root.retakeKeyboard()
      // A summon with the form open keeps the focus on the field being edited.
      Qt.callLater(function() {
        if (root.opened && view === "list")
          listView.searchField.forceActiveFocus()
      })
    })
  }

  function close() {
    openToken++
    opening = false
    refreshAfterModal = false
    wipeSensitiveState()
    confirmDialog.closeConfirm()
    searchText = ""
    selectedId = ""
    copiedFlash = false
    copyFlashText = ""
    lastCopiedAccount = ""
    lastCopiedKind = ""
    lastCopiedFolder = ""
    savedFlash = false
    view = "list"
    folderFilter = Model.ALL_FOLDERS
    folderIndex = 0
    actionsMenuOpen = false
    focusSection = "search"
    addFolder = ""
    addAccount = ""
    addError = ""
    addKind = "account"
    focusSnapshot = null
    root.controller.hide()
  }
  // Another bar panel takes over: close exactly like close(), and tell
  // KeyboardPanel (which reads the flag on close) why.
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }

  function toggle() {
    if (root.opened || root.opening) root.close()
    else root.open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function indexOfRecord(record) {
    if (!record) return -1
    for (var i = 0; i < visibleRecords.length; i++) {
      var r = visibleRecords[i]
      if (r.account === record.account && r.folder === record.folder
          && String(r.kind || "") === String(record.kind || ""))
        return i
    }
    return -1
  }

  function currentRecord() {
    if (listIndex < 0 || listIndex >= visibleRecords.length) return null
    return visibleRecords[listIndex]
  }

  function setListCursor(idx) {
    if (visibleRecords.length === 0) return
    focusSection = "list"
    selectedId = Model.identity(visibleRecords[Math.max(0, Math.min(visibleRecords.length - 1, idx))])
  }

  function selectRow(delta) {
    if (visibleRecords.length === 0) {
      selectedId = ""
      return
    }
    focusSection = "list"
    selectedId = Model.identity(visibleRecords[(listIndex + delta + visibleRecords.length) % visibleRecords.length])
  }

  function syncFolderIndex() {
    selectedId = ""
    for (var i = 0; i < folderChipIds.length; i++) {
      if (folderChipIds[i].id === folderFilter) {
        folderIndex = i
        break
      }
    }
  }

  function setFolderFilter(next) {
    folderFilter = next
    syncFolderIndex()
  }

  function flashCopied(message, ok, record) {
    flashOk = ok !== false
    lastCopiedAccount = flashOk && record ? String(record.account || "") : ""
    lastCopiedKind = flashOk && record ? String(record.kind || "") : ""
    lastCopiedFolder = flashOk && record ? String(record.folder || "") : ""
    copyFlashText = message
    copiedFlash = true
    copiedTimer.restart()
  }

  function flashSaved() {
    savedFlash = true
    savedTimer.restart()
  }

  function togglePanelPosition() {
    if (settingProc.running)
      return
    settingProc.command = ["/usr/share/omarchy/bin/omarchy-bar", "set", moduleName, "centerPanel", centerPanel ? "false" : "true", "--json"]
    settingProc.running = true
  }

  function openAddView() {
    // Until the first list arrives, existing logins are unknown.
    if (vault.loading || modalOpen)
      return
    formToken++
    // Keyring state is unknown: adding could overwrite existing logins.
    if (vault.listError !== "") {
      vault.refresh()
      return
    }
    // Carry the context over: the open folder, or the name just searched for.
    var typed = searchText.trim()
    view = "add"
    addKind = "account"
    addFolder = folderFilter !== Model.ALL_FOLDERS ? folderFilter : ""
    addAccount = typed !== "" && visibleRecords.length === 0 ? typed : ""
    addError = ""
    wipeSensitiveState()
    focusSection = "addFields"
    Qt.callLater(function() {
      if (!root.opened) return
      addForm.focusFirstEmpty()
    })
  }

  function saveAdd(replace) {
    addForm.saveAdd(replace)
  }

  function copyRecord(record) {
    if (!record || confirmOpen) return
    vault.copy(record.account, function(ok, err, code) {
      if (!ok && confirmDialog.reportDamaged(err, code))
        return
      flashCopied(ok ? (Model.isNostr(record) ? "Copied key" : "Copied password") : (err || "Could not copy"), ok, record)
    }, record.kind, record.folder)
  }

  function copyAccount(record) {
    if (!record || confirmOpen) return
    vault.copyText(record.account, function(ok, err) {
      flashCopied(ok ? "Copied account" : (err || "Could not copy"), ok)
    })
  }

  function typeRecord(record) {
    if (!record || confirmOpen) return
    var snap = root.focusSnapshot
    if (!snap || !snap.id) {
      flashCopied("Type unavailable", false)
      return
    }
    // The panel is closed by then: report a failure by notification.
    vault.type(record.account, snap, function(ok, err) {
      if (!ok)
        vault.notifyTypeFailure(err || "Type aborted")
    }, record.kind, record.folder)
    root.close()
  }

  // The keyboard goes to the field of the current view.
  function focusInput() {
    if (view === "add")
      (addKind === "nostr" ? addForm.accountField : addForm.passwordField).forceActiveFocus()
    else
      listView.searchField.forceActiveFocus()
  }

  function focusSearchSoon() {
    Qt.callLater(function() {
      if (root.opened) listView.searchField.forceActiveFocus()
    })
  }

  function focusCatcher() {
    keyCatcher.forceActiveFocus()
  }

  function generateNostr(replace) {
    addForm.doGenerateNostr(replace)
  }

  // Give the keys back to the panel after a dialog or menu is gone.
  function refocusCatcher() {
    if (opened && !confirmOpen) keyCatcher.forceActiveFocus()
  }

  // While a dialog or the row menu is open, only it may act: no key may
  // copy or type a secret behind it.
  readonly property bool modalOpen: confirmOpen || actionsMenuOpen

  function copySelected(record) {
    if (modalOpen) return
    copyRecord(record || currentRecord())
  }

  function copyAccountSelected() {
    if (modalOpen) return
    copyAccount(currentRecord())
  }

  function typeSelected() {
    if (modalOpen) return
    typeRecord(currentRecord())
  }

  function openSelectedOverflow() {
    if (root.view !== "list" || !currentRecord()) return
    root.openOverflowForRow(listIndex)
  }

  function handleEnter(event) {
    if (modalOpen || listLoading) return
    // Nothing to copy: Enter only opens the form, it never saves.
    if (visibleRecords.length === 0 && vault.listError === "") {
      openAddView()
      return
    }
    if (event.modifiers & Qt.ShiftModifier || event.modifiers & Qt.ControlModifier)
      typeSelected()
    else
      copySelected()
  }

  function handleEscape() {
    if (confirmOpen) {
      confirmDialog.closeConfirm()
      return
    }
    if (view === "add") {
      addForm.cancelAdd()
      return
    }
    if (listView.searchField.activeFocus && searchText !== "") {
      searchText = ""
      return
    }
    if (listView.searchField.activeFocus && searchText === "") {
      keyCatcher.forceActiveFocus()
      return
    }
    root.close()
  }

  onSearchTextChanged: selectedId = ""

  onFolderFilterChanged: syncFolderIndex()

  property alias notifyCommand: vault.notifyCommand
  property alias vault: vault
  property alias confirmCard: confirmDialog
  // Read-only views for the QML runtime tests.
  readonly property int loadedRecordCount: vault.records.length
  readonly property string listError: vault.listError
  readonly property bool listLoading: vault.loading

  Vault {
    id: vault
  }

  HyprBorder {
    id: hypr
  }

  Process {
    id: settingProc
    running: false
    command: []
    stderr: StdioCollector {
      id: settingStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode !== 0)
        console.warn("omapass: could not save centerPanel:", String(settingStderr.text || "").trim() || "exit " + exitCode)
    }
  }

  Timer {
    id: copiedTimer
    interval: 1200
    repeat: false
    onTriggered: {
      copiedFlash = false
      lastCopiedAccount = ""
      lastCopiedKind = ""
      lastCopiedFolder = ""
    }
  }

  Timer {
    id: savedTimer
    interval: 1200
    repeat: false
    onTriggered: savedFlash = false
  }

  Shortcut {
    sequences: ["Ctrl+N"]
    enabled: root.opened
    onActivated: root.openAddView()
  }

  Shortcut {
    sequences: ["Ctrl+P"]
    enabled: root.opened && root.view === "list"
    onActivated: root.togglePanelPosition()
  }

  Shortcut {
    sequences: ["Delete"]
    enabled: root.opened && root.view === "list" && root.focusSection === "list"
             && !listView.searchField.activeFocus && !root.actionsMenuOpen && !root.confirmOpen
    onActivated: confirmDialog.removeRecord(root.currentRecord())
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: root.centerPanel
    focusTarget: keyCatcher
    borderSpec: root.frameBorderSpec
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(root.desiredContentHeight, Style.space(800))

    PanelKeyCatcher {
      PointerTracker { panel: root }

      Keys.onPressed: function(event) {
        // The shell's catcher reports Shift/Ctrl+Enter as a plain activate;
        // take it here so it types and the deferred copy below skips it.
        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
            && (event.modifiers & (Qt.ShiftModifier | Qt.ControlModifier))
            && !keyCatcher.blocked) {
          // Flag only where a plain Enter would copy, so the deferred copy
          // below consumes it; elsewhere nothing is left behind.
          if (root.view === "list" && root.focusSection === "list" && !root.confirmOpen) {
            root.modifiedReturn = true
            root.typeSelected()
          }
          event.accepted = true
          return
        }
        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_N) {
          root.openAddView()
          event.accepted = true
          return
        }
        if (root.view === "add" && root.focusSection === "addKind" && !root.confirmOpen) {
          if (addForm.handleCtrlKey(event, true)) {
            event.accepted = true
            return
          }
        }
        if (root.confirmOpen && confirmDialog.handleKey(event))
          event.accepted = true
      }
      id: keyCatcher
      anchors.fill: parent
      blocked: listView.searchField.activeFocus || addForm.folderField.activeFocus
               || addForm.accountField.activeFocus || addForm.passwordField.activeFocus || root.actionsMenuOpen

      onMoveRequested: function(dx, dy) {
        if (root.confirmOpen) {
          confirmDialog.toggleSelection()
          return
        }
        if (root.view === "add") {
          if (root.focusSection === "addKind" && dx !== 0)
            root.addKind = root.addKind === "account" ? "nostr" : "account"
          return
        }
        if (root.view === "list") listView.move(dx, dy)
      }

      onCloseRequested: root.handleEscape()
      onTabRequested: function(direction) {
        if (root.confirmOpen) {
          confirmDialog.toggleSelection()
          return
        }
        if (root.view === "add" && root.focusSection === "addKind") {
          addForm.folderField.forceActiveFocus()
          return
        }
        root.switchPanel(direction)
      }

      onTextKey: function(t) {
        if (root.confirmOpen) return
        if (t === "+" && root.view === "list") {
          root.openAddView()
          return
        }
        if (root.view === "list") listView.handleTextKey(t)
      }

      onDeleteRequested: {
        if (root.confirmOpen) return
        if (root.view === "list" && root.focusSection === "list")
          confirmDialog.removeRecord(root.currentRecord())
      }

      onActivateRequested: {
        var byReturn = root.activateByReturn
        root.activateByReturn = false
        if (root.confirmOpen) {
          if (confirmDialog.selectedIndex === 0)
            confirmDialog.closeConfirm()
          else
            confirmDialog.handleConfirm()
          return
        }
        if (root.view === "add") {
          addForm.activate()
          return
        }
        if (root.visibleRecords.length === 0 && vault.listError === "") {
          root.openAddView()
          return
        }
        if (root.focusSection === "folders") {
          if (root.folderChipIds.length > 0)
            root.setFolderFilter(root.folderChipIds[root.folderIndex].id)
          return
        }
        // Only Enter copies; Space activates chips and buttons but never a
        // secret.
        if (root.focusSection === "list" && byReturn) {
          // Deferred: the panel's own key handler may run after this one and
          // flag a Shift/Ctrl+Enter, which types instead. The row is taken
          // now: a list refresh before then must not change the target.
          var chosen = root.currentRecord()
          Qt.callLater(function() {
            if (root.modifiedReturn) {
              root.modifiedReturn = false
              return
            }
            root.copySelected(chosen)
          })
          return
        }
        if (root.focusSection === "search")
          listView.searchField.forceActiveFocus()
      }

      // Emitted just before activateRequested, for Return/Enter only.
      onReturnRequested: root.activateByReturn = true

      LoginListView {
        id: listView
        panel: root
      }

      AddLoginForm {
        id: addForm
        panel: root
      }

      FooterStrip { panel: root }
    }

    ConfirmCard {
      id: confirmDialog
      panel: root
      anchors.fill: parent
      z: 100
      opened: root.confirmOpen
      message: root.confirmMessage
      detail: root.confirmDetail
      confirmText: root.confirmConfirmText
      alertOnly: root.confirmAction === "alert"
    }
  }
}
