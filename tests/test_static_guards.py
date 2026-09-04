"""Static guards: forbid unsafe patterns in QML, wrapper, and helper."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QML_FILES = (
    ROOT / "Vault.qml",
    ROOT / "Panel.qml",
    ROOT / "BarWidget.qml",
)

GUARDED_TEXT_FILES = QML_FILES + (
    ROOT / "bin" / "omapass",
    ROOT / "bin" / "omapass-keyring",
)

BARE_QML_COMMAND = re.compile(
    r"""command:\s*\[\s*"(?:secret-tool|wl-copy|wtype|python3)"\b"""
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_function_body(text: str, name: str) -> str:
    marker = f"function {name}("
    start = text.find(marker)
    if start < 0:
        return ""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for idx in range(brace, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return ""


class TestStaticGuards(unittest.TestCase):
    def test_no_secret_tool_search(self) -> None:
        for path in GUARDED_TEXT_FILES:
            with self.subTest(path=path.name):
                if not path.exists():
                    self.skipTest(f"{path} missing")
                text = read_text(path)
                self.assertNotIn(
                    "secret-tool search",
                    text,
                    f"{path} must not call secret-tool search",
                )

    def test_qml_no_bare_external_commands(self) -> None:
        for path in QML_FILES:
            with self.subTest(path=path.name):
                if not path.exists():
                    self.skipTest(f"{path} missing")
                text = read_text(path)
                match = BARE_QML_COMMAND.search(text)
                self.assertIsNone(
                    match,
                    f"{path} uses bare external command near: {match.group(0) if match else ''}",
                )

    def test_vault_uses_pinned_python3(self) -> None:
        path = ROOT / "Vault.qml"
        if not path.exists():
            self.skipTest("Vault.qml missing")
        text = read_text(path)
        self.assertIn("/usr/bin/python3", text)

    def test_wrapper_uses_pinned_python3(self) -> None:
        path = ROOT / "bin" / "omapass"
        text = read_text(path)
        self.assertIn("/usr/bin/python3", text)
        for forbidden in ("secret-tool", "wl-copy", "wtype"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_helper_pins_path_and_avoids_shell_lookup(self) -> None:
        path = ROOT / "bin" / "omapass-keyring"
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = read_text(path)
        self.assertIn('os.environ["PATH"] = "/usr/bin:/bin"', text)
        self.assertNotIn("shutil.which", text)
        self.assertNotIn("shell=True", text)

    def test_helper_uses_libsecret_sync_apis(self) -> None:
        path = ROOT / "bin" / "omapass-keyring"
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = read_text(path)
        for required in (
            "password_lookup_sync",
            "password_store_sync",
            "password_clear_sync",
            "search_sync(None,",
        ):
            with self.subTest(fragment=required):
                self.assertIn(required, text, f"{path} must use {required}")
        forbidden = (
            re.compile(r"Secret\.password_lookup\("),
            re.compile(r"Secret\.password_store\("),
            re.compile(r"Secret\.password_clear\("),
        )
        for pattern in forbidden:
            with self.subTest(pattern=pattern.pattern):
                match = pattern.search(text)
                self.assertIsNone(
                    match,
                    f"{path} must not use async libsecret API near: {match.group(0) if match else ''}",
                )

    def test_helper_has_clipboard_expire_and_paste_once(self) -> None:
        path = ROOT / "bin" / "omapass-keyring"
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = read_text(path)
        self.assertIn("--paste-once", text)
        self.assertIn("clipboard-expire", text)

    def test_vault_generate_nostr_conditional_replace(self) -> None:
        path = ROOT / "Vault.qml"
        if not path.exists():
            self.skipTest("Vault.qml missing")
        body = extract_function_body(read_text(path), "generateNostr")
        self.assertTrue(body, "generateNostr function not found")
        helper_array = re.search(
            r'helperCmd\(\[\s*"generate-nostr"[^\]]*\]\)',
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(helper_array, "generateNostr must build helperCmd array")
        assert helper_array is not None
        self.assertNotIn('"--replace"', helper_array.group(0))
        self.assertIn("if (replace)", body)
        self.assertIn('cmd.push("--replace")', body)

    def test_panel_wipes_sensitive_state_on_popout(self) -> None:
        path = ROOT / "Panel.qml"
        if not path.exists():
            self.skipTest("Panel.qml missing")
        text = read_text(path)
        self.assertIn("function wipeSensitiveState(", text)
        self.assertIn("function closeForPopoutSwitch(", text)

    def test_wipe_sensitive_state_clears_password_fields(self) -> None:
        path = ROOT / "Panel.qml"
        if not path.exists():
            self.skipTest("Panel.qml missing")
        body = extract_function_body(read_text(path), "wipeSensitiveState")
        self.assertTrue(body, "wipeSensitiveState function not found")
        self.assertIn('addPassword = ""', body)
        self.assertIn("passwordField.text", body)

    def test_close_for_popout_switch_calls_wipe(self) -> None:
        path = ROOT / "Panel.qml"
        if not path.exists():
            self.skipTest("Panel.qml missing")
        body = extract_function_body(read_text(path), "closeForPopoutSwitch")
        self.assertTrue(body, "closeForPopoutSwitch function not found")
        self.assertIn("wipeSensitiveState()", body)

    def test_save_add_wipes_password_before_store(self) -> None:
        path = ROOT / "Panel.qml"
        if not path.exists():
            self.skipTest("Panel.qml missing")
        body = extract_function_body(read_text(path), "saveAdd")
        self.assertTrue(body, "saveAdd function not found")
        self.assertIn("var secret = addPassword", body)
        wipe_pos = body.find('addPassword = ""')
        store_pos = body.find("vault.store")
        self.assertGreater(wipe_pos, -1, "saveAdd must clear addPassword")
        self.assertGreater(store_pos, -1, "saveAdd must call vault.store")
        self.assertLess(
            wipe_pos,
            store_pos,
            "addPassword must be cleared before vault.store",
        )
        self.assertRegex(body, r"vault\.store\([^,]+,\s*[^,]+,\s*secret\b")

    def test_panel_nostr_replace_only_after_confirm(self) -> None:
        path = ROOT / "Panel.qml"
        if not path.exists():
            self.skipTest("Panel.qml missing")
        text = read_text(path)
        gen_body = extract_function_body(text, "generateNostrKey")
        self.assertTrue(gen_body, "generateNostrKey function not found")
        self.assertIn("doGenerateNostr(false)", gen_body)
        self.assertNotIn("doGenerateNostr(true)", gen_body)
        confirm_body = extract_function_body(text, "handleConfirm")
        self.assertTrue(confirm_body, "handleConfirm function not found")
        self.assertIn("doGenerateNostr(true)", confirm_body)


if __name__ == "__main__":
    unittest.main()
