import QtQuick
import Quickshell.Io

Item {
  id: root
  visible: false

  readonly property string keyringService: "omapass"
  readonly property string helperPath: {
    var u = Qt.resolvedUrl("bin/omapass-keyring")
    var s = String(u)
    if (s.indexOf("file://") === 0)
      s = s.substring(7)
    return decodeURIComponent(s)
  }

  property var records: []
  property string copyTextPayload: ""
  property var storeDoneCallback: null
  property string storePayload: ""
  property string storeExtraKind: ""
  property var generatePasswordDoneCallback: null
  property var generateNostrDoneCallback: null
  property var removeDoneCallback: null
  property var focusCallback: null
  property var typeDoneCallback: null

  function helperCmd(args) {
    var cmd = ["/usr/bin/python3", helperPath]
    for (var i = 0; i < args.length; i++)
      cmd.push(args[i])
    return cmd
  }

  function refresh() {
    if (!listProc.running)
      listProc.running = true
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

  function copy(account) {
    account = String(account || "").trim()
    if (!account)
      return
    copyProc.command = helperCmd(["copy", "--account", account])
    if (!copyProc.running)
      copyProc.running = true
  }

  function copyText(text) {
    text = String(text || "")
    if (!text)
      return
    copyTextPayload = text
    copyTextProc.stdinEnabled = true
    if (!copyTextProc.running)
      copyTextProc.running = true
  }

  function type(account, snapshot, onDone) {
    account = String(account || "").trim()
    if (!account) {
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
    typeProc.command = helperCmd([
      "type", "--account", account,
      "--compositor", String(snapshot.compositor),
      "--expect-id", String(snapshot.id)
    ])
    typeProc.running = true
  }

  function forgetSecrets() {
    copyTextPayload = ""
    storePayload = ""
    storeExtraKind = ""
    storeDoneCallback = null
    generatePasswordDoneCallback = null
    generateNostrDoneCallback = null
  }

  function store(account, folder, secret, onDone, extraKind) {
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
    var cmd = helperCmd(["store", "--account", account, "--folder", folder])
    if (storeExtraKind)
      cmd.push("--kind", storeExtraKind)
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
      "generate-nostr", "--account", nick, "--folder", fold
    ])
    if (replace)
      cmd.push("--replace")
    genNostrProc.command = cmd
    genNostrProc.running = true
  }

  function remove(account, onDone) {
    account = String(account || "").trim()
    if (!account) {
      if (onDone) onDone(false, "Missing account")
      return
    }
    if (removeProc.running) {
      if (onDone) onDone(false, "Remove already in progress")
      return
    }
    removeDoneCallback = onDone
    removeProc.command = helperCmd(["clear", "--account", account])
    removeProc.running = true
  }

  Process {
    id: listProc
    running: false
    command: root.helperCmd(["list", "--json"])
    stdout: StdioCollector {
      id: listStdout
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        try {
          var parsed = JSON.parse(String(listStdout.text || "[]"))
          root.records = Array.isArray(parsed) ? parsed : []
        } catch (e) {
          root.records = []
        }
      } else {
        root.records = []
      }
    }
  }

  Process {
    id: focusProc
    running: false
    command: root.helperCmd(["focus-snapshot"])
    stdout: StdioCollector {
      id: focusStdout
      waitForEnd: true
    }
    onExited: function(exitCode) {
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
      if (!running)
        Qt.callLater(function() {
          if (root.focusCallback)
            root.finishFocus(null)
        })
    }
  }

  Process {
    id: copyProc
    running: false
    command: []
  }

  Process {
    id: copyTextProc
    running: false
    command: root.helperCmd(["copy-text"])
    stdinEnabled: true
    onStarted: {
      write(copyTextPayload)
      copyTextPayload = ""
      stdinEnabled = false
    }
  }

  Process {
    id: typeProc
    running: false
    command: []
    stderr: StdioCollector {
      id: typeStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var cb = root.typeDoneCallback
      root.typeDoneCallback = null
      if (!cb)
        return
      if (exitCode === 0) {
        cb(true, "")
      } else {
        var err = String(typeStderr.text || "").trim()
        cb(false, err || "Type aborted")
      }
    }
  }

  Process {
    id: storeProc
    running: false
    command: []
    stdinEnabled: true
    stderr: StdioCollector {
      id: storeStderr
      waitForEnd: true
    }
    onStarted: {
      write(storePayload)
      storePayload = ""
      stdinEnabled = false
    }
    onExited: function(exitCode) {
      var cb = storeDoneCallback
      storeDoneCallback = null
      storeExtraKind = ""
      if (exitCode === 0) {
        root.refresh()
        if (cb) cb(true, "")
      } else if (cb) {
        var err = String(storeStderr.text || "").trim()
        cb(false, err || "Could not save (keyring?)")
      }
    }
  }

  Process {
    id: removeProc
    running: false
    command: []
    stderr: StdioCollector {
      id: removeStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var cb = removeDoneCallback
      removeDoneCallback = null
      if (exitCode === 0) {
        root.refresh()
        if (cb) cb(true, "")
      } else if (cb) {
        var err = String(removeStderr.text || "").trim()
        cb(false, err || "Could not remove (keyring?)")
      }
    }
  }

  Process {
    id: genPassProc
    running: false
    command: root.helperCmd(["generate-password"])
    stdout: StdioCollector {
      id: genPassStdout
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var cb = root.generatePasswordDoneCallback
      root.generatePasswordDoneCallback = null
      if (!cb)
        return
      var text = String(genPassStdout.text || "").trim()
      if (exitCode !== 0 || !text)
        cb("")
      else
        cb(text)
    }
  }

  Process {
    id: genNostrProc
    running: false
    command: []
    stdout: StdioCollector {
      id: genNostrStdout
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: genNostrStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var cb = root.generateNostrDoneCallback
      root.generateNostrDoneCallback = null
      if (!cb)
        return
      if (exitCode !== 0) {
        var genErr = String(genNostrStderr.text || "").trim()
        cb(false, genErr || "Could not generate Nostr key")
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
}
