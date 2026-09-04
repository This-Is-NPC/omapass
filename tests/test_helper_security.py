"""Security tests for bin/omapass-keyring (unittest only, no live keyring)."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "bin" / "omapass-keyring"
PINNED_PYTHON = "/usr/bin/python3"


def load_helper():
    """Load omapass-keyring (dash filename) via importlib."""
    if not HELPER_PATH.is_file():
        raise FileNotFoundError(f"missing helper: {HELPER_PATH}")
    loader = SourceFileLoader("omapass_keyring", str(HELPER_PATH))
    spec = importlib.util.spec_from_loader("omapass_keyring", loader)
    if spec is None:
        raise ImportError(f"cannot load spec for {HELPER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["omapass_keyring"] = mod
    loader.exec_module(mod)
    return mod


class FakeBackend:
    """Minimal keyring backend for tests; never returns real secrets in list."""

    def __init__(self, items: list[dict[str, str]] | None = None, secret: str = "test-secret") -> None:
        self.items = items or [{"account": "acct", "folder": "Fold", "kind": ""}]
        self.secret = secret
        self.get_secret_calls: list[str] = []
        self.store_calls: list[tuple[str, str, str, str]] = []
        self.clear_calls: list[str] = []

    def list_items(self) -> list[dict[str, str]]:
        return list(self.items)

    def get_secret(self, account: str) -> str:
        self.get_secret_calls.append(account)
        return self.secret

    def store(self, account: str, folder: str, secret: str, kind: str = "") -> None:
        self.store_calls.append((account, folder, secret, kind))

    def clear(self, account: str) -> None:
        self.clear_calls.append(account)

    def exists(self, account: str) -> bool:
        return any(i.get("account") == account for i in self.items)


def make_evil_dir(tmp: Path) -> Path:
    evil = tmp / "evil"
    evil.mkdir()
    script = textwrap.dedent(
        f"""\
        #!/bin/sh
        echo pwned > "{tmp / "pwned"}"
        cat > "{tmp / "evil_stdin"}"
        """
    )
    for name in ("secret-tool", "wl-copy", "wtype", "python3"):
        path = evil / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    return evil


def make_recorder_script(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            cat > "{dest}.stdin"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    dest.chmod(0o755)
    return dest


def invoke_main(mod: Any, argv: list[str], *, tty_stdout: bool = False) -> tuple[int, str, str]:
    """Run helper main(argv=...) capturing stdout/stderr."""
    main = getattr(mod, "main", None)
    if main is None:
        raise unittest.SkipTest("helper has no main()")
    out: io.StringIO = io.StringIO()
    if tty_stdout:
        out.isatty = lambda: True  # type: ignore[method-assign]
    err = io.StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            main(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None else 1
    return code, out.getvalue(), err.getvalue()


def call_type_helper(
    mod: Any,
    account: str,
    compositor: str = "hyprland",
    expect_id: str = "0xabc",
    *,
    focus_stable: bool,
    focus_unavailable: bool = False,
) -> tuple[int, str, str, list[str]]:
    """Exercise cmd_type with mocked focus and exec_abs."""
    wtype_inputs: list[str] = []

    def fake_exec_abs(path, args, input=None, capture=False):
        if path == mod.WTYPE:
            wtype_inputs.append(input or "")
            return types.SimpleNamespace(returncode=0)
        return types.SimpleNamespace(returncode=1)

    backend = FakeBackend(secret="typed-secret")
    mod.BACKEND = backend

    args = argparse.Namespace(
        account=account,
        compositor=compositor,
        expect_id=expect_id,
        rest=[],
    )

    out = io.StringIO()
    err = io.StringIO()
    code = 0

    def read_focus_side_effect(comp: str):
        if focus_unavailable:
            return None
        if focus_stable:
            return {"compositor": comp, "id": expect_id}
        return {"compositor": comp, "id": "OTHER"}

    with (
        mock.patch.object(mod, "wait_for_focus", return_value=True),
        mock.patch.object(mod, "read_focus_for", side_effect=read_focus_side_effect),
        mock.patch.object(mod, "exec_abs", side_effect=fake_exec_abs),
    ):
        try:
            with redirect_stdout(out), redirect_stderr(err):
                mod.cmd_type(args)
        except SystemExit as exc:
            code = int(exc.code) if exc.code is not None else 1

    return code, out.getvalue(), err.getvalue(), wtype_inputs


@unittest.skipUnless(HELPER_PATH.is_file(), "omapass-keyring not present yet")
class TestHelperSecurity(unittest.TestCase):
    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_helper()
        for attr in ("BACKEND", "WL_COPY", "WTYPE", "HYPRCTL", "TYPE_TIMEOUT_MS", "TYPE_POLL_MS"):
            if not hasattr(cls.mod, attr):
                raise unittest.SkipTest(f"helper missing required attribute {attr}")

    def setUp(self) -> None:
        self.mod.BACKEND = None

    def test_list_never_calls_get_secret(self) -> None:
        backend = FakeBackend(
            items=[{"account": "a1", "folder": "F1", "kind": ""}],
            secret="must-not-appear",
        )

        def poison_get_secret(_account: str) -> str:
            raise AssertionError("list must not call get_secret")

        backend.get_secret = poison_get_secret  # type: ignore[method-assign]
        self.mod.BACKEND = backend

        code, stdout, _stderr = invoke_main(self.mod, ["list", "--json"])
        self.assertEqual(code, 0)
        self.assertNotIn("must-not-appear", stdout)
        data = json.loads(stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["account"], "a1")
        self.assertNotIn("secret", stdout.lower())

    def test_copy_uses_pinned_wl_copy_not_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            evil = make_evil_dir(tmp)
            recorder = make_recorder_script(tmp / "fake-wl-copy")
            pwned = tmp / "pwned"

            backend = FakeBackend(secret="clip-secret")
            self.mod.BACKEND = backend
            self.mod.WL_COPY = str(recorder)
            exec_calls: list[tuple[Any, list[str], Any, bool]] = []

            def fake_exec_abs(path, args, input=None, capture=False):
                exec_calls.append((path, list(args), input, capture))
                if path == str(recorder):
                    Path(f"{recorder}.stdin").write_text(input or "", encoding="utf-8")
                    return types.SimpleNamespace(returncode=0)
                return types.SimpleNamespace(returncode=1)

            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{evil}:{old_path}"
            try:
                with (
                    mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
                    mock.patch.object(self.mod, "spawn_clipboard_expire"),
                ):
                    code, stdout, _stderr = invoke_main(self.mod, ["copy", "--account", "acct"])
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(code, 0)
            self.assertFalse(pwned.exists(), "PATH-poisoned wl-copy must not run")
            stdin_file = Path(f"{recorder}.stdin")
            self.assertTrue(stdin_file.exists(), "pinned WL_COPY must receive stdin")
            self.assertEqual(stdin_file.read_text(encoding="utf-8"), "clip-secret")
            self.assertNotIn("clip-secret", stdout)
            wl_copy_calls = [call for call in exec_calls if call[0] == str(recorder)]
            self.assertTrue(wl_copy_calls, "copy must invoke pinned wl-copy")
            self.assertIn("--paste-once", wl_copy_calls[0][1])

    def test_type_wtypes_when_focus_stable(self) -> None:
        code, _stdout, stderr, wtype_stdin = call_type_helper(
            self.mod,
            "acct",
            expect_id="0xaaa",
            focus_stable=True,
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(wtype_stdin, ["typed-secret"])

    def test_type_aborts_when_focus_changes(self) -> None:
        code, _stdout, stderr, wtype_stdin = call_type_helper(
            self.mod,
            "acct",
            expect_id="0xaaa",
            focus_stable=False,
        )
        self.assertEqual(code, 2, stderr)
        self.assertEqual(wtype_stdin, [])
        self.assertIn("focus changed", stderr.lower())

    def test_type_aborts_when_focus_unavailable(self) -> None:
        code, _stdout, stderr, wtype_stdin = call_type_helper(
            self.mod,
            "acct",
            expect_id="0xaaa",
            focus_stable=True,
            focus_unavailable=True,
        )
        self.assertEqual(code, 2, stderr)
        self.assertEqual(wtype_stdin, [])
        self.assertIn("unavailable", stderr.lower())

    def test_type_qml_expect_id_not_resnapshot(self) -> None:
        wtype_inputs: list[str] = []

        def fake_exec_abs(path, args, input=None, capture=False):
            if path == self.mod.WTYPE:
                wtype_inputs.append(input or "")
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        backend = FakeBackend(secret="typed-secret")
        self.mod.BACKEND = backend

        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(
                self.mod,
                "read_focus_for",
                return_value={"compositor": "hyprland", "id": "0xaaa"},
            ),
            mock.patch.object(
                self.mod,
                "focus_snapshot",
                side_effect=AssertionError("focus_snapshot must not be called"),
            ),
            mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
        ):
            code, _stdout, stderr = invoke_main(
                self.mod,
                [
                    "type",
                    "--account",
                    "acct",
                    "--compositor",
                    "hyprland",
                    "--expect-id",
                    "0xaaa",
                ],
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(wtype_inputs, ["typed-secret"])

    def test_type_positional_account_cli(self) -> None:
        wtype_inputs: list[str] = []

        def fake_exec_abs(path, args, input=None, capture=False):
            if path == self.mod.WTYPE:
                wtype_inputs.append(input or "")
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        backend = FakeBackend(secret="typed-secret")
        self.mod.BACKEND = backend

        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(
                self.mod,
                "read_focus_for",
                return_value={"compositor": "hyprland", "id": "0xaaa"},
            ),
            mock.patch.object(
                self.mod,
                "focus_snapshot",
                return_value={"compositor": "hyprland", "id": "0xaaa"},
            ),
            mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
        ):
            code, _stdout, stderr = invoke_main(self.mod, ["type", "--", "acct"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(wtype_inputs, ["typed-secret"])

    def test_clipboard_expire_clears_only_if_unchanged(self) -> None:
        if not hasattr(self.mod, "cmd_clipboard_expire"):
            self.skipTest("clipboard-expire not implemented yet")
        if not hasattr(self.mod, "WL_PASTE"):
            self.skipTest("helper missing WL_PASTE")

        secret = "clip-secret"
        cases = (
            ("matches", secret, True),
            ("differs", "other-content", False),
        )
        for label, paste_text, should_clear in cases:
            with self.subTest(case=label):
                exec_calls: list[tuple[Any, list[str], Any, bool]] = []

                def fake_exec_abs(path, args, input=None, capture=False):
                    exec_calls.append((path, list(args), input, capture))
                    if path == self.mod.WL_PASTE:
                        return types.SimpleNamespace(returncode=0, stdout=paste_text)
                    return types.SimpleNamespace(returncode=0)

                with (
                    mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
                    mock.patch.object(self.mod.time, "sleep"),
                    mock.patch("sys.stdin", io.StringIO(secret)),
                ):
                    try:
                        self.mod.cmd_clipboard_expire(argparse.Namespace(delay=0))
                    except SystemExit as exc:
                        self.fail(f"clipboard-expire raised unexpectedly: {exc}")

                clear_calls = [
                    call
                    for call in exec_calls
                    if call[0] == self.mod.WL_COPY and "--clear" in call[1]
                ]
                if should_clear:
                    self.assertEqual(len(clear_calls), 1)
                else:
                    self.assertEqual(clear_calls, [])

    def test_get_refuses_tty_without_yes(self) -> None:
        backend = FakeBackend(secret="must-not-print")
        self.mod.BACKEND = backend
        code, stdout, stderr = invoke_main(
            self.mod,
            ["get", "--account", "acct"],
            tty_stdout=True,
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertNotIn("must-not-print", stdout + stderr)
        self.assertIn("terminal", stderr.lower())

    def test_get_allows_pipe_without_yes(self) -> None:
        backend = FakeBackend(secret="piped-secret")
        self.mod.BACKEND = backend
        code, stdout, stderr = invoke_main(self.mod, ["get", "--account", "acct"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "piped-secret")
        self.assertEqual(stderr, "")

    def test_generate_nostr_without_replace_fails_if_exists(self) -> None:
        backend = FakeBackend(
            items=[{"account": "nostr:exists", "folder": "Nostr", "kind": "nostr"}],
            secret="",
        )
        self.mod.BACKEND = backend
        code, stdout, stderr = invoke_main(
            self.mod,
            ["generate-nostr", "--account", "nostr:exists", "--folder", "Nostr"],
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("already exists", stderr.lower())

    def test_generate_nostr_stdout_has_no_nsec(self) -> None:
        backend = FakeBackend(items=[], secret="")
        self.mod.BACKEND = backend

        fake_nsec = "nsec1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
        with mock.patch.object(
            self.mod,
            "generate_nsec_material",
            return_value=(fake_nsec, "npub1example"),
        ):
            code, stdout, _stderr = invoke_main(
                self.mod,
                ["generate-nostr", "--account", "nostr:test", "--folder", "Nostr"],
            )

        self.assertEqual(code, 0)
        self.assertNotIn(fake_nsec, stdout)
        payload = json.loads(stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("account"), "nostr:test")
    def test_spawn_clipboard_expire_secret_on_stdin_not_argv(self) -> None:
        fake_stdin = mock.MagicMock()
        popen_calls: list[dict[str, Any]] = []

        def fake_popen(cmd: list[str], **kwargs: Any) -> mock.MagicMock:
            popen_calls.append({"cmd": cmd, "kwargs": kwargs})
            return mock.MagicMock(stdin=fake_stdin)

        with mock.patch.object(self.mod.subprocess, "Popen", side_effect=fake_popen):
            self.mod.spawn_clipboard_expire("clip-secret")

        self.assertEqual(len(popen_calls), 1)
        argv = popen_calls[0]["cmd"]
        self.assertEqual(argv[0], "/usr/bin/python3")
        self.assertIn("clipboard-expire", argv)
        self.assertIn("--delay", argv)
        self.assertNotIn("clip-secret", " ".join(str(arg) for arg in argv))
        fake_stdin.write.assert_called_once_with("clip-secret")
        fake_stdin.close.assert_called_once_with()



@unittest.skipUnless(HELPER_PATH.is_file(), "omapass-keyring not present yet")
class TestHelperPathPinningCli(unittest.TestCase):
    """PATH poison via real /usr/bin/python3 subprocess (no GI required)."""

    def test_list_subprocess_ignores_path_poison(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            evil = make_evil_dir(tmp)
            env = os.environ.copy()
            env["PATH"] = f"{evil}:{env.get('PATH', '')}"

            proc = subprocess.run(
                [PINNED_PYTHON, str(HELPER_PATH), "list", "--json"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("pwned", proc.stdout)


if __name__ == "__main__":
    unittest.main()
