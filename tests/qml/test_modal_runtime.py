"""Modal, lifecycle and keyboard behaviour of the panel (round 14).

Each test names the matrix cell (state x event) or gap it covers, from
the state x event matrix of the interaction review. Run with scripts/test-qml.
"""
import os
import shutil
import time
import unittest

import session
from session import Session, in_qml_sandbox, HERE
from vptr import VPtr

SECRET = "dummy-secret-not-real"
MENU_LABELS = ("Copy account", "Type password", "Remove")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class ModalCase(unittest.TestCase):
    config = {}

    def setUp(self):
        self.s = Session(self.config)
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s.open_panel()
        self.first = self.s.state()["current"]

    def select_second_row(self):
        self.s.press("-k", "Down")
        self.s.wait_state("second row selected, list focused",
                          lambda st: st["focusSection"] == "list" and st["listIndex"] == 1)

    def open_menu(self):
        self.select_second_row()
        self.s.press("m")
        self.s.wait_state("row menu open", lambda st: st["menuOpen"])

    def menu_rows(self):
        return [b["label"] for b in self.s.buttons() if b["label"] in MENU_LABELS]

    def open_add_form(self):
        self.s.chord("ctrl", "n")
        self.s.wait_state("folder field focused",
                          lambda st: st["view"] == "add"
                          and any(f["placeholder"] == "Folder" and f["focus"] for f in st["fields"]))

    def field_focused(self, placeholder):
        return lambda st: any(f["placeholder"] == placeholder and f["focus"] for f in st["fields"])

    def assert_fresh_list(self):
        """The reopened panel shows a plain list, with the first row current."""
        st = self.s.state()
        self.assertEqual((st["view"], st["searchText"], st["menuOpen"], st["confirmOpen"]),
                         ("list", "", False, False))
        self.assertEqual(st["current"], self.first)
        self.assertEqual(self.menu_rows(), [])


class RowMenuLifecycle(ModalCase):
    """Gap 1 / matrix E2, E3, E4 x S8 (new finding 1): the row menu must not
    outlive close(), a toggle or a popout switch."""

    def check(self, ipc):
        self.open_menu()
        self.s._ipc(ipc)
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        self.assertFalse(self.s.state()["menuOpen"])
        self.assertEqual(self.menu_rows(), [], "the menu is still drawn after the panel closed")
        self.s.open_panel()
        self.assert_fresh_list()
        # Enter in the search field copies the current row, not a menu option.
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("copy", "copy-text")],
                         [["copy", "--account=alice@example", "--folder=Work"]])

    def test_close(self):
        self.check("close")

    def test_toggle(self):
        self.check("toggle")

    def test_popout_switch(self):
        self.check("popoutClose")


class PopoutSwitch(ModalCase):
    """Gap 7 / matrix E4: a popout switch closes like close(), and
    popoutSwitchClosing does not stay set."""

    def test_the_flag_is_reset_after_the_switch(self):
        self.s._ipc("popoutClose")
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        self.s.wait_state("flag reset", lambda st: not st["popoutSwitchClosing"])

    def test_reopen_shows_a_fresh_list(self):
        self.s.press("c")
        self.s.wait_state("search typed", lambda st: st["searchText"] == "c")
        self.s.press("-k", "Down")
        self.s.wait_state("row selected", lambda st: st["focusSection"] == "list")
        self.s._ipc("popoutClose")
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        self.s.open_panel()
        self.assert_fresh_list()


class AddFormKeys(ModalCase):
    """Gap 5 / matrix E12 x S8, S9, S10: Ctrl+N is refused under a dialog or
    the row menu, and never leaves the old password in the field."""

    def test_ctrl_n_is_refused_under_the_confirm(self):
        self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.s.chord("ctrl", "n")
        self.s.press("-k", "Escape")  # processed after Ctrl+N: the same key stream
        self.s.wait_state("confirm cancelled", lambda st: not st["confirmOpen"])
        self.assertEqual(self.s.state()["view"], "list")

    def test_ctrl_n_is_refused_under_the_row_menu(self):
        self.open_menu()
        self.s.chord("ctrl", "n")
        self.s.press("-k", "Escape")
        self.s.wait_state("menu closed", lambda st: not st["menuOpen"])
        self.assertEqual(self.s.state()["view"], "list")

    def test_the_entry_point_itself_refuses_under_a_modal(self):
        # Every key path is blocked above; the function guards on its own too.
        self.select_second_row()
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.s._ipc("act", "openAddView")
        self.s.press("-k", "Escape")
        self.s.wait_state("confirm cancelled", lambda st: not st["confirmOpen"])
        self.assertEqual(self.s.state()["view"], "list")
        self.s.close_panel()
        self.s.open_panel()
        self.open_menu()
        self.s._ipc("act", "openAddView")
        self.s.press("-k", "Escape")
        self.s.wait_state("menu closed", lambda st: not st["menuOpen"])
        self.assertEqual(self.s.state()["view"], "list")

    def test_ctrl_n_from_the_form_does_not_keep_the_password(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        # Back to the Password / Nostr segment, where Ctrl+N reaches the panel.
        self.s.press("-M", "shift", "-k", "Tab", "-k", "Tab", "-k", "Tab", "-m", "shift")
        self.s.wait_state("kind segment focused", lambda st: st["focusSection"] == "addKind")
        self.s.chord("ctrl", "n")
        self.s.wait_state("form reset", lambda st: st["addPasswordLength"] == 0)
        self.assertEqual(self.s.field("Password")["text"], "")


class SummonKeepsTheModal(ModalCase):
    """Gap 3 and A3 / matrix E1 x S8: a summon takes the keyboard back, and
    a list that changed does not kill the open menu."""

    def test_summon_primes_the_keyboard_again(self):
        self.s.wait_state("primed", lambda st: st["primed"])
        before = self.s.state()["primeDrops"]
        self.s.summon_again()
        self.s.wait_state("keyboard primed again", lambda st: st["primeDrops"] == before + 1)
        self.s.wait_state("primed", lambda st: st["primed"])

    def test_summon_with_a_modal_primes_too_and_keeps_it(self):
        self.open_menu()
        self.s.wait_state("primed", lambda st: st["primed"])
        before = self.s.state()["primeDrops"]
        self.s.summon_again()
        self.s.wait_state("keyboard primed again", lambda st: st["primeDrops"] == before + 1)
        self.assertTrue(self.s.state()["menuOpen"])

    def test_a_changed_list_does_not_kill_the_row_menu(self):
        self.open_menu()
        self.s.set_config({"records": [{"account": "aaron", "folder": "Home", "kind": ""},
                                       {"account": "bob", "folder": "Home", "kind": ""},
                                       {"account": "carol", "folder": "Home", "kind": ""}]})
        listed = len(self.s.helper_calls("list"))
        self.s.summon_again()
        self.assertEqual(len(self.s.helper_calls("list")), listed, "refreshed under the open menu")
        self.assertTrue(self.s.state()["menuOpen"])
        self.assertEqual(sorted(self.menu_rows()), sorted(MENU_LABELS))
        # Closing the menu runs the refresh that was held back.
        self.s.press("-k", "Escape")
        self.s.wait_state("menu closed", lambda st: not st["menuOpen"])
        self.s.wait_state("new list shown", lambda st: st["loadedRecords"] == 3
                          and len(self.s.helper_calls("list")) > listed)
        self.assertFalse(self.s.state()["menuOpen"])

    def test_the_menu_flag_follows_a_rebuilt_row(self):
        # A refresh that is not a summon (a save elsewhere) may still rebuild
        # the rows under an open menu: the flag must not stay set.
        self.open_menu()
        self.s.set_config({"records": [{"account": "aaron", "folder": "Home", "kind": ""}]})
        self.s._ipc("refreshNow")
        self.s.wait_state("rows rebuilt", lambda st: st["loadedRecords"] == 1)
        self.assertFalse(self.s.state()["menuOpen"])


class PointerOutside(ModalCase):
    """Gap 7 / matrix E13: a click outside the card closes the panel and wipes
    the form and the menu."""

    def click_outside(self):
        # A click before the compositor has put the pointer on the panel is
        # lost and harmless, so click again until the panel reports closed.
        p = self.s.pointer()

        def clicked():
            p.move(5, 400)
            p.click()
            return not self.s.state()["opened"]
        self.s.wait(clicked, "the click outside to close the panel")

    def test_click_outside_wipes_the_form(self):
        self.open_add_form()
        self.s.press("Work", "-k", "Tab", "svc", "-k", "Tab", SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.click_outside()
        st = self.s.state()
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertEqual(self.s.field("Password")["text"], "")
        self.s.open_panel()
        self.assert_fresh_list()

    def test_click_outside_closes_the_row_menu(self):
        self.open_menu()
        self.click_outside()
        self.assertFalse(self.s.state()["menuOpen"])
        self.assertEqual(self.menu_rows(), [])
        self.s.open_panel()
        self.assert_fresh_list()


class EscapeKey(ModalCase):
    """Matrix E9 x S4, S7: Escape clears the search, then closes."""

    def test_escape_clears_the_search_then_closes(self):
        self.s.press("bo")
        self.s.wait_state("search typed", lambda st: st["searchText"] == "bo")
        self.s.press("-k", "Escape")
        self.s.wait_state("search cleared", lambda st: st["searchText"] == "")
        self.assertTrue(self.s.state()["opened"])
        self.s.press("-k", "Escape")  # leaves the empty search field
        self.s.wait_state("search field left", lambda st: not any(
            f["placeholder"] == "Search" and f["focus"] for f in st["fields"]))
        self.assertTrue(self.s.state()["opened"])
        self.s.press("-k", "Escape")
        self.s.wait_state("panel closed", lambda st: not st["opened"])

    def test_escape_from_the_list_closes(self):
        self.select_second_row()
        self.s.press("-k", "Escape")
        self.s.wait_state("panel closed", lambda st: not st["opened"])


class NostrReplaceDialog(ModalCase):
    """Matrix E8 x S11: generate-nostr exit 4 asks to Replace; Escape and Enter
    keep the key, only Right then Enter replaces."""

    config = {"exit": {"generate-nostr": 4}}

    def ask(self):
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("Nostr form", lambda st: self.s.field("Nickname") is not None)
        self.s.press("-k", "Tab", "nick", "-k", "Return")
        self.s.wait_state("replace confirm", lambda st: st["confirmOpen"])
        self.assertEqual(self.s.state()["confirmMessage"], "Replace the Nostr key nick?")
        self.assertEqual([c["argv"] for c in self.s.helper_calls("generate-nostr")],
                         [["generate-nostr", "--account=nick", "--folder=Nostr"]])

    def assert_not_replaced(self):
        self.s.settle()
        self.assertEqual(len(self.s.helper_calls("generate-nostr")), 1)
        self.assertEqual(self.s.state()["view"], "add")

    def test_escape_cancels(self):
        self.ask()
        self.s.press("-k", "Escape")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.assert_not_replaced()

    def test_enter_cancels_by_default(self):
        self.ask()
        self.s.press("-k", "Return")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.assert_not_replaced()

    def test_right_then_enter_replaces(self):
        self.ask()
        self.s.set_config({})
        self.s.press("-k", "Right", "-k", "Return")
        self.s.wait(lambda: len(self.s.helper_calls("generate-nostr")) == 2, "the replace call")
        self.assertEqual(self.s.helper_calls("generate-nostr")[1]["argv"],
                         ["generate-nostr", "--account=nick", "--folder=Nostr", "--replace"])
        self.s.wait_state("back on the list", lambda st: st["view"] == "list")


BUTTON_STUB = """import QtQuick
Item {
  property QtObject bar: null
  property string text: ""
  property string tooltipText: ""
  signal pressed(int buttonCode)
  implicitWidth: 24
  implicitHeight: 24
}
"""


class WidgetSession(Session):
    """A session that hosts BarWidget.qml instead of Panel.qml alone."""

    def _stage(self):
        super()._stage()
        shutil.copy(os.path.join(HERE, "harness_widget.qml"), os.path.join(self.dir, "shell.qml"))
        shutil.copy(os.path.join(session.ROOT, "BarWidget.qml"),
                    os.path.join(self.dir, "plugin", "BarWidget.qml"))
        # The shell's bar icon is not vendored: a stand-in with the same API.
        ui = os.path.join(self.dir, "Ui")
        with open(os.path.join(ui, "BarIconButton.qml"), "w") as f:
            f.write(BUTTON_STUB)
        with open(os.path.join(ui, "qmldir"), "a") as f:
            f.write("BarIconButton 1.0 BarIconButton.qml\n")
        self._shim_imports()


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class ShellToggle(unittest.TestCase):
    """Gap 6 / matrix E2 x S2: the shell's toggle reads BarWidget.opened. A
    panel that is still waiting for the focus snapshot counts as open, so a
    second toggle closes it instead of opening it again."""

    def setUp(self):
        self.s = WidgetSession({"delay": {"focus-snapshot": 1.0}})
        self.addCleanup(self.s.stop)
        self.s.start()

    def test_toggle_while_opening_closes(self):
        self.s._ipc("shellToggle")
        self.s.wait_state("opening", lambda st: st["opening"])
        self.assertTrue(self.s.state()["widgetOpened"])
        self.s._ipc("shellToggle")
        st = self.s.state()
        self.assertFalse(st["opening"])
        self.assertFalse(st["widgetOpened"])
        # The abandoned open never shows the panel.
        self.s.settle()
        self.assertFalse(self.s.state()["panelOpened"])
        self.assertEqual(len(self.s.helper_calls("focus-snapshot")), 1)
