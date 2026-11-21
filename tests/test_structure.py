"""The entrypoint finds its package with `python3 -I` from any directory."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from tests.helper_loader import HELPER_PATH, LIB_DIR, PACKAGE

PYTHON = "/usr/bin/python3"


def run_isolated(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-I", *args], cwd=cwd, capture_output=True, text=True,
        timeout=30, stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"},
    )


class TestEntrypointStructure(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = tmp.name  # not the repository: nothing is found by the cwd

    def test_help_runs_from_another_directory(self) -> None:
        proc = run_isolated(str(HELPER_PATH), "--help", cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage: omapass-keyring", proc.stdout)

    def test_generate_password_runs_from_another_directory(self) -> None:
        proc = run_isolated(str(HELPER_PATH), "generate-password", cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout.strip(), r"^\S{8,}$")
        self.assertEqual(proc.stderr, "")

    def test_the_entrypoint_runs_through_a_symlink(self) -> None:
        link = f"{self.cwd}/omapass-keyring"
        os.symlink(HELPER_PATH, link)
        proc = run_isolated(link, "--help", cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_every_package_module_imports(self) -> None:
        names = sorted(p.stem for p in (LIB_DIR / PACKAGE).glob("*.py") if p.stem != "__init__")
        self.assertGreaterEqual(len(names), 5, names)
        code = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "import importlib\n"
            "for name in sys.argv[2:]: importlib.import_module('%s.' + name)\n" % PACKAGE
        )
        proc = run_isolated("-c", code, str(LIB_DIR), *names, cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
