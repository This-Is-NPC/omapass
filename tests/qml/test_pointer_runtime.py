"""A pointer at rest never steers the keyboard.

Qt re-delivers hover when items move under a pointer that does not move:
the list re-lays out after a search, the panel opens, a dialog appears. The
virtual pointer here is placed once and then stays still. Only real motion
may change the selected row, the confirm dialog's button, the row menu's
option or the chips. To assert that nothing happened, each test first waits
until the panel reports the hover on the item under the pointer
(`pointerOver` in the harness state): Qt has then delivered it, and a
handler that reacted to it would already have acted.
"""
import unittest

from session import Session, in_qml_sandbox

RECORDS = [{"account": a, "folder": "Web", "kind": ""} for a in
           ["amazon", "bank-main", "bank-old", "github", "gitlab", "google", "paypal", "proton"]]


def center(box):
    return box["x"] + box["w"] / 2, box["y"] + box["h"] / 2


def find(boxes, key, value):
    return [b for b in boxes if b[key] == value][0]


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class PointerCase(unittest.TestCase):
    config = {"records": RECORDS}

    def setUp(self):
        self.s = Session(self.config)
        self.addCleanup(self.s.stop)
        self.s.start()

    def move_pointer(self, x, y):
        """Enter the panel at (x, y), then really move one pixel. The first
        position after entering is only a baseline, and Qt merges moves that
        arrive together, so wait until the panel has seen the first."""
        self.s.pointer().move(x, y)
        self.s.wait_state("pointer position seen", lambda st: st["pointerSeen"])
        self.s.pointer().move(x + 1, y)

    def row_center(self, account):
        return center(find(self.s.rows(), "account", account))

    def labels(self, *names):
        return {b["label"]: b["selected"] for b in self.s.buttons() if b["label"] in names}

    def wait_hover(self, name):
        """Wait until the hover on the item called `name` reached the panel."""
        self.s.wait_state("hover delivered to " + name, lambda st: name in st["pointerOver"])

    def open_remove_confirm(self, hover=None):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        if hover:
            self.wait_hover(hover)

    def where_dialog_button_appears(self, label, open_dialog):
        """Open the dialog once without a pointer, note the button, close it."""
        open_dialog()
        spot = center(find(self.s.buttons(), "label", label))
        self.s.press("-k", "Escape")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        return spot


class RowSelection(PointerCase):
    def test_real_motion_moves_the_selection(self):
        self.s.open_panel()
        self.move_pointer(*self.row_center("paypal"))
        self.s.wait_state("row under the pointer selected", lambda st: st["current"] == "paypal")

    def test_resting_pointer_does_not_pick_the_row_after_a_search(self):
        self.s.open_panel()
        # Real motion first, so the pointer rests over the list.
        self.move_pointer(*self.row_center("bank-main"))
        self.s.wait_state("hovered row selected", lambda st: st["current"] == "bank-main")
        # "g" leaves github, gitlab, google; gitlab now slides under the pointer.
        self.s.press("g")
        self.s.wait_state("search applied", lambda st: st["searchText"] == "g" and st["records"] == 3)
        self.wait_hover("gitlab")  # the row that slid under the pointer
        self.assertEqual(self.s.state()["current"], "github")
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual(self.s.helper_calls("type")[0]["argv"][:2], ["type", "--account=github"])

    def test_resting_pointer_does_not_pick_the_row_when_the_panel_opens(self):
        self.s.open_panel()
        spot = self.row_center("github")
        self.s.close_panel()
        self.s.pointer().move(*spot)
        self.s.open_panel()
        self.wait_hover("github")
        self.assertEqual(self.s.state()["current"], "amazon")
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.assertEqual(self.s.helper_calls("copy")[0]["argv"], ["copy", "--account=amazon", "--folder=Web"])

    def test_a_small_move_after_a_search_selects_the_row_again(self):
        self.s.open_panel()
        x, y = self.row_center("bank-main")
        self.move_pointer(x, y)
        self.s.wait_state("hovered row selected", lambda st: st["current"] == "bank-main")
        self.s.press("g")
        self.s.wait_state("search applied", lambda st: st["searchText"] == "g" and st["records"] == 3)
        self.s.pointer().move(x + 2, y)
        self.s.wait_state("moved pointer selects the row under it", lambda st: st["current"] == "gitlab")


class ConfirmButtons(PointerCase):
    config = {"records": RECORDS, "exit": {"store": 4}}

    def test_remove_confirm_opens_on_cancel_under_a_resting_pointer(self):
        self.s.open_panel()
        spot = self.where_dialog_button_appears("Remove", self.open_remove_confirm)
        self.s.pointer().move(*spot)
        self.s.wait_state("pointer position seen", lambda st: st["pointerSeen"])
        self.open_remove_confirm(hover="Remove")
        self.assertEqual(self.labels("Cancel", "Remove"), {"Cancel": True, "Remove": False})
        self.s.press("-k", "Return")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.s.settle()
        self.assertEqual(self.s.helper_calls("clear"), [])

    def test_moving_onto_remove_then_enter_removes(self):
        self.s.open_panel()
        self.open_remove_confirm()
        self.move_pointer(*center(find(self.s.buttons(), "label", "Remove")))
        self.s.wait_state("Remove selected", lambda st: self.labels("Remove")["Remove"])
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")

    def test_replace_confirm_opens_on_cancel_under_a_resting_pointer(self):
        def save_existing():
            self.s.chord("ctrl", "n")
            self.s.wait_state("form", lambda st: st["view"] == "add")
            self.s.press("Web", "-k", "Tab", "github", "-k", "Tab", "dummy-new-pass", "-k", "Return")
            self.s.wait_state("replace confirm", lambda st: st["confirmOpen"])

        self.s.open_panel()
        spot = self.where_dialog_button_appears("Replace", save_existing)
        self.s.pointer().move(*spot)
        self.s.wait_state("pointer position seen", lambda st: st["pointerSeen"])
        self.s.wait_state("password field focused",
                          lambda st: any(f["placeholder"] == "Password" and f["focus"] for f in st["fields"]))
        self.s.press("-k", "Return")
        self.s.wait_state("replace confirm again", lambda st: st["confirmOpen"])
        self.wait_hover("Replace")
        self.assertEqual(self.labels("Cancel", "Replace"), {"Cancel": True, "Replace": False})
        self.s.press("-k", "Return")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.s.settle()
        stores = [c["argv"] for c in self.s.helper_calls("store")]
        self.assertEqual(len(stores), 2, stores)
        self.assertTrue(all("--replace" not in a for a in stores), stores)


class RowMenu(PointerCase):
    def open_menu(self, hover=None):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("m")
        self.s.wait_state("menu open", lambda st: st["menuOpen"])
        if hover:
            self.wait_hover(hover)

    def close_menu(self):
        self.s.press("-k", "Escape")
        self.s.wait_state("menu closed", lambda st: not st["menuOpen"])

    def options(self):
        return {b["label"]: b["selected"] for b in self.s.buttons()
                if b["label"] in ("Copy account", "Type password", "Remove")}

    def test_resting_pointer_never_picks_a_menu_option(self):
        self.s.open_panel()
        self.open_menu()
        spot = center(find(self.s.buttons(), "label", "Type password"))
        self.close_menu()
        self.s.close_panel()
        # Park the pointer where "Type password" will appear; it never moves again.
        self.s.pointer().move(*spot)
        self.s.open_panel()
        self.s.wait_state("pointer position seen", lambda st: st["pointerSeen"])
        self.open_menu(hover="Type password")
        self.assertEqual(self.options(), {"Copy account": True, "Type password": False, "Remove": False})
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("type", "copy-text"), "a menu action")
        self.s.settle()
        self.assertEqual([c["cmd"] for c in self.s.helper_calls("type", "copy-text", "copy")], ["copy-text"])

    def test_real_motion_selects_a_menu_option(self):
        self.s.open_panel()
        self.open_menu()
        self.move_pointer(*center(find(self.s.buttons(), "label", "Remove")))
        self.s.wait_state("Remove selected", lambda st: self.options()["Remove"])

    def test_a_click_on_type_password_types(self):
        self.s.open_panel()
        self.open_menu()
        self.move_pointer(*center(find(self.s.buttons(), "label", "Type password")))
        self.s.wait_state("Type password selected", lambda st: self.options()["Type password"])
        self.s.pointer().click()
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")

    def test_space_never_runs_a_menu_option(self):
        self.s.open_panel()
        self.open_menu()
        self.s.press("-k", "Down")
        self.s.wait_state("Type password selected", lambda st: self.options()["Type password"])
        # One wtype call drops at most its first key, so send several Spaces
        # and the Escape in the same call. Keys are handled in order: once
        # Escape closed the menu, the Spaces were handled.
        self.s.press("-k", "space", "-k", "space", "-k", "space", "-k", "Escape")
        self.s.wait_state("menu closed", lambda st: not st["menuOpen"])
        self.s.settle()
        self.assertEqual(self.s.helper_calls("type", "copy-text", "copy", "clear"), [])
        self.assertFalse(self.s.state()["confirmOpen"])


class Chips(PointerCase):
    def test_resting_pointer_does_not_move_the_cursor_to_a_chip(self):
        self.s.open_panel()
        spot = center(find(self.s.buttons(), "label", "All"))
        self.s.pointer().move(*spot)
        self.wait_hover("All")
        self.assertEqual(self.s.state()["focusSection"], "search")

    def test_real_motion_moves_the_cursor_to_a_chip(self):
        self.s.open_panel()
        self.move_pointer(*center(find(self.s.buttons(), "label", "Web 8")))
        self.s.wait_state("chip cursor", lambda st: st["focusSection"] == "folders")


class SearchField(PointerCase):
    def focus_list_then_rest_over_search(self):
        self.s.open_panel()
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        spot = center(find(self.s.buttons(), "label", "Search"))
        self.s.pointer().move(*spot)
        self.wait_hover("Search")
        return spot

    def test_resting_pointer_does_not_move_the_cursor_to_the_search_field(self):
        self.focus_list_then_rest_over_search()
        self.assertEqual(self.s.state()["focusSection"], "list")

    def test_real_motion_moves_the_cursor_to_the_search_field(self):
        x, y = self.focus_list_then_rest_over_search()
        self.s.pointer().move(x + 1, y)
        self.s.wait_state("search cursor", lambda st: st["focusSection"] == "search")


if __name__ == "__main__":
    unittest.main()
