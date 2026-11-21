"""Data paths of the panel (round 14): failed saves, queued refreshes, helper
timeouts and destruction, duplicate rows, the Replace dialog.

Run with scripts/test-qml. Each docstring names the cell or gap of the
state x event matrix it covers (G = section 3 gap, E/S = event/state).
"""
import subprocess
import unittest

from session import Session, in_qml_sandbox
from test_panel_runtime import PanelCase, SECRET

DUP = [
    {"account": "github", "folder": "Work", "kind": ""},
    {"account": "github", "folder": "Home", "kind": ""},
    {"account": "bob", "folder": "Home", "kind": ""},
]


class FailedSaveKeepsThePassword(PanelCase):
    """E8 x S10 (store fails, exit not 4), new finding 2."""
    config = {"exit": {"store": 5}, "stderr": {"store": "refusing to write: dummy reason"}}

    def fill_and_save(self):
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("store"), "a store call")
        return self.s.wait_state("error shown", lambda st: st["addError"] != "")

    def test_exit_5_keeps_the_typed_password_and_a_retry_sends_it(self):
        st = self.fill_and_save()
        self.assertEqual(st["addError"], "refusing to write: dummy reason")
        self.assertEqual(st["addPasswordLength"], len(SECRET))
        self.assertEqual(self.s.field("Password")["text"], SECRET)
        self.assertEqual(st["view"], "add")
        self.s.set_config({})
        self.s.press("-k", "Return")
        self.s.wait_state("saved, back on the list", lambda st: st["view"] == "list")
        self.assertEqual([c["stdin"] for c in self.s.helper_calls("store")], [SECRET, SECRET])

    def test_other_exit_codes_keep_it_too(self):
        for code in (1, 10):
            self.s.set_config({"exit": {"store": code}, "stderr": {"store": "failed %d" % code}})
            self.s.helper_calls("store")
            if code == 1:
                self.focus_password()
                self.s.press(SECRET, "-k", "Return")
            else:
                self.s.press("-k", "Return")
            st = self.s.wait_state("error %d" % code, lambda st: st["addError"] == "failed %d" % code)
            self.assertEqual(st["addPasswordLength"], len(SECRET), code)

    def test_success_still_wipes_it(self):
        self.s.set_config({})
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        st = self.s.wait_state("saved", lambda st: st["view"] == "list")
        self.assertEqual(st["addPasswordLength"], 0)

    def test_cancel_after_a_failure_wipes_it(self):
        self.fill_and_save()
        self.s.press("-k", "Escape")
        st = self.s.wait_state("back on the list", lambda st: st["view"] == "list")
        self.assertEqual(st["addPasswordLength"], 0)

    def test_close_after_a_failure_wipes_it(self):
        self.fill_and_save()
        self.s.close_panel()
        self.s.open_panel()
        self.assertEqual(self.s.state()["addPasswordLength"], 0)

    def test_a_damaged_keyring_keeps_it_behind_the_alert(self):
        self.s.set_config({"exit": {"store": 6}, "stderr": {"store": "THE WRITE FAILED dummy"}})
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        st = self.s.wait_state("alert", lambda st: st["confirmOpen"])
        self.assertEqual(st["addPasswordLength"], len(SECRET))


class GenerateFailures(PanelCase):
    """E8 x S10 (generate-password fails) and S11 (generate-nostr)."""

    def test_a_failed_password_generation_shows_an_error(self):
        self.s.set_config({"exit": {"generate-password": 1}})
        self.open_add_form()
        self.s.chord("ctrl", "g")
        st = self.s.wait_state("error", lambda st: st["addError"] == "Could not generate password")
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertFalse(st["addPasswordGenerated"])

    def open_nostr_form(self):
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.wait_state("nostr form", lambda st: any(f["placeholder"] == "Nickname" for f in st["fields"]))

    def test_enter_in_the_nostr_account_field_generates_the_key(self):
        """E10 x S11."""
        self.s.set_config({"records": [], "exit": {}})
        self.open_nostr_form()
        self.s.press("-k", "Tab", "nick", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("generate-nostr"), "a generate-nostr call")
        self.assertEqual(self.s.helper_calls("generate-nostr")[0]["argv"],
                         ["generate-nostr", "--account=nick", "--folder=Nostr"])

    def test_nostr_failure_is_shown_in_the_form(self):
        self.s.set_config({"exit": {"generate-nostr": 1}, "stderr": {"generate-nostr": "no entropy"}})
        self.open_nostr_form()
        self.s.press("-k", "Tab", "nick", "-k", "Return")
        self.s.wait_state("error", lambda st: st["addError"] == "no entropy")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class FocusSnapshotFailure(unittest.TestCase):
    """E8 x S2 and E11 (snapshot null): Type is unavailable, the panel stays."""

    def start(self, config, timeouts=None):
        s = Session(config)
        self.addCleanup(s.stop)
        s.start()
        if timeouts:
            s._ipc("setTimeouts", *[str(t) for t in timeouts])
        self.s = s
        s._ipc("open")
        s.wait_state("opened with rows", lambda st: st["opened"] and st["records"] > 0)
        return s

    def assert_type_unavailable(self):
        self.s.press("-M", "shift", "-k", "Return", "-m", "shift")
        st = self.s.wait_state("flash", lambda st: st["flash"] == "Type unavailable")
        self.assertFalse(st["flashOk"])
        self.assertTrue(st["opened"])
        self.s.settle()
        self.assertEqual(self.s.helper_calls("type"), [])

    def test_a_failed_snapshot(self):
        self.start({"exit": {"focus-snapshot": 3}})
        self.s.prime_keys()
        self.assert_type_unavailable()

    def test_a_hung_snapshot_is_cut_and_the_panel_opens(self):
        """G10: no QML timeout on focus-snapshot."""
        self.start({"delay": {"focus-snapshot": 30}}, (60000, 20000, 1000))
        self.s.prime_keys()
        self.assert_type_unavailable()
        self.assertTrue(any(c.get("event") == "terminated" and c["cmd"] == "focus-snapshot"
                            for c in self.s.calls()))


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class ListTimeoutAndRecovery(unittest.TestCase):
    """E8 x S3 (list hangs) and E7 x S6 (a good list clears the error)."""

    def setUp(self):
        self.s = None

    def start(self, config, timeouts=None):
        s = Session(config)
        self.addCleanup(s.stop)
        s.start()
        if timeouts:
            s._ipc("setTimeouts", *[str(t) for t in timeouts])
        self.s = s
        return s

    def test_a_hung_list_becomes_an_error_and_the_next_open_recovers(self):
        s = self.start({"delay": {"list": 30}}, (1000, 20000, 8000))
        s._ipc("open")
        st = s.wait_state("timed out", lambda st: st["listError"] != "")
        self.assertEqual(st["listError"], "The keyring did not answer in time")
        self.assertFalse(st["loading"])
        self.assertTrue(any(c.get("event") == "terminated" and c["cmd"] == "list" for c in s.calls()))
        s.set_config({})
        s._ipc("open")
        st = s.wait_state("recovered", lambda st: st["listError"] == "" and st["records"] == 3)
        self.assertEqual(st["emptyText"], "")

    def test_a_list_error_is_cleared_by_the_next_good_list(self):
        s = self.start({"exit": {"list": 1}, "stderr": {"list": "keyring locked"}})
        s._ipc("open")
        s.wait_state("error", lambda st: st["listError"] == "keyring locked")
        s.set_config({})
        s._ipc("open")
        s.wait_state("cleared", lambda st: st["listError"] == "" and st["records"] == 3)

    def test_a_hung_copy_is_cut_and_the_next_copy_runs(self):
        """G10: no QML timeout on copy."""
        s = self.start({"delay": {"copy": 30}}, (60000, 1000, 8000))
        s.open_panel()
        s.press("-k", "Return")
        st = s.wait_state("timed out", lambda st: st["flash"] == "Copy timed out")
        self.assertFalse(st["flashOk"])
        s.set_config({})
        s.press("-k", "Return")
        s.wait_state("copied", lambda st: st["flash"] == "Copied password")


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class QueuedRefresh(unittest.TestCase):
    """A4 (E7): a refresh asked for while a list runs is not dropped."""

    def test_the_second_list_runs_after_the_slow_one(self):
        s = Session({"delay": {"list": 2}})
        self.addCleanup(s.stop)
        s.start()
        s._ipc("open")
        s.wait(lambda: s.helper_calls("list"), "the first list call")
        # The slow list holds the old data; the keyring has changed since.
        s.set_config({"records": [{"account": "carol", "folder": "Home", "kind": ""}]})
        s._ipc("open")
        s.wait_state("the fresh list shown", lambda st: st["loadedRecords"] == 1)
        self.assertEqual(len(s.helper_calls("list")), 2)


class DuplicateRowsFlash(PanelCase):
    """E7 x S14: only the copied one of two same-named rows shows the check."""
    config = {"records": DUP}

    def test_only_the_copied_folder_shows_the_check(self):
        rows = self.s.rows()
        work = next(r for r in rows if r["folder"] == "Work")
        # Select the Work row: one Down per row above it.
        order = [(r["account"], r["folder"]) for r in rows]
        for _ in range(order.index(("github", "Work"))):
            self.s.press("-k", "Down")
        self.s.wait_state("work selected", lambda st: st["current"] == "github" and st["listIndex"] == order.index(("github", "Work")))
        self.s.press("-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.assertEqual(self.s.helper_calls("copy")[0]["argv"][-1], "--folder=Work")
        marked = self.s.wait(lambda: [r for r in self.s.rows() if r["copied"]], "a check mark")
        self.assertEqual([(r["account"], r["folder"]) for r in marked], [("github", "Work")], work)


class ReplaceDialogNamesTheFolder(PanelCase):
    """A6: the Replace question says which item goes and where it ends up."""
    config = {"exit": {"store": 4}}

    def save(self, folder, account, records=None):
        if records is not None:
            self.s.set_config({"exit": {"store": 4}, "records": records})
            self.s.close_panel()
            self.s.open_panel()
        self.open_add_form()
        self.s.press(folder, "-k", "Tab", account, "-k", "Tab", SECRET, "-k", "Return")
        return self.s.wait_state("replace dialog", lambda st: st["confirmOpen"])

    def test_a_folder_that_differs_is_named_and_the_move_is_announced(self):
        st = self.save("Personal", "github", DUP[:1] + DUP[2:])
        self.assertEqual(st["confirmMessage"], "Replace the secret for github in Work?")
        self.assertEqual(st["confirmDetail"], "It moves to Personal. The old password is lost for good.")
        self.assertEqual([b["label"] for b in self.s.buttons() if b["selected"]], ["Cancel"])
        self.assertEqual(st["addPasswordLength"], len(SECRET))

    def test_the_same_folder_announces_no_move(self):
        st = self.save("Work", "github", DUP[:1] + DUP[2:])
        self.assertEqual(st["confirmMessage"], "Replace the secret for github in Work?")
        self.assertEqual(st["confirmDetail"], "The old password is lost for good.")

    def test_an_item_missing_from_the_list_names_no_folder(self):
        st = self.save("Personal", "ghost")
        self.assertEqual(st["confirmMessage"], "Replace the secret for ghost?")
        self.assertEqual(st["confirmDetail"], "It is stored in Personal. The old password is lost for good.")

    def test_an_nfd_item_matches_the_nfc_name_typed(self):
        nfd = [{"account": "café", "folder": "Work", "kind": ""}]
        st = self.save("Work", "café", nfd)
        self.assertEqual(st["confirmMessage"], "Replace the secret for café in Work?")

    def test_a_nostr_key_says_the_old_key_is_lost(self):
        records = [{"account": "nick", "folder": "Nostr", "kind": "nostr"},
                   {"account": "nick", "folder": "Work", "kind": ""}]
        self.s.set_config({"exit": {"generate-nostr": 4}, "records": records})
        self.s.close_panel()
        self.s.open_panel()
        self.open_add_form()
        self.s.chord("ctrl", "2")
        self.s.press("-k", "Tab", "nick", "-k", "Return")
        st = self.s.wait_state("replace dialog", lambda st: st["confirmOpen"])
        self.assertEqual(st["confirmMessage"], "Replace the Nostr key nick in Nostr?")
        self.assertEqual(st["confirmDetail"], "The old key is lost for good.")
        self.assertEqual([b["label"] for b in self.s.buttons() if b["selected"]], ["Cancel"])


class DeferredCopyKeepsItsRow(PanelCase):
    """A11 q5 (E7 x S12): the row is taken at Return, not when the copy runs."""

    def test_a_selection_change_between_return_and_the_copy_does_not_retarget_it(self):
        self.select_second_row()
        chosen = self.s.state()["current"]
        other = "alice@example" if chosen != "alice@example" else "bob"
        self.s._ipc("returnThenSelect", other, {"alice@example": "Work"}.get(other, "Home"))
        self.s.wait(lambda: self.s.helper_calls("copy"), "a copy call")
        self.s.settle()
        self.assertEqual([c["argv"][1] for c in self.s.helper_calls("copy")], ["--account=" + chosen])


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class DestroyedWithoutClose(unittest.TestCase):
    """G4 (E17 x S10/S13): the Vault goes away while a helper runs.

    Quickshell kills a Process's child when the Process is destroyed (the
    stub's SIGTERM handler does not run, so it is SIGKILL), so a running
    helper never outlives the Vault and Vault needs no destructor of its own.
    These tests guard that: `type` must stop and not go on typing.
    """

    def alive(self, s, name):
        return subprocess.run(["pgrep", "-f", s.dir + "/plugin/bin/omapass-keyring " + name],
                              capture_output=True).returncode == 0

    def run_and_destroy(self, name):
        # The stub waits 20 s: a helper still alive 3 s after the destruction was not killed.
        s = Session({"delay": {name: 20}})
        self.addCleanup(s.stop)
        s.start()
        s._ipc("vaultCreate")
        s._ipc("vaultStart", name)
        s.wait(lambda: s.helper_calls(name) and self.alive(s, name), "the %s helper running" % name)
        s._ipc("vaultDestroy")
        s.wait(lambda: not self.alive(s, name), "the %s helper gone" % name, timeout=3)
        return s

    def test_a_running_type_is_stopped_with_the_vault(self):
        s = self.run_and_destroy("type")
        self.assertEqual([c for c in s.calls() if c.get("event") == "exit"], [])

    def test_a_running_store_is_cut_not_finished_unverified(self):
        """Documents the kill: the helper is gone before it reports success."""
        s = self.run_and_destroy("store")
        self.assertEqual([c for c in s.calls() if c.get("event") == "exit"], [])

    def test_a_helper_left_alone_does_finish(self):
        """Control: without the destruction the stub does reach its exit."""
        s = Session({"delay": {"type": 1}})
        self.addCleanup(s.stop)
        s.start()
        s._ipc("vaultCreate")
        s._ipc("vaultStart", "type")
        s.wait(lambda: any(c.get("event") == "exit" for c in s.calls()), "the type to finish")


if __name__ == "__main__":
    unittest.main()
