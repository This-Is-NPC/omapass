"""focus-snapshot and type with a missing compositor binary or no focus."""

from __future__ import annotations

import types
import unittest
from unittest import mock

from tests.helper_loader import load_helper
from tests.test_helper_security import FakeBackend, invoke_main

MISSING = "/nonexistent/compositor-binary"


class TestCompositorMissing(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def setUp(self) -> None:
        self.saved = {k: getattr(self.mod, k) for k in ("HYPRCTL", "NIRI", "TYPE_TIMEOUT_MS")}
        self.addCleanup(self._cleanup)
        self.mod.TYPE_TIMEOUT_MS = 50
        self.mod.BACKEND = FakeBackend(secret="abc")
        self.outputs: dict[str, str] = {}
        real = self.mod.exec_abs

        # The sandbox /tmp is noexec: serve present binaries from a stub and
        # run the real exec_abs for a missing one.
        def exec_abs(path, args, **kw):
            if path in self.outputs:
                return types.SimpleNamespace(returncode=0, stdout=self.outputs[path], stderr="")
            return real(path, args, **kw)

        patcher = mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cleanup(self) -> None:
        for k, v in self.saved.items():
            setattr(self.mod, k, v)
        self.mod.BACKEND = None

    def setup_compositors(self, hypr: str | None, niri: str | None) -> None:
        for attr, name, output in (("HYPRCTL", "/fake/hyprctl", hypr), ("NIRI", "/fake/niri", niri)):
            if output is None:
                setattr(self.mod, attr, MISSING)
            else:
                setattr(self.mod, attr, name)
                self.outputs[name] = output

    CASES = {
        "hyprland without focus, niri missing": ("{}", None),
        "hyprland missing, niri without focus": (None, "null"),
        "both missing": (None, None),
    }

    def test_focus_snapshot_exits_3_without_a_traceback(self) -> None:
        for name, (hypr, niri) in self.CASES.items():
            with self.subTest(name):
                self.setup_compositors(hypr, niri)
                code, out, err = invoke_main(self.mod, ["focus-snapshot"])
                self.assertEqual((code, out), (3, ""))
                self.assertIn("no compositor focus", err)

    def test_type_exits_3_without_a_traceback(self) -> None:
        for name, (hypr, niri) in self.CASES.items():
            with self.subTest(name):
                self.setup_compositors(hypr, niri)
                code, _out, err = invoke_main(self.mod, ["type", "--account", "a"])
                self.assertEqual(code, 3)
                self.assertIn("no compositor focus", err)

    def test_type_with_an_explicit_compositor_exits_8(self) -> None:
        for compositor in ("hyprland", "niri"):
            with self.subTest(compositor):
                self.setup_compositors(None, None)
                code, _out, err = invoke_main(
                    self.mod,
                    ["type", "--account", "a", "--compositor", compositor, "--expect-id", "1"],
                )
                self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED)
                self.assertIn("focus changed", err)
                self.assertEqual(self.mod.BACKEND.get_secret_calls, [])

    def test_niri_alone_still_works(self) -> None:
        self.setup_compositors(None, '{"id": 7}')
        code, out, _err = invoke_main(self.mod, ["focus-snapshot"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), '{"compositor": "niri", "id": "7"}')

    def test_layers_unreadable_when_the_binary_is_missing(self) -> None:
        self.setup_compositors(None, None)
        for compositor in ("hyprland", "niri"):
            self.assertIsNone(self.mod.read_layers(compositor))


if __name__ == "__main__":
    unittest.main()
