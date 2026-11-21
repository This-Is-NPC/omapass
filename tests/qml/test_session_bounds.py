"""The test harness bounds its own hangs and releases its files (adv6 A11)."""
import time
import unittest
from unittest import mock

import session
from session import Session, in_qml_sandbox


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class SessionBounds(unittest.TestCase):
    def test_the_watchdog_kills_quickshell_and_fails_the_test(self):
        with mock.patch.object(session, "WATCHDOG", 2):
            s = Session()
            s.start()
            began = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "watchdog killed quickshell"):
                s.wait(lambda: False, "something that never happens", timeout=60)
            self.assertLess(time.monotonic() - began, 20)
            with self.assertRaisesRegex(AssertionError, "watchdog"):
                s.stop()
        self.assertIsNotNone(s.proc.poll())

    def test_stop_closes_the_log(self):
        s = Session()
        s.start()
        s.stop()
        self.assertTrue(s.log.closed)


if __name__ == "__main__":
    unittest.main()
