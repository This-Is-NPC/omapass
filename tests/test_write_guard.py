"""The helper must never be the write that corrupts a plaintext keyring."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only
from tests.helper_loader import HELPER_PATH, ROOT

HEALTH = "/opt/sandbox/keyring-health.py"

PREPARE = STOP_OWN_KEYRING + r"""
set -u
mkdir -p "$HOME/.local/share/keyrings"
F="$HOME/.local/share/keyrings/Default_keyring.keyring"
printf '[keyring]\ndisplay-name=Default keyring\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n' > "$F"
printf 'Default_keyring' > "$HOME/.local/share/keyrings/default"
start() { gnome-keyring-daemon --start --components=secrets >/dev/null; }
h() { python3 -I "$HELPER" "$@"; }
"""
SETUP = PREPARE + "start\n"

# Another app's item with a literal backslash-n, as the old helper wrote it.
LEGACY_ITEM = r"""
python3 -I - <<'PY'
import os
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None)
col = Secret.Collection.for_alias_sync(svc, "default", Secret.CollectionFlags.NONE, None)
svc.unlock_sync([col], None)
text = os.environ.get("RAW_TEXT") or "a" + chr(92) + "nb"
Secret.Item.create_sync(col, None, {"service": "omapass", "account": "x"}, "f",
    Secret.Value.new(text, len(text), "text/plain"), Secret.ItemCreateFlags.NONE, None)
PY
"""

UNSAFE_RUN = SETUP + LEGACY_ITEM + r"""
stop_keyring; start
sha256sum "$F" > "$HOME/before"
printf 'pw' | h store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
h clear --account x 2>"$HOME/clear.err"; echo $? > "$HOME/clear.rc"
sha256sum "$F" > "$HOME/after"
stop_keyring; start
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

# The daemon parses item ids with strtoul, so [0x1] is a real item too.
HEX_ID_RUN = PREPARE + r"""
printf '\n[0x1]\ndisplay-name=f\ncreated=0\nmodified=0\nsecret=a\\nb\n' >> "$F"
start
sha256sum "$F" > "$HOME/before"
printf 'pw' | h store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
sha256sum "$F" > "$HOME/after"
stop_keyring
"""

CLEAN_RUN = SETUP + r"""
printf 'pw' | h store --account a --folder f 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
h clear --account a 2>"$HOME/clear.err"; echo $? > "$HOME/clear.rc"
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""


# The helper sees a different XDG_DATA_HOME, holding a fake safe keyring file,
# than the daemon whose real keyring has an unsafe item.
MISMATCH_RUN = SETUP + LEGACY_ITEM + r"""
stop_keyring; start
FAKE="$HOME/fake/keyrings"; mkdir -p "$FAKE"
cp "$HOME/.local/share/keyrings/default" "$FAKE/default"
head -n 6 "$F" > "$FAKE/Default_keyring.keyring"
sha256sum "$F" > "$HOME/before"
printf 'pw' | XDG_DATA_HOME="$HOME/fake" python3 -I "$HELPER" store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
sha256sum "$F" > "$HOME/after"
stop_keyring
"""

# Another app's clean non-ASCII item must not be refused.
NON_ASCII_RUN = SETUP + "export RAW_TEXT='pässwörd-日本'\n" + LEGACY_ITEM + r"""
stop_keyring; start
printf 'pw' | h store --account b --folder f 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

# Encrypted login keyring (password-protected) holding an item a plaintext
# keyring could not keep: the guard must not block it.
ENCRYPTED_SETUP = STOP_OWN_KEYRING + r"""
set -u
h() { python3 -I "$HELPER" "$@"; }
echo -n pw | gnome-keyring-daemon --unlock --components=secrets >/dev/null
F="$HOME/.local/share/keyrings/login.keyring"
""" + LEGACY_ITEM
ENCRYPTED_RUN = ENCRYPTED_SETUP + r"""
printf 'pw' | h store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
head -c 16 "$F" | od -An -c | tr -d ' ' > "$HOME/magic"
stop_keyring
"""

# The daemon cannot save: the helper must exit 6 with a message, not a traceback.
ENCRYPTED_READONLY_RUN = ENCRYPTED_SETUP + r"""
chmod a-w "$HOME/.local/share/keyrings"
printf 'pw' | h store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
chmod u+w "$HOME/.local/share/keyrings"
stop_keyring
"""

HEALTH_ENCRYPTED_RUN = ENCRYPTED_SETUP + r"""
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

# Daemon environment unreadable: the guard must still check (and refuse), even
# when the keyring file is encrypted.
NO_ENVIRON_RUN = ENCRYPTED_SETUP + r"""
python3 -I - <<'PY' > "$HOME/fallback.out" 2>&1; echo $? > "$HOME/fallback.rc"
import builtins, os, sys
sys.path.insert(0, os.environ["ROOT"])
from tests.helper_loader import load_helper
helper = load_helper()
real_open = builtins.open
def deny(path, *a, **k):
    if str(path).startswith("/proc/"):
        raise PermissionError(path)
    return real_open(path, *a, **k)
builtins.open = deny
kr = helper.GiKeyring()
col = kr._default_collection()
print("path", helper.daemon_keyring_path(col))
kr._guard_write(col)
print("not refused")
PY
stop_keyring
"""

LOAD_HELPER = r"""
import os, sys
sys.path.insert(0, os.environ["ROOT"])
from tests.helper_loader import load_helper
helper = load_helper()
kr = helper.GiKeyring()
col = kr._default_collection()
"""

# A keyring file that stops parsing after a write is reported loudly.
DAMAGED_RUN = SETUP + r"""
python3 -I - <<'PY' > "$HOME/damaged.out" 2>&1; echo $? > "$HOME/damaged.rc"
""" + LOAD_HELPER + r"""
kr._verify_written(col, "a")
print("intact file accepted")
with open(os.path.expanduser("~/.local/share/keyrings/Default_keyring.keyring"), "a") as fh:
    fh.write("\n[0]\nsecret=a\nb\n")
kr._verify_written(col, "a")
PY
stop_keyring
"""


# Another app writes between the guard and the daemon's write. The guard passed
# on a clean keyring; only the post-write check can still notice.
RACE_RUN = SETUP + r"""
python3 -I - <<'PY' > "$HOME/race.out" 2>&1; echo $? > "$HOME/race.rc"
""" + LOAD_HELPER + r"""
from gi.repository import Secret
guard = kr._guard_write
def racing_guard(collection):
    count = guard(collection)
    text = os.environ["RACE_TEXT"]
    Secret.Item.create_sync(collection, None, {"app": "other"}, "o",
        Secret.Value.new(text, len(text), "text/plain"), Secret.ItemCreateFlags.NONE, None)
    return count
kr._guard_write = racing_guard
kr.store("mine", "f", "pw")
print("store accepted")
PY
stop_keyring
"""

# An encrypted keyring is confirmed through the Secret Service, not the file.
ENCRYPTED_VERIFY_RUN = ENCRYPTED_SETUP + r"""
python3 -I - <<'PY' > "$HOME/verify.out" 2>&1; echo $? > "$HOME/verify.rc"
""" + LOAD_HELPER + r"""
def verdict(label, *args):
    try:
        kr._verify_written(col, "mine", *args)
        print(label, "confirmed")
    except SystemExit as e:
        print(label, "exit", e.code)
kr.store("mine", "f", "pw")
good = helper.encode_secret("pw")
verdict("store", "", "f", good)
verdict("wrong-secret", "", "f", helper.encode_secret("other"))
verdict("wrong-label", "", "other", good)
verdict("wrong-kind", "nostr", "f", good)
verdict("clear-too-early", "")
kr.clear("mine")
verdict("clear", "")
verdict("store-missing", "", "f", good)
PY
stop_keyring
"""


# Another app's raw item, as printf formats for the group's lines, and whether
# the guard allows a rewrite. A rewrite is allowed unless it makes the item
# worse than a plain reload would: the daemon serves leading whitespace and CR
# stripped, and a value it already loses on reload (invalid escape) is not lost
# by writing it again. Binary secrets must be valid and unambiguous. Each case
# runs on the freshly loaded file and after a write and restart.
RAW_CASES = {
    "leading space": ("secret= abc\\n", True, True),
    "leading tab": ("secret=\\tabc\\n", True, True),
    "carriage return": ("secret=abc\\r\\n", True, True),
    "only a space": ("secret= \\n", True, True),
    "valid escape": ("secret=a\\\\sb\\n", True, True),
    "empty secret line": ("secret=\\n", True, True),
    "binary only": ("binary-secret=ff41\\n", True, True),
    "invalid escape": ("secret=a\\\\b\\n", True, True),
    "trailing backslash": ("secret=abc\\\\\\n", True, True),
    "invalid utf-8": ("secret=\\xff\\n", False, True),
    "binary invalid hex": ("binary-secret=zz\\n", False, True),
    "binary 0x": ("binary-secret=0x\\n", False, True),
    "binary spaced": ("binary-secret=ff ff\\n", False, True),
    "binary odd length": ("binary-secret=abc\\n", False, True),
    "secret and binary": ("secret=abc\\nbinary-secret=616263\\n", False, True),
    "secret and other binary": ("secret=abc\\nbinary-secret=646566\\n", False, True),
    "empty secret and bad binary": ("secret=\\nbinary-secret=zz\\n", False, True),
    "secret and bad binary": ("secret=abc\\nbinary-secret=zz\\n", False, True),
    "repeated secret": ("secret=abc\\nsecret=abc\\n", False, True),
}

RAW_RUN = PREPARE + r"""
printf '\n[1]\nitem-type=0\ndisplay-name=f\nmtime=0\nctime=0\n' >> "$F"
printf "$RAW_LINES" >> "$F"
start
""" + "\n" + "@@POKE@@" + r"""
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
sha256sum "$F" > "$HOME/before"
printf 'pw' | h store --account other --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
sha256sum "$F" > "$HOME/after"
stop_keyring; start
python3 -I "$HEALTH" > "$HOME/health2.out" 2>&1; echo $? > "$HOME/health2.rc"
stop_keyring
"""


# Another app creates one item over D-Bus; the daemon is restarted so the file
# is what it wrote, then the helper stores. CASE picks the secret bytes.
OTHER_ITEM = r"""
python3 -I - <<'PY'
import os
import gi
gi.require_version("Secret", "1")
from gi.repository import Gio, GLib, Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None)
col = Secret.Collection.for_alias_sync(svc, "default", Secret.CollectionFlags.NONE, None)
svc.unlock_sync([col], None)
data = bytes.fromhex(os.environ["CASE_HEX"])
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
def call(path, iface, method, args, sig):
    return bus.call_sync("org.freedesktop.secrets", path, iface, method,
        GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE, 5000, None)
out, session = call("/org/freedesktop/secrets", "org.freedesktop.Secret.Service",
                    "OpenSession", ("plain", GLib.Variant("s", "")), "(sv)").unpack()
props = {"org.freedesktop.Secret.Item.Label": GLib.Variant("s", "other"),
         "org.freedesktop.Secret.Item.Attributes": GLib.Variant("a{ss}", {"app": "other"})}
call(col.get_object_path(), "org.freedesktop.Secret.Collection", "CreateItem",
     (props, (session, b"", data, os.environ.get("CASE_TYPE", "text/plain")), False),
     "(a{sv}(oayays)b)")
PY
"""

# A write by another app, then a restart: the file is what the daemon wrote.
RESTART = "stop_keyring; start\n"
RAW_RUN = RAW_RUN.replace(
    "@@POKE@@", 'if [ "${RESTART:-}" = 1 ]; then\n' + OTHER_ITEM + RESTART + "fi\n"
)

ITEM_RUN = SETUP + OTHER_ITEM + r"""
if [ "${RESTART:-1}" = 1 ]; then stop_keyring; start; fi
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
sha256sum "$F" > "$HOME/before"
printf 'pw' | h store --account mine --folder f >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
sha256sum "$F" > "$HOME/after"
python3 -I "$HEALTH" > "$HOME/health2.out" 2>&1; echo $? > "$HOME/health2.rc"
stop_keyring
"""

# Secrets another app may store over D-Bus: (name, hex bytes, content type,
# allowed while the daemon still serves what was stored, allowed after a restart).
OTHER_ITEMS = (
    ("empty", "", "text/plain", True, True),
    ("trailing spaces", b"abc  ".hex(), "text/plain", True, True),
    # Spaces are lost at the next restart whether or not omapass writes.
    ("leading and trailing spaces", b"  pad  ".hex(), "text/plain", True, True),
    # Served as typed until the daemon reloads the file (it may at any time,
    # e.g. right after our write); then it is a real newline, which the next
    # rewrite would put raw into the file.
    ("literal backslash n", b"a\\nb".hex(), "text/plain", False, False),
    ("invalid escape", b"a\\b".hex(), "text/plain", True, True),
    # The daemon stores it as `binary-secret=<hex>` and reloads it intact.
    ("binary", bytes([0xFF, 0xFE, 1, 0x5C]).hex(), "application/octet-stream", True, True),
    ("binary after ascii", b"abc\xff".hex(), "application/octet-stream", True, True),
)


class TestPreWriteCountGuard(unittest.TestCase):
    """The pre-write guard refuses when the daemon serves other items than the file holds."""

    FILE = (
        b"[keyring]\ndisplay-name=d\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n"
        b"\n[1]\nitem-type=0\ndisplay-name=f\nmtime=0\nctime=0\nsecret=abc\n"
    )

    def guard(self, served):
        from unittest import mock

        from tests.helper_loader import load_helper

        mod = load_helper()
        with tempfile.NamedTemporaryFile() as fh:
            fh.write(self.FILE)
            fh.flush()
            with (
                mock.patch.object(mod, "daemon_keyring_path", return_value=fh.name),
                mock.patch.object(mod, "served_secrets", return_value=served),
            ):
                kr = object.__new__(mod.GiKeyring)
                try:
                    return mod, kr._guard_write(object())
                except SystemExit as exc:
                    return mod, exc

    def test_served_matches_the_file(self) -> None:
        _mod, result = self.guard({"1": b"abc"})
        self.assertEqual(result, 1)

    def test_daemon_serves_more_items_than_the_file_holds(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()) as err:
            mod, result = self.guard({"1": b"abc", "2": b"other"})
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(result.code, mod.EXIT_UNSAFE_KEYRING)
        self.assertIn("different number of items", err.getvalue())


class TestHealthSharesTheRule(unittest.TestCase):
    """keyring-health.py imports the helper's rule instead of keeping a copy."""

    def test_health_loads_the_helper(self) -> None:
        src = (Path(__file__).with_name("sandbox") / "keyring-health.py").read_text()
        self.assertIn("helper.main([\"doctor\"])", src)
        self.assertNotIn("def is_item", src)


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestWriteGuard(unittest.TestCase):
    def _run(self, script: str, **extra: str) -> Path:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "HELPER": str(HELPER_PATH),
            "ROOT": str(ROOT),
            "HEALTH": HEALTH,
            "LANG": "C.UTF-8",
            **extra,
        }
        subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", script],
            env=env, capture_output=True, text=True, timeout=90,
        )
        return home

    def test_unsafe_keyring_refuses_store_and_clear(self) -> None:
        home = self._run(UNSAFE_RUN)
        for name in ("store", "clear"):
            self.assertEqual((home / f"{name}.rc").read_text().strip(), "5", name)
            err = (home / f"{name}.err").read_text()
            self.assertIn("1 item(s)", err)
            self.assertIn("Nothing was written", err)
        self.assertEqual((home / "before").read_text(), (home / "after").read_text())
        # The legacy item itself stays unfaithful (not ours to fix), but the
        # file must still parse with exactly that one item.
        self.assertIn("OK   file Default_keyring.keyring: parses, 1 items",
                      (home / "health.out").read_text())

    def test_guard_and_health_agree_on_raw_items(self) -> None:
        for name, (lines, *allowed) in RAW_CASES.items():
            for restarted in (False, True):
                with self.subTest(name, restarted=restarted):
                    home = self._run(RAW_RUN, RAW_LINES=lines, CASE_HEX="78",
                                     RESTART="1" if restarted else "0")
                    self.check(home, allowed[restarted])

    def check(self, home: Path, allowed: bool) -> None:
        """Guard and health agree, and both match `allowed`."""
        store = (home / "store.rc").read_text().strip()
        health = (home / "health.rc").read_text().strip()
        self.assertEqual(store, "0" if allowed else "5", (home / "store.err").read_text())
        self.assertEqual(health, "0" if allowed else "1", (home / "health.out").read_text())
        if allowed:  # the rewritten file is still healthy
            self.assertEqual((home / "health2.rc").read_text().strip(), "0",
                             (home / "health2.out").read_text())
        else:
            self.assertEqual((home / "before").read_text(), (home / "after").read_text())

    def test_other_apps_items(self) -> None:
        for name, hexdata, ctype, *allowed in OTHER_ITEMS:
            for restarted in (False, True):
                with self.subTest(name, restarted=restarted):
                    home = self._run(ITEM_RUN, CASE_HEX=hexdata, CASE_TYPE=ctype,
                                     RESTART="1" if restarted else "0")
                    self.check(home, allowed[restarted])

    def test_non_decimal_item_id_is_checked_too(self) -> None:
        home = self._run(HEX_ID_RUN)
        self.assertEqual((home / "store.rc").read_text().strip(), "5",
                         (home / "store.err").read_text())
        self.assertEqual((home / "before").read_text(), (home / "after").read_text())

    def test_clean_keyring_allows_store_and_clear(self) -> None:
        home = self._run(CLEAN_RUN)
        self.assertEqual((home / "store.rc").read_text().strip(), "0",
                         (home / "store.err").read_text())
        self.assertEqual((home / "clear.rc").read_text().strip(), "0",
                         (home / "clear.err").read_text())
        self.assertEqual((home / "health.rc").read_text().strip(), "0",
                         (home / "health.out").read_text())

    def test_guard_ignores_helper_xdg_data_home(self) -> None:
        home = self._run(MISMATCH_RUN)
        self.assertEqual((home / "store.rc").read_text().strip(), "5",
                         (home / "store.err").read_text())
        self.assertEqual((home / "before").read_text(), (home / "after").read_text())

    def test_non_ascii_clean_keyring_is_allowed(self) -> None:
        home = self._run(NON_ASCII_RUN)
        self.assertEqual((home / "store.rc").read_text().strip(), "0",
                         (home / "store.err").read_text())
        self.assertEqual((home / "health.rc").read_text().strip(), "0",
                         (home / "health.out").read_text())

    def test_encrypted_keyring_is_not_blocked(self) -> None:
        home = self._run(ENCRYPTED_RUN)
        self.assertEqual((home / "store.rc").read_text().strip(), "0",
                         (home / "store.err").read_text())
        self.assertTrue((home / "magic").read_text().startswith("GnomeKeyring"),
                        (home / "magic").read_text())

    def test_health_accepts_encrypted_keyring(self) -> None:
        home = self._run(HEALTH_ENCRYPTED_RUN)
        out = (home / "health.out").read_text()
        self.assertEqual((home / "health.rc").read_text().strip(), "0", out)
        self.assertIn("login.keyring: encrypted (not parsed)", out)
        self.assertIn("items: 1 read back", out)

    def test_unreadable_daemon_environ_falls_back_to_checking(self) -> None:
        home = self._run(NO_ENVIRON_RUN)
        out = (home / "fallback.out").read_text()
        self.assertIn("path None", out)
        self.assertNotIn("not refused", out)
        self.assertEqual((home / "fallback.rc").read_text().strip(), "5", out)

    def test_race_after_the_guard_is_reported(self) -> None:
        # An extra item (the count is not the expected one); a newline, which
        # the daemon writes raw into the file.
        for name, text in (("extra item", "abc"), ("newline", "a\nb")):
            with self.subTest(name):
                home = self._run(RACE_RUN, RACE_TEXT=text)
                out = (home / "race.out").read_text()
                self.assertEqual((home / "race.rc").read_text().strip(), "6", out)
                self.assertNotIn("store accepted", out)

    def test_encrypted_write_is_confirmed_through_the_service(self) -> None:
        home = self._run(ENCRYPTED_VERIFY_RUN)
        out = (home / "verify.out").read_text()
        self.assertEqual((home / "verify.rc").read_text().strip(), "0", out)
        for line in ("store confirmed", "clear confirmed", "wrong-secret exit 6",
                     "wrong-label exit 6", "wrong-kind exit 6",
                     "clear-too-early exit 6", "store-missing exit 6"):
            self.assertIn(line, out)

    def test_encrypted_write_failure_is_a_clean_exit_6(self) -> None:
        home = self._run(ENCRYPTED_READONLY_RUN)
        err = (home / "store.err").read_text()
        self.assertEqual((home / "store.rc").read_text().strip(), "6", err)
        self.assertIn("THE WRITE FAILED", err)
        self.assertNotIn("Traceback", err)

    def test_damaged_file_after_write_is_reported(self) -> None:
        home = self._run(DAMAGED_RUN)
        out = (home / "damaged.out").read_text()
        self.assertIn("intact file accepted", out)
        self.assertEqual((home / "damaged.rc").read_text().strip(), "6", out)
        self.assertIn("MAY BE DAMAGED", out)
        self.assertIn("Do not log out", out)


if __name__ == "__main__":
    unittest.main()
