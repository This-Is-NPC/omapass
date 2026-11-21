"""Panel.qml runtime tests: real Panel, real keys, stub helper.

Run with scripts/test-qml. Each test starts its own quickshell, so state
never leaks between tests. Tests assert on what the user sees (panel state,
widget state) and on which helper commands ran; the helper is a stub that
never touches a keyring.
"""
import unittest

from session import Session, in_qml_sandbox

SECRET = "dummy-secret-not-real"
FOLDERS = {"alice@example": "Work", "bob": "Home", "carol": "Home"}


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class PanelCase(unittest.TestCase):
    config = {}

    def setUp(self):
        self.s = Session(self.config)
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s.open_panel()

    # Navigation helpers, each ending on an observable state.
    def select_second_row(self):
        self.s.press("-k", "Down")
        self.s.wait_state("second row selected, list focused",
                          lambda st: st["focusSection"] == "list" and st["listIndex"] == 1)
        return self.s.state()["current"]

    def open_add_form(self):
        self.s.chord("ctrl", "n")
        self.s.wait_state("folder field focused",
                          lambda st: st["view"] == "add"
                          and any(f["placeholder"] == "Folder" and f["focus"] for f in st["fields"]))

    def focus_password(self, folder="Work", account="svc"):
        self.open_add_form()
        self.s.press(folder, "-k", "Tab", account, "-k", "Tab")
        self.s.wait_state("password field focused",
                          lambda st: any(f["placeholder"] == "Password" and f["focus"] for f in st["fields"]))

    def assert_no_helper_calls(self, *cmds):
        self.s.settle()
        self.assertEqual(self.s.helper_calls(*cmds), [])


class CopyAndType(PanelCase):
    def test_enter_on_selected_row_copies_it(self):
        account = self.select_second_row()
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("copy")],
                         [["copy", "--account=" + account, "--folder=" + FOLDERS[account]]])
        self.assertEqual(self.s.helper_calls("type"), [])

    def test_enter_in_search_copies_selected_row(self):
        account = self.s.state()["current"]
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("copy")],
                         [["copy", "--account=" + account, "--folder=" + FOLDERS[account]]])
        self.assertEqual(self.s.helper_calls("type"), [])

    def _assert_types_only(self, mod, from_list):
        account = self.select_second_row() if from_list else self.s.state()["current"]
        self.s.chord(mod, "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.s.wait_state("panel closed after typing", lambda st: not st["opened"])
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("type")],
                         [["type", "--account=" + account, "--folder=" + FOLDERS[account], "--compositor=hyprland", "--expect-id=0x1"]])
        self.assertEqual(self.s.helper_calls("copy", "copy-text"), [])

    def test_shift_enter_in_list_types_and_never_copies(self):
        self._assert_types_only("shift", True)

    def test_ctrl_enter_in_list_types_and_never_copies(self):
        self._assert_types_only("ctrl", True)

    def test_shift_enter_in_search_types_and_never_copies(self):
        self._assert_types_only("shift", False)

    def test_space_and_single_letters_never_copy_or_type(self):
        self.select_second_row()
        # Every letter except the documented keys (h j k l move, m menu,
        # u copies the account, x removes), upper and lower case, then space.
        letters = "abcdefginopqrstvwyz"
        self.s.press(letters, letters.upper(), " ", "1234567890", "j")
        self.s.wait_state("last key (j) processed", lambda st: st["listIndex"] == 2)
        self.assert_no_helper_calls("copy", "type", "copy-text", "store", "clear")
        self.assertTrue(self.s.state()["opened"])
        self.assertFalse(self.s.state()["confirmOpen"])

    def test_space_on_a_chip_filters_but_never_copies(self):
        self.s.press("-k", "Up", "-k", "Right")
        self.s.wait_state("chip cursor", lambda st: st["focusSection"] == "folders")
        self.s.press(" ")
        self.s.wait_state("a folder filter applied", lambda st: st["records"] < 3)
        self.assert_no_helper_calls("copy", "type", "copy-text")


class ConfirmDialog(PanelCase):
    def open_confirm(self):
        account = self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(self.s.state()["confirmMessage"], "Remove " + account + "?")
        return account

    def test_enter_on_the_confirm_cancels(self):
        self.open_confirm()
        self.s.press("-k", "Return")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.assert_no_helper_calls("clear")

    def test_escape_cancels_the_confirm_and_keeps_the_panel(self):
        self.open_confirm()
        self.s.press("-k", "Escape")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.assert_no_helper_calls("clear")
        self.assertTrue(self.s.state()["opened"])

    def test_confirming_removes(self):
        # Control: the dialog does remove when the user picks Remove.
        account = self.open_confirm()
        self.s.press("-k", "Tab", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.assertEqual(self.s.helper_calls("clear")[0]["argv"], ["clear", "--account=" + account, "--folder=" + FOLDERS[account]])

    def test_delete_in_the_row_menu_opens_the_confirm(self):
        account = self.select_second_row()
        self.s.press("m")
        self.s.wait_state("row menu open", lambda st: st["menuOpen"])
        self.s.press("-k", "Delete")
        st = self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(st["confirmMessage"], "Remove " + account + "?")
        self.assertFalse(st["menuOpen"])
        self.assert_no_helper_calls("clear")


class ListLook(PanelCase):
    def test_selected_row_is_unlit_while_on_the_chips(self):
        self.s.wait_state("one row lit at rest", lambda st: st["lit"] == 1)
        self.s.press("-k", "Up")
        self.s.wait_state("cursor on the chips", lambda st: st["focusSection"] == "folders")
        self.s.wait_state("no row lit on the chips", lambda st: st["lit"] == 0)
        self.s.press("-k", "Down")
        self.s.wait_state("one row lit again", lambda st: st["focusSection"] == "list" and st["lit"] == 1)


class AddForm(PanelCase):
    config = {"generated": "Gen#Pass-0123456789abcdef"}

    def password_field(self):
        return self.s.field("Password")

    def test_generated_password_is_masked_even_after_reveal(self):
        self.focus_password()
        self.s.chord("ctrl", "g")
        self.s.wait_state("password generated", lambda st: st["addPasswordGenerated"])
        field = self.password_field()
        self.assertEqual(field["text"], "Gen#Pass-0123456789abcdef")
        self.assertTrue(field["masked"])

        self.s.chord("ctrl", "e")
        self.s.wait_state("password revealed", lambda st: not self.password_field()["masked"])

        self.s.set_config({"generated": "Second#Pass-fedcba9876543210"})
        self.s.chord("ctrl", "g")
        self.s.wait_state("second password generated",
                          lambda st: self.password_field()["text"] == "Second#Pass-fedcba9876543210")
        self.assertTrue(self.password_field()["masked"])
        self.assertTrue(self.s.state()["addPasswordGenerated"])

    def test_popout_switch_wipes_the_form(self):
        self.focus_password()
        self.s.press(SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s._ipc("popoutClose")
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        st = self.s.state()
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertEqual(self.password_field()["text"], "")


class ListLoading(PanelCase):
    # About 75 KB of JSON, more than a pipe buffer holds, in few rows.
    COUNT = 150
    config = {"records": [{"account": "acct-%04d-" % i + "x" * 230, "folder": "F%d-" % (i % 3) + "y" * 200,
                           "kind": ""} for i in range(COUNT)]}

    def test_a_large_list_arrives_whole(self):
        # The exit is reported before a big output has been read; the panel
        # must wait for the output and never show a partial or empty list.
        self.s.wait_state("all records loaded", lambda st: st["loadedRecords"] == self.COUNT)
        self.assertEqual(self.s.state()["listError"], "")
        for _ in range(3):
            self.s._ipc("open")
            self.s.wait_state("reloaded in full", lambda st: st["loadedRecords"] == self.COUNT)
            self.assertEqual(self.s.state()["listError"], "")

    def test_empty_output_is_an_error_not_an_empty_keyring(self):
        self.s.wait_state("all records loaded", lambda st: st["loadedRecords"] == self.COUNT)
        self.s.set_config({"list_raw": ""})
        self.s._ipc("open")
        self.s.wait_state("list error shown", lambda st: st["listError"] != "")
        self.assertEqual(self.s.state()["loadedRecords"], self.COUNT)


class LateSaveReply(PanelCase):
    # The stub answers "already exists" (exit 4) after a delay, the reply that
    # would put the typed secret back into the form and ask to replace it.
    config = {"delay": {"store": 1.5}, "exit": {"store": 4}}

    def save_and_wait_for_store(self):
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        call = self.s.wait(lambda: self.s.helper_calls("store"), "a store call")[0]
        self.assertEqual(call["stdin"], SECRET)

    def wait_reply_handled(self):
        self.s.wait(lambda: any(c.get("event") == "exit" for c in self.s.calls()), "the helper to exit")
        self.s.settle()

    def assert_form_empty(self):
        st = self.s.state()
        self.assertFalse(st["confirmOpen"])
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertEqual(self.s.field("Password")["text"], "")

    def test_reply_after_close_does_not_restore_the_secret(self):
        self.save_and_wait_for_store()
        self.s.close_panel()
        self.wait_reply_handled()
        self.assert_form_empty()
        self.assertEqual(self.s.state()["view"], "list")
        self.assertEqual(len(self.s.helper_calls("store")), 1)

    def test_reply_for_a_cancelled_form_does_not_restore_the_secret(self):
        # Same folder and account typed again: only the form's age tells the
        # old reply from one for this form.
        self.save_and_wait_for_store()
        self.s.press("-k", "Escape")
        self.s.wait_state("back on the list", lambda st: st["view"] == "list")
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc")
        self.s.wait_state("same account typed", lambda st: self.s.field("Account or nickname")["text"] == "svc")
        self.wait_reply_handled()
        self.assert_form_empty()
        self.assertEqual(len(self.s.helper_calls("store")), 1)


class RemoveTargetsTheConfirmedRecord(PanelCase):
    config = {"records": [{"account": a, "folder": "Web", "kind": ""} for a in ("amazon", "github", "paypal")]}

    def test_remove_acts_on_the_named_record_after_the_selection_moves(self):
        self.select_second_row()
        self.assertEqual(self.s.state()["current"], "github")
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(self.s.state()["confirmMessage"], "Remove github?")
        # A list refresh behind the dialog moves the selection to another row.
        # github is gone, so the selection falls back to the first row. (A
        # summon no longer refreshes under a dialog, so refresh directly.)
        self.s.set_config({"records": [{"account": a, "folder": "Web", "kind": ""} for a in ("paypal", "zeta")]})
        self.s._ipc("refreshNow")
        self.s.wait_state("selection moved behind the dialog",
                          lambda st: st["records"] == 2 and st["current"] == "paypal" and st["confirmOpen"])
        remove = [b for b in self.s.buttons() if b["label"] == "Remove"][0]
        self.s.pointer().move(remove["x"] + remove["w"] / 2, remove["y"] + remove["h"] / 2)
        # Qt must have seen the pointer enter the button before the click.
        self.s.wait_state("pointer over Remove", lambda st: "Remove" in st["pointerOver"])
        self.s.pointer().click()
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.assertEqual([c["argv"] for c in self.s.helper_calls("clear")], [["clear", "--account=github", "--folder=Web"]])


class DisplayOrder(PanelCase):
    # The helper sorts by account; the "All" view shows folder cards, so the
    # screen order is alice, carol (Home), bob (Work).
    config = {"records": [{"account": "alice", "folder": "Home", "kind": ""},
                          {"account": "bob", "folder": "Work", "kind": ""},
                          {"account": "carol", "folder": "Home", "kind": ""}]}

    def test_arrow_keys_follow_the_screen_order(self):
        shown = [r["account"] for r in sorted(self.s.rows(), key=lambda r: r["y"])]
        self.assertEqual(shown, ["alice", "carol", "bob"])
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        # Down from the search field already lands on the second row.
        visited = [self.s.state()["current"]]
        for _ in range(2):
            before = self.s.state()["listIndex"]
            self.s.press("-k", "Down")
            self.s.wait_state("cursor moved", lambda st: st["listIndex"] != before)
            visited.append(self.s.state()["current"])
        self.assertEqual(visited, shown[1:] + shown[:1])
        self.s.press("-k", "Down")
        self.s.wait_state("cursor on the second row", lambda st: st["current"] == shown[1])
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual(self.s.helper_calls("type")[0]["argv"][:2], ["type", "--account=carol"])


class LateGenerateReply(PanelCase):
    # The reply to "generate password" arrives after a save started. It
    # must not replace the password the form is asking to replace.
    config = {"delay": {"generate-password": 1.0}, "exit": {"store": 4},
              "generated": "Gen#Pass-0123456789abcdef"}

    def test_a_reply_for_an_older_form_state_is_ignored(self):
        self.focus_password()
        self.s.press(SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s.chord("ctrl", "g")
        self.s.wait(lambda: self.s.helper_calls("generate-password"), "a generate call")
        self.s.press("-k", "Return")
        self.s.wait_state("replace confirm", lambda st: st["confirmOpen"])
        self.s.wait(lambda: any(c.get("event") == "exit" and c["cmd"] == "generate-password"
                                for c in self.s.calls()), "the generate reply")
        self.s.settle()
        st = self.s.state()
        self.assertEqual(st["addPasswordLength"], len(SECRET))
        self.assertFalse(st["addPasswordGenerated"])
        self.assertEqual(self.s.field("Password")["text"], SECRET)


COPY_TYPE = ("copy", "type", "copy-text")


class ModalBlocksSecrets(PanelCase):
    """While the Remove dialog or the row menu is open, no path may copy or
    type a secret. Each guard has its own test: focusSearch() puts the focus
    in the search field and act() calls an entry point directly, so one guard
    cannot hide a missing one."""

    def open_confirm(self):
        self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])

    def open_menu(self):
        self.select_second_row()
        self.s.press("m")
        self.s.wait_state("row menu open", lambda st: st["menuOpen"])

    def assert_still_modal(self, key):
        st = self.s.state()
        self.assertTrue(st[key])
        self.assertFalse(any(f["placeholder"] == "Search" and f["focus"] for f in st["fields"]),
                         "a second open() moved the focus behind the modal")

    def test_summon_keeps_the_confirm_and_its_focus(self):
        self.open_confirm()
        self.s.summon_again()
        self.assert_still_modal("confirmOpen")
        self.assertEqual(self.s.helper_calls("focus-snapshot")[1:], [])

    def test_summon_keeps_the_row_menu_and_its_focus(self):
        self.open_menu()
        self.s.summon_again()
        self.assert_still_modal("menuOpen")
        self.assertEqual(self.s.helper_calls("focus-snapshot")[1:], [])

    def assert_summon_then_enter_cancels(self, *keys):
        self.open_confirm()
        self.s.summon_again()
        if keys[0] == "shift":
            self.s.chord(*keys)
        else:
            self.s.press(*keys)
        self.s.wait_state("confirm cancelled", lambda st: not st["confirmOpen"])
        self.assert_no_helper_calls(*COPY_TYPE, "clear")
        self.assertTrue(self.s.state()["opened"])

    def test_enter_after_summon_with_the_confirm_cancels_it(self):
        self.assert_summon_then_enter_cancels("-k", "Return")

    def test_shift_enter_after_summon_with_the_confirm_types_nothing(self):
        # The dialog keeps the keys; the shell's catcher reports Shift+Enter
        # as a plain activate, so it presses Cancel.
        self.assert_summon_then_enter_cancels("shift", "Return")

    def test_enter_after_summon_with_the_row_menu_runs_the_menu_not_a_secret(self):
        # The menu keeps the keys, so Enter runs its first option, "Copy
        # account": the account name, never the password. (Its own Shift+Enter
        # shortcut is the menu's visible "Type password", an explicit choice.)
        self.open_menu()
        self.s.summon_again()
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy-text"), "the menu's Copy account")
        self.assert_no_helper_calls("copy", "type")

    def assert_search_keys_ignored(self, opener):
        opener()
        self.s._ipc("focusSearch")
        self.s.wait_state("search focused", lambda st: any(
            f["placeholder"] == "Search" and f["focus"] for f in st["fields"]))
        self.s.press("-k", "Return")
        self.s.chord("shift", "Return")
        self.s.chord("ctrl", "Return")
        self.s.chord("ctrl", "u")
        self.assert_no_helper_calls(*COPY_TYPE)

    def test_search_enter_is_ignored_while_the_confirm_is_open(self):
        self.assert_search_keys_ignored(self.open_confirm)

    def test_search_enter_is_ignored_while_the_row_menu_is_open(self):
        self.assert_search_keys_ignored(self.open_menu)

    def test_search_enter_with_no_matches_does_not_open_the_form_behind_a_dialog(self):
        self.open_confirm()
        self.s._ipc("focusSearch")
        self.s.wait_state("search focused", lambda st: any(
            f["placeholder"] == "Search" and f["focus"] for f in st["fields"]))
        self.s.press("zzz")
        self.s.wait_state("no rows", lambda st: st["records"] == 0)
        self.s.press("-k", "Return")
        self.s.settle()
        self.assertEqual(self.s.state()["view"], "list")

    def test_every_entry_point_refuses_while_the_confirm_is_open(self):
        self.open_confirm()
        for name in ("copySelected", "copyAccountSelected", "typeSelected",
                     "copyRecord", "copyAccount", "typeRecord"):
            with self.subTest(entry=name):
                self.s._ipc("act", name)
        self.assert_no_helper_calls(*COPY_TYPE)
        self.assertTrue(self.s.state()["opened"])

    def test_the_selected_row_entry_points_refuse_while_the_menu_is_open(self):
        self.open_menu()
        for name in ("copySelected", "copyAccountSelected", "typeSelected"):
            with self.subTest(entry=name):
                self.s._ipc("act", name)
        self.assert_no_helper_calls(*COPY_TYPE)
        self.assertTrue(self.s.state()["opened"])

    def test_control_the_entry_points_work_with_no_modal(self):
        # Without this the tests above could pass on dead entry points.
        self.select_second_row()
        self.s._ipc("act", "copySelected")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s._ipc("act", "copyAccountSelected")
        self.s.wait(lambda: self.s.helper_calls("copy-text"), "a copy-text call")
        self.s._ipc("act", "typeSelected")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class FirstListIsLoading(unittest.TestCase):
    def setUp(self):
        self.s = Session({"delay": {"list": 3}})
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s._ipc("open")
        self.s.wait_state("panel open", lambda st: st["opened"]
                          and any(f["placeholder"] == "Search" and f["active"] for f in st["fields"]))
        self.s.wait(lambda: self.s.helper_calls("list"), "the list call")

    def test_it_says_loading_not_no_logins_and_enter_does_nothing(self):
        st = self.s.wait_state("loading text", lambda st: st["emptyText"] != "")
        self.assertEqual(st["emptyText"], "Loading\u2026")
        self.assertTrue(st["loading"])
        self.s.prime_keys()
        self.s.press("-k", "Return")
        self.s.chord("shift", "Return")
        st = self.s.state()
        self.assertEqual(st["view"], "list")
        self.assertEqual(st["loadedRecords"], 0, "the list answered too early for this test")
        self.s.wait_state("rows arrived", lambda st: st["records"] == 3)
        st = self.s.state()
        self.assertFalse(st["loading"])
        self.assertEqual(st["view"], "list")
        self.assertEqual(st["emptyText"], "")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class EmptyKeyring(unittest.TestCase):
    def test_after_loading_it_says_no_logins_and_enter_opens_the_form(self):
        s = Session({"delay": {"list": 1}, "records": []})
        self.addCleanup(s.stop)
        s.start()
        s._ipc("open")
        s.wait_state("loading", lambda st: st["emptyText"] == "Loading\u2026")
        s.wait_state("loaded", lambda st: st["emptyText"] == "No logins yet")
        s.wait(lambda: any(f["placeholder"] == "Search" and f["active"] for f in s.state()["fields"]), "focus")
        s.prime_keys()
        s.press("-k", "Return")
        s.wait_state("add form", lambda st: st["view"] == "add")


if __name__ == "__main__":
    unittest.main()


REC = [
    {"account": "alice@example", "folder": "Work", "kind": ""},
    {"account": "bob", "folder": "Home", "kind": ""},
    {"account": "carol", "folder": "Home", "kind": ""},
]
EARLIER = {"account": "aaron-bank", "folder": "Work", "kind": ""}


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class SelectionSurvivesRefresh(unittest.TestCase):
    """The selected row is an item, not a position (adv5 R1).

    The reopened panel shows the cached list at once; a slower refresh then
    inserts a row before "bob" while the user has bob selected.
    """

    def setUp(self):
        self.s = Session({"records": REC})
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s.open_panel()
        self.s.close_panel()
        self.s.set_config({"records": [EARLIER] + REC, "delay": {"list": 2}})
        self.s._ipc("open")
        self.s.wait_state("cached list shown", lambda st: st["opened"] and st["records"] == 3)
        self.s.prime_keys()
        self.s.press("-k", "Down")
        self.s.wait_state("bob selected", lambda st: st["current"] == "bob" and st["focusSection"] == "list")

    def refreshed(self):
        st = self.s.wait_state("refresh arrived", lambda st: st["records"] == 4)
        self.assertEqual(st["current"], "bob", "the highlight must stay on the item the user chose")

    def test_enter_copies_the_item_that_was_selected(self):
        self.refreshed()
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("copy")],
                         [["copy", "--account=bob", "--folder=Home"]])

    def test_shift_enter_types_the_item_that_was_selected(self):
        self.refreshed()
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.s.settle()
        self.assertEqual([c["argv"][:3] for c in self.s.helper_calls("type")],
                         [["type", "--account=bob", "--folder=Home"]])
        self.assertEqual(self.s.helper_calls("copy"), [])

    def test_a_removed_item_falls_back_to_the_first_row_and_enter_follows_it(self):
        self.refreshed()
        self.s.set_config({"records": [EARLIER, REC[0], REC[2]]})
        self.s._ipc("open")
        st = self.s.wait_state("bob gone", lambda st: st["loadedRecords"] == 3 and st["records"] == 3
                               and st["current"] != "bob")
        self.assertEqual(st["listIndex"], 0)
        shown = st["current"]
        self.assertEqual(shown, "aaron-bank")
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"][:2] for c in self.s.helper_calls("copy")], [["copy", "--account=" + shown]])


DUP = [
    {"account": "dup", "folder": "Home", "kind": ""},
    {"account": "dup", "folder": "Work", "kind": ""},
    {"account": "solo", "folder": "Home", "kind": ""},
]


class DuplicateItems(PanelCase):
    """Same account and kind in two folders (adv5 R2): both rows show with a
    warning, and every action names the folder of the row it came from."""
    config = {"records": DUP}

    def select_in_folder(self, folder):
        # Screen order: the Home card (dup, solo), then the Work card (dup).
        shown = [(r["account"], r["folder"]) for r in sorted(self.s.rows(), key=lambda r: r["y"])]
        target = shown.index(("dup", folder))
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        while self.s.state()["listIndex"] != target:
            before = self.s.state()["listIndex"]
            self.s.press("-k", "Down")
            self.s.wait_state("cursor moved", lambda st: st["listIndex"] != before)

    def test_both_rows_are_shown_with_a_warning_and_the_single_one_without(self):
        rows = {(r["account"], r["folder"]): r["warn"] for r in self.s.rows()}
        self.assertEqual(rows, {("dup", "Home"): True, ("dup", "Work"): True, ("solo", "Home"): False})

    def test_remove_names_the_folder_and_sends_one_clear_for_it(self):
        self.select_in_folder("Work")
        self.s.press("x")
        st = self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(st["confirmMessage"], "Remove dup from Work?")
        self.s.press("-k", "Tab", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("clear")],
                         [["clear", "--account=dup", "--folder=Work"]])

    def test_copy_and_type_name_the_folder_of_the_row(self):
        self.select_in_folder("Work")
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("copy")],
                         [["copy", "--account=dup", "--folder=Work"]])
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual(self.s.helper_calls("type")[0]["argv"][:3], ["type", "--account=dup", "--folder=Work"])


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class LoadingNeverOpensTheForm(unittest.TestCase):
    """While the first list loads, no key opens the add form (adv5 R7)."""

    def test_escape_then_enter_and_the_add_shortcuts_do_nothing(self):
        s = Session({"delay": {"list": 10}})
        self.addCleanup(s.stop)
        s.start()
        s._ipc("open")
        s.wait_state("open", lambda st: st["opened"] and any(
            f["placeholder"] == "Search" and f["active"] for f in st["fields"]))
        s.wait(lambda: s.helper_calls("list"), "the list call")
        s.prime_keys()
        s.press("-k", "Escape")  # empty search: the key catcher takes the keys
        s.wait_state("search left", lambda st: not any(
            f["placeholder"] == "Search" and f["focus"] for f in st["fields"]))
        s.press("-k", "Return", "+", "-k", "Return")
        s.chord("ctrl", "n")
        s.press("-k", "Return")
        # No event ends "the keys do nothing" (the list call is still running,
        # so settle() would wait for it), so poll for a bounded window: the
        # form must not open at any poll while the list is still loading.
        st = s.stays(lambda st: st["view"] == "list" and st["opened"], "the list view stays open", 0.8)
        self.assertEqual(st["loadedRecords"], 0, "the list answered too early for this test")
        s.wait_state("rows arrived", lambda st: st["records"] == 3)
        self.assertEqual(s.state()["view"], "list")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class CloseDuringFocusCapture(unittest.TestCase):
    """A close while open() waits for the focus snapshot is honored (adv5 R8)."""

    def setUp(self):
        self.s = Session({"delay": {"focus-snapshot": 1.5}})
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s._ipc("open")
        self.s.wait(lambda: self.s.state()["opening"], "open() waiting for the snapshot")

    def assert_stays_closed(self):
        self.s.wait(lambda: self.s.helper_calls("focus-snapshot"), "the snapshot call")
        self.s.settle()  # the snapshot has been answered by now
        st = self.s.state()
        self.assertFalse(st["opened"])
        self.assertFalse(st["opening"])

    def test_close_request(self):
        self.s._ipc("close")
        self.assert_stays_closed()

    def test_toggle_counts_as_close_while_opening(self):
        self.s._ipc("toggle")
        self.assert_stays_closed()

    def test_a_later_open_still_works(self):
        self.s._ipc("close")
        self.assert_stays_closed()
        self.s.open_panel()
        self.assertTrue(self.s.state()["opened"])


DAMAGED = ("THE KEYRING FILE MAY BE DAMAGED: it no longer parses after this write (another app "
           "probably wrote at the same time). Do not log out or reboot. Back up the keyring file "
           "now and follow your keyring recovery guide.")


class DamagedKeyringIsNotAFlash(PanelCase):
    """Exit 6 stays on screen, in full, until dismissed, and is notified (adv5 R9)."""
    config = {"exit": {"clear": 6, "store": 6, "copy": 6}, "stderr": {"clear": DAMAGED, "store": DAMAGED, "copy": DAMAGED}}

    def assert_persistent_alert(self):
        st = self.s.wait_state("alert open", lambda st: st["confirmOpen"] and st["confirmDetail"] == DAMAGED)
        self.assertEqual(st["confirmMessage"], "Keyring may be damaged")
        # Longer than the 1.2 s a footer flash lasts.
        self.s.wait(lambda: len(self.s.notifications()) >= 1, "a notification")
        # Polled for a window, not slept: the alert must be there at every
        # poll, not only at the end. No event marks the end of a flash, so
        # the window is a bound.
        self.s.stays(lambda st: st["confirmOpen"] and st["confirmDetail"] == DAMAGED,
                     "the alert stays on screen", 1.6)
        labels = [b["label"] for b in self.s.buttons()]
        self.assertIn("Dismiss", labels)
        self.assertNotIn("Remove", labels)
        self.assertEqual(self.s.notifications()[0]["argv"][-1], "Keyring may be damaged: " + DAMAGED)
        self.s.press("-k", "Escape")
        st = self.s.wait_state("alert dismissed", lambda st: not st["confirmOpen"])
        self.assertTrue(st["opened"])
        self.assertEqual(st["confirmDetail"], "This can't be undone.")

    def test_remove(self):
        self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.s.press("-k", "Tab", "-k", "Return")
        self.assert_persistent_alert()

    def test_copy(self):
        self.s.press("-k", "Return")
        self.assert_persistent_alert()

    def test_save(self):
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        self.assert_persistent_alert()

    def test_other_failures_stay_a_footer_flash(self):
        self.s.set_config({"exit": {"copy": 1}, "stderr": {"copy": "plain failure"}})
        self.s.press("-k", "Return")
        st = self.s.wait_state("flash", lambda st: st["flash"] == "plain failure")
        self.assertFalse(st["confirmOpen"])
        self.assertEqual(self.s.notifications(), [])


class LateSaveReplyAfterEdit(PanelCase):
    """The guard's own case (adv5 R11): the account is edited while a save is
    in flight and the reply is "exists". It must not put the old password back
    or offer to replace under the edited account."""
    config = {"delay": {"store": 1.5}, "exit": {"store": 4}}

    def test_reply_for_an_edited_account_is_dropped(self):
        self.focus_password(account="svc")
        self.s.press(SECRET, "-k", "Return")
        call = self.s.wait(lambda: self.s.helper_calls("store"), "a store call")[0]
        self.assertEqual(call["stdin"], SECRET)
        # Edit Account while the save is in flight.
        self.s.press("-M", "shift", "-k", "Tab", "-m", "shift", "x")
        self.s.wait_state("account edited", lambda st: self.s.field("Account or nickname")["text"] == "svcx")
        self.s.wait(lambda: any(c.get("event") == "exit" for c in self.s.calls()), "the helper to exit")
        self.s.settle()
        st = self.s.state()
        self.assertFalse(st["confirmOpen"], "no Replace question for the edited account")
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertEqual(self.s.field("Password")["text"], "")
        self.assertEqual(len(self.s.helper_calls("store")), 1)
