import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root
  visible: false

  readonly property string keyringService: "omapass"
  readonly property string helperPath: {
    var u = Qt.resolvedUrl("../bin/omapass-keyring")
    var s = String(u)
    if (s.indexOf("file://") === 0)
      s = s.substring(7)
    return decodeURIComponent(s)
  }

  // The panel is closed once typing starts, so a failure is shown as an
  // Omarchy notification. It never carries the secret: only the helper's
  // error text.
  property var notifyCommand: ["/usr/share/omarchy/bin/omarchy-notification-send"]

  function notifyFailure(title, message) {
    Quickshell.execDetached(notifyCommand.concat(["-u", "critical", "--app-name", "omapass",
      "omapass", title + ": " + String(message).substring(0, 400)]))
  }

  function notifyTypeFailure(message) {
    notifyFailure("Autotype failed", message)
  }

  // Helper exit status for "item already exists" (needs --replace).
  readonly property int exitExists: 4
  // Helper exit status for "the keyring file may be damaged".
  readonly property int exitDamaged: 6

  property var records: []
  property string listError: ""
  // Set by the first good list reply; until then, with no error, the list is loading.
  property bool loaded: false
  readonly property bool loading: !loaded && listError === ""
  property string copyTextPayload: ""
  property var storeDoneCallback: null
  property string storePayload: ""
  property string storeExtraKind: ""
  property var generatePasswordDoneCallback: null
  property var generateNostrDoneCallback: null
  property var removeDoneCallback: null
  property var copyDoneCallback: null
  property var copyTextDoneCallback: null
  property var focusCallback: null
  property var typeDoneCallback: null

  function helperCmd(args) {
    var cmd = ["/usr/bin/python3", "-I", helperPath]
    for (var i = 0; i < args.length; i++)
      cmd.push(args[i])
    return cmd
  }

  // A refresh asked for while a list runs is queued, not dropped: that run
  // may hold data from before the change (a removal, a save) that asked.
  property bool refreshPending: false

  function refresh() {
    if (listProc.running)
      refreshPending = true
    else
      listProc.running = true
  }

  // Bounds for helpers that only read. A hung one is stopped and reported;
  // `type` and `store` get none: a cut `type` leaves half a secret in the
  // target window, a cut `store` may leave a duplicate.
  property int listTimeoutMs: 60000
  property int copyTimeoutMs: 20000
  property int focusTimeoutMs: 8000

  Timer {
    interval: 100
    repeat: true
    running: listProc.running || focusProc.running || copyProc.running || copyTextProc.running
    onTriggered: {
      listProc.expire(root.listTimeoutMs)
      focusProc.expire(root.focusTimeoutMs)
      copyProc.expire(root.copyTimeoutMs)
      copyTextProc.expire(root.copyTimeoutMs)
    }
  }

  function captureFocus(cb) {
    focusCallback = cb || null
    if (!focusProc.running)
      focusProc.running = true
  }

  function finishFocus(snap) {
    var cb = focusCallback
    focusCallback = null
    if (cb)
      cb(snap)
  }

  // Name exactly one item: the helper refuses or acts on that folder only,
  // so a duplicate account never gets another row's secret or removal. The
  // name goes to the helper's stdin as JSON (--item-stdin), not argv: other
  // users can read a process's arguments in /proc.
  function runWithItem(proc, cmd, account, kind, folder, extra) {
    var item = {account: String(account), folder: String(folder || "")}
    if (kind)
      item.kind = String(kind)
    for (var key in extra)
      item[key] = extra[key]
    proc.command = helperCmd([cmd, "--item-stdin"])
    proc.input = JSON.stringify(item)
    proc.stdinEnabled = true
    proc.running = true
  }

  function copy(account, onDone, kind, folder) {
    account = String(account || "")
    if (account === "") {
      if (onDone) onDone(false, "Missing account")
      return
    }
    if (copyProc.running) {
      if (onDone) onDone(false, "Copy already in progress")
      return
    }
    copyDoneCallback = onDone || null
    runWithItem(copyProc, "copy", account, kind, folder, {})
  }

  function copyText(text, onDone) {
    text = String(text || "")
    if (!text) {
      if (onDone) onDone(false, "Nothing to copy")
      return
    }
    if (copyTextProc.running) {
      if (onDone) onDone(false, "Copy already in progress")
      return
    }
    copyTextDoneCallback = onDone || null
    copyTextPayload = text
    copyTextProc.stdinEnabled = true
    copyTextProc.running = true
  }

  function type(account, snapshot, onDone, kind, folder) {
    account = String(account || "")
    if (account === "") {
      if (onDone) onDone(false, "Missing account")
      return
    }
    if (!snapshot || !snapshot.compositor || !snapshot.id) {
      if (onDone) onDone(false, "Type unavailable")
      return
    }
    if (typeProc.running) {
      if (onDone) onDone(false, "Type already in progress")
      return
    }
    typeDoneCallback = onDone || null
    runWithItem(typeProc, "type", account, kind, folder,
                {compositor: String(snapshot.compositor), expect_id: String(snapshot.id)})
  }

  // Stop a running autotype (SIGTERM). The helper holds no state to clean up.
  // Every screen's bar has its own Vault, so also stop a type started by
  // another instance: the helper's command line holds this plugin's path.
  function cancelType() {
    typeDoneCallback = null
    if (typeProc.running)
      typeProc.running = false
    Quickshell.execDetached(["/usr/bin/pkill", "-TERM", "-f", "--",
      "^/usr/bin/python3 -I " + helperPath.replace(/[.^$*+?()[\]{}|\\]/g, "\\$&") + " type "])
  }

  function forgetSecrets() {
    copyTextPayload = ""
    copyTextDoneCallback = null
    storePayload = ""
    storeExtraKind = ""
    storeDoneCallback = null
    generatePasswordDoneCallback = null
    generateNostrDoneCallback = null
  }

  function store(account, folder, secret, onDone, extraKind, replace) {
    account = String(account || "").trim()
    folder = String(folder || "").trim()
    secret = String(secret || "")
    if (!account || !folder || !secret) {
      if (onDone) onDone(false, "Need account, folder, and password")
      return
    }
    if (secret.indexOf("\n") >= 0 || secret.indexOf("\r") >= 0) {
      if (onDone) onDone(false, "Password must be a single line")
      return
    }
    if (storeProc.running) {
      if (onDone) onDone(false, "Save already in progress")
      return
    }
    storeDoneCallback = onDone
    storePayload = secret
    storeExtraKind = extraKind ? String(extraKind) : ""
    var cmd = helperCmd(["store", "--account=" + account, "--folder=" + folder])
    if (storeExtraKind)
      cmd.push("--kind=" + storeExtraKind)
    if (replace)
      cmd.push("--replace")
    storeProc.command = cmd
    storeProc.stdinEnabled = true
    storeProc.running = true
  }

  function generatePassword(onDone) {
    if (genPassProc.running) {
      if (onDone) onDone("")
      return
    }
    generatePasswordDoneCallback = onDone || null
    genPassProc.stdout = genPassOutput.createObject(genPassProc)
    genPassProc.running = true
  }

  function generateNostr(account, folder, onDone, replace) {
    var nick = String(account || "").trim() || "nostr:default"
    var fold = String(folder || "").trim() || "Nostr"
    if (genNostrProc.running) {
      if (onDone) onDone(false, "Generate already in progress")
      return
    }
    generateNostrDoneCallback = onDone || null
    var cmd = helperCmd([
      "generate-nostr", "--account=" + nick, "--folder=" + fold
    ])
    if (replace)
      cmd.push("--replace")
    genNostrProc.command = cmd
    genNostrProc.running = true
  }

  function remove(account, onDone, kind, folder) {
    account = String(account || "")
    if (account === "") {
      if (onDone) onDone(false, "Missing account")
      return
    }
    if (removeProc.running) {
      if (onDone) onDone(false, "Remove already in progress")
      return
    }
    removeDoneCallback = onDone
    runWithItem(removeProc, "clear", account, kind, folder, {})
  }

  HelperProcess {
    id: listProc
    running: false
    command: root.helperCmd(["list", "--json"])
    streams: 2
    stdout: StdioCollector {
      id: listStdout
      waitForEnd: true
      onStreamFinished: listProc.streamDone()
    }
    stderr: StdioCollector {
      id: listStderr
      waitForEnd: true
      onStreamFinished: listProc.streamDone()
    }
    onDone: function(code) { root.finishList(code) }
  }

  function finishList(code) {
    var retry = refreshPending
    refreshPending = false
    applyList(code)
    if (retry)
      refresh()
  }

  function applyList(code) {
    // Keep the last known list on failure; an error is not an empty keyring.
    // The helper always prints a JSON array, so empty output is a failure too.
    if (listProc.timedOut) {
      root.listError = "The keyring did not answer in time"
      return
    }
    var text = String(listStdout.text || "")
    if (code === 0 && text.trim() !== "") {
      try {
        var parsed = JSON.parse(text)
        if (Array.isArray(parsed)) {
          root.records = parsed
          root.loaded = true
          root.listError = ""
          return
        }
      } catch (e) {
      }
    }
    var msg = String(listStderr.text || "").trim()
    root.listError = msg || "Keyring unavailable"
  }

  HelperProcess {
    id: focusProc
    streams: 1
    running: false
    command: root.helperCmd(["focus-snapshot"])
    stdout: StdioCollector {
      id: focusStdout
      waitForEnd: true
      onStreamFinished: focusProc.streamDone()
    }
    onDone: function(exitCode) {
      if (exitCode !== 0) {
        root.finishFocus(null)
        return
      }
      try {
        var data = JSON.parse(String(focusStdout.text || ""))
        if (data && data.compositor && data.id)
          root.finishFocus({ compositor: String(data.compositor), id: String(data.id) })
        else
          root.finishFocus(null)
      } catch (e) {
        root.finishFocus(null)
      }
    }
    onRunningChanged: {
      // A process that never started reports no exit; answer then.
      if (!running && !focusProc.launched)
        Qt.callLater(function() {
          if (root.focusCallback)
            root.finishFocus(null)
        })
    }
  }

  HelperProcess {
    id: copyProc
    streams: 1
    running: false
    command: []
    stderr: StdioCollector {
      id: copyStderr
      waitForEnd: true
      onStreamFinished: copyProc.streamDone()
    }
    onDone: function(exitCode) {
      var cb = root.copyDoneCallback
      root.copyDoneCallback = null
      if (!cb)
        return
      if (exitCode === 0) {
        cb(true, "")
      } else {
        var err = String(copyStderr.text || "").trim()
        cb(false, copyProc.timedOut ? "Copy timed out"
                  : err || "Could not copy (keyring?)", exitCode)
      }
    }
  }

  HelperProcess {
    id: copyTextProc
    streams: 1
    running: false
    command: root.helperCmd(["copy-text"])
    stdinEnabled: true
    stderr: StdioCollector {
      id: copyTextStderr
      waitForEnd: true
      onStreamFinished: copyTextProc.streamDone()
    }
    onStarted: {
      write(copyTextPayload)
      copyTextPayload = ""
      stdinEnabled = false
    }
    onDone: function(exitCode) {
      var cb = root.copyTextDoneCallback
      root.copyTextDoneCallback = null
      if (!cb)
        return
      if (exitCode === 0)
        cb(true, "")
      else
        cb(false, copyTextProc.timedOut ? "Copy timed out"
                  : String(copyTextStderr.text || "").trim() || "Could not copy")
    }
  }

  HelperProcess {
    id: typeProc
    streams: 1
    running: false
    command: []
    stderr: StdioCollector {
      id: typeStderr
      waitForEnd: true
      onStreamFinished: typeProc.streamDone()
    }
    onDone: function(exitCode) {
      var cb = root.typeDoneCallback
      root.typeDoneCallback = null
      if (!cb)
        return
      if (exitCode === 0) {
        cb(true, "")
      } else {
        var err = String(typeStderr.text || "").trim()
        cb(false, err || (exitCode === 8 ? "Focus changed"
                          : exitCode === 9 ? "Typing failed" : "Type aborted"), exitCode)
      }
    }
  }

  HelperProcess {
    id: storeProc
    streams: 1
    running: false
    command: []
    stdinEnabled: true
    stderr: StdioCollector {
      id: storeStderr
      waitForEnd: true
      onStreamFinished: storeProc.streamDone()
    }
    onStarted: {
      write(storePayload)
      storePayload = ""
      stdinEnabled = false
    }
    onDone: function(exitCode) {
      var cb = storeDoneCallback
      storeDoneCallback = null
      storeExtraKind = ""
      if (exitCode === 0) {
        root.refresh()
        if (cb) cb(true, "")
      } else if (cb) {
        var err = String(storeStderr.text || "").trim()
        cb(false, err || "Could not save (keyring?)", exitCode)
      }
    }
  }

  HelperProcess {
    id: removeProc
    streams: 1
    running: false
    command: []
    stderr: StdioCollector {
      id: removeStderr
      waitForEnd: true
      onStreamFinished: removeProc.streamDone()
    }
    onDone: function(exitCode) {
      var cb = removeDoneCallback
      removeDoneCallback = null
      if (exitCode === 0) {
        root.refresh()
        if (cb) cb(true, "")
      } else if (cb) {
        var err = String(removeStderr.text || "").trim()
        cb(false, err || "Could not remove (keyring?)", exitCode)
      }
    }
  }

  // The output is read once the process has exited and its output has
  // ended, so it is never missed. A StdioCollector keeps its text until the
  // next run and cannot be cleared: each run gets a new one, destroyed when
  // the result is handled. forgetSecrets() drops the callback, so nothing
  // is delivered after the form is closed or wiped.
  Component {
    id: genPassOutput
    StdioCollector {
      waitForEnd: true
      onStreamFinished: genPassProc.streamDone()
    }
  }

  HelperProcess {
    id: genPassProc
    streams: 1
    running: false
    command: root.helperCmd(["generate-password"])
    onDone: function(exitCode) {
      var cb = root.generatePasswordDoneCallback
      root.generatePasswordDoneCallback = null
      var out = genPassProc.stdout
      var text = String(out.text || "").trim()
      genPassProc.stdout = null
      out.destroy()
      if (!cb)
        return
      if (exitCode !== 0 || !text)
        cb("")
      else
        cb(text)
    }
  }

  HelperProcess {
    id: genNostrProc
    streams: 2
    running: false
    command: []
    stdout: StdioCollector {
      id: genNostrStdout
      waitForEnd: true
      onStreamFinished: genNostrProc.streamDone()
    }
    stderr: StdioCollector {
      id: genNostrStderr
      waitForEnd: true
      onStreamFinished: genNostrProc.streamDone()
    }
    onDone: function(exitCode) {
      var cb = root.generateNostrDoneCallback
      root.generateNostrDoneCallback = null
      if (!cb)
        return
      if (exitCode !== 0) {
        var genErr = String(genNostrStderr.text || "").trim()
        cb(false, genErr || "Could not generate Nostr key", exitCode)
        return
      }
      try {
        var data = JSON.parse(String(genNostrStdout.text || ""))
        if (data && data.ok && data.account)
          cb(true, String(data.account))
        else
          cb(false, "Invalid response from generator")
      } catch (e) {
        cb(false, "Could not generate Nostr key")
      }
    }
  }

  // A helper process whose result is handled only once it has exited AND
  // every attached output stream has been read to the end. Quickshell can
  // report the exit first; reading the output then saw it empty or cut.
  // `streams` is the number of StdioCollectors that call streamDone().
  component HelperProcess: Process {
    id: hp
    signal done(int exitCode)
    property int streams: 0
    property bool launched: false
    property int _code: -1
    property int _finished: 0
    // Written to stdin once, then stdin is closed. Not for secrets.
    property string input: ""
    property bool timedOut: false
    property double startedAt: 0
    // Stop the process once it has run longer than `limitMs`; the exit then
    // takes the normal path, with `timedOut` set.
    function expire(limitMs) {
      if (running && startedAt > 0 && !timedOut && Date.now() - startedAt > limitMs) {
        timedOut = true
        running = false
      }
    }
    // Stamped when the child starts and cleared when it exits. Under load
    // `running` reads true before `runningChanged` fires; a stamp taken
    // there was still 0 (or an earlier run's) and the watchdog killed a
    // list that had just started.
    onStarted: {
      timedOut = false
      startedAt = Date.now()
      launched = true
      _code = -1
      _finished = 0
      if (input !== "") {
        write(input)
        input = ""
        stdinEnabled = false
      }
    }
    onExited: function(code) {
      startedAt = 0
      _code = code
      _check()
    }
    function streamDone() {
      _finished++
      _check()
    }
    function _check() {
      if (_code < 0 || _finished < streams)
        return
      var code = _code
      _code = -1
      done(code)
    }
  }
}
