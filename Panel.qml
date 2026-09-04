import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
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
  property int selectedIndex: 0
  property int listIndex: 0
  property bool copiedFlash: false
  property string copyFlashText: ""
  property string view: "list"
  property string folderFilter: "all"
  property int folderIndex: 0
  property bool actionsMenuOpen: false
  property string focusSection: "search"
  property string addFolder: ""
  property string addAccount: ""
  property string addPassword: ""
  property string addError: ""
  property string addKind: "account"
  property bool addPasswordVisible: false
  property bool confirmOpen: false
  property string confirmMessage: ""
  property string confirmConfirmText: "Confirm"
  property string confirmAction: ""
  property var pendingRemoveRecord: null
  property var focusSnapshot: null
  property bool popoutSwitchClosing: false

  function wipeSensitiveState() {
    vault.forgetSecrets()
    addPassword = ""
    addPasswordVisible = false
    if (passwordField)
      passwordField.text = ""
  }


  signal openOverflowForRow(int rowIndex)

  property bool savedFlash: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color selectedBackground: Color.menu.selectedBackground
  readonly property color selectedText: Color.menu.selectedText
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property int rowHeight: Style.space(36)
  readonly property int headerHeight: Style.space(20)
  readonly property var filteredRecords: Model.filterByFolder(Model.searchBy(vault.records, searchText), folderFilter)
  readonly property var groups: folderFilter === "all" ? Model.groupByFolder(filteredRecords) : []
  readonly property var visibleRecords: filteredRecords
  readonly property var folderChipIds: {
    var chips = [{ id: "all", name: "All" }]
    var names = Model.folders(vault.records)
    for (var i = 0; i < names.length; i++)
      chips.push({ id: names[i], name: names[i] })
    return chips
  }
  readonly property int maxListBodyHeight: rowHeight * 8
  readonly property int listHeight: {
    if (visibleRecords.length === 0)
      return rowHeight * 2
    if (folderFilter !== "all")
      return Math.min(visibleRecords.length * rowHeight, maxListBodyHeight)
    var body = 0
    for (var g = 0; g < groups.length; g++) {
      body += headerHeight + Style.space(4)
      body += groups[g].records.length * rowHeight
      if (g > 0)
        body += Style.space(10)
    }
    return Math.min(body, maxListBodyHeight + groups.length * (headerHeight + Style.space(4)))
  }

  function open() {
    vault.captureFocus(function(snap) {
      root.focusSnapshot = snap
      vault.refresh()
      root.controller.show()
      Qt.callLater(function() {
        if (root.opened) {
          if (view === "list")
            searchField.forceActiveFocus()
          else {
            focusSection = "addKind"
            keyCatcher.forceActiveFocus()
          }
        }
      })
    })
  }

  function close() {
    wipeSensitiveState()
    closeConfirm()
    searchText = ""
    selectedIndex = 0
    listIndex = 0
    copiedFlash = false
    copyFlashText = ""
    savedFlash = false
    view = "list"
    folderFilter = "all"
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
  function closeForPopoutSwitch() {
    wipeSensitiveState()
    closeConfirm()
    addFolder = ""
    addAccount = ""
    addKind = "account"
    focusSnapshot = null
    if ("popoutSwitchClosing" in root)
      popoutSwitchClosing = true
    root.controller.hide()
  }


  function toggle() {
    if (root.opened) root.close()
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
      if (r.account === record.account && r.folder === record.folder)
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
    listIndex = Math.max(0, Math.min(visibleRecords.length - 1, idx))
    selectedIndex = listIndex
  }

  function selectRow(delta) {
    if (visibleRecords.length === 0) {
      listIndex = 0
      selectedIndex = 0
      return
    }
    focusSection = "list"
    if (listIndex < 0) listIndex = 0
    listIndex = (listIndex + delta + visibleRecords.length) % visibleRecords.length
    selectedIndex = listIndex
  }

  function setFolderFilter(next) {
    folderFilter = next
    listIndex = 0
    selectedIndex = 0
    for (var i = 0; i < folderChipIds.length; i++) {
      if (folderChipIds[i].id === next) {
        folderIndex = i
        break
      }
    }
  }

  function flashCopied(message) {
    copyFlashText = message
    copiedFlash = true
    copiedTimer.restart()
  }

  function flashSaved() {
    savedFlash = true
    savedTimer.restart()
  }

  function openAddView() {
    view = "add"
    addKind = "account"
    addFolder = ""
    addAccount = ""
    addPassword = ""
    addError = ""
    addPasswordVisible = false
    focusSection = "addKind"
    Qt.callLater(function() {
      if (root.opened) keyCatcher.forceActiveFocus()
    })
  }

  function cancelAdd() {
    wipeSensitiveState()
    addFolder = ""
    addAccount = ""
    addError = ""
    addKind = "account"
    view = "list"
    Qt.callLater(function() {
      if (root.opened) searchField.forceActiveFocus()
    })
  }

  function saveAdd() {
    addError = ""
    var secret = addPassword
    addPassword = ""
    if (passwordField)
      passwordField.text = ""
    vault.store(addAccount, addFolder, secret, function(ok, err) {
      if (ok) {
        addFolder = ""
        addAccount = ""
        addError = ""
        view = "list"
        flashSaved()
        Qt.callLater(function() {
          if (root.opened) searchField.forceActiveFocus()
        })
      } else {
        addError = err
      }
    })
  }

  function copyRecord(record) {
    if (!record) return
    vault.copy(record.account)
    flashCopied("Copied password")
  }

  function copyAccount(record) {
    if (!record) return
    vault.copyText(record.account)
    flashCopied("Copied account")
  }

  function typeRecord(record) {
    if (!record) return
    var snap = root.focusSnapshot
    if (!snap || !snap.id) {
      flashCopied("Type unavailable")
      return
    }
    vault.type(record.account, snap, function(ok, err) {
      if (!ok)
        flashCopied(err || "Type aborted")
    })
    root.close()
  }

  function accountExists(account) {
    var nick = String(account || "").trim()
    if (!nick) return false
    for (var i = 0; i < vault.records.length; i++) {
      if (vault.records[i].account === nick) return true
    }
    return false
  }

  function closeConfirm() {
    confirmOpen = false
    confirmAction = ""
    confirmMessage = ""
    pendingRemoveRecord = null
  }

  function handleConfirm() {
    if (confirmAction === "remove") {
      var record = pendingRemoveRecord
      var account = record ? record.account : ""
      closeConfirm()
      if (!account) return
      vault.remove(account, function(ok) {
        if (ok) flashCopied("Removed")
      })
    } else if (confirmAction === "replaceNostr") {
      closeConfirm()
      doGenerateNostr(true)
    } else {
      closeConfirm()
    }
  }

  function generateAddPassword() {
    vault.generatePassword(function(pw) {
      if (!pw) {
        addError = "Could not generate password"
        return
      }
      addPassword = pw
      if (passwordField)
        passwordField.text = pw
      flashCopied("Generated password")
    })
  }

  function doGenerateNostr(replace) {
    var nick = String(addAccount || "").trim()
    var fold = String(addFolder || "").trim() || "Nostr"
    vault.generateNostr(nick, fold, function(ok, msg) {
      if (ok) {
        addPassword = ""
        addFolder = ""
        addAccount = ""
        addError = ""
        view = "list"
        vault.refresh()
        flashSaved()
        Qt.callLater(function() {
          if (root.opened) searchField.forceActiveFocus()
        })
      } else {
        addError = msg || "Failed to generate Nostr key"
      }
    }, replace === true)
  }

  function generateNostrKey() {
    addError = ""
    var nick = String(addAccount || "").trim()
    if (!nick) {
      addError = "Need a nickname in Account"
      return
    }
    if (accountExists(nick)) {
      confirmAction = "replaceNostr"
      confirmMessage = "Replace the secret for " + nick + "?"
      confirmConfirmText = "Replace"
      confirmOpen = true
      return
    }
    doGenerateNostr(false)
  }

  function removeRecord(record) {
    if (!record) return
    confirmAction = "remove"
    pendingRemoveRecord = record
    confirmMessage = "Remove " + record.account + " from omapass?"
    confirmConfirmText = "Remove"
    confirmOpen = true
  }

  function copySelected() {
    copyRecord(currentRecord())
  }

  function copyAccountSelected() {
    copyAccount(currentRecord())
  }

  function typeSelected() {
    typeRecord(currentRecord())
  }

  function openSelectedOverflow() {
    if (root.view !== "list" || !currentRecord()) return
    root.openOverflowForRow(listIndex)
  }

  function handleEnter(event) {
    if (event.modifiers & Qt.ShiftModifier || event.modifiers & Qt.ControlModifier)
      typeSelected()
    else
      copySelected()
  }

  function handleEscape() {
    if (confirmOpen) {
      closeConfirm()
      return
    }
    if (view === "add") {
      cancelAdd()
      return
    }
    if (searchField.activeFocus && searchText !== "") {
      searchText = ""
      return
    }
    if (searchField.activeFocus && searchText === "") {
      keyCatcher.forceActiveFocus()
      return
    }
    root.close()
  }

  onSearchTextChanged: {
    listIndex = 0
    selectedIndex = 0
  }

  onFolderFilterChanged: {
    listIndex = 0
    selectedIndex = 0
    for (var i = 0; i < folderChipIds.length; i++) {
      if (folderChipIds[i].id === folderFilter) {
        folderIndex = i
        break
      }
    }
  }

  onVisibleRecordsChanged: {
    if (listIndex >= visibleRecords.length)
      listIndex = visibleRecords.length > 0 ? 0 : 0
    selectedIndex = listIndex
  }

  Vault {
    id: vault
  }

  Timer {
    id: copiedTimer
    interval: 1200
    repeat: false
    onTriggered: copiedFlash = false
  }

  Timer {
    id: savedTimer
    interval: 1200
    repeat: false
    onTriggered: savedFlash = false
  }

  Shortcut {
    sequences: ["Ctrl+N"]
    enabled: root.opened && !folderField.activeFocus && !accountField.activeFocus && !passwordField.activeFocus
    onActivated: root.openAddView()
  }

  Shortcut {
    sequences: ["Delete"]
    enabled: root.opened && root.view === "list" && root.focusSection === "list"
             && !searchField.activeFocus && !root.actionsMenuOpen && !root.confirmOpen
    onActivated: root.removeRecord(root.currentRecord())
  }

  Shortcut {
    sequences: ["Shift+Return", "Shift+Enter", "Ctrl+Return", "Ctrl+Enter"]
    enabled: root.opened && root.view === "list" && !searchField.activeFocus
             && !folderField.activeFocus && !accountField.activeFocus && !passwordField.activeFocus
    onActivated: root.typeSelected()
  }


  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(Style.space(480), Style.space(800))

    PanelKeyCatcher {

      Keys.onPressed: function(event) {
        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_N) {
          if (!searchField.activeFocus && !folderField.activeFocus
              && !accountField.activeFocus && !passwordField.activeFocus) {
            root.openAddView()
            event.accepted = true
          }
          return
        }
        if (root.view === "add" && root.focusSection === "addKind" && !root.confirmOpen) {
          if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_G) {
            if (root.addKind === "nostr") root.generateNostrKey()
            else root.generateAddPassword()
            event.accepted = true
            return
          }
          if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_E && root.addKind === "account") {
            root.addPasswordVisible = !root.addPasswordVisible
            event.accepted = true
            return
          }
          if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_1) {
            root.addKind = "account"
            event.accepted = true
            return
          }
          if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_2) {
            root.addKind = "nostr"
            event.accepted = true
            return
          }
        }
        if (root.confirmOpen && confirmDialog.handleKey(event))
          event.accepted = true
      }
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus || folderField.activeFocus || accountField.activeFocus
               || passwordField.activeFocus || root.actionsMenuOpen

      onMoveRequested: function(dx, dy) {
        if (root.confirmOpen) {
          confirmDialog.selectedIndex = confirmDialog.selectedIndex === 0 ? 1 : 0
          return
        }
        if (root.view === "add") {
          if (root.focusSection === "addKind" && dx !== 0)
            root.addKind = root.addKind === "account" ? "nostr" : "account"
          return
        }
        if (root.view !== "list") return
        if (root.focusSection === "folders") {
          if (dx !== 0)
            root.folderIndex = Math.max(0, Math.min(root.folderChipIds.length - 1, root.folderIndex + dx))
          else if (dy > 0)
            root.focusSection = "search"
          return
        }
        if (root.focusSection === "search") {
          if (dy > 0 && root.visibleRecords.length > 0)
            root.selectRow(1)
          else if (dy < 0 && root.folderChipIds.length > 0)
            root.focusSection = "folders"
          return
        }
        if (root.focusSection === "list") {
          if (dx > 0) {
            root.openSelectedOverflow()
            return
          }
          if (dy !== 0)
            root.selectRow(dy)
        }
      }

      onCloseRequested: root.handleEscape()
      onTabRequested: function(direction) {
        if (root.confirmOpen) {
          confirmDialog.selectedIndex = confirmDialog.selectedIndex === 0 ? 1 : 0
          return
        }
        if (root.view === "add" && root.focusSection === "addKind") {
          folderField.forceActiveFocus()
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
        if (root.view !== "list") return
        if (t === "/")
          searchField.forceActiveFocus()
        else if (t === "m" || t === "M")
          root.openSelectedOverflow()
        else if (t === "u" || t === "U")
          root.copyAccountSelected()
        else if (t === "p" || t === "P")
          root.copySelected()
        else if (t === "t" || t === "T")
          root.typeSelected()
        else if ((t === "x" || t === "X") && root.focusSection === "list")
          root.removeRecord(root.currentRecord())
      }

      onDeleteRequested: {
        if (root.confirmOpen) return
        if (root.view === "list" && root.focusSection === "list")
          root.removeRecord(root.currentRecord())
      }

      onActivateRequested: {
        if (root.confirmOpen) {
          if (confirmDialog.selectedIndex === 0)
            root.closeConfirm()
          else
            root.handleConfirm()
          return
        }
        if (root.view === "add") {
          if (root.focusSection === "addKind") {
            folderField.forceActiveFocus()
            return
          }
          if (passwordField.activeFocus) {
            root.saveAdd()
            return
          }
          if (accountField.activeFocus && root.addKind === "nostr") {
            root.generateNostrKey()
            return
          }
          return
        }
        if (root.focusSection === "folders") {
          if (root.folderChipIds.length > 0)
            root.setFolderFilter(root.folderChipIds[root.folderIndex].id)
          return
        }
        if (root.focusSection === "list") {
          root.copySelected()
          return
        }
        if (root.focusSection === "search")
          searchField.forceActiveFocus()
      }

      Column {
        id: topChrome
        width: parent.width
        spacing: Style.space(8)

        RowLayout {
          width: parent.width
          spacing: Style.space(6)
          visible: root.view === "list"

          TextField {
            id: searchField
            Layout.fillWidth: true
            placeholderText: "Search"
            text: root.searchText
            font.family: contentFontFamily
            foreground: root.foreground
            font.pixelSize: Style.font.body
            verticalPadding: Style.space(4)
            hasCursor: root.focusSection === "search" && !activeFocus
            onTextChanged: root.searchText = text
            onActiveFocusChanged: if (activeFocus) root.focusSection = "search"
            onHoveredChanged: if (hovered) root.focusSection = "search"
            Keys.onPressed: function(event) {
              if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_N) {
                root.openAddView()
                event.accepted = true
              } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_U) {
                root.copyAccountSelected()
                event.accepted = true
              } else if (event.key === Qt.Key_Escape) {
                root.handleEscape()
                event.accepted = true
              } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                root.handleEnter(event)
                event.accepted = true
              } else if (event.key === Qt.Key_Down) {
                if (root.visibleRecords.length > 0) {
                  root.selectRow(1)
                  root.focusSection = "list"
                  keyCatcher.forceActiveFocus()
                }
                event.accepted = true
              } else if (event.key === Qt.Key_Up) {
                if (root.visibleRecords.length > 0) {
                  root.selectRow(-1)
                  keyCatcher.forceActiveFocus()
                } else if (root.folderChipIds.length > 0) {
                  root.focusSection = "folders"
                  keyCatcher.forceActiveFocus()
                }
                event.accepted = true
              }
            }
          }

          PanelActionButton {
            iconText: "󰐕"
            tooltipText: "Add login"
            foreground: root.foreground
            fontFamily: contentFontFamily
            onClicked: root.openAddView()
          }
        }

        Row {
          id: folderRow
          visible: root.view === "list" && vault.records.length > 0
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.folderChipIds

            Button {
              required property var modelData
              required property int index
              text: modelData.name
              fontSize: Style.font.bodySmall
              foreground: root.foreground
              fontFamily: contentFontFamily
              bordered: true
              active: root.folderFilter === modelData.id
              hasCursor: root.focusSection === "folders" && root.folderIndex === index
              onClicked: root.setFolderFilter(modelData.id)
              onHovered: function(h) {
                if (h) {
                  root.focusSection = "folders"
                  root.folderIndex = index
                }
              }
            }
          }
        }

        Text {
          width: parent.width
          visible: copiedFlash || savedFlash
          horizontalAlignment: Text.AlignHCenter
          text: savedFlash ? "Saved" : copyFlashText
          color: root.dim
          font.family: contentFontFamily
          font.pixelSize: Style.font.caption
        }

        Column {
          id: addForm
          width: parent.width
          spacing: Style.space(8)
          visible: root.view === "add"
          Row {
            id: addKindRow
            width: parent.width
            spacing: Style.space(6)

            Button {
              text: "Account"
              fontSize: Style.font.bodySmall
              foreground: root.foreground
              fontFamily: contentFontFamily
              bordered: true
              hasCursor: root.focusSection === "addKind" && root.addKind === "account"
              onClicked: root.addKind = "account"
            }

            Button {
              text: "Nostr"
              fontSize: Style.font.bodySmall
              foreground: root.foreground
              fontFamily: contentFontFamily
              bordered: true
              hasCursor: root.focusSection === "addKind" && root.addKind === "nostr"
              onClicked: root.addKind = "nostr"
            }
          }

          TextField {
            id: folderField
            width: parent.width
            placeholderText: "Folder"
            text: root.addFolder
            foreground: root.foreground
            onTextChanged: root.addFolder = text
            onActiveFocusChanged: if (activeFocus) root.focusSection = "addFields"
            Keys.onPressed: function(event) {
              if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_G) {
                if (root.addKind === "nostr") root.generateNostrKey()
                else root.generateAddPassword()
                event.accepted = true
              } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_1) {
                root.addKind = "account"
                event.accepted = true
              } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_2) {
                root.addKind = "nostr"
                event.accepted = true
              } else if (event.key === Qt.Key_Tab) {
                if (event.modifiers & Qt.ShiftModifier) {
                  root.focusSection = "addKind"
                  keyCatcher.forceActiveFocus()
                } else {
                  accountField.forceActiveFocus()
                }
                event.accepted = true
              } else if (event.key === Qt.Key_Escape) {
                root.cancelAdd()
                event.accepted = true
              }
            }
          }

          TextField {
            id: accountField
            width: parent.width
            placeholderText: root.addKind === "nostr" ? "Nickname" : "Account or nickname"
            text: root.addAccount
            font.family: contentFontFamily
            onTextChanged: root.addAccount = text
            onActiveFocusChanged: if (activeFocus) root.focusSection = "addFields"
            Keys.onPressed: function(event) {
              if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_G) {
                if (root.addKind === "nostr") root.generateNostrKey()
                else root.generateAddPassword()
                event.accepted = true
              } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_1) {
                root.addKind = "account"
                event.accepted = true
              } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_2) {
                root.addKind = "nostr"
                event.accepted = true
              } else if (event.key === Qt.Key_Tab) {
                if (event.modifiers & Qt.ShiftModifier)
                  folderField.forceActiveFocus()
                else if (root.addKind === "account")
                  passwordField.forceActiveFocus()
                event.accepted = true
              } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                if (root.addKind === "nostr") {
                  root.generateNostrKey()
                  event.accepted = true
                }
              } else if (event.key === Qt.Key_Escape) {
                root.cancelAdd()
                event.accepted = true
              }
            }
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(6)
            visible: root.addKind === "account"

            TextField {
              id: passwordField
              Layout.fillWidth: true
              placeholderText: "Password"
              password: !root.addPasswordVisible
              text: root.addPassword
              font.family: contentFontFamily
              onTextChanged: root.addPassword = text
              onActiveFocusChanged: if (activeFocus) root.focusSection = "addFields"
              Keys.onPressed: function(event) {
                if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_G) {
                  root.generateAddPassword()
                  event.accepted = true
                } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_E) {
                  root.addPasswordVisible = !root.addPasswordVisible
                  event.accepted = true
                } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_1) {
                  root.addKind = "account"
                  event.accepted = true
                } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_2) {
                  root.addKind = "nostr"
                  event.accepted = true
                } else if (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier)) {
                  accountField.forceActiveFocus()
                  event.accepted = true
                } else if (event.key === Qt.Key_Escape) {
                  root.cancelAdd()
                  event.accepted = true
                } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                  root.saveAdd()
                  event.accepted = true
                }
              }
            }

            PanelActionButton {
              iconText: root.addPasswordVisible ? "󰈉" : "󰈈"
              tooltipText: root.addPasswordVisible ? "Hide password" : "Show password"
              foreground: root.foreground
              fontFamily: contentFontFamily
              onClicked: root.addPasswordVisible = !root.addPasswordVisible
            }

            PanelActionButton {
              iconText: "󰑐"
              tooltipText: "Generate password"
              foreground: root.foreground
              fontFamily: contentFontFamily
              onClicked: root.generateAddPassword()
            }
          }

          Row {
            width: parent.width
            spacing: Style.space(8)

            Button {
              text: "Save"
              visible: root.addKind === "account"
              foreground: root.foreground
              fontFamily: contentFontFamily
              onClicked: root.saveAdd()
            }

            Button {
              text: "Generate key"
              visible: root.addKind === "nostr"
              foreground: root.foreground
              fontFamily: contentFontFamily
              onClicked: root.generateNostrKey()
            }

            Button {
              text: "Cancel"
              foreground: root.foreground
              fontFamily: contentFontFamily
              onClicked: root.cancelAdd()
            }
          }

          Text {
            width: parent.width
            visible: root.addError !== ""
            wrapMode: Text.WordWrap
            text: root.addError
            color: Qt.rgba(1, 0.45, 0.45, 0.95)
            font.family: contentFontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Item {
        id: listArea
        anchors.top: topChrome.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.topMargin: Style.space(8)
        visible: root.view === "list"

        Item {
          id: emptyState
          anchors.fill: parent
          visible: root.visibleRecords.length === 0

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openAddView()
          }

          Column {
            anchors.centerIn: parent
            width: parent.width
            spacing: Style.space(4)

            Text {
              width: parent.width
              text: vault.records.length === 0 ? "No logins yet" : "No matches"
              color: root.dim
              font.family: contentFontFamily
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              width: parent.width
              text: "Add login"
              color: root.foreground
              font.family: contentFontFamily
              font.pixelSize: Style.font.body
              font.underline: true
              horizontalAlignment: Text.AlignHCenter
            }

            Text {
              width: parent.width
              text: "Ctrl+N or + to add"
              color: root.dim
              font.family: contentFontFamily
              font.pixelSize: Style.font.caption
              horizontalAlignment: Text.AlignHCenter
            }
          }
        }

        Flickable {
          id: listFlick
          anchors.fill: parent
          visible: root.visibleRecords.length > 0
          contentWidth: width
          contentHeight: listColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          interactive: contentHeight > height
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: function(event) {
              if (listFlick.contentHeight <= listFlick.height)
                return
              var maxY = listFlick.contentHeight - listFlick.height
              listFlick.contentY = Math.max(0, Math.min(listFlick.contentY - event.angleDelta.y, maxY))
              event.accepted = true
            }
          }

          Column {
            id: listColumn
            width: listFlick.width
            spacing: Style.space(10)

            Column {
              width: listColumn.width
              spacing: Style.space(10)
              visible: root.folderFilter === "all"

              Repeater {
                model: root.groups

                Column {
                  required property var modelData
                  width: listColumn.width
                  spacing: Style.space(4)

                  PanelSectionHeader {
                    width: parent.width
                    text: modelData.name.toUpperCase() + " " + modelData.total
                    foreground: root.foreground
                    fontFamily: contentFontFamily
                  }

                  Repeater {
                    model: modelData.records

                    LoginRow {
                      required property var modelData
                      width: listColumn.width
                      record: modelData
                      rowIndex: root.indexOfRecord(modelData)
                    }
                  }
                }
              }
            }

            Column {
              width: listColumn.width
              spacing: Style.space(4)
              visible: root.folderFilter !== "all"

              Repeater {
                model: root.filteredRecords

                LoginRow {
                  required property var modelData
                  width: listColumn.width
                  record: modelData
                  rowIndex: root.indexOfRecord(modelData)
                }
              }
            }
          }
        }
      }
    }

    ConfirmDialog {
      id: confirmDialog
      anchors.fill: parent
      z: 100
      opened: root.confirmOpen
      message: root.confirmMessage
      confirmText: root.confirmConfirmText
      cancelText: "Cancel"
      foreground: root.foreground
      background: Color.popups.background
      selectedText: root.selectedText

      onOpenedChanged: {
        if (opened)
          Qt.callLater(function() { confirmDialog.forceActiveFocus() })
      }

      onCanceled: root.closeConfirm()
      onConfirmed: root.handleConfirm()

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (confirmDialog.handleKey(event))
          event.accepted = true
      }
    }
  }

  component MenuRow: CursorSurface {
    id: menuRow
    signal chosen()
    signal hovered()
    property string label: ""
    property bool selected: false

    visible: enabled
    foreground: root.foreground
    hasCursor: selected
    implicitHeight: Style.space(48)
    radius: 0

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: menuRow.hovered()
      onClicked: menuRow.chosen()
    }

    Text {
      anchors.fill: parent
      anchors.leftMargin: Style.space(12)
      anchors.rightMargin: Style.space(12)
      verticalAlignment: Text.AlignVCenter
      textFormat: Text.PlainText
      text: menuRow.label
      color: root.foreground
      font.family: root.contentFontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }
  }

  component LoginRow: CursorSurface {
    id: row
    property var record: null
    property int rowIndex: -1
    property bool actionsMenuOpen: false
    property int menuIndex: 0

    readonly property bool selected: rowIndex === root.listIndex
    readonly property var menuOptions: [
      { id: "copyAccount", label: "Copy account" },
      { id: "typePassword", label: "Type password" },
      { id: "remove", label: "Remove" }
    ]

    hasCursor: root.focusSection === "list" && root.listIndex === rowIndex && rowIndex >= 0
    current: selected
    foreground: root.foreground
    implicitHeight: root.rowHeight

    function openActionsMenu() {
      menuIndex = 0
      actionsPopup.open()
    }

    function scrollIntoView() {
      if (row.rowIndex !== root.listIndex) return
      var pos = row.mapToItem(listColumn, 0, 0)
      var viewTop = listFlick.contentY
      var viewBottom = viewTop + listFlick.height
      var itemTop = pos.y
      var itemBottom = pos.y + row.height
      if (itemTop < viewTop)
        listFlick.contentY = Math.max(0, itemTop)
      else if (itemBottom > viewBottom)
        listFlick.contentY = Math.min(listFlick.contentHeight - listFlick.height, itemBottom - listFlick.height)
    }

    function moveMenuCursor(delta) {
      if (menuOptions.length === 0) return
      menuIndex = (menuIndex + delta + menuOptions.length) % menuOptions.length
    }

    function activateMenuOption() {
      if (menuIndex < 0 || menuIndex >= menuOptions.length) return
      runMenuAction(menuOptions[menuIndex].id)
      actionsPopup.close()
    }

    function runMenuAction(actionId) {
      if (!row.record) return
      if (actionId === "copyAccount")
        root.copyAccount(row.record)
      else if (actionId === "typePassword")
        root.typeRecord(row.record)
      else if (actionId === "remove")
        root.removeRecord(row.record)
    }

    HoverHandler {
      cursorShape: Qt.PointingHandCursor
      onHoveredChanged: if (hovered && row.rowIndex >= 0) root.setListCursor(row.rowIndex)
    }

    Connections {
      target: root
      function onListIndexChanged() {
        if (row.rowIndex === root.listIndex)
          Qt.callLater(row.scrollIntoView)
      }
      function onOpenOverflowForRow(idx) {
        if (idx === row.rowIndex)
          row.openActionsMenu()
      }
    }

    RowLayout {
      anchors.fill: parent
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(8)

      Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        TapHandler {
          acceptedButtons: Qt.LeftButton
          gesturePolicy: TapHandler.ReleaseWithinBounds
          onTapped: root.copyRecord(row.record)
        }

        Text {
          anchors.fill: parent
          verticalAlignment: Text.AlignVCenter
          text: row.record ? row.record.account : ""
          color: row.selected ? root.selectedText : root.foreground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
      }

      PanelActionButton {
        id: copyButton
        iconText: "󰆏"
        tooltipText: "Copy password"
        foreground: root.foreground
        fontFamily: root.contentFontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: root.copyRecord(row.record)
      }

      PanelActionButton {
        id: moreButton
        iconText: "󰇘"
        tooltipText: "More"
        foreground: root.foreground
        fontFamily: root.contentFontFamily
        Layout.alignment: Qt.AlignVCenter
        onClicked: row.openActionsMenu()
      }

      Popup {
        id: actionsPopup
        x: moreButton.x + moreButton.width - width
        y: moreButton.y + moreButton.height + Style.space(4)
        width: Style.space(220)
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
          if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            row.activateMenuOption()
            event.accepted = true
          }
        }

        onOpenedChanged: {
          row.actionsMenuOpen = opened
          root.actionsMenuOpen = opened
          if (opened) {
            row.menuIndex = 0
            Qt.callLater(function() { actionsPopupContent.forceActiveFocus() })
          } else if (root.opened) {
            Qt.callLater(function() { keyCatcher.forceActiveFocus() })
          }
        }

        background: BorderSurface {
          color: Color.background
          borderSpec: Border.flat(root.dim, 1)
          radius: Style.cornerRadius
        }

        contentItem: Column {
          id: actionsPopupContent
          width: parent.width
          focus: true
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: function(event) { actionsPopup.handleKey(event) }

          Repeater {
            model: row.menuOptions

            MenuRow {
              required property var modelData
              required property int index
              width: parent.width
              label: String(modelData.label || "")
              selected: row.menuIndex === index
              onHovered: row.menuIndex = index
              onChosen: {
                row.runMenuAction(String(modelData.id || ""))
                actionsPopup.close()
              }
            }
          }
        }
      }
    }
  }
}
