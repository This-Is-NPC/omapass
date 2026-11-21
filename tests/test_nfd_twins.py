"""--replace never merges items whose names differ only in NFC/NFD.

An older version stored names as typed, so a keyring can hold "café" in NFC
and in NFD as two items with different secrets. Replacing one must not delete
the other.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH
from tests.test_secret_validation import SETUP

RUN = SETUP + r"""
python3 -I - <<'PY'
import base64, unicodedata
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None)
col = Secret.Collection.for_alias_sync(svc, "default", Secret.CollectionFlags.NONE, None)
svc.unlock_sync([col], None)
def mk(acct, secret, enc):
    attrs = {"service": "omapass", "account": acct}
    if enc:
        attrs["enc"] = "b64"
        secret = base64.b64encode(secret.encode()).decode()
    Secret.Item.create_sync(col, None, attrs, "Web", Secret.Value.new(secret, len(secret), "text/plain"), Secret.ItemCreateFlags.NONE, None)
mk(unicodedata.normalize("NFD", "café"), "old-nfd-secret", False)
mk("café", "nfc-secret", True)
PY
NFC=$(printf 'caf\xc3\xa9'); NFD=$(printf 'cafe\xcc\x81')
for spelling in "$NFC" "$NFD"; do
  printf 'new-secret' | h store --account="$spelling" --folder Web --replace 2>"$HOME/err"; echo "replace_rc=$?"
  cat "$HOME/err"
done
printf 'new-secret' | h store --account="$NFC" --folder Web 2>/dev/null; echo "plain_rc=$?"
echo "nfd_secret=$(h get --account="$NFD")"
echo "nfc_secret=$(h get --account="$NFC")"
echo "count=$(h list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
h rm -- "$NFD" 2>&1; echo "rm_nfd_rc=$?"
printf 'new-secret' | h store --account="$NFC" --folder Web --replace; echo "after_rm_rc=$?"
echo "final_count=$(h list --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
echo "final_secret=$(h get --account="$NFC")"
stop_keyring
"""


@sandbox_only
class TestNfdTwins(unittest.TestCase):
    def test_replace_refuses_twins_then_works_after_removing_one(self) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", RUN],
            text=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                 "HELPER": str(HELPER_PATH)},
        )
        out = proc.stdout + proc.stderr
        # Both replace attempts are refused with exit 11; a plain store says "exists".
        self.assertEqual(out.count("replace_rc=11"), 2, out)
        self.assertIn("differ only in Unicode normalization", out)
        self.assertIn("plain_rc=4", out)
        # Nothing was deleted or changed.
        self.assertIn("nfd_secret=old-nfd-secret", out)
        self.assertIn("nfc_secret=nfc-secret", out)
        self.assertIn("count=2", out)
        # Removing one twin by its exact spelling makes the replace unambiguous.
        self.assertIn("rm_nfd_rc=0", out)
        self.assertIn("after_rm_rc=0", out)
        self.assertIn("final_count=1", out)
        self.assertIn("final_secret=new-secret", out)


if __name__ == "__main__":
    unittest.main()
