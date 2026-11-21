"""omapass doctor: the read-only keyring check, one implementation shared with the sandbox."""

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
F="$HOME/.local/share/keyrings/Default_keyring.keyring"
locked() { gdbus call --session -d org.freedesktop.secrets \
  -o /org/freedesktop/secrets/collection/Default_5fkeyring \
  -m org.freedesktop.DBus.Properties.Get org.freedesktop.Secret.Collection Locked; }
echo "== locked"; sha256sum "$F" > "$HOME/before"
h doctor 2>&1; echo "rc=$?"
locked; sha256sum -c --quiet "$HOME/before" && echo unchanged
echo "== healthy"
printf 'doctor-dummy-secret' | h store --account alice --folder Home
printf 'doctor-dummy-secret' | h store --account bob --folder Work
sha256sum "$F" > "$HOME/before"
h doctor 2>&1; echo "rc=$?"
sha256sum -c --quiet "$HOME/before" && echo unchanged
stop_keyring
echo "== damaged"
printf '[keyring\nbroken' >> "$F"
start
h doctor 2>&1; echo "rc=$?"
stop_keyring
"""


@sandbox_only
class TestDoctor(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        home = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", SCRIPT],
            text=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH), "PYTHONPATH": str(ROOT)},
        )
        cls.out = proc.stdout + proc.stderr

    def part(self, start: str, end: str) -> str:
        return self.out.split(start, 1)[1].split(end, 1)[0]

    def test_a_healthy_keyring_exits_0_with_counts_only(self) -> None:
        part = self.part("== healthy", "== damaged")
        self.assertIn("OK   file Default_keyring.keyring: parses, 2 items", part)
        self.assertIn("OK   items: 2 read back, safe to rewrite", part)
        self.assertIn("rc=0", part)
        self.assertNotIn("FAIL", part)
        self.assertNotIn("doctor-dummy-secret", self.out)
        self.assertNotIn("ZG9jdG9y", self.out)  # the base64 form

    def test_a_locked_keyring_is_not_unlocked_and_exits_10(self) -> None:
        part = self.part("== locked", "== healthy")
        self.assertIn("locked", part.split("rc=")[0])
        self.assertIn("rc=10", part)
        self.assertIn("(<true>,)", part)
        self.assertIn("unchanged", part)

    def test_it_never_writes_the_keyring(self) -> None:
        self.assertEqual(self.part("== healthy", "== damaged").count("unchanged"), 1, self.out)

    def test_a_damaged_file_exits_1(self) -> None:
        part = self.out.split("== damaged", 1)[1]
        self.assertIn("FAIL", part)
        self.assertIn("rc=1", part)

    def test_the_check_code_has_no_write_or_unlock_call(self) -> None:
        mod = load_helper()
        for fn in (mod.cmd_doctor, mod.doctor_items, mod.keyring_file_lines):
            src = inspect.getsource(fn)
            for banned in ("unlock_sync", "create_sync", "delete_sync", "set_secret", "set_label", "open(path, \"w"):
                self.assertNotIn(banned, src, fn.__name__)

    def test_exit_6_messages_point_at_doctor(self) -> None:
        self.assertIn("omapass doctor", load_helper().HOWTO_CHECK)


if __name__ == "__main__":
    unittest.main()
