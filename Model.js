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
  var indexByKey = {}

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
    group.records.push({ account: account, folder: folder })
    group.total = group.records.length
  }

  return groups
}

function folders(records) {
  var list = records || []
  var seen = {}
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

function filterByFolder(records, folderName) {
  var list = records || []
  if (!folderName || folderName === "all") return list.slice()
  var out = []
  for (var i = 0; i < list.length; i++) {
    var record = list[i]
    if (!record) continue
    if (displayName(record.account, record.folder) === folderName) out.push(record)
  }
  return out
}
