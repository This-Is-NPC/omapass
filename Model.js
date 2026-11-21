// Login list helpers, pure JS without Qt. Panel imports via `import "Model.js" as Model`.

function displayName(account, folder) {
  account = String(account || "")
  folder = String(folder || "")
  if (account === "nostr:default" && !folder) return "Nostr"
  return folder || account
}

function groupKey(account, folder) {
  folder = String(folder || "")
  if (folder) return folder
  return String(account || "")
}

function searchHaystack(record) {
  if (!record) return ""
  var account = String(record.account || "")
  var folder = String(record.folder || "")
  var kind = String(record.kind || "")
  return (account + " " + folder + " " + kind + " " + displayName(account, folder)).toLowerCase()
}

function isNostr(record) {
  if (!record) return false
  var kind = String(record.kind || "")
  var account = String(record.account || "")
  return kind === "nostr" || account === "nostr:default"
}


// The exact item a row stands for. Account, kind and folder together name one
// keyring item, so a selection kept by this survives any change of the list.
function identity(record) {
  if (!record) return ""
  return String(record.account || "") + "\u0000" + String(record.kind || "") + "\u0000" + String(record.folder || "")
}

function indexOfIdentity(records, id) {
  var list = records || []
  if (id === "") return -1
  for (var i = 0; i < list.length; i++)
    if (identity(list[i]) === id) return i
  return -1
}

// Account+kind pairs held by more than one item (in different folders), as
// an object used as a set. Such rows need a warning: they look identical.
function duplicateKeys(records) {
  var list = records || []
  var seen = Object.create(null)
  var dups = Object.create(null)
  for (var i = 0; i < list.length; i++) {
    if (!list[i]) continue
    var key = String(list[i].account || "") + "\u0000" + String(list[i].kind || "")
    if (seen[key]) dups[key] = true
    seen[key] = true
  }
  return dups
}

function isDuplicate(dups, record) {
  if (!record) return false
  return dups[String(record.account || "") + "\u0000" + String(record.kind || "")] === true
}

// Same text, whatever the Unicode normalization: legacy items may hold NFD.
function sameName(a, b) {
  return String(a || "").normalize("NFC") === String(b || "").normalize("NFC")
}

// The folders that hold an item named `account` of `kind` ("" or "nostr"),
// as the helper's replace would see it: exact or NFC-equal name.
function foldersOf(records, account, kind) {
  var list = records || []
  var out = []
  for (var i = 0; i < list.length; i++) {
    var r = list[i]
    if (!r || !sameName(r.account, account) || String(r.kind || "") !== kind) continue
    var folder = String(r.folder || "")
    if (out.indexOf(folder) < 0) out.push(folder)
  }
  return out
}

function searchBy(records, query) {
  var list = records || []
  var q = String(query || "").trim().toLowerCase()
  if (!q) return list.slice()
  var out = []
  for (var i = 0; i < list.length; i++) {
    if (searchHaystack(list[i]).indexOf(q) >= 0) out.push(list[i])
  }
  return out
}

function groupByFolder(records) {
  var list = records || []
  var groups = []
  var indexByKey = Object.create(null)

  for (var i = 0; i < list.length; i++) {
    var record = list[i]
    if (!record) continue
    var account = String(record.account || "")
    var folder = String(record.folder || "")
    var key = groupKey(account, folder)
    var groupIndex = indexByKey[key]
    if (groupIndex === undefined) {
      groupIndex = groups.length
      indexByKey[key] = groupIndex
      groups.push({
        name: displayName(account, folder),
        total: 0,
        records: []
      })
    }
    var group = groups[groupIndex]
    group.records.push(record)
    group.total = group.records.length
  }

  return groups
}

// Records in the order the "All" view shows them: card by card.
function flattenGroups(groups) {
  var out = []
  var list = groups || []
  for (var i = 0; i < list.length; i++)
    for (var j = 0; j < list[i].records.length; j++)
      out.push(list[i].records[j])
  return out
}

function folders(records) {
  var list = records || []
  var seen = Object.create(null)
  var out = []
  for (var i = 0; i < list.length; i++) {
    var record = list[i]
    if (!record) continue
    var name = displayName(record.account, record.folder)
    if (!name || seen[name]) continue
    seen[name] = true
    out.push(name)
  }
  return out
}

// Folder filter meaning "every folder". The helper rejects control
// characters in folder names, so no real folder can equal it.
var ALL_FOLDERS = "\u0001all"

function filterByFolder(records, folderName) {
  var list = records || []
  if (!folderName || folderName === ALL_FOLDERS) return list.slice()
  var out = []
  for (var i = 0; i < list.length; i++) {
    var record = list[i]
    if (!record) continue
    if (displayName(record.account, record.folder) === folderName) out.push(record)
  }
  return out
}

// Hyprland's active window border from `hyprctl -j getoption` output:
// general:border_size and general:col.active_border ("AARRGGBB ... 45deg").
// Returns { width, colors: ["#AARRGGBB", ...], angle } (Qt color order) or
// null if unusable.
function hyprBorder(sizeJson, colorJson) {
  var size, color
  try {
    size = JSON.parse(String(sizeJson || ""))
    color = JSON.parse(String(colorJson || ""))
  } catch (e) {
    return null
  }
  var width = Number(size && size.int)
  if (!isFinite(width) || width < 0) return null
  var raw = String((color && (color.gradient || color.str)) || "").trim()
  var colors = []
  var angle = 0
  var parts = raw.length > 0 ? raw.split(/\s+/) : []
  for (var i = 0; i < parts.length; i++) {
    var deg = parts[i].match(/^(-?\d+(?:\.\d+)?)deg$/)
    var hex = parts[i].replace(/^0x/i, "").match(/^([0-9a-fA-F]{2})([0-9a-fA-F]{6})$/)
    if (deg) angle = Number(deg[1])
    else if (hex) colors.push("#" + (hex[1] + hex[2]).toLowerCase())
  }
  if (colors.length === 0) return null
  return { width: width, colors: colors, angle: angle }
}
