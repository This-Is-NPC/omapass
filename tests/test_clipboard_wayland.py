"""Clipboard lifetime against a real compositor: headless sway, wl-clipboard
and an Omarchy-style history watcher (`wl-paste --watch`), all in the sandbox.

A paste must work (as often as the user pastes), a new copy must replace the
secret and end the helper, an unpasted copy must be cleared by the TTL, and the
secret must never appear in argv or env.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.sandbox_env import sandbox_only

HELPER = Path(__file__).resolve().parents[1] / "bin" / "omapass-keyring"
SECRET = "dummy-clip-123"
WAIT_S = 10


def wait_for(check, what: str, timeout: float = WAIT_S):
    """Poll check() until it returns something truthy; fail after timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


@sandbox_only
@unittest.skipUnless(
    os.path.exists("/usr/bin/sway") and os.path.exists("/usr/bin/wl-paste"),
    "needs sway and wl-clipboard (sandbox image)",
)
class TestClipboardLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = tempfile.mkdtemp(prefix="omapass-wl-", dir="/tmp")
        os.chmod(cls.runtime, 0o700)
        cls.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": cls.runtime,
            "XDG_RUNTIME_DIR": cls.runtime,
            "WAYLAND_DISPLAY": "wayland-1",
            "WLR_BACKENDS": "headless",
            "WLR_RENDERER": "pixman",
            "WLR_LIBINPUT_NO_DEVICES": "1",
        }
        # The packaged sway has file capabilities the sandbox cannot grant.
        # It lives under $HOME: the sandbox's /tmp is noexec.
        cls.bindir = tempfile.mkdtemp(prefix="omapass-sway-", dir=Path.home())
        sway = Path(cls.bindir) / "sway"
        shutil.copy("/usr/bin/sway", sway)
        cls.sway = subprocess.Popen(
            [str(sway)], env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        socket = Path(cls.runtime) / "wayland-1"
        wait_for(lambda: socket.exists() or cls.sway.poll() is not None, "sway socket")
        if cls.sway.poll() is not None:
            raise AssertionError("sway did not start")
        # Same command line as Omarchy's clipboard history watcher.
        cls.watcher = subprocess.Popen(
            ["/usr/bin/wl-paste", "--type", "text", "--watch", "sh", "-c", "cat >/dev/null"],
            env=cls.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        for proc in (cls.watcher, cls.sway):
            proc.terminate()
            proc.wait(5)
        shutil.rmtree(cls.runtime, ignore_errors=True)
        shutil.rmtree(cls.bindir, ignore_errors=True)

    def setUp(self) -> None:
        self.addCleanup(self.clear)

    def clear(self) -> None:
        subprocess.run(["/usr/bin/wl-copy", "--clear"], env=self.env, timeout=WAIT_S, check=False)

    def paste(self) -> str | None:
        done = subprocess.run(
            ["/usr/bin/wl-paste", "--no-newline"],
            env=self.env, capture_output=True, text=True, timeout=WAIT_S, check=False,
        )
        return done.stdout if done.returncode == 0 else None

    def serve(self, *extra: str) -> subprocess.Popen:
        """Start clipboard-serve directly; returns once it reports "ok"."""
        proc = subprocess.Popen(
            ["/usr/bin/python3", "-I", str(HELPER), "clipboard-serve", *extra],
            env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.addCleanup(self.reap, proc)
        proc.stdin.write(SECRET.encode())
        proc.stdin.close()
        self.assertEqual(proc.stdout.readline(), b"ok\n")
        return proc

    @staticmethod
    def reap(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        proc.wait(5)

    def children_of(self, proc: subprocess.Popen) -> list[int]:
        out = subprocess.run(
            ["/usr/bin/pgrep", "-P", str(proc.pid)], capture_output=True, text=True, check=False
        ).stdout
        return [int(p) for p in out.split()]

    def test_a_paste_works_and_the_history_watcher_does_not_end_the_copy(self) -> None:
        proc = self.serve()
        self.assertEqual(self.paste(), SECRET)
        self.assertEqual(self.paste(), SECRET)
        self.assertIsNone(proc.poll(), "pasting must not end the helper")

    def test_unpasted_copy_is_cleared_by_the_ttl(self) -> None:
        started = time.monotonic()
        proc = self.serve("--ttl", "3")
        proc.wait(WAIT_S)
        self.assertGreaterEqual(time.monotonic() - started, 2.5)
        self.assertIsNone(self.paste())

    def test_copying_something_else_ends_the_helper(self) -> None:
        proc = self.serve()
        subprocess.run(
            ["/usr/bin/wl-copy", "other-content"], env=self.env, timeout=WAIT_S, check=True
        )
        proc.wait(WAIT_S)
        self.assertEqual(self.paste(), "other-content")  # the new copy is not cleared

    def test_killing_the_helper_clears_the_clipboard(self) -> None:
        proc = self.serve()
        proc.kill()
        proc.wait(5)
        wait_for(lambda: self.paste() is None, "wl-copy to die with the helper")

    def test_secret_is_not_in_argv_or_environment(self) -> None:
        proc = self.serve()
        pids = [proc.pid, *self.children_of(proc)]
        self.assertEqual(len(pids), 2, "helper should own exactly wl-copy")
        # The helper is non-dumpable, so even its owner cannot read its environ.
        for pid, name in ((pids[0], "cmdline"), (pids[1], "cmdline"), (pids[1], "environ")):
            data = Path(f"/proc/{pid}/{name}").read_bytes()
            self.assertNotIn(SECRET.encode(), data, f"{name} of {pid}")

    def test_same_user_process_can_read_the_buffer(self) -> None:
        # Documents why same-user memory hardening of wl-copy is moot (README).
        proc = self.serve()
        (wl_copy,) = self.children_of(proc)
        script = (
            'for f in /proc/$1/fd/*; do case "$(readlink "$f")" in '
            '*/wl-copy-buffer-*) cat "$f";; esac; done'
        )
        done = subprocess.run(
            ["/bin/sh", "-c", script, "sh", str(wl_copy)],
            capture_output=True, text=True, timeout=WAIT_S, check=False,
        )
        self.assertEqual(done.stdout, SECRET)

    def test_copy_text_command_end_to_end(self) -> None:
        done = subprocess.run(
            ["/usr/bin/python3", "-I", str(HELPER), "copy-text"],
            env=self.env, input=SECRET, text=True, capture_output=True, timeout=WAIT_S, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.paste(), SECRET)


if __name__ == "__main__":
    unittest.main()
