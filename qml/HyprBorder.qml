import Quickshell
import Quickshell.Io
import "Model.js" as Model

// The active window border from the user's Hyprland config. `border` is null
// until read (or on other compositors).
Scope {
  id: hypr
  property var border: null

  function refresh() {
    if (!sizeProc.running && !colorProc.running) {
      sizeProc.running = true
      colorProc.running = true
    }
  }

  function apply() {
    if (sizeProc.running || colorProc.running) return
    hypr.border = Model.hyprBorder(sizeOut.text, colorOut.text)
  }

  Process {
    id: sizeProc
    running: false
    command: ["/usr/bin/hyprctl", "-j", "getoption", "general:border_size"]
    stdout: StdioCollector {
      id: sizeOut
      waitForEnd: true
    }
    onExited: hypr.apply()
  }

  Process {
    id: colorProc
    running: false
    command: ["/usr/bin/hyprctl", "-j", "getoption", "general:col.active_border"]
    stdout: StdioCollector {
      id: colorOut
      waitForEnd: true
    }
    onExited: hypr.apply()
  }
}
