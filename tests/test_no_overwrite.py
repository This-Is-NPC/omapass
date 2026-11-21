"""Sandbox integration: a write never replaces an item unless asked to.

Runs the real helper against the sandbox gnome-keyring in a private D-Bus
session. Identity is (account, kind): a login and an nsec with the same
account are different items.
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
mkdir -p "$HOME/.local/share/keyrings"
printf '[keyring]\ndisplay-name=Default keyring\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n' \
  > "$HOME/.local/share/keyrings/Default_keyring.keyring"
printf 'Default_keyring' > "$HOME/.local/share/keyrings/default"
gnome-keyring-daemon --start --components=secrets >/dev/null
h() { python3 -I "$HELPER" "$@"; }
r() { echo "$1=$2"; }

printf one | h store --account a --folder F1 2>/dev/null;            r store1 $?
printf two | h store --account a --folder F2 2>/dev/null;            r store2 $?
r get_after_refuse "$(h get --account a --yes)"
r list_after_refuse "$(h list)"
printf two | h store --account a --folder F2 --replace 2>/dev/null;  r store_replace $?
r get_after_replace "$(h get --account a --yes)"
r list_after_replace "$(h list | tr '\t\n' ' ')"

printf nsec | h store --account a --folder N --kind nostr 2>/dev/null;       r store_kind $?
r get_login "$(h get --account a --yes)"
r get_nostr "$(h get --account a --kind nostr --yes)"
printf three | h store --account a --folder F3 --replace 2>/dev/null;        r login_replace $?
r get_nostr_after_login_replace "$(h get --account a --kind nostr --yes)"
r count_after_login_replace "$(h list | wc -l)"
printf four | h store --account a --folder F4 --kind nostr 2>/dev/null;      r store_kind_again $?
h clear --account a --kind nostr;                                            r clear_kind $?
r get_login_after_clear "$(h get --account a --yes)"
h exists --account a --kind nostr;                                           r exists_nostr_after_clear $?

h nostr new --account n1 >/dev/null 2>&1;                                    r nostr_new $?
before=$(h get --account n1 --kind nostr --yes)
h generate-nostr --account n1 >/dev/null 2>&1;                               r gen_refused $?
r nsec_kept "$([ "$before" = "$(h get --account n1 --kind nostr --yes)" ] && echo yes || echo no)"
h generate-nostr --account n1 --replace >/dev/null 2>&1;                     r gen_replace $?
r nsec_changed "$([ "$before" != "$(h get --account n1 --kind nostr --yes)" ] && echo yes || echo no)"
stop_keyring
"""


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestNoSilentOverwrite(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "PATH": os.environ["PATH"],
                "HOME": tmp,
                "XDG_RUNTIME_DIR": tmp,
                "HELPER": str(HELPER),
            }
            proc = subprocess.run(
                ["dbus-run-session", "--", "bash", "-c", SESSION],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        cls.out = dict(
            line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
        )

    def test_same_account_is_refused_without_replace(self) -> None:
        self.assertEqual(self.out["store1"], "0")
        self.assertEqual(self.out["store2"], "4")
        self.assertEqual(self.out["get_after_refuse"], "one")
        self.assertEqual(self.out["list_after_refuse"], "a\tF1")

    def test_replace_updates_secret_and_label(self) -> None:
        self.assertEqual(self.out["store_replace"], "0")
        self.assertEqual(self.out["get_after_replace"], "two")
        self.assertEqual(self.out["list_after_replace"], "a F2 ")

    def test_kind_is_part_of_identity(self) -> None:
        self.assertEqual(self.out["store_kind"], "0")
        self.assertEqual(self.out["get_login"], "two")
        self.assertEqual(self.out["get_nostr"], "nsec")
        self.assertEqual(self.out["store_kind_again"], "4")

    def test_replacing_login_keeps_same_account_nsec(self) -> None:
        self.assertEqual(self.out["login_replace"], "0")
        self.assertEqual(self.out["get_nostr_after_login_replace"], "nsec")
        self.assertEqual(self.out["count_after_login_replace"], "2")

    def test_clear_with_kind_removes_only_that_item(self) -> None:
        self.assertEqual(self.out["clear_kind"], "0")
        self.assertEqual(self.out["get_login_after_clear"], "three")
        self.assertEqual(self.out["exists_nostr_after_clear"], "1")

    def test_generate_nostr_needs_replace(self) -> None:
        self.assertEqual(self.out["nostr_new"], "0")
        self.assertEqual(self.out["gen_refused"], "4")
        self.assertEqual(self.out["nsec_kept"], "yes")
        self.assertEqual(self.out["gen_replace"], "0")
        self.assertEqual(self.out["nsec_changed"], "yes")


if __name__ == "__main__":
    unittest.main()
