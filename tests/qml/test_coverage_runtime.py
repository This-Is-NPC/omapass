"""Runtime coverage for the cells the round-15 audit found untested.

Each test names the matrix cell (state x event) or gap it covers. Run with
scripts/test-qml.
"""
import unittest

from session import Session, in_qml_sandbox

SECRET = "dummy-secret-not-real"
FOLDERS = {"alice@example": "Work", "bob": "Home", "carol": "Home", "aaron": "Home"}
THREE = [{"account": "aaron", "folder": "Home", "kind": ""},
         {"account": "bob", "folder": "Home", "kind": ""},
         {"account": "carol", "folder": "Home", "kind": ""}]
MENU_LABELS = ("Copy account", "Type password", "Remove")
DIALOG_LABELS = ("Remove", "Cancel")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class CoverageCase(unittest.TestCase):
    config = {}
    auto_open = True

    def setUp(self):
        self.s = Session(self.config)
        self.addCleanup(self.s.stop)
        self.s.start()
        if self.auto_open:
            self.s.open_panel()

    def open_without_rows(self):
        """Open when the list has no rows (empty keyring or list error)."""
        self.s._ipc("open")
        self.s.wait_state("panel open, list settled", lambda st: st["opened"] and not st["loading"]
                          and any(f["placeholder"] == "Search" and f["active"] for f in st["fields"]))
        self.s.prime_keys()

    def focused(self, placeholder):
        return lambda st: any(f["placeholder"] == placeholder and f["focus"] for f in st["fields"])

    def select_second_row(self):
        self.s.press("-k", "Down")
        self.s.wait_state("second row selected", lambda st: st["focusSection"] == "list"
                          and st["listIndex"] == 1)
        return self.s.state()["current"]

    def open_menu(self):
        self.select_second_row()
        self.s.press("m")
        self.s.wait_state("row menu open", lambda st: st["menuOpen"])

    def open_confirm(self):
        self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])

    def open_add_form(self):
        self.s.chord("ctrl", "n")
        self.s.wait_state("folder field focused", lambda st: st["view"] == "add"
                          and self.focused("Folder")(st))

    def labels(self, names):
        return [b["label"] for b in self.s.buttons() if b["label"] in names]

    def copies(self):
        return [c["argv"] for c in self.s.helper_calls("copy", "copy-text")]

    def wait_copy(self):
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()

    def assert_plain_reopen(self):
        """A reopened panel shows the plain list, and Enter copies a row, not a dialog option."""
        self.s.open_panel()
        st = self.s.state()
        self.assertEqual((st["view"], st["confirmOpen"], st["menuOpen"]), ("list", False, False))
        self.assertEqual(self.labels(DIALOG_LABELS + MENU_LABELS), [])
        self.s.press("-k", "Return")
        self.wait_copy()
        self.assertEqual(len(self.s.helper_calls("copy")), 1)
        self.assertEqual(self.s.helper_calls("clear"), [])


class RebuiltRowFocus(CoverageCase):
    """E7 x S8 (WRONG): a refresh rebuilds the row that holds the menu. The
    keys must still reach the panel."""

    def test_keys_work_after_a_refresh_rebuilt_the_open_row(self):
        self.open_menu()
        self.s.set_config({"records": THREE[:2]})
        self.s._ipc("refreshNow")
        self.s.wait_state("rows rebuilt", lambda st: st["loadedRecords"] == 2 and not st["menuOpen"])
        # The refocus is deferred to the next turn. Wait so a missing one
        # cannot win a race against the keys.
        self.s.stays(lambda st: not st["menuOpen"], "menu stays closed", 0.3)
        before = self.s.state()["listIndex"]
        self.s.press("-k", "Down")
        self.s.wait_state("selection moved", lambda st: st["listIndex"] != before)
        self.s.press("-k", "Return")
        self.wait_copy()
        self.assertEqual(len(self.s.helper_calls("copy")), 1)


class SummonKeepsFormFocus(CoverageCase):
    """E1 x S10, S11 (WRONG): a summon with the add form open leaves the
    focus on the field being edited."""

    def check(self, placeholder, typed_before, typed_after):
        n = len(self.s.helper_calls("focus-snapshot"))
        self.s._ipc("open")
        self.s.wait_state("summon settled", lambda st: not st["opening"]
                          and len(self.s.helper_calls("focus-snapshot")) > n)
        # open() moves focus from a callLater. Hold the field across that turn.
        self.s.stays(self.focused(placeholder), "focus stays in " + placeholder, 0.4)
        self.s.press(typed_after)
        self.s.wait_state("typing continues in " + placeholder, typed_before)

    def test_summon_keeps_focus_in_the_password_field(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", "abc")
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == 3)
        self.check("Password", lambda st: st["addPasswordLength"] == 5, "de")
        self.assertEqual(self.s.field("Account or nickname")["text"], "svc")

    def test_summon_keeps_focus_in_the_nostr_nickname_field(self):
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("nostr form", lambda st: any(f["placeholder"] == "Nickname" for f in st["fields"]))
        self.s.press("-k", "Tab", "ni")
        self.s.wait_state("nickname typed", lambda st: self.s.field("Nickname")["text"] == "ni")
        self.check("Nickname", lambda st: self.s.field("Nickname")["text"] == "nick", "ck")


class CtrlNInTheForm(CoverageCase):
    """E12 x S10, S11 and README R4: Ctrl+N starts a fresh form from every field."""

    def fill_account(self):
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))

    def fresh(self):
        self.s.wait_state("form reset", lambda st: st["addPasswordLength"] == 0
                          and self.focused("Folder")(st))
        self.assertEqual((self.s.field("Folder")["text"], self.s.field("Account or nickname")["text"],
                          self.s.field("Password")["text"]), ("", "", ""))

    def test_ctrl_n_in_the_password_field(self):
        self.open_add_form()
        self.fill_account()
        self.s.chord("ctrl", "n")
        self.fresh()

    def test_ctrl_n_in_the_account_field(self):
        self.open_add_form()
        self.fill_account()
        self.s.press("-M", "shift", "-k", "Tab", "-m", "shift")
        self.s.wait_state("account focused", self.focused("Account or nickname"))
        self.s.chord("ctrl", "n")
        self.fresh()

    def test_ctrl_n_in_the_folder_field(self):
        self.open_add_form()
        self.fill_account()
        self.s.press("-M", "shift", "-k", "Tab", "-k", "Tab", "-m", "shift")
        self.s.wait_state("folder focused", self.focused("Folder"))
        self.s.chord("ctrl", "n")
        self.fresh()

    def test_ctrl_n_in_the_nostr_form_clears_it(self):
        """E12 x S11, Nostr segment."""
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("nostr form", lambda st: any(f["placeholder"] == "Nickname" for f in st["fields"]))
        self.s.press("-k", "Tab", "nick")
        self.s.wait_state("nickname typed", lambda st: self.s.field("Nickname")["text"] == "nick")
        # Back on the Account | Nostr segment, where Ctrl+N already reached.
        self.s.press("-M", "shift", "-k", "Tab", "-k", "Tab", "-m", "shift")
        self.s.wait_state("kind segment focused", lambda st: st["focusSection"] == "addKind")
        self.s.chord("ctrl", "n")
        self.s.wait_state("fresh account form", lambda st: any(f["placeholder"] == "Folder" for f in st["fields"])
                          and self.s.field("Account or nickname")["text"] == "")

    def test_ctrl_n_in_the_nostr_nickname_field(self):
        """E12 x S11: Ctrl+N from the nickname field starts a fresh account form."""
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("nostr form", lambda st: any(f["placeholder"] == "Nickname" for f in st["fields"]))
        self.s.press("-k", "Tab", "nick")
        self.s.wait_state("nickname focused", lambda st: self.focused("Nickname")(st)
                          and self.s.field("Nickname")["text"] == "nick")
        self.s.chord("ctrl", "n")
        self.s.wait_state("fresh account form", lambda st: self.focused("Folder")(st)
                          and self.s.field("Account or nickname")["text"] == "")


class NostrFormEscape(CoverageCase):
    """E9 x S11: Escape in the Nostr form returns to the list and clears it."""

    def test_escape_in_the_nickname_field(self):
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("nostr form", lambda st: any(f["placeholder"] == "Nickname" for f in st["fields"]))
        self.s.press("-k", "Tab", "nick")
        self.s.wait_state("nickname typed", lambda st: self.s.field("Nickname")["text"] == "nick")
        self.s.press("-k", "Escape")
        self.s.wait_state("back on the list", lambda st: st["view"] == "list" and st["opened"])
        self.open_add_form()
        self.assertEqual(self.s.field("Account or nickname")["text"], "")


class FieldToFieldEnter(CoverageCase):
    """E10 x S10: Enter moves Folder -> Account -> Password at runtime."""

    def test_enter_moves_between_the_fields(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Return")
        self.s.wait_state("account focused", self.focused("Account or nickname"))
        self.s.press("svc", "-k", "Return")
        self.s.wait_state("password focused", self.focused("Password"))
        self.assertEqual(self.s.helper_calls("store"), [])


class EnterWithASearch(CoverageCase):
    """E10, E11 x S7: Enter and Shift+Enter act on the filtered list."""

    def test_enter_copies_the_match(self):
        self.s.press("car")
        self.s.wait_state("filtered", lambda st: st["records"] == 1)
        self.s.press("-k", "Return")
        self.wait_copy()
        self.assertEqual(self.copies(), [["copy", "--account=carol", "--folder=Home"]])

    def test_shift_enter_types_the_match(self):
        self.s.press("car")
        self.s.wait_state("filtered", lambda st: st["records"] == 1)
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual([c["argv"] for c in self.s.helper_calls("type")],
                         [["type", "--account=carol", "--folder=Home", "--compositor=hyprland", "--expect-id=0x1"]])
        self.assertEqual(self.s.helper_calls("copy"), [])

    def test_no_match_opens_the_form_with_the_name(self):
        """E10 x S5."""
        self.s.press("newsite")
        self.s.wait_state("no matches", lambda st: st["records"] == 0)
        self.s.press("-k", "Return")
        self.s.wait_state("form open", lambda st: st["view"] == "add")
        self.assertEqual(self.s.field("Account or nickname")["text"], "newsite")


class NoRows(CoverageCase):
    auto_open = False

    def test_enter_with_an_empty_keyring_opens_the_form_and_types_nothing(self):
        """E11 x S5."""
        self.s.set_config({"records": []})
        self.open_without_rows()
        self.s.chord("shift", "Return")
        self.s.wait_state("form open", lambda st: st["view"] == "add")
        self.s.settle()
        self.assertEqual(self.s.helper_calls("type", "copy"), [])

    def test_enter_with_a_list_error_and_no_cache_does_nothing(self):
        """E10 x S6, no rows."""
        self.s.set_config({"exit": {"list": 1}, "stderr": {"list": "keyring locked"}})
        self.open_without_rows()
        self.s.press("-k", "Return")
        self.s.chord("shift", "Return")
        self.s.settle()
        st = self.s.state()
        self.assertEqual((st["view"], st["listError"]), ("list", "keyring locked"))
        self.assertEqual(self.s.helper_calls("copy", "type"), [])

    def test_ctrl_n_with_a_list_error_refreshes_instead(self):
        """E12 x S6."""
        self.s.set_config({"exit": {"list": 1}, "stderr": {"list": "keyring locked"}})
        self.open_without_rows()
        before = len(self.s.helper_calls("list"))
        self.s.chord("ctrl", "n")
        self.s.wait(lambda: len(self.s.helper_calls("list")) > before, "a second list call")
        self.assertEqual(self.s.state()["view"], "list")


class StaleRowsWithAnError(CoverageCase):
    """Gap 11 / E10 x S6, cached rows: Enter copies the cached row while the
    list shows an error; the helper still checks the item."""

    def test_enter_copies_the_cached_row_and_the_error_stays_shown(self):
        self.s.set_config({"exit": {"list": 1}, "stderr": {"list": "keyring locked"}})
        self.s.summon_again()
        st = self.s.wait_state("error with cached rows", lambda st: st["listError"] == "keyring locked"
                               and not st["loading"])
        self.assertEqual(st["loadedRecords"], 3)
        account = st["current"]
        self.s.press("-k", "Return")
        self.wait_copy()
        self.assertEqual(self.copies(), [["copy", "--account=" + account,
                                          "--folder=" + FOLDERS[account]]])
        self.assertEqual(self.s.state()["listError"], "keyring locked")


class SecondCopy(CoverageCase):
    config = {"delay": {"copy": 2}}

    def test_a_second_enter_is_refused_and_the_first_finishes(self):
        """E10 x S12."""
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "the first copy")
        self.s.press("-k", "Return")
        self.s.wait_state("refused", lambda st: st["flash"] == "Copy already in progress")
        self.assertEqual(len(self.s.helper_calls("copy")), 1)
        self.s.wait_state("first copy done", lambda st: st["flash"] == "Copied password")

    def test_ctrl_n_during_a_copy_opens_the_form_and_the_copy_finishes(self):
        """E12 x S12."""
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "the copy")
        self.s.chord("ctrl", "n")
        self.s.wait_state("form open", lambda st: st["view"] == "add")
        self.s.wait_state("copy done", lambda st: st["flash"] == "Copied password")

    def test_a_summon_during_a_copy_keeps_it(self):
        """E1 x S12."""
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "the copy")
        self.s.summon_again()
        self.s.wait_state("copy done", lambda st: st["flash"] == "Copied password")

    def test_a_popout_switch_during_a_copy_does_not_kill_it(self):
        """E4 x S12."""
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "the copy")
        self.s._ipc("popoutClose")
        self.s.wait_state("closed", lambda st: not st["opened"])
        self.s.settle()
        self.assertFalse([c for c in self.s.calls() if c.get("event") == "terminated"])


class CloseWithTheConfirmOpen(CoverageCase):
    """E2, E3, E4, E13 x S9 and README R6: every close path drops the dialog."""

    def check(self, close):
        self.open_confirm()
        self.assertEqual(self.labels(DIALOG_LABELS).count("Cancel"), 1)
        close()
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        st = self.s.state()
        self.assertFalse(st["confirmOpen"])
        self.assertEqual(self.labels(("Cancel",)), [])
        self.assert_plain_reopen()

    def test_close(self):
        self.check(lambda: self.s._ipc("close"))

    def test_toggle(self):
        self.check(lambda: self.s._ipc("toggle"))

    def test_popout_switch(self):
        self.check(lambda: self.s._ipc("popoutClose"))

    def test_click_outside(self):
        def click_outside():
            p = self.s.pointer()

            def clicked():
                p.move(5, 400)
                p.click()
                return not self.s.state()["opened"]
            self.s.wait(clicked, "the click outside to close the panel")
        self.check(click_outside)


class SummonKeepsState(CoverageCase):
    """E1 x S3, S5, S7, S14: a summon keeps the search text and the flash."""

    def test_search_and_flash_survive_a_summon(self):
        self.s.press("bo")
        self.s.wait_state("filtered", lambda st: st["searchText"] == "bo" and st["records"] == 1)
        self.s.press("-k", "Return")
        self.s.wait_state("flash", lambda st: st["flash"] == "Copied password")
        st = self.s.summon_again()
        self.assertEqual(st["searchText"], "bo")
        self.assertEqual(st["flash"], "Copied password")

    def test_two_summons_while_opening_take_one_snapshot(self):
        """E1 x S2."""
        self.s.close_panel()
        self.s.set_config({"delay": {"focus-snapshot": 1}})
        before = len(self.s.helper_calls("focus-snapshot"))
        self.s._ipc("open")
        self.s._ipc("open")
        self.s.wait_state("opened", lambda st: st["opened"] and not st["opening"])
        self.assertEqual(len(self.s.helper_calls("focus-snapshot")) - before, 1)


class Toggle(CoverageCase):
    """E2 x S1, S13 and E3 x S1."""

    def test_toggle_opens_a_closed_panel_and_cuts_a_running_type(self):
        self.s.set_config({"delay": {"type": 20}})
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.s.wait_state("closed after typing started", lambda st: not st["opened"])
        self.s._ipc("toggle")
        self.s.wait_state("opened again", lambda st: st["opened"])
        self.s.wait(lambda: [c for c in self.s.calls() if c.get("event") == "terminated"
                             and c["cmd"] == "type"], "the type to be terminated")

    def test_closing_twice_is_harmless(self):
        """E3 x S1: a second close runs no helper."""
        self.s.close_panel()
        self.s.settle()
        before = self.s.calls()
        self.s._ipc("close")
        self.s.settle()
        self.assertEqual(self.s.calls(), before)
        self.assertFalse(self.s.state()["opened"])
        self.s.open_panel()
        self.s.press("-k", "Return")
        self.wait_copy()


class ListChanges(CoverageCase):
    """E7 x S1, S2, S5, S10, S11."""

    def test_a_refresh_while_closed_updates_the_records(self):
        self.s.close_panel()
        self.s.set_config({"records": THREE[:1]})
        self.s._ipc("refreshNow")
        self.s.wait_state("one record loaded", lambda st: st["loadedRecords"] == 1)

    def test_rows_arrive_after_an_empty_list(self):
        self.s.close_panel()
        self.s.set_config({"records": []})
        self.s._ipc("open")
        self.s.wait_state("empty", lambda st: st["opened"] and st["emptyText"].startswith("No logins"))
        self.s.set_config({"records": THREE})
        self.s.summon_again()
        st = self.s.wait_state("rows shown", lambda st: st["records"] == 3 and st["emptyText"] == "")
        self.assertEqual(st["loadedRecords"], 3)

    def test_rows_arrive_for_a_search_with_no_matches(self):
        self.s.press("zzz")
        self.s.wait_state("no matches", lambda st: st["records"] == 0 and st["emptyText"].startswith("No matches"))
        self.s.set_config({"records": THREE + [{"account": "zzz1", "folder": "Home", "kind": ""}]})
        self.s.summon_again()
        self.s.wait_state("the new row matches", lambda st: st["records"] == 1 and st["emptyText"] == "")

    def test_a_refresh_leaves_the_form_alone(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", "abc")
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == 3)
        self.s.set_config({"records": THREE[:1]})
        self.s._ipc("refreshNow")
        self.s.wait_state("list changed", lambda st: st["loadedRecords"] == 1)
        st = self.s.state()
        self.assertEqual((st["view"], st["addPasswordLength"]), ("add", 3))
        self.assertEqual((self.s.field("Folder")["text"], self.s.field("Account or nickname")["text"]),
                         ("Work", "svc"))


class EscapeTwice(CoverageCase):
    """E9 x S12, S14: Escape twice closes with a copy running or a flash showing."""

    def test_with_a_flash(self):
        self.s.press("-k", "Return")
        self.s.wait_state("flash", lambda st: st["flash"] != "")
        self.s.press("-k", "Escape", "-k", "Escape", "-k", "Escape")
        self.s.wait_state("closed", lambda st: not st["opened"])

    def test_with_a_copy_running(self):
        self.s.set_config({"delay": {"copy": 2}})
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "the copy")
        self.s.press("-k", "Escape", "-k", "Escape")
        self.s.wait_state("closed", lambda st: not st["opened"])


class EnterAgain(CoverageCase):
    """E10 x S14: a second Enter after the flash copies again."""

    def test_second_copy_after_the_flash(self):
        self.s.press("-k", "Return")
        self.s.wait_state("flash", lambda st: st["flash"] == "Copied password")
        self.s.settle()
        self.s.press("-k", "Return")
        self.s.wait(lambda: len(self.s.helper_calls("copy")) == 2, "a second copy call")
        self.assertEqual(self.copies()[0], self.copies()[1])


class ShiftEnter(CoverageCase):
    """E11 x S8, S10."""

    def test_the_row_menu_shift_enter_types_its_row(self):
        self.open_menu()
        row = self.s.state()["current"]
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual([c["argv"][1] for c in self.s.helper_calls("type")], ["--account=" + row])
        self.assertEqual(self.s.helper_calls("copy"), [])

    def test_shift_enter_in_the_password_field_saves(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("store"), "a store call")
        self.s.settle()
        self.assertEqual(len(self.s.helper_calls("store")), 1)
        self.assertEqual(self.s.helper_calls("type"), [])
