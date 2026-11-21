"""Names: NFC on write, control and invisible characters refused, flagged on list."""

from __future__ import annotations

import io
import json
import shutil
import contextlib
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from contextlib import redirect_stderr

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, load_helper
from tests.test_secret_validation import SETUP

CYR_A = "а"
GREEK_O = "ο"


class TestNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def validate(self, account="acct", folder="f", kind=""):
        with redirect_stderr(io.StringIO()):
            return self.mod.validate_entry(account, folder, "pw", kind)

    def assertRejected(self, **kw):
        with self.assertRaises(SystemExit) as ctx:
            self.validate(**kw)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_nfc_normalized(self) -> None:
        self.assertEqual(self.validate(account="café")[0], "café")
        self.assertEqual(self.validate(folder="café")[1], "café")

    def test_spaces_and_look_alike_letters_are_accepted(self) -> None:
        # Only control and invisible characters are refused; a Cyrillic letter
        # inside a Latin word and an edge space are ordinary visible text.
        for ok in (" a", "a ", "a\u2003b", f"p{CYR_A}ypal", f"g{GREEK_O}ogle", "\u0430bc"):
            for field in ("account", "folder", "kind"):
                with self.subTest(ok=ascii(ok), field=field):
                    got = self.validate(**{field: ok})
                    self.assertEqual(got[{"account": 0, "folder": 1, "kind": 3}[field]], ok)

    def test_inner_ascii_space_allowed(self) -> None:
        self.assertEqual(self.validate(account="my bank")[0], "my bank")

    def test_legitimate_names_allowed(self) -> None:
        for ok in ("café", "密码", "\U0001f600", "bank 密码",
                   "Москва", "αβγ",
                   "Яндекс Mail", "a1-b_c.d@e", ""):
            with self.subTest(ok=ascii(ok)):
                self.assertEqual(self.validate(account=ok)[0], ok)

    def test_panel_asks_to_replace_only_on_exit_exists(self) -> None:
        root = Path(__file__).resolve().parent.parent
        panel = (root / "qml" / "AddLoginForm.qml").read_text()
        self.assertIn("readonly property int exitExists: 4", (root / "qml" / "Vault.qml").read_text())
        for fn in ("function saveAdd(", "function doGenerateNostr("):
            body = panel[panel.index(fn):]
            body = body[: body.index("\n  function ", 10)]
            calls = body.count("askReplace(")
            self.assertEqual(calls, 1, fn)
            guard = body[: body.index("askReplace(")]
            self.assertIn("code === panel.vault.exitExists", guard[-300:], fn)
            self.assertIn("addError = ", body, fn)

    def test_invisible_non_format_characters_rejected(self) -> None:
        # Default-ignorable or blank code points that are not category Cf.
        for ch in ("\u3164", "\u115f", "\u1160", "\u034f", "\ufe00", "\ufe0f",
                   "\u2800", "\uffa0", "\u17b4", "\u180b", "\u2065",
                   "\U000e0100", "\U000e01ef"):
            for bad in (f"pay{ch}pal", f"paypal{ch}", f"{ch}paypal", ch):
                with self.subTest(ch=ascii(ch), bad=ascii(bad)):
                    self.assertEqual(self.mod.name_problem(bad), "invisible")
                    self.assertRejected(account=bad)
                    self.assertRejected(folder=bad)
                    self.assertRejected(kind=bad)

    def test_control_characters_flagged_and_listed_escaped(self) -> None:
        for bad in ("bank\x1b]52;c;ZXZpbA==\x07", "bank\nPayPal", "a\x9bb", "a\u2028b", "a\x7fb"):
            with self.subTest(bad=ascii(bad)):
                self.assertEqual(self.mod.name_problem(bad), "control")
                shown = self.mod.printable(bad)
                self.assertTrue(shown.isascii() and shown.isprintable(), shown)
        self.assertEqual(self.mod.printable("café 密码"), "café 密码")
        self.assertEqual(self.mod.printable("a\u3164b"), "a\\u3164b")

    def test_plain_list_never_prints_control_characters(self) -> None:
        rows = [{"account": "bank\x1b]0;x\x07\n", "folder": "f\x9b\u202e", "kind": "", "warn": "control"}]
        backend = type("B", (), {"list_items": lambda self: rows})()
        self.mod.BACKEND = backend
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.mod.cmd_list(types.SimpleNamespace(json=False))
        text = out.getvalue()
        self.assertTrue(text.endswith("\n") and text.count("\n") == 1, ascii(text))
        self.assertTrue(text.rstrip("\n").replace("\t", "").isprintable(), ascii(text))
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x9b", text)
        self.assertNotIn("\u202e", text)

    def test_name_problem_codes(self) -> None:
        self.assertIsNone(self.mod.name_problem("café"))
        self.assertIsNone(self.mod.name_problem("a "))
        self.assertIsNone(self.mod.name_problem(f"p{CYR_A}ypal"))
        self.assertEqual(self.mod.name_problem("a\u200bb"), "invisible")
        self.assertEqual(self.mod.name_problem("a\nb"), "control")


@sandbox_only
class TestListWarn(unittest.TestCase):
    def test_list_json_flags_foreign_items(self) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        script = SETUP + r"""
for a in "$ZW" "$SP" "$LOOK" "$FILL" "$CTL" fine; do
  printf x | secret-tool store --label=f service omapass account "$a"
done
h list --json > "$HOME/out"
"""
        env = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": str(home),
            "HELPER": str(HELPER_PATH),
            "ZW": "a\u200bb",
            "SP": "trail ",
            "LOOK": f"p{CYR_A}ypal",
            "FILL": "pay\u3164x",
            "CTL": "bank\x1b]0;x\x07",
        }
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", script],
            text=True, env=env, capture_output=True, timeout=90,
        )
        rows = {r["account"]: r["warn"] for r in json.loads((home / "out").read_text())}
        self.assertEqual(
            rows,
            {
                "a\u200bb": "invisible",
                "pay\u3164x": "invisible",
                "bank\x1b]0;x\x07": "control",
                "trail ": "",
                f"p{CYR_A}ypal": "",
                "fine": "",
            },
            proc.stderr,
        )


@sandbox_only
class TestPaddedNames(unittest.TestCase):
    """Legacy items with edge spaces are served and removed exactly."""

    def test_get_and_clear_match_the_exact_account(self) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        script = SETUP + r"""
printf 'plain-pw' | secret-tool store --label=f service omapass account "shop"
printf 'padded-pw' | secret-tool store --label=f service omapass account "shop "
h get --account="shop " > "$HOME/get_padded"
h get --account=shop > "$HOME/get_plain"
h clear --account="shop "; echo $? > "$HOME/clear.rc"
h list --json > "$HOME/left"
"""
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home), "HELPER": str(HELPER_PATH)}
        proc = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", script],
            text=True, env=env, capture_output=True, timeout=90,
        )
        self.assertEqual((home / "get_padded").read_text().strip(), "padded-pw", proc.stderr)
        self.assertEqual((home / "get_plain").read_text().strip(), "plain-pw", proc.stderr)
        self.assertEqual((home / "clear.rc").read_text().strip(), "0", proc.stderr)
        left = [r["account"] for r in json.loads((home / "left").read_text())]
        self.assertEqual(left, ["shop"], proc.stderr)


if __name__ == "__main__":
    unittest.main()
