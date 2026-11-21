"""One omapass write at a time: the lock file, its safety checks, and who holds it."""

from __future__ import annotations

import contextlib
import fcntl
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.helper_loader import HELPER_PATH, load_helper
from tests.sandbox_env import sandbox_only
from tests.test_secret_validation import HEALTH, SETUP

UID = os.getuid()
FALLBACK = f"/tmp/omapass-{UID}.lock"
HOLDER = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
)


class LockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "omapass.lock"
        self.mod.lock_path = lambda: str(self.path)
        self.mod.LOCK_TIMEOUT_S = 0.3
        self.mod.LOCK_POLL_S = 0.01

    def exit_of(self, fn, *args) -> tuple[int, str]:
        err = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(err):
            fn(*args)
        return ctx.exception.code, err.getvalue()

    def hold(self) -> subprocess.Popen:
        """Another process holds the lock until its stdin closes."""
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", HOLDER, str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, proc)
        self.assertEqual(proc.stdout.readline(), "locked\n")
        return proc

    @staticmethod
    def release(proc: subprocess.Popen) -> None:
        proc.stdin.close()
        proc.stdout.close()
        proc.wait(5)

    def is_locked(self) -> bool:
        """True if another open of the lock file cannot take the lock now."""
        fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(fd)
        return False

    def under_lock(self):
        with self.mod.write_lock():
            pass


class TestLockPath(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_helper()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def path_with(self, **env: str) -> str:
        with mock.patch.dict(os.environ, env):
            if "XDG_RUNTIME_DIR" not in env:
                os.environ.pop("XDG_RUNTIME_DIR", None)
            return self.mod.lock_path()

    def test_a_private_runtime_dir_holds_the_lock(self) -> None:
        self.tmp.chmod(0o700)
        self.assertEqual(
            self.path_with(XDG_RUNTIME_DIR=str(self.tmp)), str(self.tmp / "omapass.lock")
        )

    def test_everything_else_falls_back_to_tmp(self) -> None:
        loose = self.tmp / "loose"
        loose.mkdir(mode=0o755)
        loose.chmod(0o755)
        (self.tmp / "file").write_text("")
        for name, value in (
            ("unset", None),
            ("empty", ""),
            ("relative", "run/user"),
            ("wrong mode", str(loose)),
            ("missing", str(self.tmp / "missing")),
            ("not a directory", str(self.tmp / "file")),
        ):
            with self.subTest(name):
                env = {} if value is None else {"XDG_RUNTIME_DIR": value}
                self.assertEqual(self.path_with(**env), FALLBACK)

    def test_a_runtime_dir_of_another_user_falls_back_to_tmp(self) -> None:
        self.tmp.chmod(0o700)
        real = os.stat(self.tmp)
        other = types.SimpleNamespace(st_mode=real.st_mode, st_uid=UID + 1)
        with mock.patch.object(self.mod.os, "stat", return_value=other):
            self.assertEqual(self.path_with(XDG_RUNTIME_DIR=str(self.tmp)), FALLBACK)


class TestWriteLockFile(LockCase):
    def test_the_lock_file_is_private_and_regular(self) -> None:
        with self.mod.write_lock():
            self.assertTrue(self.is_locked())
        st = os.stat(self.path)
        self.assertTrue(stat.S_ISREG(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode) & 0o177, 0)  # no group or other access

    def test_the_lock_is_released_on_exit_and_after_an_error(self) -> None:
        self.under_lock()
        self.assertFalse(self.is_locked())
        with self.assertRaises(RuntimeError), self.mod.write_lock():
            raise RuntimeError("write failed")
        self.assertFalse(self.is_locked())

    def test_a_symlink_is_refused_and_not_followed(self) -> None:
        target = self.tmp / "target"
        target.write_text("keep")
        self.path.symlink_to(target)
        code, err = self.exit_of(self.under_lock)
        self.assertEqual(code, 5)
        self.assertIn("cannot open a safe omapass write lock", err)
        self.assertIn("Nothing was written", err)
        self.assertEqual(target.read_text(), "keep")

    def test_a_file_of_another_user_is_refused(self) -> None:
        self.path.write_text("")
        real = os.fstat
        mine = types.SimpleNamespace

        def fstat(fd):
            st = real(fd)
            return mine(st_mode=st.st_mode, st_uid=UID + 1)

        with mock.patch.object(self.mod.os, "fstat", fstat):
            code, err = self.exit_of(self.under_lock)
        self.assertEqual(code, 5)
        self.assertIn("cannot open a safe omapass write lock", err)

    def test_a_file_that_is_not_regular_is_refused(self) -> None:
        os.mkfifo(self.path, 0o600)
        code, err = self.exit_of(self.under_lock)
        self.assertEqual(code, 5)
        self.assertIn("cannot open a safe omapass write lock", err)

    def test_an_unopenable_path_is_refused(self) -> None:
        self.mod.lock_path = lambda: str(self.tmp / "missing" / "omapass.lock")
        code, err = self.exit_of(self.under_lock)
        self.assertEqual(code, 5)
        self.assertIn("cannot open a safe omapass write lock", err)


class TestWriteLockWait(LockCase):
    def test_a_lock_held_by_another_process_times_out_with_exit_5(self) -> None:
        self.hold()
        started = time.monotonic()
        code, err = self.exit_of(self.under_lock)
        self.assertEqual(code, 5)
        self.assertGreaterEqual(time.monotonic() - started, self.mod.LOCK_TIMEOUT_S)
        self.assertIn("another omapass write is running; retry", err)
        self.assertIn("Nothing was written", err)

    def test_the_wait_ends_when_the_holder_lets_go(self) -> None:
        proc = self.hold()
        self.mod.LOCK_TIMEOUT_S = 5
        threading.Timer(0.2, proc.stdin.close).start()
        started = time.monotonic()
        self.under_lock()
        self.assertGreaterEqual(time.monotonic() - started, 0.1)

    def test_a_killed_holder_does_not_leave_the_lock_behind(self) -> None:
        proc = self.hold()
        proc.kill()
        proc.wait(5)
        self.under_lock()


class TestStoreAndClearHoldTheLock(LockCase):
    def backend(self, seen: list[tuple[str, bool]]):
        kr = object.__new__(self.mod.GiKeyring)
        collection = object()
        created = mock.Mock()
        kr._Secret = mock.Mock(
            Value=mock.Mock(new=lambda text, *_: text),
            Item=mock.Mock(create_sync=lambda *_: created),
        )
        kr._default_collection = lambda: collection
        kr.list_items = lambda: []
        kr._find = lambda *_a, **_k: []
        kr._group = lambda *_a, **_k: [
            mock.Mock(get_attributes=lambda: {"account": "a"}, get_label=lambda: "F")
        ]

        def step(name, result=None):
            def run(*_a, **_k):
                seen.append((name, self.is_locked()))
                return result
            return run

        kr._guard_write = step("guard", 0)
        kr._verify_written = step("verify")
        return kr

    def test_store_holds_the_lock_from_the_guard_to_the_verification(self) -> None:
        seen: list[tuple[str, bool]] = []
        self.backend(seen).store("a", "F", "pw")
        self.assertEqual(seen, [("guard", True), ("verify", True)])
        self.assertFalse(self.is_locked())

    def test_clear_holds_the_lock_from_the_guard_to_the_verification(self) -> None:
        seen: list[tuple[str, bool]] = []
        kr = self.backend(seen)
        kr._find = lambda *_a, **_k: [object()]
        with mock.patch.object(self.mod, "daemon_write", contextlib.nullcontext):
            kr.clear("a")
        self.assertEqual(seen, [("guard", True), ("verify", True)])
        self.assertFalse(self.is_locked())

    def test_a_busy_lock_stops_store_and_clear_before_anything_is_written(self) -> None:
        self.hold()
        for name, call in (
            ("store", lambda kr: kr.store("a", "F", "pw")),
            ("clear", lambda kr: kr.clear("a")),
        ):
            with self.subTest(name):
                seen: list[tuple[str, bool]] = []
                kr = self.backend(seen)
                code, err = self.exit_of(call, kr)
                self.assertEqual(code, 5)
                self.assertIn("another omapass write is running", err)
                self.assertEqual(seen, [])

    def test_an_invalid_entry_is_refused_before_the_lock_is_taken(self) -> None:
        self.hold()
        code, err = self.exit_of(self.backend([]).store, "bad\nname", "F", "pw")
        self.assertNotIn("write is running", err)
        self.assertEqual(code, 1)


def sandbox_run(script: str, env: dict[str, str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["dbus-run-session", "--", "bash", "-c", script],
        text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HELPER": str(HELPER_PATH),
             "HEALTH": HEALTH, **env},
    )


# Several real stores started together, in a private runtime dir.
SAME_NAME = 4
SAME_ROUNDS = 6
PARALLEL_SAME = SETUP + r"""
for i in $(seq %d); do
  for j in $(seq %d); do
    ( printf "secret-$j" | h store --account "p$i" --folder F >/dev/null 2>"$HOME/e$j"; echo $? > "$HOME/r$j" ) &
  done
  wait
  n=$(h list --json | python3 -I -c 'import json,sys; print(sum(r["account"] == "p'$i'" for r in json.load(sys.stdin)))')
  echo "round $i: $(cat "$HOME"/r? | sort | tr '\n' ' ')items=$n"
done
stop_keyring
""" % (SAME_ROUNDS, SAME_NAME)

PARALLEL_DIFFERENT = SETUP + r"""
for j in $(seq 6); do
  ( printf "secret-$j" | h store --account "q$j" --folder F >/dev/null 2>"$HOME/e$j"; echo $? > "$HOME/r$j" ) &
done
wait
echo "codes: $(cat "$HOME"/r? | sort | tr '\n' ' ')"
echo "items: $(h list --json | python3 -I -c 'import json,sys; print(len(json.load(sys.stdin)))')"
python3 -I "$HEALTH" > "$HOME/health.out" 2>&1; echo "health=$?"
stop_keyring
"""


@sandbox_only
@unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session missing")
class TestParallelStores(unittest.TestCase):
    def run_in_home(self, script: str):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        proc = sandbox_run(script, {"HOME": str(home), "XDG_RUNTIME_DIR": str(home)})
        return home, proc

    def test_stores_of_one_new_name_leave_one_item_and_the_losers_exit_4(self) -> None:
        home, proc = self.run_in_home(PARALLEL_SAME)
        rounds = [ln for ln in proc.stdout.splitlines() if ln.startswith("round ")]
        self.assertEqual(len(rounds), SAME_ROUNDS, proc.stdout + proc.stderr)
        for line in rounds:
            with self.subTest(line):
                codes = line.split(":")[1].split("items=")[0].split()
                self.assertEqual(sorted(codes), ["0"] + ["4"] * (SAME_NAME - 1), line)
                self.assertTrue(line.endswith("items=1"), line)
        self.assertEqual(stat.S_IMODE(os.stat(home / "omapass.lock").st_mode), 0o600)

    def test_stores_of_different_names_all_succeed_and_the_keyring_stays_healthy(self) -> None:
        _home, proc = self.run_in_home(PARALLEL_DIFFERENT)
        self.assertIn("codes: 0 0 0 0 0 0", proc.stdout, proc.stdout + proc.stderr)
        self.assertIn("items: 6", proc.stdout)
        self.assertIn("health=0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
