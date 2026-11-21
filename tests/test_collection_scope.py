"""Sandbox integration: the helper only ever touches the default collection.

An item with service=omapass in the ephemeral `session` collection (any local
client can create one) must not affect list/get/exists/store/clear.
Uses a private D-Bus session with its own HOME.
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

# Session-collection items die with the D-Bus client that created them, so
# keep one client alive holding the decoys until the end.
python3 -I - <<'PY' &
import os, sys, time, gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION, None)
col = Secret.Collection.for_alias_sync(svc, "session", Secret.CollectionFlags.NONE, None)
for account, secret in (("dec", "evil"), ("only", "evil2")):
    val = Secret.Value.new(secret, len(secret), "text/plain")
    Secret.Item.create_sync(col, None, {"service": "omapass", "account": account},
                            "Decoy", val, Secret.ItemCreateFlags.NONE, None)
open(os.environ["HOME"] + "/ready", "w").close()
time.sleep(60)
PY
holder=$!
for _ in $(seq 50); do [ -e "$HOME/ready" ] && break; sleep 0.1; done
# decoy_state <account>: secret of the session item, or "gone".
decoy_state() {
python3 -I - "$1" <<'PY'
import sys, gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION, None)
col = Secret.Collection.for_alias_sync(svc, "session", Secret.CollectionFlags.LOAD_ITEMS, None)
items = [i for i in col.get_items() if (i.get_attributes() or {}).get("account") == sys.argv[1]]
if not items:
    print("gone")
else:
    items[0].load_secret_sync(None)
    print(items[0].get_secret().get_text())
PY
}

r list_has_decoy "$(h list | cut -f1 | tr '\n' ' ')"
h get --account only --yes >/dev/null 2>&1;                  r get_spoof $?
h exists --account only;                                     r exists_spoof $?
h clear --account only >/dev/null 2>&1;                      r clear_spoof $?
r decoy_only_after_clear "$(decoy_state only)"

printf real | h store --account dec --folder F 2>/dev/null;  r store_over_decoy $?
r get_dec "$(h get --account dec --yes)"
r decoy_after_store "$(decoy_state dec)"
printf real2 | h store --account dec --folder F2 --replace 2>/dev/null; r replace_dec $?
r get_dec2 "$(h get --account dec --yes)"
r decoy_after_replace "$(decoy_state dec)"
r list_after "$(h list | tr '\t\n' ' ')"
h clear --account dec;                                       r clear_dec $?
h exists --account dec;                                      r exists_after_clear $?
r decoy_after_clear "$(decoy_state dec)"
kill $holder
stop_keyring
"""


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestCollectionScope(unittest.TestCase):
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

    def test_list_ignores_session_collection(self) -> None:
        self.assertEqual(self.out["list_has_decoy"], "")

    def test_get_exists_clear_ignore_session_items(self) -> None:
        self.assertNotEqual(self.out["get_spoof"], "0")
        self.assertEqual(self.out["exists_spoof"], "1")
        self.assertNotEqual(self.out["clear_spoof"], "0")
        self.assertEqual(self.out["decoy_only_after_clear"], "evil2")

    def test_store_writes_default_not_session(self) -> None:
        self.assertEqual(self.out["store_over_decoy"], "0")
        self.assertEqual(self.out["get_dec"], "real")
        self.assertEqual(self.out["decoy_after_store"], "evil")
        self.assertEqual(self.out["replace_dec"], "0")
        self.assertEqual(self.out["get_dec2"], "real2")
        self.assertEqual(self.out["decoy_after_replace"], "evil")
        self.assertEqual(self.out["list_after"], "dec F2 ")

    def test_clear_only_removes_default_item(self) -> None:
        self.assertEqual(self.out["clear_dec"], "0")
        self.assertEqual(self.out["exists_after_clear"], "1")
        self.assertEqual(self.out["decoy_after_clear"], "evil")


if __name__ == "__main__":
    unittest.main()
