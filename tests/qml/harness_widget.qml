import QtQuick
import Quickshell
import Quickshell.Io
import "plugin/qml" as P

// Hosts the real BarWidget (and so the Panel it loads) for the tests that
// need the shell's side of the lifecycle: what the shell's toggle reads.
//   quickshell ipc call harness state   -> JSON
ShellRoot {
  P.BarWidget { id: widget }

  function eachItem(item, fn) {
    if (!item) return
    fn(item)
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++)
      eachItem(kids[i], fn)
  }

  // The Panel the widget loaded, and whether its Vault runs a helper.
  function panelItem() {
    var found = null
    eachItem(widget, function(it) { if (it.item && it.item.opening !== undefined) found = it.item })
    return found
  }
  function busy() {
    var p = panelItem()
    for (var i = 0; p && i < p.data.length; i++) {
      var v = p.data[i]
      if (!v || v.helperPath === undefined) continue
      for (var j = 0; j < v.data.length; j++)
        if (v.data[j] && v.data[j].running === true) return true
    }
    return false
  }

  IpcHandler {
    target: "harness"
    function state(): string {
      var p = panelItem()
      return JSON.stringify({
        widgetOpened: widget.opened,
        opening: p ? p.opening : false,
        panelOpened: p ? p.opened : false,
        busy: busy()
      })
    }
    function open(): void { widget.open() }
    function close(): void { widget.close() }
    function toggle(): void { widget.toggle() }
    // What the shell's toggle does: it reads the widget's `opened`.
    function shellToggle(): void { if (widget.opened) widget.close(); else widget.open() }
  }
}
