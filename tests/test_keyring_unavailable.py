"""An unreachable keyring is one line and exit 10 in every command, never a traceback."""

from __future__ import annotations

import subprocess
import tempfile
import unittest

from tests.sandbox_env import sandbox_only
from tests.helper_loader import HELPER_PATH, load_helper

COMMANDS = {
    "list": (["list"], ""),
    "list-json": (["list", "--json"], ""),
    "get": (["get", "--account", "a", "--yes"], ""),
    "exists": (["exists", "--account", "a"], ""),
    "store": (["store", "--account", "a", "--folder", "F"], "pw\n"),
    "add": (["add", "--account", "a", "--folder", "F"], "pw\n"),
    "rm": (["rm", "--", "a"], ""),
    "copy": (["copy", "--", "a"], ""),
    "nostr-new": (["nostr", "new"], ""),
    "nostr-rm": (["nostr", "rm"], ""),
}


@sandbox_only
class TestKeyringUnavailable(unittest.TestCase):
    def run_helper(self, argv: list[str], stdin: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as home:
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": home,
                "LANG": "C.UTF-8",
                # No session bus: the socket does not exist.
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={home}/no-bus",
            }
            return subprocess.run(
                ["/usr/bin/python3", "-I", str(HELPER_PATH), *argv],
                input=stdin, text=True, capture_output=True, timeout=60, env=env,
            )

    def test_no_session_bus_is_exit_10_and_one_line(self) -> None:
        for name, (argv, stdin) in COMMANDS.items():
            with self.subTest(name):
                proc = self.run_helper(argv, stdin)
                self.assertEqual(proc.returncode, 10, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1, proc.stderr)
                self.assertTrue(proc.stderr.startswith("keyring unavailable:"), proc.stderr)
                self.assertEqual(proc.stdout, "")

    def test_exists_never_says_not_found_when_unreachable(self) -> None:
        proc = self.run_helper(["exists", "--account", "a"], "")
        self.assertNotIn(proc.returncode, (0, 1))

    def test_codes_are_distinct_from_the_others(self) -> None:
        mod = load_helper()
        others = {1, 2, 3, mod.EXIT_EXISTS, mod.EXIT_UNSAFE_KEYRING, mod.EXIT_DAMAGED_KEYRING,
                  mod.EXIT_FOCUS_CHANGED, mod.EXIT_WTYPE_FAILED}
        self.assertNotIn(mod.EXIT_KEYRING_UNAVAILABLE, others)
        self.assertNotIn(mod.EXIT_AMBIGUOUS, others | {mod.EXIT_KEYRING_UNAVAILABLE})


if __name__ == "__main__":
    unittest.main()
