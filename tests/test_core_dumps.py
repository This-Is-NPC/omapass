"""The helper must not leave secrets in core dumps or readable via ptrace."""

from __future__ import annotations

import resource
import subprocess
import sys
import textwrap
import unittest
from unittest import mock

from tests.helper_loader import ROOT, load_helper
from tests.sandbox_env import sandbox_only

class TestHardenProcess(unittest.TestCase):
    def test_sets_core_limit_and_dumpable(self) -> None:
        mod = load_helper()
        libc = mock.Mock()
        with mock.patch.object(mod.resource, "setrlimit") as setrlimit, \
                mock.patch.object(mod.ctypes, "CDLL", return_value=libc):
            mod.harden_process()
        setrlimit.assert_called_once_with(resource.RLIMIT_CORE, (0, 0))
        libc.prctl.assert_called_once_with(4, 0, 0, 0, 0)

    def test_failures_do_not_crash(self) -> None:
        mod = load_helper()
        with mock.patch.object(mod.resource, "setrlimit", side_effect=OSError), \
                mock.patch.object(mod.ctypes, "CDLL", side_effect=OSError):
            mod.harden_process()

    def test_rlimit_failure_still_tries_prctl(self) -> None:
        mod = load_helper()
        libc = mock.Mock()
        with mock.patch.object(mod.resource, "setrlimit", side_effect=ValueError), \
                mock.patch.object(mod.ctypes, "CDLL", return_value=libc):
            mod.harden_process()
        libc.prctl.assert_called_once()

    def test_main_hardens_before_any_command(self) -> None:
        # clipboard-serve is the helper re-exec'd, so it goes through main too.
        mod = load_helper()
        order = []
        with mock.patch.object(mod, "harden_process", lambda: order.append("harden")), \
                mock.patch.object(mod, "cmd_clipboard_serve", lambda a: order.append("cmd")):
            mod.main(["clipboard-serve"])
        self.assertEqual(order, ["harden", "cmd"])


CHILD = textwrap.dedent(
    """
    import ctypes, subprocess, sys
    sys.path.insert(0, sys.argv[1])
    from tests.helper_loader import load_helper
    mod = load_helper()
    mod.harden_process()
    libc = ctypes.CDLL(None)
    print("dumpable", libc.prctl(3, 0, 0, 0, 0))
    out = subprocess.run(
        ["/usr/bin/grep", "core file", "/proc/self/limits"],
        capture_output=True, text=True,
    ).stdout
    print("child", out.split())
    """
)


@sandbox_only
class TestHardenedProcess(unittest.TestCase):
    def test_real_process_is_not_dumpable_and_child_has_no_core(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD, str(ROOT)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dumpable 0", proc.stdout)
        self.assertIn("'0', '0', 'bytes'", proc.stdout)


if __name__ == "__main__":
    unittest.main()
