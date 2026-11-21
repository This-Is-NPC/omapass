"""A kill in the middle of --replace leaves a duplicate, never a half-written item (R2)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, ROOT
from tests.test_secret_validation import HEALTH, SETUP

# The patched delete_sync stands in for SIGKILL arriving between the steps of a
# replace: the new item exists, the old one is not yet removed.
SCRIPT = SETUP + r"""
printf 'old-secret' | h store --account acc --folder OldFolder
python3 -I - <<'PY'
import os, signal, sys
sys.path.insert(0, os.environ["PYTHONPATH"])
from tests.helper_loader import load_helper
mod = load_helper()
Secret = mod.GiKeyring()._Secret
Secret.Item.delete_sync = lambda self, *a: os.kill(os.getpid(), signal.SIGKILL)
sys.stdin = __import__("io").StringIO("new-secret")
mod.main(["store", "--account", "acc", "--folder", "NewFolder", "--replace"])
PY
echo "killed=$?"
h list --json
echo "== old"; h get --account acc --folder OldFolder --yes
echo "== new"; h get --account acc --folder NewFolder --yes
echo "== health"; python3 -I "$HEALTH"; echo "health=$?"
printf 'third' | h store --account acc --folder NewFolder --replace 2>&1; echo "rerun=$?"
h rm --folder OldFolder -- acc; echo "rm=$?"
echo "== after"; h list --json
stop_keyring
"""


@sandbox_only
class TestKilledReplace(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        home = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", SCRIPT],
            text=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH), "HEALTH": HEALTH, "PYTHONPATH": str(ROOT)},
        )
        cls.out = proc.stdout + proc.stderr

    def part(self, start: str, end: str) -> str:
        return self.out.split(start, 1)[1].split(end, 1)[0]

    def test_the_helper_was_killed(self) -> None:
        self.assertIn("killed=137", self.out, self.out)

    def test_both_copies_survive_whole(self) -> None:
        self.assertIn("old-secret", self.part("== old", "== new"), self.out)
        self.assertIn("new-secret", self.part("== new", "== health"), self.out)
        self.assertEqual(self.part("killed=137", "== old").count('"account": "acc"'), 2, self.out)

    def test_the_keyring_is_healthy_after_the_kill(self) -> None:
        self.assertIn("health=0", self.out, self.out)

    def test_the_old_copy_is_removed_by_folder(self) -> None:
        # Two folders: replace refuses (exit 12) and names rm --folder.
        self.assertIn("rerun=12", self.out, self.out)
        self.assertIn("rm=0", self.out, self.out)
        self.assertEqual(self.out.split("== after", 1)[1].count('"account": "acc"'), 1, self.out)


if __name__ == "__main__":
    unittest.main()
