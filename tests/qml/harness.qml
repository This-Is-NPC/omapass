import QtQuick
import Quickshell
import Quickshell.Io
import "plugin" as P

// Hosts the real Panel and exposes what a user would see, over IPC:
//   quickshell ipc call harness state   -> JSON
// It reads the Panel's public properties and walks the item tree, so the
// tests do not depend on ids inside Panel.qml.
ShellRoot {
  P.Panel {
    id: panel
    // A stub that logs its argv: notifications never reach a real daemon.
    // (Run through python3: the sandbox's /tmp is not executable.)
    notifyCommand: ["/usr/bin/python3", "-I", String(Qt.resolvedUrl("plugin/bin/notify-stub")).replace("file://", "")]
  }

  // A second Vault that tests create and destroy, to see what destroying it
  // does to a running helper. `vaultCall` runs a Vault function on it.
  Loader {
    id: vaultHost
    active: false
    source: "plugin/Vault.qml"
  }

  function eachItem(item, fn) {
    if (!item) return
    fn(item)
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++)
      eachItem(kids[i], fn)
  }

  function windows() {
    var out = []
    for (var i = 0; i < panel.data.length; i++)
      if (panel.data[i] && panel.data[i].contentItem !== undefined
          && panel.data[i].contentItem.length !== undefined)
        out.push(panel.data[i])
    return out
  }

  // Vault is the child that has a helper path; its Processes are its data.
  function busy() {
    for (var i = 0; i < panel.data.length; i++) {
      var v = panel.data[i]
      if (!v || v.helperPath === undefined) continue
      for (var j = 0; j < v.data.length; j++)
        if (v.data[j] && v.data[j].running === true) return true
    }
    return false
  }

  // The items of each panel window, including its Popup overlay.
  function sceneRoots() {
    var out = []
    var ws = windows()
    for (var w = 0; w < ws.length; w++) {
      var kids = ws[w].contentItem
      out.push(kids.length > 0 && kids[0].Window && kids[0].Window.contentItem
               ? kids[0].Window.contentItem : kids[0])
    }
    return out
  }

  // Screen rectangles of the visible rows and dialog buttons, for the tests
  // that move a pointer onto them.
  function rects(match) {
    var out = []
    var roots = sceneRoots()
    for (var w = 0; w < roots.length; w++) {
      var kids = [roots[w]]
      for (var k = 0; k < kids.length; k++)
        eachItem(kids[k], function(it) {
          var r = it.visible && it.width > 0 ? match(it) : null
          if (r) {
            var p = it.mapToItem(null, 0, 0)
            r.x = p.x; r.y = p.y; r.w = it.width; r.h = it.height
            out.push(r)
          }
        })
    }
    return out
  }
  function rowRects() {
    return rects(function(it) {
      if (it.record === undefined || it.rowIndex === undefined || !it.record) return null
      // A visible warning sign inside the row.
      var warn = false
      eachItem(it, function(c) { if (c.visible && c.text === "\u26a0") warn = true })
      return { account: String(it.record.account), folder: String(it.record.folder || ""), warn: warn,
               copied: it.copied === true }
    })
  }
  function buttonRects() {
    return rects(function(it) {
      if (it.placeholderText === "Search" && it.pointerOver !== undefined)
        return { label: "Search", selected: false }
      return it.label !== undefined && (it.primary !== undefined || it.danger !== undefined
                                        || it.hoverFollows !== undefined)
        ? { label: String(it.label), selected: it.selected === true } : null
    })
  }

  // The visible empty-list message, "" when the list shows rows.
  function emptyText() {
    var out = ""
    var ws = windows()
    for (var w = 0; w < ws.length; w++) {
      var kids = ws[w].contentItem
      for (var k = 0; k < kids.length; k++)
        eachItem(kids[k], function(it) {
          if (it.visible && it.text !== undefined && it.wrapMode !== undefined
              && /^(Loading|No logins yet|No matches)/.test(String(it.text)))
            out = String(it.text)
        })
    }
    return out
  }

  function snapshot() {
    var fields = []
    var lit = 0
    var ws = windows()
    for (var w = 0; w < ws.length; w++) {
      // KeyboardPanel aliases its contentItem to the children it hosts.
      var kids = ws[w].contentItem
      for (var k = 0; k < kids.length; k++)
      eachItem(kids[k], function(it) {
        if (it.placeholderText !== undefined && it.echoMode !== undefined)
          fields.push({ placeholder: String(it.placeholderText), text: String(it.text),
                        masked: it.echoMode === TextInput.Password, focus: it.focus, active: it.activeFocus })
        // CursorSurface rows: lit while painted with a visible fill.
        if (it.hasCursor !== undefined && it.current !== undefined && it.visible
            && it.width > 150 && (it.hasCursor || it.current) && it.color.a > 0.01)
          lit++
      })
    }
    // Labels of the items (menu row, chip, search field) the pointer is over:
    // once listed, the hover has reached the panel.
    var over = []
    var roots = sceneRoots()
    for (var r = 0; r < roots.length; r++)
      eachItem(roots[r], function(it) { if (it.pointerOver === true) over.push(String(it.label || it.placeholderText || (it.record && it.record.account))) })
    var cur = panel.currentRecord()
    return {
      opened: panel.opened,
      view: panel.view,
      searchText: panel.searchText,
      focusSection: panel.focusSection,
      listIndex: panel.listIndex,
      current: cur ? cur.account : null,
      records: panel.visibleRecords.length,
      loadedRecords: panel.loadedRecordCount,
      listError: panel.listError,
      loading: panel.listLoading,
      emptyText: emptyText(),
      menuOpen: panel.actionsMenuOpen,
      confirmOpen: panel.confirmOpen,
      confirmMessage: panel.confirmMessage,
      confirmDetail: panel.confirmDetail,
      opening: panel.opening,
      flash: panel.copiedFlash ? panel.copyFlashText : "",
      flashOk: panel.flashOk,
      pointerSeen: panel.lastPointer !== null,
      pointerOver: over,
      popoutSwitchClosing: panel.popoutSwitchClosing,
      primeDrops: primeDrops,
      primed: keyboardPanel() ? keyboardPanel().focusPrimed : false,
      addError: panel.addError,
      addPasswordLength: panel.addPassword.length,
      addPasswordGenerated: panel.addPasswordGenerated,
      fields: fields,
      lit: lit,
      busy: busy()
    }
  }

  // Count the times KeyboardPanel drops its Exclusive prime (a summon
  // re-primes the keyboard), and tell the tests whether it is primed.
  property int primeDrops: 0
  function keyboardPanel() { var ws = windows(); return ws.length ? ws[0] : null }
  Component.onCompleted: Qt.callLater(function() {
    var w = keyboardPanel()
    if (w) w.focusPrimedChanged.connect(function() { if (!w.focusPrimed) primeDrops++ })
  })

  IpcHandler {
    target: "harness"
    function open(): void { panel.open() }
    function close(): void { panel.close() }
    function toggle(): void { panel.toggle() }
    function popoutClose(): void { panel.closeForPopoutSwitch() }
    // A list refresh that is not a summon (the Vault is the child with a helper path).
    function refreshNow(): void {
      for (var i = 0; i < panel.data.length; i++)
        if (panel.data[i] && panel.data[i].helperPath !== undefined) panel.data[i].refresh()
    }
    function state(): string { return JSON.stringify(snapshot()) }
    // Save the form and close the panel in one tick: the helper has not
    // started yet when the panel wipes its secrets.
    // Put the keyboard focus in the search field, as any path that moves it
    // there would (a click, a second open()).
    function focusSearch(): void {
      var ws = windows()
      for (var w = 0; w < ws.length; w++)
        for (var k = 0; k < ws[w].contentItem.length; k++)
          eachItem(ws[w].contentItem[k], function(it) {
            if (it.placeholderText === "Search" && it.echoMode !== undefined) it.forceActiveFocus()
          })
    }
    // Call a Panel entry point that copies or types the current row.
    function act(name: string): void {
      var r = panel.currentRecord()
      if (name === "copySelected") panel.copySelected()
      else if (name === "copyAccountSelected") panel.copyAccountSelected()
      else if (name === "typeSelected") panel.typeSelected()
      else if (name === "copyRecord") panel.copyRecord(r)
      else if (name === "copyAccount") panel.copyAccount(r)
      else if (name === "typeRecord") panel.typeRecord(r)
      else if (name === "openAddView") panel.openAddView()
    }
    // Shorter bounds for the Vault's read-only helpers (milliseconds).
    function setTimeouts(list: int, copy: int, focus: int): void {
      for (var i = 0; i < panel.data.length; i++) {
        var v = panel.data[i]
        if (v && v.helperPath !== undefined) {
          v.listTimeoutMs = list
          v.copyTimeoutMs = copy
          v.focusTimeoutMs = focus
        }
      }
    }
    // Press Return on the list as the key catcher does, then change the
    // selection before the deferred copy runs.
    function returnThenSelect(account: string, folder: string): void {
      var catcher = null
      var ws = windows()
      for (var w = 0; w < ws.length; w++)
        for (var k = 0; k < ws[w].contentItem.length; k++)
          eachItem(ws[w].contentItem[k], function(it) {
            if (it.returnRequested !== undefined && it.activateRequested !== undefined) catcher = it
          })
      panel.focusSection = "list"
      catcher.returnRequested()
      catcher.activateRequested()
      panel.selectedId = account + "\u0000\u0000" + folder
    }
    function vaultCreate(): void { vaultHost.active = true }
    function vaultDestroy(): void { vaultHost.active = false }
    function vaultStart(name: string): void {
      var v = vaultHost.item
      if (name === "type") v.type("bob", { compositor: "hyprland", id: "0x1" }, null, "", "Home")
      else if (name === "store") v.store("svc", "Work", "dummy-secret-not-real", null)
    }
    function saveThenClose(): void { panel.saveAdd(); panel.close() }
    function rows(): string { return JSON.stringify(rowRects()) }
    function buttons(): string { return JSON.stringify(buttonRects()) }
  }
}
