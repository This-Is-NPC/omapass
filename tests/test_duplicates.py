"""Items that share account and kind (different folders): never guess, never delete both."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH
from tests.test_secret_validation import SETUP

# Two items made the way another app or an old version would: the same
# account, different labels. The omapass one is encoded, the other legacy.
SCRIPT = SETUP + r"""
r() { local out; out=$("$@" 2>"$HOME/err"); echo "rc=$? out=[$out] err=[$(cat "$HOME/err")]"; }
printf 'work-secret' | h store --account dup --folder Work
printf 'home-secret' | secret-tool store --label=Home service omapass account dup origin other-app
printf 'solo' | h store --account solo --folder Solo
h list --json
echo "== no folder"
r h get --account dup
r h exists --account dup
r h clear --account dup
r h rm -- dup
r h copy --account dup
echo "== with folder"
r h get --account dup --folder Work
r h get --account dup --folder Home
r h get --account dup --folder Nowhere
r h exists --account dup --folder Home
r h exists --account dup --folder Nowhere
r h get --account solo
r h get --account solo --folder Solo
r h get --account solo --folder Other
echo "== store"
r h store --account dup --folder Home <<< x
r h store --account dup --folder Work --replace <<< x
echo "== rm one"
r h rm --folder Home -- dup
h list --json
r h get --account dup
r h exists --account dup
stop_keyring
"""


@sandbox_only
class TestDuplicates(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        home = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", SCRIPT],
            text=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH)},
        )
        cls.out = proc.stdout
        cls.err = proc.stderr

    def line(self, prefix: str, nth: int = 0) -> str:
        hits = [ln for ln in self.out.splitlines() if ln.startswith(prefix)]
        return hits[nth]

    def after(self, marker: str) -> list[str]:
        lines = self.out.splitlines()
        return lines[lines.index(marker) + 1:]

    def test_list_flags_both_rows_as_duplicate(self) -> None:
        rows = json.loads(self.line("["))
        warns = {(r["account"], r["folder"]): r["warn"] for r in rows}
        self.assertEqual(warns[("dup", "Work")], "duplicate", self.out)
        self.assertEqual(warns[("dup", "Home")], "duplicate")
        self.assertEqual(warns[("solo", "Solo")], "")

    def test_without_a_folder_nothing_is_done_and_the_exit_is_12(self) -> None:
        got = self.after("== no folder")[:5]
        for line in got:
            self.assertTrue(line.startswith("rc=12 out=[]"), got)
            self.assertIn("ambiguous: 2 items in folders 'Home', 'Work'; pass --folder", line)
        self.assertNotIn("secret", "".join(got))

    def test_a_folder_picks_exactly_one(self) -> None:
        got = self.after("== with folder")
        self.assertTrue(got[0].startswith("rc=0 out=[work-secret]"), got[0])
        self.assertTrue(got[1].startswith("rc=0 out=[home-secret]"), got[1])
        self.assertTrue(got[2].startswith("rc=1 out=[]") and "no secret" in got[2], got[2])
        self.assertTrue(got[3].startswith("rc=0"), got[3])
        self.assertTrue(got[4].startswith("rc=1"), got[4])

    def test_a_single_item_works_with_or_without_its_folder(self) -> None:
        got = self.after("== with folder")
        self.assertTrue(got[5].startswith("rc=0 out=[solo]"), got[5])
        self.assertTrue(got[6].startswith("rc=0 out=[solo]"), got[6])
        self.assertTrue(got[7].startswith("rc=1"), got[7])

    def test_store_never_adds_or_merges_a_duplicate(self) -> None:
        got = self.after("== store")
        self.assertTrue(got[0].startswith("rc=4 "), got[0])
        self.assertTrue(got[1].startswith("rc=12 ") and "refusing to replace" in got[1], got[1])

    def test_rm_with_a_folder_removes_only_that_item(self) -> None:
        got = self.after("== rm one")
        self.assertTrue(got[0].startswith("rc=0 "), got[0])
        rows = json.loads(got[1])
        self.assertEqual(sorted((r["account"], r["folder"], r["warn"]) for r in rows),
                         [("dup", "Work", ""), ("solo", "Solo", "")])
        self.assertTrue(got[2].startswith("rc=0 out=[work-secret]"), got[2])
        self.assertTrue(got[3].startswith("rc=0"), got[3])


class TestFolderOption(unittest.TestCase):
    def test_every_single_item_command_accepts_folder(self) -> None:
        from tests.helper_loader import load_helper
        from tests.test_helper_security import FakeBackend, invoke_main

        mod = load_helper()
        for argv in (["get", "--account", "a", "--folder", "F"],
                     ["copy", "--account", "a", "--folder", "F"],
                     ["clear", "--account", "a", "--folder", "F"],
                     ["rm", "--folder", "F", "a"],
                     ["exists", "--account", "a", "--folder", "F"]):
            with self.subTest(argv=argv):
                backend = FakeBackend(secret="s")
                mod.BACKEND = backend
                self.addCleanup(setattr, mod, "BACKEND", None)
                from unittest import mock
                with mock.patch.object(mod, "clipboard_copy"):
                    invoke_main(mod, argv)
                self.assertEqual(backend.folders, ["F"])


if __name__ == "__main__":
    unittest.main()
