"""Failed keyring writes and clearing a missing item must not look like success."""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.helper_loader import HELPER_PATH as HELPER, load_helper
from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only

SESSION = STOP_OWN_KEYRING + r"""
set -u
mkdir -p "$HOME/.local/share/keyrings"
printf '[keyring]\ndisplay-name=Default keyring\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n' \
  > "$HOME/.local/share/keyrings/Default_keyring.keyring"
printf 'Default_keyring' > "$HOME/.local/share/keyrings/default"
gnome-keyring-daemon --start --components=secrets >/dev/null
h() { python3 -I "$HELPER" "$@"; }
r() { echo "$1=$2"; }

h clear --account nothere 2>"$HOME/err";                     r clear_missing $?
r clear_missing_err "$(cat "$HOME/err")"
h rm nothere 2>/dev/null;                                    r rm_missing $?
h nostr rm nothere 2>/dev/null;                              r nostr_rm_missing $?
stop_keyring
"""


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestClearMissing(unittest.TestCase):
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

    def test_clear_missing_item_fails(self) -> None:
        self.assertNotEqual(self.out["clear_missing"], "0")
        self.assertIn("nothere", self.out["clear_missing_err"])
        self.assertNotEqual(self.out["rm_missing"], "0")
        self.assertNotEqual(self.out["nostr_rm_missing"], "0")


class FakeItem:
    """Item with state; each failure flag makes one libsecret call return False."""

    count = itertools.count(1)

    def __init__(self, attrs, secret="", label="", fail=()):
        self.attrs, self.secret, self.label = dict(attrs), secret, label
        self.fail, self.deleted = set(fail), False
        self.path = f"/collection/default/{next(self.count)}"

    def get_object_path(self):
        return self.path

    def get_attributes(self):
        return self.attrs

    def get_secret(self):
        return mock.Mock(get_text=lambda: self.secret)

    def get_label(self):
        return self.label

    def set_secret_sync(self, value, *_):
        if "secret" in self.fail:
            return False
        self.secret = value
        return True

    def set_label_sync(self, label, *_):
        if "label" in self.fail:
            return False
        self.label = label
        return True

    def set_attributes_sync(self, _schema, attrs, *_):
        if "attributes" in self.fail:
            return False
        self.attrs = dict(attrs)
        return True

    def delete_sync(self, *_):
        if "delete" in self.fail:
            return False
        self.deleted = True
        return True


class FakeCollection:
    def __init__(self, items):
        self.items = items

    def live(self):
        return [i for i in self.items if not i.deleted]

    def search_sync(self, _schema, attrs, *_):
        return [
            i for i in self.live()
            if all(i.attrs.get(k) == v for k, v in attrs.items())
        ]


LEGACY = {"service": "omapass", "account": "a"}
ENCODED = {**LEGACY, "enc": "b64"}


class TestReplaceKeepsStateConsistent(unittest.TestCase):
    def backend(self, items, create_fails=False, create_none=False):
        mod = load_helper()
        col = FakeCollection(items)

        def create(_col, _schema, attrs, label, value, *_):
            if create_fails:
                raise RuntimeError("create failed")
            if create_none:
                return None
            item = FakeItem(attrs, value, label)
            col.items.append(item)
            return item

        kr = object.__new__(mod.GiKeyring)
        kr._Secret = mock.Mock(
            Value=mock.Mock(new=lambda text, *_: text),
            Item=mock.Mock(create_sync=create),
            SearchFlags=mock.Mock(ALL=1, UNLOCK=2, LOAD_SECRETS=4),
        )
        kr._default_collection = lambda: col
        kr.list_items = lambda: [{"account": i.attrs["account"]} for i in col.live()]
        kr._guard_write = lambda *_: None
        kr._verify_written = lambda *_: None
        return mod, kr, col

    def store(self, kr, mod, secret="new"):
        with mock.patch("sys.stderr"):
            kr.store("a", "F", secret, "", True)

    def assert_no_unencoded_base64(self, col, mod):
        for item in col.live():
            if item.attrs.get("enc") != "b64":
                self.assertNotEqual(item.secret, mod.encode_secret("new"))

    def test_legacy_replace_ends_with_one_encoded_item(self) -> None:
        legacy = FakeItem(LEGACY, "old", "f")
        mod, kr, col = self.backend([legacy])
        kr.store("a", "F", "new", "", True)
        self.assertTrue(legacy.deleted)
        (item,) = col.live()
        self.assertEqual(item.attrs, ENCODED)
        self.assertEqual((item.secret, item.label), (mod.encode_secret("new"), "F"))

    def test_legacy_replace_never_edits_the_legacy_item(self) -> None:
        # Every step on the legacy item fails: nothing may be written to it.
        legacy = FakeItem(LEGACY, "old", "f", fail={"secret", "attributes", "label"})
        mod, kr, col = self.backend([legacy])
        kr.store("a", "F", "new", "", True)
        self.assertEqual(legacy.secret, "old")
        self.assertEqual(legacy.attrs, LEGACY)

    def test_failing_create_leaves_legacy_untouched(self) -> None:
        legacy = FakeItem(LEGACY, "old", "f")
        mod, kr, col = self.backend([legacy], create_fails=True)
        with self.assertRaises(RuntimeError):
            kr.store("a", "F", "new", "", True)
        self.assertEqual(col.live(), [legacy])
        self.assertEqual((legacy.secret, legacy.attrs, legacy.label), ("old", LEGACY, "f"))

    def test_create_returning_none_keeps_the_legacy_item(self) -> None:
        legacy = FakeItem(LEGACY, "old", "f")
        mod, kr, col = self.backend([legacy], create_none=True)
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
            kr.store("a", "F", "new", "", True)
        self.assertNotEqual(cm.exception.code, 0)
        self.assertFalse(legacy.deleted)
        self.assertEqual(col.live(), [legacy])

    def test_failing_delete_prefers_the_encoded_item(self) -> None:
        legacy = FakeItem(LEGACY, "old", "F", fail={"delete"})
        mod, kr, col = self.backend([legacy])
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr") as err:
            kr.store("a", "F", "new", "", True)
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("old copy", "".join(c.args[0] for c in err.write.call_args_list))
        self.assertEqual(kr.get_secret("a"), "new")
        self.assert_no_unencoded_base64(col, mod)

    def test_rerun_removes_the_leftover_copy(self) -> None:
        legacy = FakeItem(LEGACY, "old", "F")
        encoded = FakeItem(ENCODED, "bmV3", "F")
        mod, kr, col = self.backend([legacy, encoded])
        self.store(kr, mod, "newer")
        self.assertTrue(legacy.deleted and encoded.deleted)
        (item,) = col.live()
        self.assertEqual(item.secret, mod.encode_secret("newer"))

    def test_encoded_replace_creates_a_new_item_and_never_edits_the_old_one(self) -> None:
        # R2: an in-place update is two daemon calls (secret, label); a kill
        # between them would leave the new secret in the old folder.
        item = FakeItem(ENCODED, "x", "f", fail={"secret", "label", "attributes"})
        mod, kr, col = self.backend([item])
        self.store(kr, mod)
        self.assertTrue(item.deleted)
        self.assertEqual((item.secret, item.label, item.attrs), ("x", "f", ENCODED))
        (new,) = col.live()
        self.assertEqual((new.secret, new.label, new.attrs), (mod.encode_secret("new"), "F", ENCODED))

    def test_encoded_replace_that_stops_before_the_delete_leaves_two_whole_items(self) -> None:
        item = FakeItem(ENCODED, "x", "f", fail={"delete"})
        mod, kr, col = self.backend([item])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.store(kr, mod)
        old, new = col.live()
        self.assertEqual((old.secret, old.label), ("x", "f"))
        self.assertEqual((new.secret, new.label), (mod.encode_secret("new"), "F"))

    def test_clear_removes_every_copy_and_reports_failure(self) -> None:
        items = [FakeItem(LEGACY, "old"), FakeItem(ENCODED, "bmV3")]
        mod, kr, col = self.backend(items)
        kr.clear("a")
        self.assertEqual(col.live(), [])
        mod, kr, col = self.backend([FakeItem(ENCODED, "x", fail={"delete"})])
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
            kr.clear("a")
        self.assertNotEqual(cm.exception.code, 0)


KEYRING_HEAD = "[keyring]\ndisplay-name=x\n\n"


def item_text(group, secret, label, attrs):
    out = f"[{group}]\nitem-type=0\ndisplay-name={label}\n"
    if secret is not None:
        out += f"secret={secret}\n"
    for n, (k, v) in enumerate(sorted(attrs.items())):
        out += f"\n[{group}:attribute{n}]\nname={k}\ntype=string\nvalue={v}\n"
    return out + "\n"


class TestVerifyAndGuardFile(unittest.TestCase):
    """The post-write check and the guard's file requirements, with a fake file."""

    def setUp(self) -> None:
        self.mod = load_helper()
        self.mod.VERIFY_TIMEOUT_S = 0.2
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "k.keyring"
        patcher = mock.patch.object(self.mod, "daemon_keyring_path", lambda _c: str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.kr = object.__new__(self.mod.GiKeyring)
        self.served = None  # None: the daemon serves each raw `secret=` line as is
        patcher = mock.patch.object(self.mod, "served_secrets", self.fake_served)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_served(self, _collection):
        if self.served is not None:
            return self.served
        kf = self.mod.load_keyfile(self.path.read_bytes())
        served, group = {}, None
        for line in self.path.read_text().split("\n"):
            if line.startswith("["):
                group = line[1:-1]
            elif line.startswith("secret=") and self.mod.is_item(group):
                served[group] = line[7:].encode()
        return {g: served.get(g, b"") for g in kf.get_groups()[0] if self.mod.is_item(g)}

    def write(self, text) -> None:
        self.path.write_text(KEYRING_HEAD + text)

    def verify(self, *args):
        with mock.patch("sys.stderr"):
            self.kr._verify_written(None, *args)

    def exit_code(self, *args):
        with self.assertRaises(SystemExit) as cm:
            self.verify(*args)
        return cm.exception.code

    ATTRS = {"service": "omapass", "account": "a", "enc": "b64"}

    def test_store_requires_the_item_in_the_file(self) -> None:
        self.write(item_text(1, "cHc=", "F", {**self.ATTRS, "account": "other"}))
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)

    def test_store_accepts_the_matching_item(self) -> None:
        self.write(item_text(1, "bmV3", "F", self.ATTRS))
        self.verify("a", "", "F", "bmV3")

    def test_store_rejects_wrong_secret_or_label(self) -> None:
        self.write(item_text(1, "b2xk", "F", self.ATTRS))
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)
        self.write(item_text(1, "bmV3", "Other", self.ATTRS))
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)

    def test_store_rejects_a_leftover_legacy_copy(self) -> None:
        legacy = {k: v for k, v in self.ATTRS.items() if k != "enc"}
        self.write(item_text(1, "bmV3", "F", self.ATTRS) + item_text(2, "old", "F", legacy))
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)

    def test_clear_requires_the_item_gone(self) -> None:
        self.write(item_text(1, "bmV3", "F", self.ATTRS))
        self.assertEqual(self.exit_code("a", ""), 6)
        self.write(item_text(1, "bmV3", "F", {**self.ATTRS, "account": "b"}))
        self.verify("a", "")

    def test_kind_is_part_of_the_identity(self) -> None:
        self.write(item_text(1, "bmV3", "F", {**self.ATTRS, "kind": "nostr"}))
        self.verify("a", "")
        self.assertEqual(self.exit_code("a", "nostr"), 6)

    def test_unparseable_file_says_damaged(self) -> None:
        self.write("[0]\nsecret=a\nb\n")
        self.assertEqual(self.exit_code("a", ""), 6)

    def test_unreadable_file_is_an_error(self) -> None:
        self.assertEqual(self.exit_code("a", ""), 6)

    def test_store_rejects_another_item_a_rewrite_would_alter(self) -> None:
        mine = item_text(1, "bmV3", "F", self.ATTRS)
        for name, other in (
            ("invalid binary", item_text(2, None, "o", {"app": "x"}).replace(
                "display-name=o\n", "display-name=o\nbinary-secret=zz\n")),
            ("secret and binary", item_text(2, "abc", "o", {"app": "x"}).replace(
                "secret=abc\n", "secret=abc\nbinary-secret=616263\n")),
        ):
            with self.subTest(name):
                self.write(mine + other)
                self.served = None
                self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)
        self.write(mine + item_text(2, "ok", "o", {"app": "x"}))
        self.verify("a", "", "F", "bmV3")

    def test_store_rejects_a_value_a_rewrite_would_change(self) -> None:
        # The file says backslash-n (reloads as a newline); the daemon serves
        # the newline, which a rewrite would write raw.
        self.write(item_text(1, "bmV3", "F", self.ATTRS) + item_text(2, "a\\nb", "o", {"app": "x"}))
        self.served = {"1": b"bmV3", "2": b"a\nb"}
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)
        # Served as typed it is still unsafe: the daemon may reload the file
        # at any time and then serve the newline.
        self.served = {"1": b"bmV3", "2": b"a\\nb"}
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)

    def test_item_count_must_be_the_expected_one(self) -> None:
        self.write(item_text(1, "bmV3", "F", self.ATTRS) + item_text(2, "ok", "o", {"app": "x"}))
        self.verify("a", "", "F", "bmV3", 2)
        self.assertEqual(self.exit_code("a", "", "F", "bmV3", 1), 6)
        self.assertEqual(self.exit_code("a", "", "F", "bmV3", 3), 6)

    def test_store_rejects_an_item_the_daemon_does_not_serve(self) -> None:
        self.write(item_text(1, "bmV3", "F", self.ATTRS) + item_text(2, "ok", "o", {"app": "x"}))
        self.served = {"1": b"bmV3"}
        self.assertEqual(self.exit_code("a", "", "F", "bmV3"), 6)

    def test_late_write_is_waited_for(self) -> None:
        self.mod.VERIFY_TIMEOUT_S = 5
        self.write("")
        text = item_text(1, "bmV3", "F", self.ATTRS)
        threading.Timer(0.3, self.write, [text]).start()
        self.verify("a", "", "F", "bmV3")

    def test_guard_refuses_when_the_file_cannot_be_read(self) -> None:
        for path in (None, str(self.path)):  # no path; missing file
            with self.subTest(path=path), mock.patch.object(
                self.mod, "daemon_keyring_path", lambda _c, p=path: p
            ):
                with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
                    self.kr._guard_write(None)
                self.assertEqual(cm.exception.code, 5)

    def test_guard_lets_an_encrypted_file_through_to_the_service_check(self) -> None:
        # Its items cannot be read here; the write is confirmed by the Secret Service.
        self.path.write_bytes(self.mod.ENCRYPTED_MAGIC + b"\0")
        self.assertIsNone(self.kr._guard_write(None))


class TestEncryptedVerify(unittest.TestCase):
    """An encrypted keyring is confirmed only through the Secret Service."""

    ATTRS = {"service": "omapass", "account": "a", "enc": "b64"}

    def setUp(self) -> None:
        self.mod = load_helper()
        self.mod.VERIFY_TIMEOUT_S = 0.1
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "k.keyring"
        path.write_bytes(self.mod.ENCRYPTED_MAGIC + bytes(32))
        patcher = mock.patch.object(self.mod, "daemon_keyring_path", lambda _c: str(path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.kr = object.__new__(self.mod.GiKeyring)
        self.served = []
        self.kr._find = lambda account, kind="", secrets=False: self.served

    def code(self, *args):
        try:
            with mock.patch("sys.stderr"):
                self.kr._verify_written(None, "a", *args)
        except SystemExit as e:
            return e.code
        return 0

    def test_store_needs_the_expected_item(self) -> None:
        self.served = [FakeItem(self.ATTRS, "bmV3", "F")]
        self.assertEqual(self.code("", "F", "bmV3"), 0)
        self.assertEqual(self.code("", "F", "b2xk"), 6)  # secret
        self.assertEqual(self.code("", "Other", "bmV3"), 6)  # label
        self.assertEqual(self.code("nostr", "F", "bmV3"), 6)  # attributes
        self.served = [FakeItem({**self.ATTRS, "extra": "1"}, "bmV3", "F")]
        self.assertEqual(self.code("", "F", "bmV3"), 0)  # extras are kept
        self.served = [FakeItem({**self.ATTRS, "kind": "nostr"}, "bmV3", "F")]
        self.assertEqual(self.code("", "F", "bmV3"), 6)  # kind is identity
        self.served = []
        self.assertEqual(self.code("", "F", "bmV3"), 6)
        self.served = [FakeItem(self.ATTRS, "bmV3", "F")] * 2
        self.assertEqual(self.code("", "F", "bmV3"), 6)

    def test_clear_needs_the_item_gone(self) -> None:
        self.assertEqual(self.code(), 0)
        self.served = [FakeItem(self.ATTRS, "bmV3", "F")]
        self.assertEqual(self.code(), 6)


class TestRewriteRisks(unittest.TestCase):
    """The one rule, on raw lines and served bytes, without a daemon."""

    CASES = (
        ("plain", "secret=abc", b"abc", 0),
        ("leading space", "secret= abc", b"abc", 0),
        ("carriage return", "secret=abc\r", b"abc", 0),
        ("empty", "", b"", 0),
        ("binary", "binary-secret=ff41", b"\xffA", 0),
        ("not served", "secret=abc", None, 1),
        ("served differs", "secret=abc", b"abd", 1),
        ("missing line, served", "", b"abc", 1),
        # Lost on reload anyway; a rewrite writes the same bytes.
        ("invalid escape, served raw", "secret=a\\b", b"a\\b", 0),
        ("invalid escape, served empty", "secret=a\\b", b"", 0),
        ("leading spaces, served raw", "secret=  pad  ", b"  pad  ", 0),
        ("leading spaces, served stripped", "secret=  pad  ", b"pad  ", 0),
        # The daemon may reload at any time; then it serves a newline.
        ("literal backslash n, served as typed", "secret=a\\nb", b"a\\nb", 1),
        ("literal backslash n, served as newline", "secret=a\\nb", b"a\nb", 1),
        ("newline served", "secret=ab", b"a\nb", 1),
        ("non-utf8 served, no line", "", b"\xff", 1),
        ("invalid hex", "binary-secret=zz", b"", 1),
        ("odd hex", "binary-secret=abc", b"", 1),
        ("binary differs", "binary-secret=ff", b"a", 1),
        ("both", "secret=abc\nbinary-secret=616263", b"abc", 1),
        ("both, empty secret", "secret=\nbinary-secret=ff", b"", 1),
        ("repeated", "secret=a\nsecret=a", b"a", 1),
    )

    def test_table(self) -> None:
        mod = load_helper()
        for name, lines, served, bad in self.CASES:
            with self.subTest(name):
                text = KEYRING_HEAD + "[1]\ndisplay-name=f\n" + lines + "\n"
                kf = mod.load_keyfile(text.encode())
                got = mod.rewrite_risks(kf, text, {} if served is None else {"1": served})
                self.assertEqual(got, (bad, served is None))


if __name__ == "__main__":
    unittest.main()
