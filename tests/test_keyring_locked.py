"""A locked or missing default keyring is exit 10 for every command, never 1 or "absent".

Real gnome-keyring on a private D-Bus session with its own HOME. The locked
case uses an encrypted keyring with a password that is locked after the item
is stored and has no prompter, so unlocking cannot succeed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only
from tests.helper_loader import HELPER_PATH, ROOT

COMMANDS = r"""
for c in "exists --account bank" "get --account bank" "rm -- bank" "copy --account bank" \
         "store --account bank --folder F --replace" "list --json" "nostr show-npub --account bank"; do
  printf x | timeout 30 /usr/bin/python3 -I "$HELPER" $c >/dev/null 2>"$HOME/err"; rc=$?
  echo "$c -> $rc [$(head -c 120 "$HOME/err")]"
done
"""

TYPE_PROBE = r"""
python3 -I - <<'PY'
import sys
from collections import Counter
from unittest import mock
sys.path.insert(0, "/src")
from tests.helper_loader import load_helper
from tests.test_helper_security import invoke_main
mod = load_helper()
with mock.patch.object(mod, "wtype_tmp_problem", return_value=None), \
     mock.patch.object(mod, "wait_for_focus", return_value=True):
    code, _o, err = invoke_main(mod, ["type", "--account", "bank", "--compositor", "hyprland", "--expect-id", "1"])
print(f"type -> {code} [{err.strip()[:120]}]")
PY
"""

LOCKED = STOP_OWN_KEYRING + r"""
set -u
printf pw | gnome-keyring-daemon --unlock --components=secrets >/dev/null
gnome-keyring-daemon --start --components=secrets >/dev/null; sleep 0.5
gdbus call --session -d org.freedesktop.secrets -o /org/freedesktop/secrets \
  -m org.freedesktop.Secret.Service.SetAlias default /org/freedesktop/secrets/collection/login >/dev/null
printf 'dummy' | python3 -I "$HELPER" store --account bank --folder F || echo STORE-FAILED
head -c 15 "$HOME/.local/share/keyrings/login.keyring" | grep -q GnomeKeyring && echo encrypted
gdbus call --session -d org.freedesktop.secrets -o /org/freedesktop/secrets \
  -m org.freedesktop.Secret.Service.Lock '["/org/freedesktop/secrets/collection/login"]' >/dev/null
""" + COMMANDS + TYPE_PROBE + "stop_keyring\n"

MISSING = STOP_OWN_KEYRING + r"""
set -u
gnome-keyring-daemon --start --components=secrets >/dev/null; sleep 0.5
""" + COMMANDS + TYPE_PROBE + "stop_keyring\n"
COMMAND_NAMES = ("exists", "get", "rm", "copy", "store", "nostr", "type")


def run(script: str) -> str:
    tmp = tempfile.mkdtemp()
    home = Path(tmp) / "home"
    home.mkdir()
    proc = subprocess.run(
        ["dbus-run-session", "--", "bash", "-c", script],
        text=True, capture_output=True, timeout=240, stdin=subprocess.DEVNULL,
        env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "HOME": str(home),
             "XDG_RUNTIME_DIR": tmp, "HELPER": str(HELPER_PATH), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    shutil.rmtree(tmp, True)
    return proc.stdout + proc.stderr


@sandbox_only
class TestLockedOrMissingKeyring(unittest.TestCase):
    def check(self, out: str, names: tuple[str, ...]) -> None:
        self.assertNotIn("STORE-FAILED", out)
        for name in names:
            hits = [ln for ln in out.splitlines() if ln.startswith(name + " ")]
            with self.subTest(command=name):
                self.assertEqual(len(hits), 1, out)
                self.assertIn(" -> 10 [", hits[0])
                self.assertIn("keyring", hits[0])

    def test_locked_default_keyring(self) -> None:
        out = run(LOCKED)
        self.assertIn("encrypted", out)
        # `list` reads the locked keyring's public attributes without unlocking.
        self.check(out, COMMAND_NAMES)

    def test_missing_default_keyring(self) -> None:
        self.check(run(MISSING), COMMAND_NAMES + ("list",))


if __name__ == "__main__":
    unittest.main()
