"""--item-stdin: the panel names its item on stdin, so names stay out of argv (A7)."""

from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from tests.helper_loader import load_helper
from tests.test_helper_security import FakeBackend, invoke_main
from tests.test_type_safety import reply


class ItemStdinCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def setUp(self) -> None:
        self.backend = FakeBackend(secret="dummy")
        self.mod.BACKEND = self.backend
        self.addCleanup(setattr, self.mod, "BACKEND", None)

    def run_cmd(self, argv, stdin, **patches):
        copied = []
        with (
            mock.patch("sys.stdin", io.StringIO(stdin)),
            mock.patch.object(self.mod, "clipboard_copy", side_effect=copied.append),
        ):
            code, out, err = invoke_main(self.mod, argv)
        return code, err, copied


class TestItemFromStdin(ItemStdinCase):
    def test_copy_acts_on_the_item_named_on_stdin(self) -> None:
        item = json.dumps({"account": "me@bank.example", "folder": "Home", "kind": "nostr"})
        code, err, copied = self.run_cmd(["copy", "--item-stdin"], item)
        self.assertEqual((code, copied), (0, ["dummy"]), err)
        self.assertEqual(self.backend.get_secret_calls, ["me@bank.example"])
        self.assertEqual(self.backend.folders, ["Home"])

    def test_clear_acts_on_the_item_named_on_stdin(self) -> None:
        code, err, _ = self.run_cmd(["clear", "--item-stdin"], json.dumps({"account": "-dash ", "folder": ""}))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.backend.clear_calls, self.backend.folders), (["-dash "], [""]))

    def test_type_takes_the_window_from_stdin_too(self) -> None:
        item = json.dumps({"account": "a", "folder": "F", "compositor": "hyprland", "expect_id": "0x1"})
        typed = []

        def exec_abs(path, args, input=None, **kw):
            if path == self.mod.WTYPE:
                typed.append(input)
                return reply()
            if args[:1] == ["activewindow"]:
                return reply('{"address":"0x1"}')
            if args[:1] == ["monitors"]:
                return reply('[{"solitaryBlockedBy": []}]')
            return reply('{"DP-1":{"levels":{}}}')

        with (
            mock.patch("sys.stdin", io.StringIO(item)),
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs),
        ):
            code, _o, err = invoke_main(self.mod, ["type", "--item-stdin"])
        self.assertEqual((code, "".join(typed)), (0, "dummy"), err)
        self.assertEqual(self.backend.folders, ["F"])

    def test_the_argv_form_still_works(self) -> None:
        code, err, copied = self.run_cmd(["copy", "--account=x", "--folder=Y"], "")
        self.assertEqual((code, copied, self.backend.folders), (0, ["dummy"], ["Y"]), err)


class TestBadItems(ItemStdinCase):
    def test_every_malformed_item_is_refused_before_the_keyring(self) -> None:
        bad = {
            "empty": "",
            "not json": "account=x",
            "list": '["x"]',
            "no account": '{"folder": "F"}',
            "empty account": '{"account": ""}',
            "non-string": '{"account": "x", "folder": 3}',
            "unknown field": '{"account": "x", "replace": "1"}',
            "bad compositor": '{"account": "x", "compositor": "sway"}',
        }
        for name, stdin in bad.items():
            with self.subTest(name):
                code, err, copied = self.run_cmd(["copy", "--item-stdin"], stdin)
                self.assertEqual((code, copied, self.backend.get_secret_calls), (1, [], []), err)
                self.assertIn("--item-stdin", err)

    def test_an_account_on_the_command_line_as_well_is_refused(self) -> None:
        for argv in (["copy", "--item-stdin", "--account=y"], ["copy", "--item-stdin", "--", "y"]):
            with self.subTest(argv):
                code, err, copied = self.run_cmd(argv, '{"account": "x"}')
                self.assertEqual((code, copied, self.backend.get_secret_calls), (1, [], []), err)

    def test_every_per_item_flag_next_to_it_is_refused(self) -> None:
        """R1: the README says all of them are refused, not only --account."""
        flags = ["--account=y", "--folder=X", "--kind=nostr", "--compositor=hyprland", "--expect-id=0x2"]
        for flag in flags:
            for cmd in ("copy", "clear", "type"):
                if cmd != "type" and flag.startswith(("--compositor", "--expect-id")):
                    continue
                with self.subTest(cmd=cmd, flag=flag):
                    code, err, copied = self.run_cmd([cmd, "--item-stdin", flag], '{"account": "x"}')
                    self.assertEqual((code, copied, self.backend.get_secret_calls), (1, [], []), err)
                    self.assertEqual(self.backend.clear_calls, [])
                    self.assertIn("--item-stdin", err)

    def test_the_command_line_path_refuses_them_too(self) -> None:
        """R1 from a shell: main() gets argv=None and reads sys.argv itself."""
        for flag in ("--account=y", "--folder=X", "--kind=nostr"):
            with self.subTest(flag=flag), mock.patch("sys.argv", ["omapass-keyring", "copy", "--item-stdin", flag]):
                code, err, copied = self.run_cmd(None, '{"account": "x"}')
                self.assertEqual((code, copied, self.backend.get_secret_calls), (1, [], []), err)
                self.assertIn("--item-stdin", err)


if __name__ == "__main__":
    unittest.main()
