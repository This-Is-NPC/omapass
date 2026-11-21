"""Secret/attribute validation: unsafe values must never reach the keyring."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only
from tests.helper_loader import HELPER_PATH, load_helper
from tests.test_helper_security import FakeBackend

HEALTH = "/opt/sandbox/keyring-health.py"

# Private session and HOME so a broken keyring never touches the shared
# sandbox one.
PREPARE = STOP_OWN_KEYRING + r"""
set -u
mkdir -p "$HOME/.local/share/keyrings"
printf '[keyring]\ndisplay-name=Default keyring\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n' \
  > "$HOME/.local/share/keyrings/Default_keyring.keyring"
printf 'Default_keyring' > "$HOME/.local/share/keyrings/default"
start() { gnome-keyring-daemon --start --components=secrets >/dev/null; }
restart() {
  stop_keyring
  start
}
h() { python3 -I "$HELPER" "$@"; }
"""
SETUP = PREPARE + "start\n"

# Keyring file written by hand before the daemon loads it; $BODY holds the items.
FILE_RUN = PREPARE + r"""
printf '%b' "$BODY" >> "$HOME/.local/share/keyrings/Default_keyring.keyring"
start
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""


def enc(n: int | str = 1) -> str:
    return f"\\n[{n}:attribute0]\\nname=enc\\ntype=string\\nvalue=b64\\n"


def item(n: int | str, secret: str | None) -> str:
    body = f"\\n[{n}]\\ndisplay-name=f\\ncreated=0\\nmodified=0\\n"
    return body + (f"secret={secret}\\n" if secret is not None else "")


# Store stdin, restart the daemon, read it back, store a second item (a
# plaintext keyring rewrites the whole file), restart again, read both, then
# run the health check. Every rc and output lands in $HOME.
ROUNDTRIP_RUN = SETUP + r"""
h store --account x --folder y < "$HOME/in" >/dev/null 2>"$HOME/store.err"; echo $? > "$HOME/store.rc"
restart
h get --account x > "$HOME/out1" 2>/dev/null; echo $? > "$HOME/get1.rc"
printf 'second' | h store --account z --folder y >/dev/null 2>&1
restart
h get --account x > "$HOME/out2" 2>/dev/null; echo $? > "$HOME/get2.rc"
h get --account z > "$HOME/outz" 2>/dev/null
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

# An item written by the pre-encoding helper: raw secret, no enc attribute.
LEGACY_RUN = SETUP + r"""
python3 -I - <<'PY'
import os
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None)
col = Secret.Collection.for_alias_sync(svc, "default", Secret.CollectionFlags.NONE, None)
svc.unlock_sync([col], None)
for acct, text in (("plain", "legacy-pw"), ("nl", "legacy-nl\n")):
    Secret.Item.create_sync(col, None, {"service": "omapass", "account": acct}, "f",
        Secret.Value.new(text, len(text), "text/plain"), Secret.ItemCreateFlags.NONE, None)
PY
h get --account plain > "$HOME/plain1"
h get --account nl > "$HOME/nl1"
restart
h get --account plain > "$HOME/plain2"
printf 'new pw\\' | h store --account plain --folder f2 --replace >/dev/null 2>"$HOME/replace.err"; echo $? > "$HOME/replace.rc"
restart
h get --account plain > "$HOME/plain3"
h list --json > "$HOME/list.json"
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

# What the pre-encoding helper wrote for secrets with literal escapes.
UNFAITHFUL_RUN = SETUP + r"""
python3 -I - <<'PY'
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
svc = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None)
col = Secret.Collection.for_alias_sync(svc, "default", Secret.CollectionFlags.NONE, None)
svc.unlock_sync([col], None)
text = "a" + chr(92) + "nb"
Secret.Item.create_sync(col, None, {"service": "omapass", "account": "x"}, "f",
    Secret.Value.new(text, len(text), "text/plain"), Secret.ItemCreateFlags.NONE, None)
PY
restart
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo $? > "$HOME/health.rc"
stop_keyring
"""

ROUNDTRIP_CASES = {
    "plain": "good-secret",
    "literal_backslash_n": "a\\nb",
    "literal_double_backslash": "a\\\\b",
    "literal_backslash_t": "a\\tb",
    "literal_backslash_s": "a\\sb",
    "leading_space": " lead",
    "trailing_space": "trail ",
    "trailing_backslash": "trail\\",
    "unicode": "pässwörd-密码",
}


@sandbox_only
class TestKeyringSurvivesStore(unittest.TestCase):
    def _run(self, script: str, payload: str = "") -> tuple[Path, subprocess.CompletedProcess]:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / "in").write_text(payload)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "HELPER": str(HELPER_PATH),
            "HEALTH": HEALTH,
        }
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", script],
            text=True,
            env=env,
            capture_output=True,
            timeout=90,
        )
        return home, proc

    def test_secret_round_trips_after_restart(self) -> None:
        for name, value in ROUNDTRIP_CASES.items():
            with self.subTest(case=name):
                home, _ = self._run(ROUNDTRIP_RUN, value + "\n")
                self.assertEqual((home / "store.rc").read_text().strip(), "0",
                                 (home / "store.err").read_text())
                self.assertEqual((home / "out1").read_text(), value)
                self.assertEqual((home / "out2").read_text(), value)
                self.assertEqual((home / "outz").read_text(), "second")
                self.assertEqual((home / "health.rc").read_text().strip(), "0",
                                 (home / "health.out").read_text())

    def test_health_flags_secret_altered_by_the_daemon(self) -> None:
        home, _ = self._run(UNFAITHFUL_RUN)
        self.assertEqual((home / "health.rc").read_text().strip(), "1")
        self.assertIn("FAIL item", (home / "health.out").read_text())

    def _health_of(self, body: str) -> tuple[str, str]:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "HELPER": str(HELPER_PATH),
               "HEALTH": HEALTH, "BODY": body}
        subprocess.run(["dbus-run-session", "--", "bash", "-c", FILE_RUN],
                       env=env, capture_output=True, timeout=90)
        return (home / "health.rc").read_text().strip(), (home / "health.out").read_text()

    def test_health_passes_a_clean_file(self) -> None:
        rc, out = self._health_of(item(1, "YQ==") + enc())
        self.assertEqual(rc, "0", out)

    def test_health_flags_invalid_base64(self) -> None:
        for name, secret in (("not_base64", "not*base64"), ("bad_utf8", "/w==")):
            with self.subTest(case=name):
                rc, out = self._health_of(item(1, secret) + enc())
                self.assertEqual(rc, "1", out)
                self.assertIn("not base64 of UTF-8", out)

    def test_health_checks_every_id_form_the_daemon_serves(self) -> None:
        # Observed: the daemon serves every group except [keyring] and groups
        # with ":", under the group name with "_xx" escapes. isdigit() would
        # miscount [0x1] and [+3], and accept the Unicode digit [\u0663].
        groups = ("0x1", "+3", "-4", "\u0663", "abc")
        rc, out = self._health_of("".join(item(g, "YQ==") + enc(g) for g in groups))
        self.assertEqual(rc, "0", out)
        self.assertIn(f"parses, {len(groups)} items", out)
        self.assertIn(f"OK   items: {len(groups)} read back", out)

    def test_health_checks_the_secret_of_a_hex_id_item(self) -> None:
        # Literal backslash-n in the file: the daemon serves a newline.
        rc, out = self._health_of(item("0x1", "a\\\\nb"))
        self.assertEqual(rc, "1", out)
        self.assertIn("FAIL items: 1 item(s) are not safe to rewrite", out)
        self.assertNotIn("file has", out)  # not reported as a count mismatch

    def test_health_does_not_count_groups_the_daemon_ignores(self) -> None:
        rc, out = self._health_of(item(1, "YQ==") + enc() + "\\n[x:y]\\nk=v\\n[2:acl0]\\nk=v\\n")
        self.assertEqual(rc, "0", out)
        self.assertIn("parses, 1 items", out)
        self.assertIn("OK   items: 1 read back", out)

    # No test for the "file has N items, daemon serves M" branch: with the
    # daemon's real rule above, no file makes the two disagree (it also
    # reloads the file when it changes), so the check stays as a guard only.

    def test_multiline_secret_is_rejected_and_keyring_stays_healthy(self) -> None:
        home, _ = self._run(ROUNDTRIP_RUN, "a\nb\n")
        self.assertNotEqual((home / "store.rc").read_text().strip(), "0")
        self.assertEqual((home / "health.rc").read_text().strip(), "0",
                         (home / "health.out").read_text())

    def test_legacy_items_stay_readable_and_get_upgraded(self) -> None:
        home, _ = self._run(LEGACY_RUN)
        self.assertEqual((home / "plain1").read_text(), "legacy-pw")
        self.assertEqual((home / "nl1").read_text(), "legacy-nl")  # trailing newline dropped
        self.assertEqual((home / "plain2").read_text(), "legacy-pw")
        self.assertEqual((home / "replace.rc").read_text().strip(), "0",
                         (home / "replace.err").read_text())
        self.assertEqual((home / "plain3").read_text(), "new pw\\")
        # Exactly one item with the replaced identity: the legacy copy is gone.
        self.assertEqual(
            json.loads((home / "list.json").read_text()),
            [{"account": "nl", "folder": "f", "kind": "", "warn": ""},
             {"account": "plain", "folder": "f2", "kind": "", "warn": ""}],
        )
        self.assertEqual((home / "health.rc").read_text().strip(), "0",
                         (home / "health.out").read_text())


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def setUp(self) -> None:
        self.backend = FakeBackend()
        self.mod.BACKEND = self.backend
        self.addCleanup(setattr, self.mod, "BACKEND", None)

    def _store(self, stdin: str, *argv: str) -> int:
        args = self.mod.build_parser().parse_args(
            ["store", "--account", "a", "--folder", "f", *argv]
        )
        with (
            mock.patch("sys.stdin", io.StringIO(stdin)),
            redirect_stderr(io.StringIO()),
        ):
            try:
                self.mod.cmd_store(args)
            except SystemExit as exc:
                return int(exc.code or 0)
        return 0

    def test_one_trailing_newline_is_stripped(self) -> None:
        self.assertEqual(self._store("pw\n"), 0)
        self.assertEqual(self.backend.store_calls[0][2], "pw")

    def test_only_one_newline_is_stripped(self) -> None:
        self.assertNotEqual(self._store("pw\n\n"), 0)
        self.assertEqual(self.backend.store_calls, [])

    def test_unsafe_secrets_rejected(self) -> None:
        for bad in ("a\nb", "a\rb", "a\x00b", "a\x1bb", "a\x7fb", "a\x85b", "", "\n", "x" * 5000):
            with self.subTest(bad=bad[:8]):
                self.assertNotEqual(self._store(bad), 0)
        self.assertEqual(self.backend.store_calls, [])

    def test_unsafe_account_folder_kind_rejected(self) -> None:
        for flag, bad in (("--account", "a\nb"), ("--folder", "f\x00"), ("--kind", "k\rk")):
            with self.subTest(flag=flag):
                args = self.mod.build_parser().parse_args(
                    ["store", "--account", "a", "--folder", "f", flag, bad]
                )
                with mock.patch("sys.stdin", io.StringIO("pw")), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        self.mod.cmd_store(args)
                self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(self.backend.store_calls, [])

    def test_backslash_and_edge_spaces_allowed_in_secret(self) -> None:
        for ok in ("a\\nb", "a\\\\b", "trail\\", " lead", "trail "):
            with self.subTest(ok=ok):
                self.assertEqual(self._store(ok + "\n"), 0)
                self.assertEqual(self.backend.store_calls[-1][2], ok)

    def test_bidi_and_zero_width_rejected_in_attributes(self) -> None:
        bad = ("\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\ufeff",
               "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
               "\u2066", "\u2067", "\u2068", "\u2069",
               # N14: format characters the old list missed
               "\u061c", "\u00ad", "\u206a", "\u206f", "\ufff9", "\ufffa", "\ufffb",
               "\U000e0001", "\U000e0020", "\U000e007f", "\udc80")
        for flag in ("--account", "--folder", "--kind"):
            for ch in bad:
                with self.subTest(flag=flag, ch=hex(ord(ch))):
                    args = self.mod.build_parser().parse_args(
                        ["store", "--account", "a", "--folder", "f", flag, "x" + ch + "y"]
                    )
                    with mock.patch("sys.stdin", io.StringIO("pw")), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            self.mod.cmd_store(args)
        self.assertEqual(self.backend.store_calls, [])

    def test_visible_unicode_allowed_in_attributes(self) -> None:
        for ok in ("caf\u00e9", "\u5bc6\u7801", "\U0001f600", "\ue000"):
            with self.subTest(ok=ascii(ok)):
                args = self.mod.build_parser().parse_args(
                    ["store", "--account", ok, "--folder", "f", "--kind", ok]
                )
                with mock.patch("sys.stdin", io.StringIO("pw")):
                    self.mod.cmd_store(args)
                self.assertEqual(self.backend.store_calls[-1][0], ok)

    def test_unicode_secret_allowed(self) -> None:
        self.assertEqual(self._store("pässwörd-密码\n"), 0)
        self.assertEqual(self.backend.store_calls[0][2], "pässwörd-密码")


if __name__ == "__main__":
    unittest.main()
