"""Behavioral tests for Model.js (pure JS, run with node when available)."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {groupByFolder, folders};")();
const names = ["__proto__", "constructor", "toString", "hasOwnProperty", "plain"];
const records = names.map(n => ({ account: n, folder: "" }))
  .concat(names.map(n => ({ account: "a-" + n, folder: n })));
console.log(JSON.stringify({
  groups: M.groupByFolder(records).map(g => [g.name, g.total]),
  folders: M.folders(records),
}));
"""


class TestModelReservedNames(unittest.TestCase):
    def test_reserved_names_group_and_list(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        data = json.loads(out)
        names = ["__proto__", "constructor", "toString", "hasOwnProperty", "plain"]
        self.assertEqual(data["folders"], names)
        self.assertEqual([g[0] for g in data["groups"]], names)
        self.assertEqual([g[1] for g in data["groups"]], [2] * 5)


KIND_SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {groupByFolder, searchBy, filterByFolder};")();
const records = [
  { account: "a", folder: "F", kind: "nostr" },
  { account: "a", folder: "F", kind: "" },
];
console.log(JSON.stringify({
  grouped: M.groupByFolder(records)[0].records,
  searched: M.searchBy(records, "a"),
  filtered: M.filterByFolder(records, "F"),
}));
"""


class TestModelKeepsKind(unittest.TestCase):
    def test_kind_survives_grouping_search_and_filter(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", KIND_SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        data = json.loads(out)
        for name in ("grouped", "searched", "filtered"):
            with self.subTest(step=name):
                self.assertEqual([r.get("kind") for r in data[name]], ["nostr", ""])


if __name__ == "__main__":
    unittest.main()


ORDER_SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {groupByFolder, flattenGroups};")();
const records = [
  { account: "alice", folder: "Home" },
  { account: "bob", folder: "Work" },
  { account: "carol", folder: "Home" },
];
console.log(JSON.stringify(M.flattenGroups(M.groupByFolder(records)).map(r => r.account)));
"""


class TestFlattenGroups(unittest.TestCase):
    def test_flat_order_is_the_card_order(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", ORDER_SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(json.loads(out), ["alice", "carol", "bob"])


HYPR_SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {hyprBorder};")();
const size = (n) => JSON.stringify({ option: "general:border_size", int: n, set: true });
const color = (g) => JSON.stringify({ option: "general:col.active_border", gradient: g, set: true });
console.log(JSON.stringify([
  M.hyprBorder(size(2), color("eec0402f ee5c3017 45deg")),
  M.hyprBorder(size(1), color("ff33ccff 0deg")),
  M.hyprBorder(size(3), color("0xff112233")),
  M.hyprBorder("not json", color("ff33ccff")),
  M.hyprBorder(size(2), color("")),
]));
"""


class TestHyprBorder(unittest.TestCase):
    def test_parses_hyprctl_getoption_output(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", HYPR_SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        gradient, solid, prefixed, bad_json, empty = json.loads(out)
        # Hyprland and Qt both order hex colors as AARRGGBB.
        self.assertEqual(gradient, {"width": 2, "colors": ["#eec0402f", "#ee5c3017"], "angle": 45})
        self.assertEqual(solid, {"width": 1, "colors": ["#ff33ccff"], "angle": 0})
        self.assertEqual(prefixed["colors"], ["#ff112233"])
        self.assertIsNone(bad_json)
        self.assertIsNone(empty)


FOLDER_SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {filterByFolder, ALL_FOLDERS};")();
const records = [{ account: "a", folder: "all" }, { account: "b", folder: "F" }];
console.log(JSON.stringify([
  M.filterByFolder(records, "all").map(r => r.account),
  M.filterByFolder(records, M.ALL_FOLDERS).map(r => r.account),
]));
"""


class TestAllFoldersSentinel(unittest.TestCase):
    def test_folder_named_all_is_a_folder(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", FOLDER_SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        only_all, everything = json.loads(out)
        self.assertEqual(only_all, ["a"])
        self.assertEqual(everything, ["a", "b"])


IDENTITY_SCRIPT = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const M = new Function(src + "; return {identity, indexOfIdentity, duplicateKeys, isDuplicate};")();
const recs = [
  { account: "dup", folder: "Home", kind: "" },
  { account: "dup", folder: "Work", kind: "" },
  { account: "dup", folder: "Work", kind: "nostr" },
  { account: "__proto__", folder: "Home", kind: "" },
];
const dups = M.duplicateKeys(recs);
console.log(JSON.stringify({
  index: recs.map(r => M.indexOfIdentity(recs, M.identity(r))),
  gone: M.indexOfIdentity(recs, M.identity({ account: "dup", folder: "Other", kind: "" })),
  empty: M.indexOfIdentity(recs, ""),
  dup: recs.map(r => M.isDuplicate(dups, r)),
}));
"""


class TestModelIdentity(unittest.TestCase):
    def test_identity_and_duplicates(self) -> None:
        self.assertIsNotNone(NODE, "node is required (installed in the sandbox image)")
        out = subprocess.run(
            [NODE, "-e", IDENTITY_SCRIPT, str(ROOT / "Model.js")],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        data = json.loads(out)
        self.assertEqual(data["index"], [0, 1, 2, 3])
        self.assertEqual(data["gone"], -1)
        self.assertEqual(data["empty"], -1)
        self.assertEqual(data["dup"], [True, True, False, False])
