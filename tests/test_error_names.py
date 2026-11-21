"""Errors that echo a name print it with control and invisible characters escaped (A12)."""

from __future__ import annotations

import inspect
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, ROOT, load_helper
from tests.test_secret_validation import SETUP

SCRIPT = SETUP + r"""
h get --yes -- $'\e[31mRED\e[0m' 2>&1 >/dev/null
h rm -- $'a​b' 2>&1 >/dev/null
h copy --account=$'x\ry' 2>&1 >/dev/null
stop_keyring
"""


@sandbox_only
class TestNamesInErrors(unittest.TestCase):
    def test_escapes_in_a_missing_name_are_not_sent_to_the_terminal(self) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", SCRIPT],
            text=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH), "PYTHONPATH": str(ROOT)},
        )
        out = proc.stdout
        self.assertIn(r"no secret for account: \x1b[31mRED\x1b[0m", out)
        self.assertIn("no such item: a\\u200bb", out)
        self.assertIn(r"no secret for account: x\ry", out)
        self.assertNotIn("\x1b", out)
        self.assertNotIn(chr(0x200B), out)
        self.assertNotIn("\r", out)


class TestExit6PointsToAGuide(unittest.TestCase):
    def test_every_exit_6_message_names_a_page_that_exists(self) -> None:
        """The messages must name a guide that ships."""
        mod = load_helper()
        page = "docs/how-to-check-the-keyring.md"
        self.assertIn(page, mod.HOWTO_CHECK)
        self.assertTrue((ROOT / page).is_file())
        self.assertIn(page, (ROOT / "README.md").read_text())
        for fn, messages in ((mod.daemon_write, 1), (mod.GiKeyring._verify_written, 2)):
            source = inspect.getsource(fn)
            self.assertEqual(source.count("HOWTO_CHECK}"), messages, fn.__name__)
            self.assertNotIn("health diagnosis", source)
            self.assertNotIn("recovery guide", source)


if __name__ == "__main__":
    unittest.main()
