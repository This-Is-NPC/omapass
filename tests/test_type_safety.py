"""type and copy: lock state fails closed, stable Hyprland ids, no control characters."""

from __future__ import annotations

import collections
import json
import subprocess
import types
import unittest
from unittest import mock

from tests.helper_loader import load_helper
from tests.test_helper_security import FakeBackend, invoke_main

TYPE_ARGV = ["type", "--account", "a", "--compositor", "hyprland", "--expect-id", "0x1"]


def reply(stdout="", code=0):
    return types.SimpleNamespace(returncode=code, stdout=stdout, stderr="")


class HyprlandCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def run_type(self, secret, monitors, *, focus='{"address":"0x1"}', layers='{"DP-1":{"levels":{}}}',
                 argv=TYPE_ARGV):
        """cmd_type against a mocked hyprctl; returns (code, err, typed)."""
        typed = []

        def exec_abs(path, args, input=None, capture=False, **kw):
            if path == self.mod.WTYPE:
                typed.append(input)
                return reply()
            if args[:1] == ["activewindow"]:
                return reply(focus)
            if args[:1] == ["layers"]:
                return reply(layers)
            if args[:1] == ["monitors"]:
                if isinstance(monitors, BaseException):
                    raise monitors
                return monitors
            raise AssertionError(args)

        self.mod.BACKEND = FakeBackend(secret=secret)
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        with (
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs),
        ):
            code, _out, err = invoke_main(self.mod, argv)
        return code, err, typed


class TestLockFailsClosed(HyprlandCase):
    def test_a_monitors_query_that_cannot_answer_stops_typing(self) -> None:
        cases = {
            "exit 1": reply("", 1),
            "empty": reply(""),
            "hung": subprocess.TimeoutExpired("hyprctl", 2),
            "not a list": reply("{}"),
            "odd entries": reply("[1, 2]"),
            "no monitors": reply("[]"),
        }
        for name, monitors in cases.items():
            with self.subTest(name):
                code, err, typed = self.run_type("dummy", monitors)
                self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
                self.assertIn("session lock state unknown", err)
                self.assertEqual(typed, [])

    def test_a_readable_answer_without_a_lock_still_types(self) -> None:
        monitors = reply(json.dumps([{"name": "m", "solitaryBlockedBy": ["WINDOWED"]}]))
        code, err, typed = self.run_type("dummy", monitors)
        self.assertEqual((code, "".join(typed)), (0, "dummy"), err)

    def test_a_lock_stops_typing(self) -> None:
        monitors = reply(json.dumps([{"solitaryBlockedBy": ["LOCK"]}]))
        code, err, typed = self.run_type("dummy", monitors)
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []))
        self.assertIn("session locked", err)


class TestStableIds(HyprlandCase):
    def test_focus_uses_the_stable_id_when_present(self) -> None:
        out = json.dumps({"address": "0xA", "stableId": "18000011"})
        with mock.patch.object(self.mod, "query_compositor", return_value=out):
            self.assertEqual(self.mod.read_hyprland_focus()["id"], "18000011")

    def test_focus_falls_back_to_the_address(self) -> None:
        with mock.patch.object(self.mod, "query_compositor", return_value='{"address": "0xA"}'):
            self.assertEqual(self.mod.read_hyprland_focus()["id"], "0xA")

    def test_a_reused_address_with_a_new_stable_id_is_a_different_window(self) -> None:
        monitors = reply(json.dumps([{"solitaryBlockedBy": []}]))
        focus = '{"address": "0x1", "stableId": "222"}'
        code, err, typed = self.run_type("dummy", monitors, focus=focus)
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)
        argv = TYPE_ARGV[:-1] + ["222"]
        code, err, typed = self.run_type("dummy", monitors, focus=focus, argv=argv)
        self.assertEqual((code, "".join(typed)), (0, "dummy"), err)

    def layers(self, *entries):
        return json.dumps({"DP-1": {"levels": {"2": list(entries)}}})

    def read(self, out):
        with mock.patch.object(self.mod, "query_compositor", return_value=out):
            return self.mod.read_layers("hyprland")

    def test_layers_are_keyed_by_stable_id_when_present(self) -> None:
        a = self.read(self.layers({"address": "0x5", "stableId": "1", "namespace": "n", "pid": 1}))
        b = self.read(self.layers({"address": "0x5", "stableId": "2", "namespace": "n", "pid": 1}))
        self.assertTrue(b - a, "a new stableId at a reused address must count as new")

    def test_layers_without_a_stable_id_use_address_namespace_and_pid(self) -> None:
        base = {"address": "0x5", "namespace": "bar", "pid": 1}
        a = self.read(self.layers(base))
        self.assertFalse(self.read(self.layers(dict(base))) - a)
        for change in ({"namespace": "launcher"}, {"pid": 2}):
            with self.subTest(change):
                self.assertTrue(self.read(self.layers({**base, **change})) - a)

    def test_a_layer_that_opens_at_a_freed_address_is_caught_while_typing(self) -> None:
        seen = collections.deque(
            [
                self.layers({"address": "0x5", "stableId": "1"}),
                self.layers({"address": "0x5", "stableId": "2"}),
            ]
        )
        typed = []

        def exec_abs(path, args, input=None, **kw):
            if path == self.mod.WTYPE:
                typed.append(input)
                return reply()
            if args[:1] == ["activewindow"]:
                return reply('{"address":"0x1"}')
            if args[:1] == ["monitors"]:
                return reply('[{"solitaryBlockedBy": []}]')
            return reply(seen[0] if len(seen) == 1 else seen.popleft())

        self.mod.BACKEND = FakeBackend(secret="abc")
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        with (
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs),
        ):
            code, _out, err = invoke_main(self.mod, TYPE_ARGV)
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)


class TestControlCharacters(HyprlandCase):
    MONITORS = reply('[{"solitaryBlockedBy": []}]')

    def test_type_refuses_a_secret_with_a_control_character(self) -> None:
        for secret in ("user\npass", "a\rb", "a\tb", "a\x1b[2Jb", "a\x7fb", "a\x85b", "a b"):
            with self.subTest(secret=ascii(secret)):
                code, err, typed = self.run_type(secret, self.MONITORS)
                self.assertEqual(code, self.mod.EXIT_CONTROL_SECRET, err)
                self.assertEqual(typed, [])
                self.assertIn("control characters", err)
                self.assertIn("not typed", err)
                self.assertNotIn("user", err)

    def test_the_exit_code_is_its_own(self) -> None:
        taken = {
            getattr(self.mod, n) for n in dir(self.mod) if n.startswith("EXIT_") and n != "EXIT_CONTROL_SECRET"
        } | {1, 2, 3}
        self.assertNotIn(self.mod.EXIT_CONTROL_SECRET, taken)

    def test_a_plain_secret_with_spaces_and_unicode_is_typed(self) -> None:
        code, err, typed = self.run_type("p ä$sé", self.MONITORS)
        self.assertEqual((code, "".join(typed)), (0, "p ä$sé"), err)

    def test_copy_refuses_it_too_and_never_reaches_the_clipboard(self) -> None:
        self.mod.BACKEND = FakeBackend(secret="user\npass")
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        with mock.patch.object(self.mod, "clipboard_copy") as copy:
            code, _out, err = invoke_main(self.mod, ["copy", "--account", "a"])
        self.assertEqual(code, self.mod.EXIT_CONTROL_SECRET, err)
        self.assertIn("not copied", err)
        copy.assert_not_called()

    def test_copy_still_copies_a_plain_secret(self) -> None:
        self.mod.BACKEND = FakeBackend(secret="plain secret")
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        with mock.patch.object(self.mod, "clipboard_copy") as copy:
            code, _out, err = invoke_main(self.mod, ["copy", "--account", "a"])
        self.assertEqual(code, 0, err)
        copy.assert_called_once_with("plain secret")


if __name__ == "__main__":
    unittest.main()
