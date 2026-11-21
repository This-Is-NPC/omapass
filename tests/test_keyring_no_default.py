"""Sandbox integration: a missing default keyring must never be recreated.

Runs the real helper against a throwaway gnome-keyring whose HOME has no
keyrings at all (so the `default` alias does not resolve). It uses its own
private D-Bus session, so the sandbox keyring the suite checks stays intact.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "omapass-keyring"

SESSION = STOP_OWN_KEYRING + r"""
set -u
gnome-keyring-daemon --start --components=secrets >/dev/null
dbus-monitor --session "member=CreateCollection" "member=SetAlias" >"$OUT/calls" 2>&1 &
mon=$!
sleep 1
printf 'secret-value' | timeout 20 /usr/bin/python3 -I "$HELPER" store \
    --account acct --folder Fold >"$OUT/stdout" 2>"$OUT/stderr"
echo $? >"$OUT/rc"
sleep 0.5
kill -0 $mon 2>/dev/null && echo alive >"$OUT/monitor"
kill $mon
find "$HOME/.local/share/keyrings" -name '*.keyring' >"$OUT/keyrings" 2>/dev/null
stop_keyring
"""


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestMissingDefaultKeyring(unittest.TestCase):
    def test_store_refuses_to_create_default_keyring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            out = Path(tmp) / "out"
            home.mkdir()
            out.mkdir()
            env = {
                "PATH": os.environ["PATH"],
                "HOME": str(home),
                "XDG_RUNTIME_DIR": tmp,
                "HELPER": str(HELPER),
                "OUT": str(out),
            }
            subprocess.run(
                ["dbus-run-session", "--", "bash", "-c", SESSION],
                env=env,
                timeout=90,
                check=True,
            )
            rc = int((out / "rc").read_text())
            keyrings = (out / "keyrings").read_text().split()
            stderr = (out / "stderr").read_text()
            calls = (out / "calls").read_text()
            monitor = out / "monitor"
            self.assertTrue(
                monitor.exists() and monitor.read_text().strip() == "alive",
                f"dbus-monitor did not stay up, the check would pass vacuously: {calls}",
            )
            self.assertNotIn("CreateCollection", calls, "store asked to create a keyring")
            self.assertNotIn("SetAlias", calls)
            self.assertEqual(keyrings, [], "store created a keyring file")
            self.assertNotEqual(rc, 0, "store succeeded without a default keyring")
            self.assertIn("default keyring", stderr)


if __name__ == "__main__":
    unittest.main()
