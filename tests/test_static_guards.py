"""Static guards: forbid unsafe patterns in QML, wrapper, and helper."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PANEL_FILES = tuple(
    ROOT / name
    for name in (
        "AddLoginForm.qml",
        "ConfirmCard.qml",
        "FolderCard.qml",
        "FooterStrip.qml",
        "FormField.qml",
        "HyprBorder.qml",
        "LoginListView.qml",
        "LoginRow.qml",
        "MenuRow.qml",
        "Pill.qml",
        "PointerTracker.qml",
        "SolidButton.qml",
        "Panel.qml",
    )
)

QML_FILES = (ROOT / "Vault.qml", ROOT / "BarWidget.qml") + PANEL_FILES

HELPER = ROOT / "bin" / "omapass-keyring"
HELPER_FILES = (HELPER, *sorted((ROOT / "bin" / "omapass_lib").glob("*.py")))
MAX_FILE_LINES = 700

GUARDED_TEXT_FILES = QML_FILES + (
    ROOT / "bin" / "omapass",
) + HELPER_FILES

BARE_QML_COMMAND = re.compile(
    r"""command:\s*\[\s*"(?:secret-tool|wl-copy|wtype|python3|omarchy-bar)"\b"""
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def panel_text() -> str:
    """The panel's QML files as one text. Panel.qml comes last: a function
    that Panel only forwards (saveAdd) is found in its component first."""
    return "\n".join(read_text(path) for path in PANEL_FILES)


def helper_text() -> str:
    """The helper script and its omapass_lib modules as one text."""
    return "\n".join(read_text(path) for path in HELPER_FILES)


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


COMMAND_LITERAL = r"command\s*[:=]\s*\[\s*\"([^\"]*)\""


class TestStaticGuards(unittest.TestCase):
    def test_list_failure_keeps_records_and_shows_error(self) -> None:
        vault = read_text(ROOT / "Vault.qml")
        panel = panel_text()
        start = vault.index("id: listProc")
        block = vault[start : vault.index("Process {", start)]
        self.assertNotIn("root.records = []", block)
        self.assertIn("listError", vault)
        self.assertIn("vault.listError", panel)

    def test_list_error_is_plain_text_and_blocks_add(self) -> None:
        panel = panel_text()
        body = extract_function_body(panel, "openAddView")
        self.assertIn("vault.listError", body)
        self.assertLess(body.index("vault.refresh()"), body.index('view = "add"'))
        shown = 0
        for m in re.finditer(r"\bText \{", panel):
            depth, i = 0, panel.index("{", m.start())
            for j in range(i, len(panel)):
                depth += (panel[j] == "{") - (panel[j] == "}")
                if depth == 0:
                    break
            block = panel[i:j]
            if re.search(r"\btext:[^\n]*(\n[^\n]*)?listError", block) and "listError" in block.split("text:", 1)[1].split("color:")[0]:
                shown += 1
                self.assertIn("textFormat: Text.PlainText", block)
        self.assertEqual(shown, 2)
        self.assertIn("showListError", panel)

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
        path = HELPER
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = helper_text()
        self.assertIn('os.environ["PATH"] = "/usr/bin:/bin"', text)
        self.assertNotIn("shutil.which", text)
        self.assertNotIn("shell=True", text)

    def test_helper_uses_libsecret_sync_apis(self) -> None:
        path = HELPER
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = helper_text()
        for required in (
            "Item.create_sync",
            "delete_sync",
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

    def test_helper_has_clipboard_serve_not_expire(self) -> None:
        path = HELPER
        if not path.exists():
            self.skipTest("omapass-keyring missing")
        text = helper_text()
        self.assertIn("clipboard-serve", text)
        self.assertNotIn("clipboard-expire", text)

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
        text = panel_text()
        self.assertIn("function wipeSensitiveState(", text)
        self.assertIn("function closeForPopoutSwitch(", text)

    def test_wipe_sensitive_state_clears_password_fields(self) -> None:
        text = panel_text()
        body = extract_function_body(text, "wipeSensitiveState")
        self.assertTrue(body, "wipeSensitiveState function not found")
        self.assertIn('addPassword = ""', body)
        self.assertIn("addForm.clearPasswordField()", body)
        self.assertIn('passwordField.text = ""', extract_function_body(text, "clearPasswordField"))

    def test_generated_password_collector_is_destroyed_after_each_run(self) -> None:
        # A collector keeps its text until the next run and cannot be cleared,
        # so each run gets its own, destroyed once the result is handled.
        vault = read_text(ROOT / "Vault.qml")
        block = vault[vault.index("id: genPassProc"):]
        block = block[: block.index("id: genNostrProc")]
        self.assertNotIn("stdout: StdioCollector", block)
        self.assertIn("out.destroy()", block)
        self.assertIn("genPassOutput.createObject", vault)
        self.assertNotIn("SplitParser", vault)
        forget = extract_function_body(vault, "forgetSecrets")
        self.assertIn("generatePasswordDoneCallback = null", forget)

    def test_close_for_popout_switch_calls_wipe(self) -> None:
        text = panel_text()
        body = extract_function_body(text, "closeForPopoutSwitch")
        self.assertTrue(body, "closeForPopoutSwitch function not found")
        # It closes exactly like close(), which wipes; and it resets its flag.
        self.assertIn("close()", body)
        self.assertIn("wipeSensitiveState()", extract_function_body(text, "close"))
        self.assertIn("popoutSwitchClosing = false", body)

    def test_save_add_wipes_password_before_store(self) -> None:
        body = extract_function_body(panel_text(), "saveAdd")
        self.assertTrue(body, "saveAdd function not found")
        self.assertIn("var secret = panel.addPassword", body)
        wipe_pos = body.find('addPassword = ""')
        store_pos = body.find("panel.vault.store")
        self.assertGreater(wipe_pos, -1, "saveAdd must clear addPassword")
        self.assertGreater(store_pos, -1, "saveAdd must call vault.store")
        self.assertLess(
            wipe_pos,
            store_pos,
            "addPassword must be cleared before vault.store",
        )
        self.assertRegex(body, r"vault\.store\([^,]+,\s*[^,]+,\s*secret\b")

    def test_panel_nostr_replace_only_after_confirm(self) -> None:
        text = panel_text()
        gen_body = extract_function_body(text, "generateNostrKey")
        self.assertTrue(gen_body, "generateNostrKey function not found")
        self.assertIn("doGenerateNostr(false)", gen_body)
        self.assertNotIn("doGenerateNostr(true)", gen_body)
        confirm_body = extract_function_body(text, "handleConfirm")
        self.assertTrue(confirm_body, "handleConfirm function not found")
        self.assertIn("generateNostr(true)", confirm_body)
        self.assertIn("doGenerateNostr(replace)", extract_function_body(text, "generateNostr"))

    def test_panel_account_replace_only_after_confirm(self) -> None:
        text = panel_text()
        save_body = extract_function_body(text, "saveAdd")
        self.assertIn("replace === true", save_body)
        self.assertIn("exitExists", save_body)
        self.assertNotIn("saveAdd(true)", save_body)
        confirm_body = extract_function_body(text, "handleConfirm")
        self.assertIn("saveAdd(true)", confirm_body)
        gen_body = extract_function_body(text, "generateNostrKey")
        self.assertNotIn("accountExists", gen_body)

    def test_copy_reports_helper_failure(self) -> None:
        vault = read_text(ROOT / "Vault.qml")
        proc = re.search(r"id: copyProc\b.*?\n  }\n", vault, re.DOTALL)
        self.assertIsNotNone(proc, "copyProc not found")
        assert proc is not None
        self.assertIn("copyStderr.text", proc.group(0))
        self.assertIn("exitCode === 0", proc.group(0))
        body = extract_function_body(panel_text(), "copyRecord")
        self.assertRegex(body, r"vault\.copy\([^)]*function\(ok, err, code\)")
        self.assertIn("ok ?", body)
        self.assertIn("err", body)

    def test_confirm_dialog_starts_on_cancel(self) -> None:
        panel = panel_text()
        dialog = re.search(r"onOpenedChanged: \{(.*?)\n  \}", read_text(ROOT / "ConfirmCard.qml"), re.DOTALL)
        self.assertIsNotNone(dialog, "confirm dialog onOpenedChanged not found")
        assert dialog is not None
        self.assertIn("selectedIndex = 0", dialog.group(1))

    def test_closing_confirm_restores_focus(self) -> None:
        text = panel_text()
        self.assertIn("focusInput()", extract_function_body(text, "closeConfirm"))
        body = extract_function_body(text, "focusInput")
        self.assertIn("searchField.forceActiveFocus()", body)
        self.assertIn("passwordField", body)

    def test_add_view_focuses_first_field(self) -> None:
        text = panel_text()
        self.assertIn("addForm.focusFirstEmpty()", extract_function_body(text, "openAddView"))
        self.assertIn("folderField.forceActiveFocus()", extract_function_body(text, "focusFirstEmpty"))

    def test_menu_closes_before_its_action(self) -> None:
        body = extract_function_body(panel_text(), "activateMenuOption")
        self.assertLess(body.index("actionsPopup.close()"), body.index("runMenuAction("))

    def test_panel_frame_follows_hyprland_border(self) -> None:
        panel = panel_text()
        self.assertIn('"/usr/bin/hyprctl", "-j", "getoption", "general:border_size"', panel)
        self.assertIn('"/usr/bin/hyprctl", "-j", "getoption", "general:col.active_border"', panel)
        self.assertIn("borderSpec: root.frameBorderSpec", panel)
        # Rounding comes from Style.cornerRadius (Hyprland decoration:rounding).
        self.assertNotRegex(panel, r"radius:\s*\d")

    def test_confirm_dialog_keys_match_the_shell(self) -> None:
        body = extract_function_body(panel_text(), "handleKey")
        for key in ("Qt.Key_Escape", "Qt.Key_Tab", "Qt.Key_Return"):
            self.assertIn(key, body)
        self.assertIn("dialog.selectedIndex === 0) dialog.canceled()", body)

    def test_row_is_not_lit_while_cursor_is_on_folders(self) -> None:
        panel = panel_text()
        self.assertIn(
            'readonly property bool selected: rowIndex === row.panel.listIndex && row.panel.focusSection !== "folders"',
            panel,
        )

    def test_no_single_key_copies_or_types_a_secret(self) -> None:
        panel = panel_text()
        text_key = re.search(r"onTextKey: function\(t\) \{(.*?)\n      \}", panel, re.DOTALL)
        self.assertIsNotNone(text_key, "onTextKey not found")
        assert text_key is not None
        self.assertNotIn("copySelected", text_key.group(1))
        self.assertNotIn("typeSelected", text_key.group(1))
        text_keys = extract_function_body(panel, "handleTextKey")
        self.assertTrue(text_keys, "handleTextKey not found")
        self.assertNotIn("copySelected", text_keys)
        self.assertNotIn("typeSelected", text_keys)
        activate = re.search(r"onActivateRequested: \{(.*?)\n      \}", panel, re.DOTALL)
        assert activate is not None
        # Space emits activateRequested too; only Return may copy.
        self.assertIn('root.focusSection === "list" && byReturn', activate.group(1))
        self.assertIn("onReturnRequested: root.activateByReturn = true", panel)

    def test_generated_password_is_masked_even_if_revealed(self) -> None:
        body = extract_function_body(panel_text(), "generateAddPassword")
        self.assertIn("addPasswordVisible = false", body)

    def test_late_helper_replies_cannot_restore_a_secret(self) -> None:
        panel = panel_text()
        self.assertIn("formToken++", extract_function_body(panel, "wipeSensitiveState"))
        save = extract_function_body(panel, "saveAdd")
        self.assertIn("var token = ++panel.formToken", save)
        self.assertIn("token === panel.formToken", save)
        self.assertIn("panel.addAccount === account\n        && panel.addFolder === folder", save)
        gen = extract_function_body(panel, "generateAddPassword")
        self.assertIn("token !== panel.formToken", gen)

    def test_modified_enter_types_and_never_copies(self) -> None:
        panel = panel_text()
        self.assertIn("(event.modifiers & (Qt.ShiftModifier | Qt.ControlModifier))", panel)
        self.assertIn("root.modifiedReturn = true", panel)
        # The flag is set only where a plain Enter would copy (N43) and reset on open.
        self.assertIn('if (root.view === "list" && root.focusSection === "list" && !root.confirmOpen) {\n            root.modifiedReturn = true', panel)
        self.assertIn("modifiedReturn = false", extract_function_body(panel, "open"))
        activate = re.search(r"onActivateRequested: \{(.*?)\n      \}", panel, re.DOTALL)
        assert activate is not None
        body = activate.group(1)
        # The copy is deferred and skipped for a Shift/Ctrl+Enter.
        self.assertIn("Qt.callLater", body)
        self.assertLess(body.index("if (root.modifiedReturn)"), body.index("root.copySelected(chosen)"))

    def test_late_replies_check_password_kind_and_nostr(self) -> None:
        panel = panel_text()
        save = extract_function_body(panel, "saveAdd")
        self.assertIn('panel.addKind === "account"', save)
        self.assertIn('panel.addPassword === ""', save)
        nostr = extract_function_body(panel, "doGenerateNostr")
        self.assertIn("var token = ++panel.formToken", nostr)
        self.assertIn('panel.addKind === "nostr"', nostr)

    def test_all_folders_sentinel_cannot_match_a_real_folder(self) -> None:
        panel = panel_text()
        self.assertNotIn('"all"', panel)
        self.assertIn('var ALL_FOLDERS = "\\u0001all"', read_text(ROOT / "Model.js"))

    def test_vault_store_passes_replace_only_when_asked(self) -> None:
        body = extract_function_body(read_text(ROOT / "Vault.qml"), "store")
        self.assertIn("if (replace)", body)
        self.assertIn('cmd.push("--replace")', body)


    def test_qml_commands_are_absolute(self) -> None:
        for path in QML_FILES:
            with self.subTest(path=path.name):
                text = read_text(path)
                for match in re.finditer(COMMAND_LITERAL, text):
                    self.assertTrue(
                        match.group(1).startswith("/"),
                        f"{path.name} runs non-absolute command {match.group(1)!r}",
                    )

    def test_reopening_panel_cancels_autotype(self) -> None:
        vault = read_text(ROOT / "Vault.qml")
        cancel = extract_function_body(vault, "cancelType")
        self.assertIn("typeProc.running = false", cancel)
        self.assertIn("typeDoneCallback = null", cancel)
        panel = panel_text()
        self.assertIn("vault.cancelType()", extract_function_body(panel, "open"))

    def test_command_guard_matches_binding_and_assignment(self) -> None:
        for snippet in ('command: ["ls"]', 'x.command = ["ls"]'):
            self.assertIsNotNone(re.search(COMMAND_LITERAL, snippet), snippet)

    def test_panel_text_shows_plain_text_only(self) -> None:
        text = panel_text()
        untrusted = ("row.record", "panel.addError", "copyFlashText")
        checked = 0
        for match in re.finditer(r"\n\s*Text\s*\{", text):
            start = match.end()
            depth, idx = 1, start
            while depth and idx < len(text):
                depth += {"{": 1, "}": -1}.get(text[idx], 0)
                idx += 1
            block = text[start:idx]
            if any(token in block for token in untrusted):
                checked += 1
                self.assertIn("textFormat: Text.PlainText", block, block.strip()[:80])
        self.assertGreaterEqual(checked, 3)

    def test_panel_height_ignores_toast_and_menu(self) -> None:
        panel = panel_text()
        self.assertNotIn("toastSpace", panel)
        self.assertNotIn("menuSpace", panel)
        height = re.search(r"desiredContentHeight:(.*?)\n  readonly", panel, re.DOTALL)
        assert height is not None
        self.assertIn("footerReserve", height.group(1))
        self.assertNotIn("toast", height.group(1).lower())
        self.assertNotIn("actionsMenuOpen", height.group(1))

    def test_list_height_is_capped_by_max_list_body_height(self) -> None:
        panel = panel_text()
        self.assertIn("Math.min(listView.listContentHeight, listBudget)", panel)
        self.assertRegex(panel, r"listBudget: maxListBodyHeight")

    def test_all_view_budget_adds_up_to_three_card_headers(self) -> None:
        panel = panel_text()
        budget = re.search(r"readonly property int listBudget:(.*?)\n\n", panel, re.DOTALL)
        assert budget is not None
        self.assertIn('folderFilter === Model.ALL_FOLDERS', budget.group(1))
        self.assertIn("Math.min(groups.length, 3) * (headerHeight + Style.space(14))", budget.group(1))

    def test_footer_is_fixed_and_shows_hints_or_status(self) -> None:
        panel = panel_text()
        body = read_text(ROOT / "FooterStrip.qml")
        self.assertIn("height: footer.panel.footerHeight", body)
        self.assertIn("anchors.bottom: parent.bottom", body)
        self.assertIn("visible: !footer.panel.toastVisible", body)
        self.assertIn("visible: footer.panel.toastVisible", body)
        self.assertIn("footer.panel.urgentColor", body)
        self.assertIn("footerHeight: Style.space(26)", panel)
        self.assertIn("anchors.bottomMargin: list.panel.footerReserve", panel)

    def test_actions_menu_opens_inside_the_panel(self) -> None:
        panel = panel_text()
        body = extract_function_body(panel, "placeActionsMenu")
        self.assertIn("row.listView.height", body)
        self.assertIn("top - h - gap", body)
        self.assertLess(
            extract_function_body(panel, "openActionsMenu").index("placeActionsMenu()"),
            extract_function_body(panel, "openActionsMenu").index("actionsPopup.open()"),
        )

    def test_menu_rows_show_shortcuts_and_remove_is_separated(self) -> None:
        panel = panel_text()
        for hint in ('hint: "u"', 'hint: "\u21e7\u21b5"', 'hint: "Del"'):
            self.assertIn(hint, panel)
        self.assertIn('divider: modelData.id === "remove"', panel)
        self.assertIn("menuRow.danger ? menuRow.panel.urgentColor", panel)

    def test_nostr_rows_have_their_own_labels(self) -> None:
        panel = panel_text()
        self.assertIn('Model.isNostr(record) ? "Copied key" : "Copied password"', panel)
        self.assertIn('row.nostr ? "Copy key" : "Copy password"', panel)
        self.assertIn('nostr ? "Type key" : "Type password"', panel)
        self.assertIn('text: "nsec"', panel)
        self.assertIn('"\U000f0306"', panel)

    def test_copy_feedback_keeps_no_secret(self) -> None:
        panel = panel_text()
        body = extract_function_body(panel, "flashCopied")
        self.assertIn("record.account", body)
        self.assertNotIn("secret", body.lower())
        self.assertNotIn("password", body.lower())
        self.assertIn("lastCopiedAccount", panel)
        self.assertIn('lastCopiedAccount = ""', panel)

    def test_folder_chips_scroll_sideways(self) -> None:
        panel = panel_text()
        flick = re.search(r"Flickable \{\n\s+id: folderFlick(.*?)Row \{\n\s+id: folderRow", panel, re.DOTALL)
        assert flick is not None
        for token in ("contentWidth: folderRow.implicitWidth", "clip: true", "Flickable.HorizontalFlick", "ensureChipVisible"):
            self.assertIn(token, flick.group(1))

    def test_folder_header_hidden_when_a_folder_is_selected(self) -> None:
        panel = panel_text()
        self.assertIn("property bool showHeader: true", panel)
        self.assertIn("visible: card.showHeader", panel)
        self.assertRegex(panel, r"showHeader: false\n\s+topPadding: Style\.space\(4\)")

    def test_destructive_and_error_colors_use_urgent(self) -> None:
        panel = panel_text()
        self.assertIn("readonly property color urgentColor: Color.urgent", panel)
        self.assertNotRegex(panel, r"Qt\.rgba\(1,\s*0\.45")
        add_error = re.search(r"text: form\.panel\.addError\n\s+color: (.*)", panel)
        assert add_error is not None
        self.assertEqual(add_error.group(1).strip(), "form.panel.urgentColor")
        self.assertRegex(panel, r"danger: true\n\s+selected: dialog\.selectedIndex === 1")
        self.assertNotRegex(panel, r"primary: true\n\s+selected: dialog")
        self.assertIn("danger ? solid.panel.urgentColor : solid.panel.accentColor", panel)
        self.assertIn("Style.hoverFillFor(menuRow.panel.urgentColor, menuRow.panel.urgentColor)", panel)

    def test_empty_state_has_a_button_and_no_background_click(self) -> None:
        panel = panel_text()
        empty = re.search(r"Item \{\n\s+id: emptyState\n(.*?)\n\s+Flickable \{\n\s+id: listFlick", panel, re.DOTALL)
        assert empty is not None
        self.assertNotIn("MouseArea", empty.group(1))
        self.assertIn('label: "+ Add login"', empty.group(1))
        self.assertIn("Enter or Ctrl+N to add", empty.group(1))
        enter = extract_function_body(panel, "handleEnter")
        self.assertIn('visibleRecords.length === 0 && vault.listError === ""', enter)
        self.assertLess(enter.index("openAddView()"), enter.index("copySelected()"))
        self.assertNotIn("saveAdd", enter)
        activate = re.search(r"onActivateRequested: \{(.*?)\n      \}\n", panel, re.DOTALL)
        assert activate is not None
        self.assertIn('root.visibleRecords.length === 0 && vault.listError === ""', activate.group(1))

    def test_open_add_view_carries_context(self) -> None:
        text = panel_text()
        body = extract_function_body(text, "openAddView") + extract_function_body(text, "focusFirstEmpty")
        self.assertIn('addFolder = folderFilter !== Model.ALL_FOLDERS ? folderFilter : ""', body)
        self.assertIn('typed !== "" && visibleRecords.length === 0 ? typed : ""', body)
        self.assertIn("searchText.trim()", body)
        self.assertIn("accountField.forceActiveFocus()", body)
        self.assertIn("passwordField.forceActiveFocus()", body)
        self.assertLess(body.index("folderField.forceActiveFocus()"), body.index("accountField.forceActiveFocus()"))
        self.assertNotIn("addPassword = typed", body)
        self.assertIn('"Nostr (default)"', panel_text())

    def test_enter_moves_between_add_fields(self) -> None:
        panel = panel_text()
        folder = re.search(r"id: folderField\n(.*?)id: accountField", panel, re.DOTALL)
        account = re.search(r"id: accountField\n(.*?)id: passwordField", panel, re.DOTALL)
        password = re.search(r"id: passwordField\n(.*?)id: kindUnused|id: passwordField\n(.*?)SolidButton", panel, re.DOTALL)
        assert folder and account and password
        enter = r"Qt\.Key_Return \|\| event\.key === Qt\.Key_Enter\) \{\n\s+"
        self.assertRegex(folder.group(1), enter + r"accountField\.forceActiveFocus\(\)")
        acc = account.group(1)
        self.assertIn("passwordField.forceActiveFocus()", acc)
        self.assertIn("form.generateNostrKey()", acc[acc.index("Qt.Key_Return"):])
        self.assertRegex("".join(g or "" for g in password.groups()), enter + r"form\.saveAdd\(\)")

    def test_primary_button_is_muted_until_the_form_is_complete(self) -> None:
        panel = panel_text()
        can = re.search(r"readonly property bool canSubmitAdd:(.*?)\n  readonly", panel, re.DOTALL)
        assert can is not None
        for token in ('addKind === "nostr"', "addAccount", "addFolder", "addPassword"):
            self.assertIn(token, can.group(1))
        self.assertIn("muted: !form.panel.canSubmitAdd", panel)
        solid = read_text(ROOT / "SolidButton.qml")
        self.assertIn("opacity: muted ? 0.45 : 1", solid)
        # Muted stays clickable so the validation message can show.
        self.assertNotIn("enabled", solid)

    def test_generated_password_stays_masked_and_shows_only_its_length(self) -> None:
        panel = panel_text()
        body = extract_function_body(panel, "generateAddPassword")
        self.assertNotIn("addPasswordVisible = true", body)
        self.assertIn("addPasswordGenerated = true", body)
        hint = re.search(r'text: "\U000f012c Generated \u00b7 " \+ (.*?)\n(.*?)\n', panel)
        assert hint is not None
        self.assertEqual(hint.group(1), 'form.panel.addPassword.length + " chars"')
        self.assertIn("color: form.panel.accentColor", hint.group(2))
        self.assertIn("onTextEdited: form.panel.addPasswordGenerated = false", panel)
        self.assertIn("addPasswordGenerated = false", extract_function_body(panel, "wipeSensitiveState"))
        # openAddView resets the form through the one wipe (field text included).
        self.assertIn("wipeSensitiveState()", extract_function_body(panel, "openAddView"))

    def test_open_menu_honors_its_shortcut_hints(self) -> None:
        panel = panel_text()
        popup = re.search(r"Popup \{\n\s+id: actionsPopup(.*?)onOpenedChanged", panel, re.DOTALL)
        assert popup is not None
        keys = popup.group(1)
        for token in ("Qt.Key_Delete", '"x"', '"u"', '"U"', "Qt.ShiftModifier | Qt.ControlModifier",
                      '"remove"', '"copyAccount"', '"typePassword"'):
            self.assertIn(token, keys)
        run = re.search(r"close\(\)\n\s+row\.runMenuAction\(action\)", keys)
        assert run is not None
        self.assertLess(run.start(), keys.index("Qt.Key_Space"))
        # The panel's Shift/Ctrl+Enter handler stands down while the menu is
        # open (blocked includes actionsMenuOpen), so the popup gets the key.
        self.assertIn("&& !keyCatcher.blocked) {", panel)
        blocked = re.search(r"blocked: (.*?)\n\n", panel, re.DOTALL)
        assert blocked is not None
        self.assertIn("root.actionsMenuOpen", blocked.group(1))

    def test_row_buttons_exist_only_on_the_selected_row(self) -> None:
        panel = panel_text()
        for name in ("copyButton", "moreButton"):
            block = re.search(rf"id: {name}\n(.*?)iconText", panel, re.DOTALL)
            assert block is not None
            self.assertIn("visible: row.selected || row.actionsMenuOpen", block.group(1))
            self.assertNotIn("opacity", block.group(1))

    def test_row_name_is_not_split_with_a_spacer(self) -> None:
        panel = panel_text()
        row = read_text(ROOT / "LoginRow.qml")
        self.assertNotRegex(row, r"Item \{ Layout\.fillWidth: true \}")
        self.assertIn("id: nsecBadge", row)
        self.assertIn("Math.min(implicitWidth,", row)

    def test_menu_is_compact_and_never_covers_search(self) -> None:
        panel = panel_text()
        self.assertIn("implicitHeight: Style.space(32)", panel)
        self.assertIn("width: Style.space(190)", panel)
        body = extract_function_body(panel, "placeActionsMenu")
        self.assertIn("listArea.y", body)
        self.assertIn("row.panel.menuRoom = true", body)
        self.assertLess(body.index("below + h <= row.listView.height"), body.index("top - h - gap >= row.listView.listArea.y"))
        height = re.search(r"desiredContentHeight:(.*?)\n  readonly", panel, re.DOTALL)
        assert height is not None
        self.assertIn("menuRoom ? Style.space(140)", height.group(1))
        self.assertIn("if (!opened) row.panel.menuRoom = false", panel)

    def test_up_from_search_reaches_the_folder_chips(self) -> None:
        panel = panel_text()
        up = re.search(r"event\.key === Qt\.Key_Up\) \{(.*?)event\.accepted = true", panel, re.DOTALL)
        assert up is not None
        body = up.group(1)
        self.assertLess(body.index("panel.folderChipIds.length > 1"), body.index("panel.selectRow(-1)"))
        self.assertIn('panel.focusSection = "folders"', body)
        self.assertIn("panel.focusCatcher()", body)
        moves = extract_function_body(panel, "move")
        self.assertIn("panel.setListCursor(panel.listIndex)", moves)
        self.assertIn('panel.focusSection = "search"', moves)

    def test_mouse_and_keyboard_share_one_highlight(self) -> None:
        panel = panel_text()
        self.assertIn("hasCursor || (hoverFollows && pillHover.hovered)", panel)
        self.assertIn("selected || (!cursorDriven && solidHover.hovered)", panel)
        self.assertIn("onHovered: dialog.selectedIndex = 0", panel)
        self.assertIn("onHovered: dialog.selectedIndex = 1", panel)
        self.assertEqual(panel.count("cursorDriven: true"), 2)

    def test_confirm_dialog_wraps_a_long_unspaced_name(self) -> None:
        panel = panel_text()
        dialog = re.search(r"Item \{\n  id: dialog\n(.*?)text: dialog\.message", read_text(ROOT / "ConfirmCard.qml"), re.DOTALL)
        assert dialog is not None
        self.assertIn("wrapMode: Text.WrapAnywhere", dialog.group(1).rsplit("Text {", 1)[1])

    def test_source_files_stay_small_and_guarded(self) -> None:
        root_qml = sorted(ROOT.glob("*.qml"))
        self.assertEqual(set(root_qml), set(QML_FILES), "every root QML file must be guarded")
        for path in (*root_qml, *HELPER_FILES):
            with self.subTest(path=path.name):
                lines = len(read_text(path).splitlines())
                self.assertLessEqual(lines, MAX_FILE_LINES, f"{path} has {lines} lines")
        self.assertRegex(read_text(HELPER), r"(?m)^(?:from|import)\s+omapass_lib\b")

    def test_wrapper_does_not_use_path_commands_before_pinning(self) -> None:
        for rel in ("bin/omapass", "tests/run.sh", "scripts/test-sandbox"):
            self.assertNotRegex(read_text(ROOT / rel), r"\bdirname\b", rel)


if __name__ == "__main__":
    unittest.main()
