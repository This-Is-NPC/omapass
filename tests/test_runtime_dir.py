"""Copying must refuse a runtime dir that is not private tmpfs.

wl-copy buffers the secret in a file under $XDG_RUNTIME_DIR, so a disk-backed
or shared directory would put the secret back on disk.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.sandbox_env import sandbox_only
from tests.helper_loader import load_helper
from tests.test_helper_security import invoke_main


@sandbox_only
class TestClipboardRuntimeDir(unittest.TestCase):
    """Sandbox facts: /tmp is a tmpfs mount, $HOME is on the container disk."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()

    def _dir(self, parent: str, mode: int = 0o700) -> str:
        path = tempfile.mkdtemp(dir=parent)
        os.chmod(path, mode)
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def _copy(self, runtime: str | None) -> tuple[int, str, list[str]]:
        """Run clipboard-serve with wl-copy mocked; returns (code, stderr, TMPDIRs)."""
        calls: list[str] = []

        def fake_popen(cmd, **kwargs):
            calls.append(kwargs["env"].get("TMPDIR", ""))
            return mock.MagicMock(poll=lambda: 0, pid=1)

        env = {} if runtime is None else {"XDG_RUNTIME_DIR": runtime}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(self.mod.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"s"))),
        ):
            if runtime is None:
                os.environ.pop("XDG_RUNTIME_DIR", None)
            code, _out, err = invoke_main(self.mod, ["clipboard-serve"])
        return code, err, calls

    def test_private_tmpfs_dir_is_accepted(self) -> None:
        runtime = self._dir("/tmp")
        code, err, calls = self._copy(runtime)
        self.assertEqual((code, calls), (0, [runtime]), err)

    def test_disk_backed_dir_is_refused(self) -> None:
        runtime = self._dir(str(Path.home()))
        code, err, calls = self._copy(runtime)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [], "wl-copy must not run with a disk-backed dir")
        self.assertIn("not tmpfs", err)

    def test_copy_refuses_before_spawning_the_helper(self) -> None:
        with (
            mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self._dir(str(Path.home()))}),
            mock.patch.object(self.mod.subprocess, "Popen") as popen,
        ):
            code, _out, err = invoke_main(self.mod, ["copy-text"])
        self.assertNotEqual(code, 0)
        self.assertIn("not tmpfs", err)
        popen.assert_not_called()

    def test_group_or_other_accessible_dir_is_refused(self) -> None:
        for mode in (0o750, 0o705, 0o755):
            with self.subTest(mode=oct(mode)):
                code, err, calls = self._copy(self._dir("/tmp", mode))
                self.assertNotEqual(code, 0)
                self.assertEqual(calls, [])
                self.assertIn("0700", err)

    def test_dir_owned_by_someone_else_is_refused(self) -> None:
        runtime = self._dir("/tmp")
        with mock.patch.object(self.mod.os, "getuid", return_value=os.getuid() + 1):
            code, err, calls = self._copy(runtime)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("not owned", err)

    def test_symlink_to_disk_dir_is_refused(self) -> None:
        target = self._dir(str(Path.home()))
        link = Path(self._dir("/tmp")) / "link"
        link.symlink_to(target)
        code, _err, calls = self._copy(str(link))
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])

    def test_symlink_to_tmpfs_dir_passes_the_resolved_target(self) -> None:
        # Passing the link would let a swap after the check escape it.
        target = os.path.realpath(self._dir("/tmp"))
        link = Path(self._dir("/tmp")) / "link"
        link.symlink_to(target)
        code, err, calls = self._copy(str(link))
        self.assertEqual((code, calls), (0, [target]), err)

    def test_missing_relative_and_file_paths_are_refused(self) -> None:
        plain = Path(self._dir("/tmp")) / "file"
        plain.write_text("x")
        for runtime in (None, "", "relative/dir", "/nonexistent-omapass", str(plain)):
            with self.subTest(runtime=runtime):
                code, _err, calls = self._copy(runtime)
                self.assertNotEqual(code, 0)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
