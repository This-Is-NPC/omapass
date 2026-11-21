"""The Nostr examples in the README parse and reach the right item."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH
from tests.test_secret_validation import SETUP


@sandbox_only
class TestNostrAccountOption(unittest.TestCase):
    def run_script(self, body: str) -> str:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", SETUP + body],
            text=True, capture_output=True, timeout=90, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH)},
        )
        return proc.stdout + proc.stderr

    def test_documented_forms_parse_and_use_the_account(self) -> None:
        out = self.run_script(r"""
h nostr new --account n1 --folder Nostr >/dev/null 2>&1; echo "new=$?"
h nostr new >/dev/null 2>&1; echo "new_default=$?"
h nostr show-npub --account n1 2>&1 | head -c 200; echo "npub=${PIPESTATUS[0]}"
h nostr show-npub --account=n1 >/dev/null 2>&1; echo "npub_eq=$?"
h nostr show-npub n1 >/dev/null 2>&1; echo "npub_pos=$?"
h nostr show-nsec --account n1 2>&1; echo "nsec=$?"
h nostr rm --account n1 2>&1; echo "rm=$?"
h exists --kind nostr --account n1; echo "n1_left=$?"
h exists --kind nostr --account nostr:default; echo "default_left=$?"
h nostr rm; echo "rm_default=$?"
h exists --kind nostr --account nostr:default; echo "default_gone=$?"
h nostr rm --account=missing 2>&1; echo "rm_missing=$?"
stop_keyring
""")
        self.assertNotIn("unrecognized arguments", out)
        self.assertIn("new=0", out)
        self.assertIn("new_default=0", out)
        # show-npub needs a crypto backend; either way the option must parse.
        self.assertTrue("npub=0" in out or "npub requires" in out, out)
        self.assertIn("nsec=1", out)  # not a terminal: refused, not a parse error
        self.assertIn("requires an interactive terminal", out)
        self.assertIn("rm=0", out)
        self.assertIn("n1_left=1", out)
        self.assertIn("default_left=0", out)
        self.assertIn("rm_default=0", out)
        self.assertIn("default_gone=1", out)
        self.assertIn("no such item: missing", out)


if __name__ == "__main__":
    unittest.main()
