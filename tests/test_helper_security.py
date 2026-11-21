"""Security tests for bin/omapass-keyring (unittest only, no live keyring)."""

from __future__ import annotations

import argparse
import collections
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
from pathlib import Path
from typing import Any
from unittest import mock

from tests.helper_loader import HELPER_PATH, ROOT, load_helper
from tests.sandbox_env import sandbox_only

PINNED_PYTHON = "/usr/bin/python3"


class FakeBackend:
    """Minimal keyring backend for tests; never returns real secrets in list."""

    def __init__(self, items: list[dict[str, str]] | None = None, secret: str = "test-secret") -> None:
        self.items = items or [{"account": "acct", "folder": "Fold", "kind": ""}]
        self.secret = secret
        self.get_secret_calls: list[str] = []
        self.store_calls: list[tuple[str, str, str, str]] = []
        self.clear_calls: list[str] = []
        self.folders: list[str | None] = []

    def list_items(self) -> list[dict[str, str]]:
        return list(self.items)

    def get_secret(self, account: str, kind: str = "", folder: str | None = None) -> str:
        self.get_secret_calls.append(account)
        self.folders.append(folder)
        return self.secret

    def store(
        self, account: str, folder: str, secret: str, kind: str = "", replace: bool = False
    ) -> None:
        if not replace and any(
            i.get("account") == account and i.get("kind", "") == kind for i in self.items
        ):
            print(f"already exists: {account}", file=sys.stderr)
            raise SystemExit(4)
        self.store_calls.append((account, folder, secret, kind))

    def clear(self, account: str, kind: str = "", folder: str | None = None) -> None:
        self.clear_calls.append(account)
        self.folders.append(folder)

    def exists(self, account: str, kind: str = "", folder: str | None = None) -> bool:
        self.folders.append(folder)
        return any(i.get("account") == account and i.get("kind", "") == kind for i in self.items)


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

    def fake_exec_abs(path, args, input=None, capture=False, **_kw):
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
        kind="",
        folder=None,
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
        mock.patch.object(mod, "read_layers", return_value=collections.Counter()),
        mock.patch.object(mod, "session_locked", return_value=False),
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
        # The helper refuses to copy without a tmpfs runtime dir; keep tests
        # independent of the environment they run in.
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"})
        env.start()
        self.addCleanup(env.stop)
        self.real_runtime_dir_problem = self.mod.runtime_dir_problem
        check = mock.patch.object(self.mod, "runtime_dir_problem", return_value=None)
        check.start()
        self.addCleanup(check.stop)

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

    def test_serve_uses_pinned_wl_copy_not_path(self) -> None:
        # Under $HOME: the sandbox's /tmp is noexec and the recorder really runs.
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmpdir:
            tmp = Path(tmpdir)
            evil = make_evil_dir(tmp)
            recorder = make_recorder_script(tmp / "fake-wl-copy")
            pwned = tmp / "pwned"
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{evil}:{old_path}"
            try:
                with (
                    mock.patch.object(self.mod, "WL_COPY", str(recorder)),
                    mock.patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"clip-secret"))),
                ):
                    code, stdout, stderr = invoke_main(self.mod, ["clipboard-serve"])
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(code, 0, stderr)
            self.assertEqual(stdout, "ok\n")
            self.assertFalse(pwned.exists(), "PATH-poisoned wl-copy must not run")
            stdin_file = Path(f"{recorder}.stdin")
            self.assertTrue(stdin_file.exists(), "pinned WL_COPY must receive stdin")
            self.assertEqual(stdin_file.read_text(encoding="utf-8"), "clip-secret")
            self.assertNotIn("clip-secret", stdout)

    def test_type_wtypes_when_focus_stable(self) -> None:
        code, _stdout, stderr, wtype_stdin = call_type_helper(
            self.mod,
            "acct",
            expect_id="0xaaa",
            focus_stable=True,
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual("".join(wtype_stdin), "typed-secret")
        self.assertGreater(len(wtype_stdin), 1, "secret must be typed in chunks")

    def test_type_aborts_when_focus_changes(self) -> None:
        code, _stdout, stderr, wtype_stdin = call_type_helper(
            self.mod,
            "acct",
            expect_id="0xaaa",
            focus_stable=False,
        )
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, stderr)
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
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, stderr)
        self.assertEqual(wtype_stdin, [])
        self.assertIn("unavailable", stderr.lower())

    def test_type_qml_expect_id_not_resnapshot(self) -> None:
        wtype_inputs: list[str] = []

        def fake_exec_abs(path, args, input=None, capture=False, **_kw):
            if path == self.mod.WTYPE:
                wtype_inputs.append(input or "")
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        backend = FakeBackend(secret="typed-secret")
        self.mod.BACKEND = backend

        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
            mock.patch.object(self.mod, "session_locked", return_value=False),
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
        self.assertEqual("".join(wtype_inputs), "typed-secret")

    def test_type_positional_account_cli(self) -> None:
        wtype_inputs: list[str] = []

        def fake_exec_abs(path, args, input=None, capture=False, **_kw):
            if path == self.mod.WTYPE:
                wtype_inputs.append(input or "")
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        backend = FakeBackend(secret="typed-secret")
        self.mod.BACKEND = backend

        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
            mock.patch.object(self.mod, "session_locked", return_value=False),
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
        self.assertEqual("".join(wtype_inputs), "typed-secret")

    def test_type_aborts_mid_typing_when_focus_changes(self) -> None:
        typed: list[str] = []
        focus = {"id": "0xaaa"}

        def fake_exec_abs(path, args, input=None, capture=False, **_kw):
            if path == self.mod.WTYPE:
                typed.append(input or "")
                if len(typed) == 2:  # focus moves while typing
                    focus["id"] = "OTHER"
                return types.SimpleNamespace(returncode=0)
            return types.SimpleNamespace(returncode=1)

        secret = "0123456789abcdefghij"
        self.mod.BACKEND = FakeBackend(secret=secret)
        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
            mock.patch.object(self.mod, "session_locked", return_value=False),
            mock.patch.object(
                self.mod,
                "read_focus_for",
                side_effect=lambda c: {"compositor": c, "id": focus["id"]},
            ),
            mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
        ):
            code, _out, stderr = invoke_main(
                self.mod,
                ["type", "--account", "acct", "--compositor", "hyprland", "--expect-id", "0xaaa"],
            )
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, stderr)
        self.assertIn("focus changed", stderr.lower())
        self.assertLess(len("".join(typed)), len(secret))
        self.assertLessEqual(len(typed), 2)

    def _type_with_layers(self, layer_json, secret, focus_ids=None, niri=False):
        """Run cmd_type with hyprctl/niri output served per call; return (code, err, typed)."""
        typed: list[str] = []
        layer_calls = {"n": 0}
        comp = "niri" if niri else "hyprland"

        def fake_exec_abs(path, args, input=None, capture=False, **_kw):
            if path == self.mod.WTYPE:
                typed.append(input or "")
                return types.SimpleNamespace(returncode=0)
            layer_calls["n"] += 1
            return types.SimpleNamespace(
                returncode=0, stdout=layer_json(len(typed)), stderr=""
            )

        self.mod.BACKEND = FakeBackend(secret=secret)
        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "session_locked", return_value=False),
            mock.patch.object(
                self.mod,
                "read_focus_for",
                side_effect=lambda c: {
                    "compositor": c,
                    "id": (focus_ids or (lambda n: "0xaaa"))(len(typed)),
                },
            ),
            mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
        ):
            code, _out, stderr = invoke_main(
                self.mod,
                ["type", "--account", "acct", "--compositor", comp, "--expect-id", "0xaaa"],
            )
        return code, stderr, typed

    @staticmethod
    def _hypr_layers(addresses):
        return json.dumps(
            {"eDP-1": {"levels": {"2": [{"address": a, "namespace": "x"} for a in addresses]}}}
        )

    def test_type_one_character_per_wtype_call(self) -> None:
        self.assertEqual(self.mod.TYPE_CHUNK, 1)
        code, err, typed = self._type_with_layers(
            lambda n: self._hypr_layers(["0x1"]), "ab'\"~é"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(typed, list("ab'\"~é"))

    def test_type_aborts_when_layer_opens_mid_typing(self) -> None:
        # A launcher layer appears after two characters were typed.
        code, err, typed = self._type_with_layers(
            lambda n: self._hypr_layers(["0x1"] if n < 2 else ["0x1", "0x2"]),
            "0123456789",
        )
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual(typed, ["0", "1"])
        self.assertIn("focus changed", err.lower())

    def test_type_aborts_when_a_layer_closes(self) -> None:
        # Any change of the baseline stops typing: a surface that held the
        # keyboard may have just given it to something else (A1).
        code, err, typed = self._type_with_layers(
            lambda n: self._hypr_layers(["0x1", "0x2"] if n < 2 else ["0x1"]), "abcd"
        )
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual(typed, ["a", "b"])

    def test_type_aborts_when_focus_snapshot_changes_mid_typing(self) -> None:
        code, err, typed = self._type_with_layers(
            lambda n: self._hypr_layers(["0x1"]),
            "0123456789",
            focus_ids=lambda n: "0xaaa" if n < 3 else "0xbbb",
        )
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual(typed, ["0", "1", "2"])

    def test_type_aborts_when_layers_unreadable(self) -> None:
        code, err, typed = self._type_with_layers(lambda n: "not json", "abc")
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual(typed, [])

    def test_niri_only_keyboard_layers_count(self) -> None:
        def layers(n):
            extra = [{"namespace": "launcher", "layer": "Overlay", "keyboard_interactivity": "exclusive"}]
            base = [{"namespace": "bar", "layer": "Top", "keyboard_interactivity": "none"}]
            return json.dumps(base + (extra if n >= 1 else []))

        code, err, typed = self._type_with_layers(layers, "abcd", niri=True)
        self.assertEqual(code, self.mod.EXIT_FOCUS_CHANGED, err)
        self.assertEqual(typed, ["a"])

        code, err, typed = self._type_with_layers(
            lambda n: json.dumps([{"namespace": "bar", "layer": "Top", "keyboard_interactivity": "none"}]),
            "abcd",
            niri=True,
        )
        self.assertEqual(code, 0, err)

    def test_type_chunks_reassemble_secret(self) -> None:
        typed: list[str] = []

        def fake_exec_abs(path, args, input=None, capture=False, **_kw):
            if path != self.mod.WTYPE:  # the session lock query
                return types.SimpleNamespace(returncode=1)
            typed.append(input or "")
            return types.SimpleNamespace(returncode=0)

        secret = "pä$$w0rd ünï-çødé-0123456789"
        self.mod.BACKEND = FakeBackend(secret=secret)
        with (
            mock.patch.object(self.mod, "wait_for_focus", return_value=True),
            mock.patch.object(self.mod, "read_layers", return_value=collections.Counter()),
            mock.patch.object(self.mod, "session_locked", return_value=False),
            mock.patch.object(
                self.mod, "read_focus_for", return_value={"compositor": "hyprland", "id": "0xaaa"}
            ),
            mock.patch.object(self.mod, "exec_abs", side_effect=fake_exec_abs),
        ):
            code, _out, stderr = invoke_main(
                self.mod,
                ["type", "--account", "acct", "--compositor", "hyprland", "--expect-id", "0xaaa"],
            )
        self.assertEqual(code, 0, stderr)
        self.assertEqual("".join(typed), secret)
        self.assertGreater(len(typed), 1)

    def test_show_nsec_refuses_non_tty_stdout(self) -> None:
        self.mod.BACKEND = FakeBackend(secret="nsec1secret")
        with (
            mock.patch.object(sys.stdin, "isatty", return_value=True, create=True),
            mock.patch("builtins.input", return_value="yes"),
        ):
            code, stdout, stderr = invoke_main(
                self.mod, ["nostr", "show-nsec"], tty_stdout=False
            )
        self.assertNotEqual(code, 0)
        self.assertNotIn("nsec1secret", stdout + stderr)
        self.assertEqual(self.mod.BACKEND.get_secret_calls, [])

    def test_show_nsec_prints_on_tty(self) -> None:
        self.mod.BACKEND = FakeBackend(secret="nsec1secret")
        with (
            mock.patch.object(sys.stdin, "isatty", return_value=True, create=True),
            mock.patch("builtins.input", return_value="yes"),
        ):
            code, stdout, stderr = invoke_main(
                self.mod, ["nostr", "show-nsec"], tty_stdout=True
            )
        self.assertEqual(code, 0, stderr)
        self.assertIn("nsec1secret", stdout)

    def _serve_loop(self, events, *, ttl=30.0, wl_copy_exit=None):
        """Run clipboard-serve's wait on a fake clock.

        events: (time, "exit") when wl-copy exits by itself, i.e. another
        client took the selection. Returns (end time, proc).
        """
        clock = [0.0]
        pending = list(events)
        proc = mock.MagicMock(pid=7)
        proc.poll.return_value = wl_copy_exit

        def fake_select(_r, _w, _x, timeout):
            if pending and pending[0][0] - clock[0] <= timeout:
                clock[0] = pending.pop(0)[0]
                return ([100], [], [])
            clock[0] += timeout
            return ([], [], [])

        with (
            mock.patch.object(self.mod.subprocess, "Popen", return_value=proc),
            mock.patch.object(self.mod.os, "pidfd_open", return_value=100),
            mock.patch.object(self.mod.os, "close"),
            mock.patch.object(self.mod.select, "select", side_effect=fake_select),
            mock.patch.object(self.mod.time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"s"))),
        ):
            code, out, err = invoke_main(
                self.mod, ["clipboard-serve", "--ttl", str(ttl)]
            )
        self.assertEqual((code, out), (0, "ok\n"), err)
        proc.terminate.assert_called_once_with()
        return clock[0], proc

    def test_serve_keeps_the_secret_until_the_ttl(self) -> None:
        # Pastes are not watched: nothing but the TTL ends an unreplaced copy.
        end, _proc = self._serve_loop([], ttl=12.0)
        self.assertEqual(end, 12.0)

    def test_serve_ends_when_another_copy_replaces_the_selection(self) -> None:
        end, _proc = self._serve_loop([(2.0, "exit")])
        self.assertEqual(end, 2.0)

    def test_serve_reports_failure_when_wl_copy_fails(self) -> None:
        proc = mock.MagicMock(pid=7)
        proc.poll.return_value = 1
        with (
            mock.patch.object(self.mod.subprocess, "Popen", return_value=proc),
            mock.patch.object(self.mod.os, "pidfd_open", return_value=100),
            mock.patch.object(self.mod.os, "close"),
            mock.patch.object(self.mod.select, "select", return_value=([100], [], [])),
            mock.patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(b"s"))),
        ):
            code, out, _err = invoke_main(self.mod, ["clipboard-serve"])
        self.assertEqual((code, out), (0, "fail\n"))

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
    def _serve_popen(self, secret: bytes = b"clip-secret") -> dict[str, Any]:
        """Run clipboard-serve with wl-copy mocked; returns wl-copy's Popen call."""
        calls: list[dict[str, Any]] = []

        def fake_popen(cmd, **kwargs):
            calls.append({"cmd": list(cmd), **kwargs})
            return mock.MagicMock(poll=lambda: 0, pid=1)

        with (
            mock.patch.object(self.mod.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(secret))),
        ):
            code, _out, _err = invoke_main(self.mod, ["clipboard-serve"])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_serve_wl_copy_is_sensitive_typed_and_tmpfs(self) -> None:
        call = self._serve_popen()
        cmd = call["cmd"]
        self.assertEqual(cmd[0], self.mod.WL_COPY)
        self.assertIn("--foreground", cmd)
        self.assertIn("--sensitive", cmd)
        self.assertEqual(cmd[cmd.index("--type") + 1], "text/plain")
        # Omarchy's history watcher would consume a paste-once offer.
        self.assertNotIn("--paste-once", cmd)
        self.assertEqual(call["env"].get("TMPDIR"), "/run/user/1000")
        self.assertNotIn("clip-secret", " ".join(cmd))
        self.assertNotIn("clip-secret", "".join(map(str, call["env"].values())))

    def test_serve_wl_copy_dies_with_the_helper(self) -> None:
        self.assertIs(self._serve_popen()["preexec_fn"], self.mod.die_with_parent)
        libc = mock.Mock()
        with mock.patch.object(self.mod.ctypes, "CDLL", return_value=libc):
            self.mod.die_with_parent()
        libc.prctl.assert_called_once_with(1, self.mod.signal.SIGTERM, 0, 0, 0)

    def test_copy_refuses_without_private_runtime_dir(self) -> None:
        self.mod.BACKEND = FakeBackend()
        old_xdg = os.environ.pop("XDG_RUNTIME_DIR", None)
        try:
            with (
                mock.patch.object(self.mod, "runtime_dir_problem", self.real_runtime_dir_problem),
                mock.patch.object(self.mod.subprocess, "run") as run,
            ):
                code, _out, _err = invoke_main(self.mod, ["copy", "--account", "acct"])
        finally:
            if old_xdg is not None:
                os.environ["XDG_RUNTIME_DIR"] = old_xdg
        self.assertNotEqual(code, 0)
        run.assert_not_called()

    def _spawned(self, argv: list[str], stdin: str = "", status: bytes = b"ok\n"):
        """Run a copy command with the helper spawn mocked; returns (code, err, calls, proc)."""
        calls: list[dict[str, Any]] = []
        proc = mock.MagicMock()
        proc.stdout.readline.return_value = status

        def fake_popen(cmd: list[str], **kwargs: Any) -> mock.MagicMock:
            calls.append({"cmd": cmd, "kwargs": kwargs})
            return proc

        self.mod.BACKEND = FakeBackend(secret="clip-secret")
        with (
            mock.patch.object(self.mod.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(sys, "stdin", io.StringIO(stdin)),
        ):
            code, _out, err = invoke_main(self.mod, argv)
        return code, err, calls, proc

    def test_copy_spawns_serve_with_secret_on_stdin_not_argv(self) -> None:
        for argv, stdin in ((["copy", "--account", "acct"], ""), (["copy-text"], "clip-secret")):
            with self.subTest(argv=argv):
                code, err, calls, proc = self._spawned(argv, stdin)
                self.assertEqual(code, 0, err)
                self.assertEqual(len(calls), 1)
                cmd = calls[0]["cmd"]
                self.assertEqual(cmd[:2], ["/usr/bin/python3", "-I"])
                self.assertEqual(cmd[-1], "clipboard-serve")
                self.assertNotIn("clip-secret", " ".join(cmd))
                self.assertNotIn("clip-secret", "".join(map(str, calls[0]["kwargs"]["env"].values())))
                self.assertTrue(calls[0]["kwargs"]["start_new_session"])
                proc.stdin.write.assert_called_once_with(b"clip-secret")
                proc.stdin.close.assert_called_once_with()

    def test_copy_fails_unless_serve_reports_ok(self) -> None:
        code, err, _calls, _proc = self._spawned(["copy", "--account", "acct"], status=b"")
        self.assertNotEqual(code, 0)
        self.assertIn("wl-copy failed", err)

@unittest.skipUnless(HELPER_PATH.is_file(), "omapass-keyring not present yet")
@sandbox_only
class TestHelperPathPinningCli(unittest.TestCase):
    """PATH poison via real /usr/bin/python3 subprocess; lists the sandbox keyring."""

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


class TestListKeyringErrors(unittest.TestCase):
    """An unreadable keyring must fail, not look like an empty one."""

    def _keyring(self, *, default, service_error=None):
        mod = load_helper()
        from gi.repository import GLib

        secret = types.SimpleNamespace()
        secret.SearchFlags = types.SimpleNamespace(ALL=1, LOAD_SECRETS=2, UNLOCK=4)
        secret.ServiceFlags = types.SimpleNamespace(OPEN_SESSION=1)
        secret.CollectionFlags = types.SimpleNamespace(NONE=0)
        service = types.SimpleNamespace(search_sync=lambda *a: [])

        def get_sync(*_a):
            if service_error:
                raise GLib.Error(service_error)
            return service

        secret.Service = types.SimpleNamespace(get_sync=get_sync)
        secret.Collection = types.SimpleNamespace(for_alias_sync=lambda *a: default)
        kr = mod.GiKeyring.__new__(mod.GiKeyring)
        kr._Secret = secret
        return kr

    def test_no_default_collection_is_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._keyring(default=None).list_items()
        self.assertNotEqual(ctx.exception.code, 0)

    def test_service_failure_is_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._keyring(default=object(), service_error="bus down").list_items()
        self.assertNotEqual(ctx.exception.code, 0)

    def test_empty_keyring_is_not_error(self) -> None:
        self.assertEqual(self._keyring(default=types.SimpleNamespace(search_sync=lambda *a: [])).list_items(), [])


if __name__ == "__main__":
    unittest.main()
