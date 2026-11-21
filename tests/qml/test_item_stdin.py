"""The panel names an item on the helper's stdin, never in argv (adv6 A7).

Other local users can read a process's arguments in /proc (no hidepid), and
`type` runs for seconds. Account names are sensitive metadata. Run with
scripts/test-qml.
"""
import json
import os
import subprocess
import unittest

from session import Session, in_qml_sandbox
from test_vault_runtime import VaultCase

ACCOUNT = "me@bank.example"
RECORDS = [{"account": ACCOUNT, "folder": "Private", "kind": ""}]


class ItemOnStdin(VaultCase):
    config = {"records": RECORDS}

    def assert_on_stdin_only(self, cmd, extra=None):
        call = self.s.helper_calls(cmd)[-1]
        self.assertEqual(call["real_argv"], [cmd, "--item-stdin"])
        self.assertEqual(json.loads(call["stdin"]),
                         dict({"account": ACCOUNT, "folder": "Private"}, **(extra or {})))
        self.assertFalse([a for a in call["real_argv"] if ACCOUNT in a or "Private" in a or "0x1" in a])

    def test_copy(self):
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.assert_on_stdin_only("copy")

    def test_type(self):
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assert_on_stdin_only("type", {"compositor": "hyprland", "expect_id": "0x1"})

    def test_remove(self):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.s.press("-k", "Tab", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.assert_on_stdin_only("clear")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class ReopenStopsAnItemStdinType(unittest.TestCase):
    """cancelType finds a `type --item-stdin` of this plugin by its command line."""

    def test_open_terminates_it(self):
        s = Session({"delay": {"type": 30}})
        self.addCleanup(s.stop)
        s.start()
        helper = os.path.join(s.dir, "plugin", "bin", "omapass-keyring")
        other = subprocess.Popen(["/usr/bin/python3", "-I", helper, "type", "--item-stdin"],
                                 stdin=subprocess.PIPE, env=dict(os.environ, OMAPASS_STUB_DIR=s.stub_dir))
        self.addCleanup(other.kill)
        other.stdin.write(json.dumps({"account": "x"}).encode())
        other.stdin.close()
        s.wait(lambda: s.helper_calls("type"), "the other instance's type call")
        s.open_panel()
        s.wait(lambda: any(c.get("event") == "terminated" for c in s.calls()), "the type to be terminated")
        self.assertEqual(other.wait(5), 143)


if __name__ == "__main__":
    unittest.main()
