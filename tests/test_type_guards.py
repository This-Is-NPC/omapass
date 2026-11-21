"""Typing guards: unsafe /tmp, hung compositor or wtype, and a session lock."""

from __future__ import annotations

import collections
import io
import json
import os
import shutil
import tempfile
import time
import types
import unittest
from contextlib import redirect_stderr
from unittest import mock

from tests.helper_loader import load_helper
from tests.test_helper_security import FakeBackend, invoke_main

TYPE_ARGV = ["type", "--account", "a", "--compositor", "hyprland", "--expect-id", "0x1"]
SLOW_TIMEOUT_S = 0.3


class TypeGuardCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def setUp(self) -> None:
        self.backend = FakeBackend(secret="abc")
        self.mod.BACKEND = self.backend
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        self.wtype: list[str] = []

    def run_type(self, *, lock=(False,), tmp_problem=None, wtype=None):
        """cmd_type with focus, layers, lock and /tmp mocked; wtype logs its input."""

        def exec_abs(path, args, input=None, capture=False, **kw):
            if path == self.mod.WTYPE:
                if wtype is not None:
                    return wtype(path, args, input=input, **kw)
                self.wtype.append(input)
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        locks = iter(lock)
        with (
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=tmp_problem),
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
            mock.patch.object(
                self.mod, "read_focus_for", return_value={"compositor": "hyprland", "id": "0x1"}
            ),
            mock.patch.object(self.mod, "session_locked", side_effect=lambda c: next(locks)),
            mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs),
        ):
            return invoke_main(self.mod, TYPE_ARGV)


class TestSessionLock(TypeGuardCase):
    def monitors(self, *blockers):
        out = json.dumps([{"name": "m", "solitaryBlockedBy": b} for b in blockers])
        return mock.patch.object(self.mod, "query_compositor", return_value=out)

    def test_lock_in_any_monitor_is_detected(self) -> None:
        with self.monitors(["WINDOWED"], ["LOCK", "CANDIDATE"]):
            self.assertTrue(self.mod.session_locked("hyprland"))

    def test_no_lock_reason_is_not_a_lock(self) -> None:
        for blockers in ([["WINDOWED", "CANDIDATE"]], [["WORKSPACE"], []], [[]], [None]):
            with self.subTest(blockers=blockers), self.monitors(*blockers):
                self.assertFalse(self.mod.session_locked("hyprland"))

    def test_monitors_all_blocked_by_workspace_are_an_unknown_lock_state(self) -> None:
        # Hyprland stops at WORKSPACE before it reaches the lock (A10).
        with self.monitors(["WORKSPACE"], ["WORKSPACE", "WINDOWED"]):
            self.assertIsNone(self.mod.session_locked("hyprland"))

    def test_unreadable_or_odd_output_is_an_unknown_lock_state(self) -> None:
        # Fail closed: "could not tell" must never read as "not locked".
        odd = ("{}", "null", "[]", "[1, 2]", '[{"solitaryBlockedBy": "LOCK"}]', '[{"name": "m"}, 3]')
        for out in (None, "", "not json") + odd:
            with self.subTest(out=out), mock.patch.object(
                self.mod, "query_compositor", return_value=out
            ):
                self.assertIsNone(self.mod.session_locked("hyprland"))

    def test_a_monitor_without_the_field_is_no_lock(self) -> None:
        with mock.patch.object(self.mod, "query_compositor", return_value='[{"name": "m"}]'):
            self.assertFalse(self.mod.session_locked("hyprland"))

    def test_other_compositors_are_not_queried(self) -> None:
        with mock.patch.object(self.mod, "query_compositor", side_effect=AssertionError):
            self.assertFalse(self.mod.session_locked("niri"))

    def test_the_query_is_read_only(self) -> None:
        with mock.patch.object(self.mod, "query_compositor", return_value="[]") as q:
            self.mod.session_locked("hyprland")
        self.assertEqual(q.call_args.args, (self.mod.HYPRCTL, ["monitors", "-j"]))

    def test_a_lock_before_typing_types_nothing(self) -> None:
        code, _out, err = self.run_type(lock=(True,))
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED)
        self.assertIn("session locked", err)
        self.assertEqual(self.wtype, [])

    def test_an_unknown_lock_state_types_nothing(self) -> None:
        code, _out, err = self.run_type(lock=(None,))
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED)
        self.assertIn("session lock state unknown", err)
        self.assertEqual(self.wtype, [])

    def test_an_unknown_lock_state_midway_stops_the_rest(self) -> None:
        code, _out, err = self.run_type(lock=(False, None))
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED)
        self.assertIn("session lock state unknown", err)
        self.assertEqual(self.wtype, ["a"])

    def test_a_lock_that_appears_stops_the_rest(self) -> None:
        code, _out, err = self.run_type(lock=(False, True))
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED)
        self.assertIn("session locked", err)
        self.assertEqual(self.wtype, ["a"])

    def test_without_a_lock_everything_is_typed(self) -> None:
        code, _out, err = self.run_type(lock=(False, False, False))
        self.assertEqual((code, "".join(self.wtype)), (0, "abc"), err)


class TestWtypeTmp(TypeGuardCase):
    def problem(self, fstype, mode=0o1777):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.chmod(tmp, mode)
        with mock.patch.object(self.mod, "mount_fstype", return_value=fstype):
            return self.mod.wtype_tmp_problem(tmp)

    def test_memory_filesystems_are_accepted(self) -> None:
        for fstype in ("tmpfs", "ramfs"):
            with self.subTest(fstype):
                self.assertIsNone(self.problem(fstype))

    def test_disk_filesystems_are_refused(self) -> None:
        for fstype in ("ext4", "btrfs", "overlay", ""):
            with self.subTest(fstype):
                self.assertIn("not tmpfs", self.problem(fstype))

    def test_a_shared_directory_without_the_sticky_bit_is_refused(self) -> None:
        self.assertIn("sticky", self.problem("tmpfs", 0o777))

    def test_the_real_mount_info_is_used(self) -> None:
        fake = '25 1 0:5 / /tmp rw - {} tmpfs rw\n'
        for fstype, expected in (("tmpfs", True), ("ext4", False)):
            with self.subTest(fstype), mock.patch(
                "builtins.open", mock.mock_open(read_data=fake.format(fstype))
            ):
                self.assertEqual(self.mod.mount_fstype("/tmp") == "tmpfs", expected)

    def test_type_refuses_before_reading_the_secret(self) -> None:
        code, _out, err = self.run_type(tmp_problem="/tmp is on ext4, not tmpfs")
        self.assertEqual(code, self.mod.EXIT_WTYPE_FAILED)
        self.assertIn("refusing to type: /tmp is on ext4", err)
        self.assertEqual((self.backend.get_secret_calls, self.wtype), ([], []))

    def test_wtype_does_not_honor_tmpdir(self) -> None:
        # Why the check is on /tmp itself: the path is compiled into wtype 0.4.
        if not os.path.exists("/usr/bin/wtype"):
            self.skipTest("wtype not installed")
        with open("/usr/bin/wtype", "rb") as f:
            data = f.read()
        self.assertIn(b"/tmp/wtype-XXXXX", data)
        self.assertNotIn(b"TMPDIR", data)


class TestTimeouts(TypeGuardCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(self.mod, "SUBPROCESS_TIMEOUT_S", SLOW_TIMEOUT_S)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.real = self.mod.exec_abs

    def hang(self, path, args, **kw):
        """The real exec_abs, running a command that sleeps far longer than the timeout."""
        return self.real("/usr/bin/sleep", ["30"], **kw)

    def test_a_hung_compositor_query_gives_up(self) -> None:
        with mock.patch.object(self.mod, "exec_abs", side_effect=self.hang):
            start = time.monotonic()
            self.assertIsNone(self.mod.query_compositor(self.mod.HYPRCTL, ["layers", "-j"]))
            self.assertIsNone(self.mod.read_layers("hyprland"))
            self.assertIsNone(self.mod.read_focus_for("niri"))
            self.assertIsNone(self.mod.session_locked("hyprland"))
        self.assertLess(time.monotonic() - start, 6 * SLOW_TIMEOUT_S + 2)

    def test_every_compositor_and_wtype_call_passes_a_timeout(self) -> None:
        seen = []

        def spy(path, args, **kw):
            seen.append((os.path.basename(path), kw.get("timeout")))
            return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")

        with (
            mock.patch.object(self.mod, "exec_abs", side_effect=spy),
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
        ):
            self.mod.read_hyprland_focus()
            self.mod.read_niri_focus()
            self.mod.read_layers("hyprland")
            self.mod.session_locked("hyprland")
        self.assertTrue(seen)
        self.assertTrue(all(t == SLOW_TIMEOUT_S for _n, t in seen), seen)

    def test_type_with_a_hung_compositor_aborts_without_the_secret_in_wtype(self) -> None:
        with (
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "TYPE_TIMEOUT_MS", 100),
            mock.patch.object(
                self.mod,
                "exec_abs",
                side_effect=lambda p, a, **kw: self.hang(p, a, **kw)
                if p != self.mod.WTYPE
                else self.wtype.append("x"),
            ),
        ):
            start = time.monotonic()
            code, _out, err = invoke_main(self.mod, TYPE_ARGV)
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual((self.wtype, self.backend.get_secret_calls), ([], []))
        self.assertLess(time.monotonic() - start, 10)

    def test_a_hung_wtype_aborts_and_types_no_more(self) -> None:
        calls = []

        def slow_wtype(path, args, input=None, **kw):
            calls.append(input)
            return self.real("/usr/bin/sleep", ["30"], **kw)

        start = time.monotonic()
        code, _out, err = self.run_type(wtype=slow_wtype)
        self.assertEqual(code, self.mod.EXIT_WTYPE_FAILED, err)
        self.assertIn("timed out", err)
        self.assertEqual(calls, ["a"])
        self.assertLess(time.monotonic() - start, 10)

    def test_a_hung_focus_snapshot_exits_3(self) -> None:
        with mock.patch.object(self.mod, "exec_abs", side_effect=self.hang):
            code, _out, err = invoke_main(self.mod, ["focus-snapshot"])
        self.assertEqual(code, 3, err)


if __name__ == "__main__":
    unittest.main()
