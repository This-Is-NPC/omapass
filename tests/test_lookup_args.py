"""Name lookup in NFC, dash-leading names, exit codes and no secret in argv."""

from __future__ import annotations

import collections
import io
import shutil
import subprocess
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, load_helper
from tests.test_helper_security import FakeBackend, call_type_helper, invoke_main
from tests.test_secret_validation import SETUP

NFC = "café"
NFD = "café"


class TestExitCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def tearDown(self) -> None:
        self.mod.BACKEND = None

    def test_codes_are_distinct_from_argparse_and_documented_ones(self) -> None:
        m = self.mod
        taken = {2, 3, m.EXIT_EXISTS, m.EXIT_UNSAFE_KEYRING, m.EXIT_DAMAGED_KEYRING}
        self.assertEqual(len(taken), 5)
        for code in (m.EXIT_FOCUS_CHANGED, m.EXIT_WTYPE_FAILED):
            self.assertNotIn(code, taken | {0, 1})
        self.assertNotEqual(m.EXIT_FOCUS_CHANGED, m.EXIT_WTYPE_FAILED)

    def test_wtype_failure_maps_to_a_fixed_code(self) -> None:
        # wtype's own status must not leak, even when it equals a helper code.
        for status in (1, 2, 4, 5, 6, 7, 127):
            with self.subTest(status=status):
                self.mod.BACKEND = FakeBackend(secret="abc")
                with (
                    mock.patch.object(self.mod, "wait_for_focus", return_value=True),
                    mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
                    mock.patch.object(self.mod, "session_locked", return_value=False),
                    mock.patch.object(
                        self.mod, "read_focus_for",
                        side_effect=lambda c: {"compositor": c, "id": "0x1"},
                    ),
                    mock.patch.object(
                        self.mod, "exec_abs", return_value=types.SimpleNamespace(returncode=status)
                    ),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as ctx,
                ):
                    self.mod.cmd_type(
                        types.SimpleNamespace(
                            account="a", compositor="hyprland", expect_id="0x1", kind="", folder=None, rest=[]
                        )
                    )
                self.assertEqual(ctx.exception.code, self.mod.EXIT_WTYPE_FAILED)

    def test_focus_changed_has_its_own_code(self) -> None:
        code, _out, err, typed = call_type_helper(self.mod, "a", focus_stable=False)
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []))
        self.assertIn("focus changed", err)

    def test_unknown_compositor_is_an_argument_error_not_focus_changed(self) -> None:
        self.mod.BACKEND = FakeBackend()
        code, _out, err = invoke_main(
            self.mod, ["type", "--account", "a", "--compositor", "bogus", "--expect-id", "1"]
        )
        self.assertEqual(code, 2)
        self.assertNotIn("focus changed", err)
        self.assertEqual(self.mod.BACKEND.get_secret_calls, [])


class TestDashAndArgv(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def tearDown(self) -> None:
        self.mod.BACKEND = None

    def test_dash_leading_account_with_equals_form(self) -> None:
        for argv in (
            ["copy", "--account=-bank"],
            ["get", "--account=-bank"],
            ["clear", "--account=-bank"],
            ["exists", "--account=-bank"],
            ["type", "--account=-bank", "--compositor=hyprland", "--expect-id=1"],
        ):
            with self.subTest(argv=argv):
                self.mod.BACKEND = backend = FakeBackend(items=[{"account": "-bank", "folder": "f"}])
                with (
                    mock.patch.object(self.mod, "clipboard_copy"),
                    mock.patch.object(self.mod, "wait_for_focus", return_value=False),
                    mock.patch.object(self.mod.sys.stdout, "isatty", return_value=False),
                ):
                    code, _out, _err = invoke_main(self.mod, argv)
                self.assertNotEqual(code, 2, argv)
                called = backend.get_secret_calls + backend.clear_calls
                if argv[0] in ("copy", "get", "clear"):
                    self.assertEqual(called, ["-bank"])
                if argv[0] == "exists":
                    self.assertEqual(code, 0)

    def test_dash_leading_account_store_end_to_end_args(self) -> None:
        self.mod.BACKEND = backend = FakeBackend(items=[])
        with mock.patch.object(self.mod.sys, "stdin", io.StringIO("pw\n")):
            code, _out, err = invoke_main(
                self.mod, ["store", "--account=-bank", "--folder=-f", "--replace"]
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(backend.store_calls, [("-bank", "-f", "pw", "")])

    def test_space_form_still_works(self) -> None:
        self.mod.BACKEND = backend = FakeBackend()
        with mock.patch.object(self.mod, "clipboard_copy"):
            code, _out, err = invoke_main(self.mod, ["copy", "--account", "acct"])
        self.assertEqual((code, backend.get_secret_calls), (0, ["acct"]))

    def test_helper_takes_no_secret_in_argv(self) -> None:
        # The secret travels on stdin only: no option or positional may carry it.
        for argv in (
            ["store", "--account", "a", "--folder", "f", "--secret", "hunter2"],
            ["store", "--account", "a", "--folder", "f", "--password=hunter2"],
            ["store", "--account", "a", "--folder", "f", "hunter2"],
            ["add", "--account", "a", "--folder", "f", "hunter2"],
            ["copy-text", "hunter2"],
            ["generate-nostr", "--account", "a", "hunter2"],
        ):
            with self.subTest(argv=argv):
                self.mod.BACKEND = backend = FakeBackend(items=[])
                with (
                    mock.patch.object(self.mod, "clipboard_copy") as copied,
                    mock.patch.object(self.mod.sys, "stdin", io.StringIO("stdin-secret\n")),
                ):
                    code, _out, _err = invoke_main(self.mod, argv)
                self.assertEqual(code, 2)
                self.assertEqual(backend.store_calls, [])
                copied.assert_not_called()

    def test_wrapper_runs_the_helper_isolated(self) -> None:
        wrapper = (HELPER_PATH.parent / "omapass").read_text()
        self.assertIn("/usr/bin/python3 -I ", wrapper)


@sandbox_only
class TestNfcLookup(unittest.TestCase):
    def run_script(self, body: str) -> str:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        script = SETUP + body
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", script],
            text=True, capture_output=True, timeout=90,
            env={
                "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
                "HELPER": str(HELPER_PATH), "NFC": NFC, "NFD": NFD,
            },
        )
        return proc.stdout + proc.stderr

    def test_decomposed_spelling_finds_the_nfc_item(self) -> None:
        out = self.run_script(r"""
printf nfc-pw | h store --account "$NFC" --folder f
echo "get=$(h get --account "$NFD" 2>&1)"
h exists --account "$NFD"; echo "exists=$?"
printf x | h store --account "$NFD" --folder f; echo "add=$?"
h clear --account "$NFD"; echo "clear=$?"
h exists --account "$NFC"; echo "left=$?"
stop_keyring
""")
        self.assertIn("get=nfc-pw", out)
        self.assertIn("exists=0", out)
        self.assertIn("add=4", out)
        self.assertIn("clear=0", out)
        self.assertIn("left=1", out)

    def test_legacy_decomposed_item_stays_reachable_and_exact_wins(self) -> None:
        out = self.run_script(r"""
printf legacy-nfd | secret-tool store --label=f service omapass account "$NFD"
echo "legacy=$(h get --account "$NFD" 2>&1)"
h exists --account "$NFD"; echo "legacy_exists=$?"
h exists --account "$NFC"; echo "nfc_exists=$?"
h clear --account "$NFD"; echo "legacy_clear=$?"
h exists --account "$NFD"; echo "legacy_left=$?"
stop_keyring
""")
        self.assertIn("legacy=legacy-nfd", out)
        self.assertIn("legacy_exists=0", out)
        self.assertIn("legacy_clear=0", out)
        self.assertIn("legacy_left=1", out)

    def test_the_nfc_spelling_reaches_a_legacy_nfd_item_as_store_does(self) -> None:
        """A8: get and rm said "no such item" while store said "already exists"."""
        out = self.run_script(r"""
printf legacy-nfd | secret-tool store --label=f service omapass account "$NFD"
echo "get=$(h get --account "$NFC" 2>&1)"
h exists --account "$NFC"; echo "exists=$?"
printf x | h store --account "$NFC" --folder f >/dev/null 2>&1; echo "store=$?"
h rm -- "$NFC"; echo "rm=$?"
h exists --account "$NFD"; echo "left=$?"
h get --account "$NFC" 2>&1; echo "get_after=$?"
stop_keyring
""")
        for expected in ("get=legacy-nfd", "exists=0", "store=4", "rm=0", "left=1", "get_after=1"):
            self.assertIn(expected, out)

    def test_exact_spelling_never_shadowed_by_a_different_item(self) -> None:
        # Both spellings exist (the NFC one made by another app); each name
        # reaches its own item, and clearing one leaves the other.
        out = self.run_script(r"""
printf legacy-nfd | secret-tool store --label=f service omapass account "$NFD"
printf other-nfc | secret-tool store --label=f service omapass account "$NFC"
echo "nfd=$(h get --account "$NFD" 2>&1)"
echo "nfc=$(h get --account "$NFC" 2>&1)"
h clear --account "$NFD"; echo "clear=$?"
echo "nfc_after=$(h get --account "$NFC" 2>&1)"
stop_keyring
""")
        self.assertIn("nfd=legacy-nfd", out)
        self.assertIn("nfc=other-nfc", out)
        self.assertIn("clear=0", out)
        self.assertIn("nfc_after=other-nfc", out)

    def test_dash_leading_name_round_trip(self) -> None:
        out = self.run_script(r"""
printf dash-pw | h store --account=-bank --folder=-f; echo "store=$?"
echo "get=$(h get --account=-bank 2>&1)"
h exists --account=-bank; echo "exists=$?"
h clear --account=-bank; echo "clear=$?"
stop_keyring
""")
        for expected in ("store=0", "get=dash-pw", "exists=0", "clear=0"):
            self.assertIn(expected, out)


if __name__ == "__main__":
    unittest.main()


@sandbox_only
class TestNfdReplace(unittest.TestCase):
    """An old NFD item is the same item as its NFC name: --replace updates it."""

    def run_script(self, body: str) -> str:
        return TestNfcLookup.run_script(self, body)

    def test_replace_updates_a_legacy_nfd_item_with_either_spelling(self) -> None:
        out = self.run_script(r"""
for spelling in "$NFD" "$NFC"; do
  if [ "$spelling" = "$NFC" ]; then  # an already base64-encoded NFD item
    printf bGVnYWN5 | secret-tool store --label=f service omapass account "$NFD" enc b64
  else
    printf legacy | secret-tool store --label=f service omapass account "$NFD"
  fi
  printf new | h store --account "$spelling" --folder g; echo "plain=$?"
  printf new | h store --account "$spelling" --folder g --replace; echo "replace=$?"
  echo "get=$(h get --account "$NFC" 2>&1)"
  h list --json | python3 -I -c 'import json,sys; r=json.load(sys.stdin); print("rows=%d folder=%s nfc=%s" % (len(r), r[0]["folder"], r[0]["account"] == sys.argv[1]))' "$NFC"
  h clear --account "$NFC" >/dev/null 2>&1
done
stop_keyring
""")
        self.assertEqual(out.count("plain=4"), 2, out)
        self.assertEqual(out.count("replace=0"), 2, out)
        self.assertEqual(out.count("get=new"), 2, out)
        self.assertEqual(out.count("rows=1 folder=g nfc=True"), 2, out)

    def test_distinct_items_are_never_merged(self) -> None:
        out = self.run_script(r"""
printf one | h store --account "$NFC" --folder f; echo "a=$?"
printf two | h store --account "caf" --folder f; echo "b=$?"
printf x | h store --account "$NFD" --folder f --replace; echo "replace=$?"
echo "caf=$(h get --account caf 2>&1)"
stop_keyring
""")
        self.assertIn("replace=0", out)
        self.assertIn("caf=two", out)
