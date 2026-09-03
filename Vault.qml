import QtQuick
import Quickshell.Io

Item {
  id: root
  visible: false

  readonly property string keyringService: "omapass"

  property var records: []
  property var lookupCallback: null
  property string copyPayload: ""
  property string copyTextPayload: ""
  property string typePayload: ""
  property var typeReadyCallback: null
  property var storeDoneCallback: null
  property string storePayload: ""
  property string storeExtraKind: ""
  property var generatePasswordDoneCallback: null
  property string generateNostrSecret: ""
  property string generateNostrAccount: ""
  property string generateNostrFolder: ""
  property var generateNostrDoneCallback: null

  function mergeSearchStreams(stdout, stderr) {
    var accounts = []
    var stderrLines = String(stderr || "").split("\n")
    for (var s = 0; s < stderrLines.length; s++) {
      var sl = stderrLines[s]
      if (sl.indexOf("attribute.account = ") === 0)
        accounts.push(sl.substring(20))
    }
    var ai = 0
    var out = []
    var stdoutLines = String(stdout || "").split("\n")
    for (var i = 0; i < stdoutLines.length; i++) {
      out.push(stdoutLines[i])
      if (stdoutLines[i].indexOf("schema = ") === 0 && ai < accounts.length) {
        out.push("attribute.account = " + accounts[ai])
        out.push("attribute.service = " + keyringService)
        ai++
      }
    }
    return out.join("\n")
  }

  function parseSearchOutput(output) {
    var lines = String(output || "").split("\n")
    var parsed = []
    var current = {}

    function flush() {
      if (current.account)
        parsed.push({ account: current.account, folder: current.folder || "", kind: current.kind || "" })
      current = {}
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i]
      if (!line.trim()) {
        flush()
        continue
      }
      if (/^\s*secret\s*=/i.test(line)) continue
      if (line.indexOf("label = ") === 0) current.folder = line.substring(8)
      else if (line.indexOf("attribute.account = ") === 0) current.account = line.substring(20)
      else if (line.indexOf("attribute.kind = ") === 0) current.kind = line.substring(17)
    }
    flush()
    parsed.sort(function(a, b) {
      return displayFolder(a.account, a.folder).localeCompare(displayFolder(b.account, b.folder))
    })
    return parsed
  }

  function displayFolder(account, folder) {
    if (account === "nostr:default" && !folder) return "Nostr"
    return folder || account
  }

  function refresh() {
    if (!searchProc.running) searchProc.running = true
  }

  function lookup(account, cb) {
    lookupCallback = cb
    lookupProc.command = ["secret-tool", "lookup", "service", keyringService, "account", account]
    lookupProc.running = true
  }

  function copy(account) {
    lookup(account, function(secret) {
      copyPayload = secret
      copyProc.stdinEnabled = true
      copyProc.running = true
    })
  }
  function copyText(text) {
    text = String(text || "")
    if (!text) return
    copyTextPayload = text
    copyTextProc.stdinEnabled = true
    copyTextProc.running = true
  }


  function type(account, onReady) {
    typeReadyCallback = onReady || null
    lookup(account, function(secret) {
      typePayload = secret
      typeDelay.restart()
      if (typeReadyCallback) {
        var cb = typeReadyCallback
        typeReadyCallback = null
        cb()
      }
    })
  }

  function forgetSecrets() {
    copyPayload = ""
    copyTextPayload = ""
    storePayload = ""
    typePayload = ""
    generateNostrSecret = ""
    generateNostrAccount = ""
    generateNostrFolder = ""
    storeExtraKind = ""
    lookupCallback = null
    typeReadyCallback = null
    storeDoneCallback = null
    removeDoneCallback = null
    generatePasswordDoneCallback = null
    generateNostrDoneCallback = null
    if (nostrGenerateProc.running)
      nostrGenerateProc.running = false
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
    var cmd = ["secret-tool", "store", "--label", folder, "service", keyringService, "account", account]
    if (storeExtraKind)
      cmd.push("kind", storeExtraKind)
    storeProc.command = cmd
    storeProc.stdinEnabled = true
    storeProc.running = true
  }

  function nostrGenerateScript() {
    return [
      "import os",
      "",
      "CHARSET = \"qpzry9x8gf2tvdw0s3jn54khce6mua7l\"",
      "GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]",
      "",
      "",
      "def polymod(values):",
      "    chk = 1",
      "    for v in values:",
      "        b = chk >> 25",
      "        chk = ((chk & 0x1FFFFFF) << 5) ^ v",
      "        for i in range(5):",
      "            if (b >> i) & 1:",
      "                chk ^= GEN[i]",
      "    return chk",
      "",
      "",
      "def hrp_expand(hrp):",
      "    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]",
      "",
      "",
      "def create_checksum(hrp, data):",
      "    values = hrp_expand(hrp) + data",
      "    mod = polymod(values + [0] * 6) ^ 1",
      "    return [(mod >> 5 * (5 - i)) & 31 for i in range(6)]",
      "",
      "",
      "def bech32_encode(hrp, data):",
      "    combined = data + create_checksum(hrp, data)",
      "    return hrp + \"1\" + \"\".join(CHARSET[d] for d in combined)",
      "",
      "",
      "def convertbits(data, frombits, tobits, pad=True):",
      "    acc = bits = 0",
      "    ret = []",
      "    maxv = (1 << tobits) - 1",
      "    for value in data:",
      "        acc = (acc << frombits) | value",
      "        bits += frombits",
      "        while bits >= tobits:",
      "            bits -= tobits",
      "            ret.append((acc >> bits) & maxv)",
      "    if pad:",
      "        if bits:",
      "            ret.append((acc << (tobits - bits)) & maxv)",
      "    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):",
      "        return None",
      "    return ret",
      "",
      "",
      "def nsec_encode(raw32):",
      "    data = convertbits(raw32, 8, 5, True)",
      "    if data is None:",
      "        raise SystemExit(\"failed to encode nsec\")",
      "    return bech32_encode(\"nsec\", data)",
      "",
      "",
      "def has_nostr_crypto():",
      "    for name in (\"coincurve\", \"nak\", \"secp256k1\"):",
      "        try:",
      "            __import__(name)",
      "            return name",
      "        except ImportError:",
      "            pass",
      "    return None",
      "",
      "",
      "def npub_from_sk(raw32):",
      "    backend = has_nostr_crypto()",
      "    if not backend:",
      "        return None",
      "    if backend == \"coincurve\":",
      "        from coincurve import PrivateKey",
      "",
      "        xonly = PrivateKey(raw32).public_key.format(compressed=True)[1:]",
      "    elif backend == \"nak\":",
      "        import nak",
      "",
      "        xonly = bytes(nak.PrivateKey(bytes(raw32)).public_key)[1:]",
      "    else:",
      "        import secp256k1",
      "",
      "        xonly = secp256k1.PrivateKey(raw32, raw=True).pubkey.serialize(compressed=True)[1:]",
      "    data = convertbits(xonly, 8, 5, True)",
      "    return bech32_encode(\"npub\", data)",
      "",
      "",
      "sk = os.urandom(32)",
      "nsec = nsec_encode(sk)",
      "npub = npub_from_sk(sk)",
      "print(nsec)",
      "if npub:",
      "    print(\"NPUB:\" + npub)",
      "else:",
      "    print(\"NOTE: install coincurve, nak, or secp256k1 to derive npub (omapass nostr show-npub)\")"
    ].join("\n")
  }

  function generatePassword(onDone) {
    if (passwordGenerateProc.running) {
      if (onDone) onDone("")
      return
    }
    generatePasswordDoneCallback = onDone || null
    passwordGenerateProc.running = true
  }

  function generateNostr(account, folder, onDone) {
    var nick = String(account || "").trim() || "nostr:default"
    var fold = String(folder || "").trim() || "Nostr"
    if (nostrGenerateProc.running || generateNostrDoneCallback !== null) {
      if (onDone) onDone(false, "Generate already in progress")
      return
    }
    generateNostrDoneCallback = onDone || null
    generateNostrAccount = nick
    generateNostrFolder = fold
    nostrGenerateProc.stdinEnabled = true
    nostrGenerateProc.running = true
  }

  property var removeDoneCallback: null

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
    removeProc.command = ["secret-tool", "clear", "service", keyringService, "account", account]
    removeProc.running = true
  }

  Process {
    id: searchProc
    command: ["secret-tool", "search", "--all", "service", root.keyringService]
    property string _stdoutText: ""
    property string _stderrText: ""

    stdout: StdioCollector {
      id: searchStdout
      waitForEnd: true
      onStreamFinished: searchProc._stdoutText = text
    }
    stderr: StdioCollector {
      id: searchStderr
      waitForEnd: true
      onStreamFinished: searchProc._stderrText = text
    }
    onExited: function() {
      var combined = root.mergeSearchStreams(
        String(searchStdout.text || searchProc._stdoutText || ""),
        String(searchStderr.text || searchProc._stderrText || "")
      )
      root.records = root.parseSearchOutput(combined)
      searchProc._stdoutText = ""
      searchProc._stderrText = ""
    }
  }

  Process {
    id: lookupProc
    running: false
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var secret = String(text || "")
        if (secret.endsWith("\n")) secret = secret.slice(0, -1)
        if (root.lookupCallback) root.lookupCallback(secret)
        root.lookupCallback = null
      }
    }
  }

  Process {
    id: copyProc
    running: false
    command: ["wl-copy"]
    stdinEnabled: true
    onStarted: {
      write(copyPayload)
      copyPayload = ""
      stdinEnabled = false
    }
  }

  Process {
    id: copyTextProc
    running: false
    command: ["wl-copy"]
    stdinEnabled: true
    onStarted: {
      write(copyTextPayload)
      copyTextPayload = ""
      stdinEnabled = false
    }
  }

  Timer {
    id: typeDelay
    interval: 220
    repeat: false
    onTriggered: {
      typeProc.stdinEnabled = true
      typeProc.running = true
    }
  }

  Process {
    id: typeProc
    running: false
    command: ["wtype", "-"]
    stdinEnabled: true
    onStarted: {
      write(typePayload)
      typePayload = ""
      stdinEnabled = false
    }
  }

  Process {
    id: storeProc
    running: false
    command: []
    stdinEnabled: true
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
        cb(false, "Could not save (keyring?)")
      }
    }
  }

  Process {
    id: removeProc
    running: false
    command: []
    onExited: function(exitCode) {
      var cb = removeDoneCallback
      removeDoneCallback = null
      if (exitCode === 0) {
        root.refresh()
        if (cb) cb(true, "")
      } else if (cb) {
        cb(false, "Could not remove (keyring?)")
      }
    }
  }

  Process {
    id: passwordGenerateProc
    running: false
    command: ["python3", "-c", "import secrets,sys; sys.stdout.write(secrets.token_urlsafe(18))"]
    stdout: StdioCollector {
      id: passwordGenerateStdout
      waitForEnd: true
    }
    onExited: function(exitCode) {
      var cb = root.generatePasswordDoneCallback
      root.generatePasswordDoneCallback = null
      if (!cb) return
      var text = String(passwordGenerateStdout.text || "").trim()
      if (exitCode !== 0 || !text)
        cb("")
      else
        cb(text)
    }
  }

  Process {
    id: nostrGenerateProc
    running: false
    command: ["python3", "-"]
    stdinEnabled: true
    stdout: StdioCollector {
      id: nostrGenerateStdout
      waitForEnd: true
    }
    onStarted: {
      write(root.nostrGenerateScript())
      stdinEnabled = false
    }
    onExited: function(exitCode) {
      var doneCb = root.generateNostrDoneCallback
      var nick = root.generateNostrAccount
      var fold = root.generateNostrFolder
      if (exitCode !== 0) {
        root.generateNostrDoneCallback = null
        root.generateNostrSecret = ""
        root.generateNostrAccount = ""
        root.generateNostrFolder = ""
        if (doneCb) doneCb(false, "Could not generate Nostr key")
        return
      }
      var lines = String(nostrGenerateStdout.text || "").split("\n")
      var nsec = lines.length > 0 ? String(lines[0]).trim() : ""
      if (!nsec || nsec.indexOf("\n") >= 0 || nsec.indexOf("\r") >= 0) {
        root.generateNostrDoneCallback = null
        root.generateNostrSecret = ""
        root.generateNostrAccount = ""
        root.generateNostrFolder = ""
        if (doneCb) doneCb(false, "Invalid nsec from generator")
        return
      }
      if (root.generateNostrDoneCallback === null) {
        root.generateNostrSecret = ""
        root.generateNostrAccount = ""
        root.generateNostrFolder = ""
        return
      }
      root.store(nick, fold, nsec, function(ok, msg) {
        root.generateNostrSecret = ""
        var cb = root.generateNostrDoneCallback
        root.generateNostrDoneCallback = null
        root.generateNostrAccount = ""
        root.generateNostrFolder = ""
        if (ok) {
          if (cb) cb(true, nick)
        } else if (cb) {
          cb(false, msg || "Could not save Nostr key")
        }
      }, "nostr")
    }
  }
}
