"""The sandbox gate, own-daemon cleanup and path handling of the scripts."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import sandbox_env
from tests.sandbox_env import STOP_OWN_KEYRING, sandbox_only

ROOT = Path(__file__).resolve().parents[1]


class TestSandboxGate(unittest.TestCase):
    def test_env_var_alone_is_not_the_sandbox(self) -> None:
        with (
            mock.patch.dict(os.environ, {"OMAPASS_SANDBOX": "1"}),
            mock.patch.object(sandbox_env, "MARKER", "/nonexistent/IN_SANDBOX"),
        ):
            self.assertFalse(sandbox_env.in_sandbox())

    def test_marker_must_be_root_owned(self) -> None:
        with tempfile.NamedTemporaryFile() as marker, mock.patch.dict(os.environ, {"OMAPASS_SANDBOX": "1"}):
            with mock.patch.object(sandbox_env, "MARKER", marker.name):
                self.assertNotEqual(os.stat(marker.name).st_uid, 0)
                self.assertFalse(sandbox_env.in_sandbox())

    def test_marker_alone_is_not_enough(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OMAPASS_SANDBOX"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(sandbox_env.in_sandbox())

    def test_run_sh_and_tests_use_the_single_gate(self) -> None:
        run_sh = (ROOT / "tests" / "run.sh").read_text()
        self.assertIn("sandbox_env.py", run_sh)
        self.assertNotIn("OMAPASS_SANDBOX", run_sh)
        for path in (ROOT / "tests").glob("*.py"):
            if path.name in ("sandbox_env.py", "test_sandbox_env.py"):
                continue
            self.assertNotIn("OMAPASS_SANDBOX", path.read_text(), path.name)
        containerfile = (ROOT / "tests" / "sandbox" / "Containerfile").read_text()
        self.assertIn("/opt/sandbox/IN_SANDBOX", containerfile)

    @sandbox_only
    def test_gate_holds_in_the_real_sandbox(self) -> None:
        proc = subprocess.run(["/usr/bin/python3", "-I", str(ROOT / "tests" / "sandbox_env.py")])
        self.assertEqual(proc.returncode, 0)


@sandbox_only
class TestStopOwnKeyring(unittest.TestCase):
    def test_other_sessions_daemon_survives(self) -> None:
        script = STOP_OWN_KEYRING + r"""
set -u
outer=$(pgrep -u "$(id -u)" -x gnome-keyring-d | head -n1)
inner() {
  gnome-keyring-daemon --start --components=secrets >/dev/null
  stop_keyring
}
dbus-run-session -- bash -c "$(declare -f stop_keyring inner); inner"
kill -0 "$outer" && echo outer-alive
stop_keyring
"""
        with tempfile.TemporaryDirectory() as home:
            env = {"PATH": os.environ["PATH"], "HOME": home}
            proc = subprocess.run(
                ["dbus-run-session", "--", "bash", "-c",
                 "gnome-keyring-daemon --start --components=secrets >/dev/null\n" + script],
                env=env, capture_output=True, text=True, timeout=60,
            )
        self.assertIn("outer-alive", proc.stdout, proc.stdout + proc.stderr)


    def test_waits_until_the_daemon_has_exited(self) -> None:
        # A stand-in daemon that takes a second to exit after SIGTERM. Its
        # script name gives it the process name the helper looks for.
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            fake = Path(tmp) / "gnome-keyring-d"
            fake.write_text("#!/bin/bash\ntrap 'sleep 1; exit 0' TERM\nwhile :; do sleep 0.1; done\n")
            fake.chmod(0o700)
            script = STOP_OWN_KEYRING + f"""
export DBUS_SESSION_BUS_ADDRESS=unix:path=/fake
{fake} &
fake=$!
sleep 0.3
stop_keyring; echo "rc=$?"
kill -0 "$fake" 2>/dev/null && echo still-running
"""
            proc = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, timeout=30,
                env={"PATH": "/usr/bin:/bin"},
            )
        self.assertIn("rc=0", proc.stdout, proc.stdout + proc.stderr)
        self.assertNotIn("still-running", proc.stdout)


class TestWrapperScripts(unittest.TestCase):
    @sandbox_only
    def test_wrapper_works_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "omapass-link"
            link.symlink_to(ROOT / "bin" / "omapass")
            proc = subprocess.run([str(link), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
