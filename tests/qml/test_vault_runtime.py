"""Panel and Vault behavior seen from the helper's side, through the stub.

Covers exact account names, the "Copied account" report, and the places
where secrets are wiped or must never appear. Run with scripts/test-qml.
"""
import os
import subprocess
import unittest

from session import Session, in_qml_sandbox

SECRET = "dummy-secret-not-real"


def web(*accounts):
    return [{"account": a, "folder": "Web", "kind": ""} for a in accounts]


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class VaultCase(unittest.TestCase):
    config = {}

    def setUp(self):
        self.s = Session(self.config)
        self.addCleanup(self.s.stop)
        self.s.start()
        self.s.open_panel()

    def select(self, account):
        """Arrow down until the row for `account` is the current one."""
        for _ in range(self.s.state()["records"]):
            if self.s.state()["current"] == account:
                return
            before = self.s.state()["listIndex"]
            self.s.press("-k", "Down")
            self.s.wait_state("cursor moved", lambda st: st["listIndex"] != before)
        self.assertEqual(self.s.state()["current"], account)

    def focus_password(self):
        self.s.chord("ctrl", "n")
        self.s.wait_state("folder field focused",
                          lambda st: st["view"] == "add"
                          and any(f["placeholder"] == "Folder" and f["focus"] for f in st["fields"]))
        self.s.press("Web", "-k", "Tab", "svc", "-k", "Tab")
        self.s.wait_state("password field focused",
                          lambda st: any(f["placeholder"] == "Password" and f["focus"] for f in st["fields"]))

    def labels(self, *names):
        return {b["label"]: b["selected"] for b in self.s.buttons() if b["label"] in names}


class ExactAccountNames(VaultCase):
    # Legacy items can carry edge spaces; the helper looks them up exactly.
    # Padded and dash-leading names must reach it unchanged, and a padded
    # name must never act on its trimmed twin.
    config = {"records": web("shop", "shop ", "-bank")}
    NAMES = ("shop ", "shop", "-bank")

    def test_copy_uses_the_exact_account(self):
        for account in self.NAMES:
            with self.subTest(account=account):
                self.select(account)
                before = len(self.s.helper_calls("copy"))
                self.s.press("-k", "Return")
                self.s.wait(lambda: len(self.s.helper_calls("copy")) > before, "a copy call")
                self.assertEqual(self.s.helper_calls("copy")[-1]["argv"], ["copy", "--account=" + account, "--folder=Web"])
                self.s.settle()

    def assert_types_exactly(self, account):
        self.select(account)
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.assertEqual([c["argv"] for c in self.s.helper_calls("type")],
                         [["type", "--account=" + account, "--folder=Web", "--compositor=hyprland", "--expect-id=0x1"]])

    def test_type_uses_the_padded_account(self):
        self.assert_types_exactly("shop ")

    def test_type_uses_a_dash_leading_account(self):
        self.assert_types_exactly("-bank")

    def test_remove_uses_the_exact_account_and_never_its_twin(self):
        self.select("shop ")
        self.s.press("x")
        st = self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(st["confirmMessage"], "Remove shop ?")
        self.s.press("-k", "Tab", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.s.settle()
        self.assertEqual([c["argv"] for c in self.s.helper_calls("clear")], [["clear", "--account=shop ", "--folder=Web"]])

    def test_remove_a_dash_leading_account(self):
        self.select("-bank")
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.s.press("-k", "Tab", "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("clear"), "a clear call")
        self.assertEqual(self.s.helper_calls("clear")[0]["argv"], ["clear", "--account=-bank", "--folder=Web"])


class CopyAccountReport(VaultCase):
    config = {"delay": {"copy-text": 1.0}}

    def test_flash_waits_for_the_helper(self):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("u")
        self.s.wait(lambda: self.s.helper_calls("copy-text"), "a copy-text call")
        self.assertEqual(self.s.state()["flash"], "")
        self.s.wait_state("copied", lambda st: st["flash"] == "Copied account")
        self.assertTrue(self.s.state()["flashOk"])


class CopyAccountFails(VaultCase):
    config = {"exit": {"copy-text": 1}, "stderr": {"copy-text": "runtime dir is not tmpfs"}}

    def test_failure_is_reported_not_claimed_as_a_copy(self):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("u")
        st = self.s.wait_state("failure shown", lambda st: st["flash"] != "")
        self.assertEqual(st["flash"], "runtime dir is not tmpfs")
        self.assertFalse(st["flashOk"])


class TypeFailureMessages(VaultCase):
    # Typing runs after the panel closed, so a failure is a notification.
    def type_and_collect_notification(self, exit_code, stderr=None):
        self.s.set_config({"exit": {"type": exit_code}, "stderr": {"type": stderr} if stderr else {}})
        before = len(self.s.notifications())
        self.s.chord("shift", "Return")
        self.s.wait(lambda: len(self.s.notifications()) > before, "a notification")
        self.assertFalse(self.s.state()["opened"], "typing closes the panel")
        return self.s.notifications()[-1]["argv"]

    def test_failures_reach_the_user_after_the_panel_closed(self):
        for code, text in ((8, "Focus changed"), (9, "Typing failed"), (5, "Type aborted")):
            with self.subTest(exit=code):
                self.s.open_panel()
                argv = self.type_and_collect_notification(code)
                self.assertEqual(argv[-2:], ["omapass", "Autotype failed: " + text])

    def test_the_helper_message_is_shown_and_no_secret_is_in_it(self):
        self.s.open_panel()
        argv = self.type_and_collect_notification(8, "Focus changed to another window")
        self.assertEqual(argv[-1], "Autotype failed: Focus changed to another window")
        self.assertNotIn(SECRET, " ".join(argv))

    def test_markup_in_the_helper_message_reaches_the_toast_as_text(self):
        # The toast restores <b>, <a href> and the like after decoding entities.
        self.s.open_panel()
        argv = self.type_and_collect_notification(
            8, '<b>x</b> <img src="https://example.invalid/x"> &lt;i&gt;')
        self.assertEqual(argv[-1], 'Autotype failed: < b>x< /b> < img src="https://example.invalid/x"> & lt;i& gt;')

    def test_success_sends_no_notification(self):
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.s.wait(lambda: any(c.get("event") == "exit" for c in self.s.calls()), "typing to end")
        self.s.settle()
        self.assertEqual(self.s.notifications(), [])


class SecretsAreWiped(VaultCase):
    config = {"delay": {"store": 0.3}}

    def assert_form_wiped(self):
        st = self.s.state()
        self.assertEqual(st["addPasswordLength"], 0)
        self.assertEqual(self.s.field("Password")["text"], "")

    def test_close_wipes_the_typed_password(self):
        self.focus_password()
        self.s.press(SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s.close_panel()
        self.assert_form_wiped()
        self.s.open_panel()
        self.s.chord("ctrl", "n")
        self.s.wait_state("form", lambda st: st["view"] == "add")
        self.assert_form_wiped()

    def test_cancelling_the_form_wipes_the_typed_password(self):
        self.focus_password()
        self.s.press(SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s.press("-k", "Escape")
        self.s.wait_state("back on the list", lambda st: st["view"] == "list")
        self.assert_form_wiped()
        self.assertTrue(self.s.state()["opened"])

    def test_closing_right_after_save_does_not_send_the_secret(self):
        # The panel closes before the helper process has started: the wiped
        # payload, not the typed secret, is what gets written to it.
        self.focus_password()
        self.s.press(SECRET)
        self.s.wait_state("password typed", lambda st: st["addPasswordLength"] == len(SECRET))
        self.s._ipc("saveThenClose")
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        self.s.settle()
        for call in self.s.helper_calls("store"):
            self.assertEqual(call["stdin"], "", call)

    def test_secrets_never_reach_the_helper_argv(self):
        self.focus_password()
        self.s.press(SECRET, "-k", "Return")
        self.s.wait(lambda: self.s.helper_calls("store"), "a store call")
        self.s.wait_state("saved", lambda st: st["view"] == "list")
        self.s.settle()
        self.focus_password()
        self.s.chord("ctrl", "g")
        self.s.wait_state("generated", lambda st: st["addPasswordGenerated"])
        self.s.press("-k", "Return")
        self.s.wait(lambda: len(self.s.helper_calls("store")) == 2, "a second store call")
        self.s.settle()
        stores = self.s.helper_calls("store")
        self.assertEqual(stores[0]["stdin"], SECRET)
        self.assertEqual(stores[1]["stdin"], "Gen#Pass-0123456789abcdef")
        for call in self.s.helper_calls("store", "copy", "type", "clear", "copy-text", "generate-password"):
            for secret in (SECRET, "Gen#Pass-0123456789abcdef"):
                self.assertFalse(any(secret in arg for arg in call["argv"]), call)


class KeysAndDialogs(VaultCase):
    def test_delete_in_the_search_field_never_opens_remove(self):
        # Once with the cursor in the field, once with it moved to the list
        # while the field still has the keyboard focus.
        self.s.press("-k", "Delete", "a")
        self.s.wait_state("later key processed", lambda st: st["searchText"] == "a")
        self.assertFalse(self.s.state()["confirmOpen"])
        self.s.press("-k", "BackSpace", "-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("/")
        self.s.wait_state("search focused again",
                          lambda st: any(f["placeholder"] == "Search" and f["focus"] for f in st["fields"]))
        self.assertEqual(self.s.state()["focusSection"], "search")
        self.s.press("-k", "Delete", "b")
        self.s.wait_state("later key processed", lambda st: st["searchText"] == "b")
        self.assertFalse(self.s.state()["confirmOpen"])

    def test_confirm_opens_on_cancel_again_after_remove_was_selected(self):
        self.s.press("-k", "Down")
        self.s.wait_state("list focused", lambda st: st["focusSection"] == "list")
        self.s.press("x")
        self.s.wait_state("confirm open", lambda st: st["confirmOpen"])
        self.assertEqual(self.labels("Cancel", "Remove"), {"Cancel": True, "Remove": False})
        self.s.press("-k", "Tab")
        self.s.wait(lambda: self.labels("Cancel", "Remove") == {"Cancel": False, "Remove": True}, "Remove selected")
        self.s.press("-k", "Escape")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.s.press("-k", "Down")
        self.s.wait_state("list focused again", lambda st: st["focusSection"] == "list")
        self.s.press("x")
        self.s.wait_state("confirm open again", lambda st: st["confirmOpen"])
        self.assertEqual(self.labels("Cancel", "Remove"), {"Cancel": True, "Remove": False})
        self.s.press("-k", "Return")
        self.s.wait_state("confirm closed", lambda st: not st["confirmOpen"])
        self.s.settle()
        self.assertEqual(self.s.helper_calls("clear"), [])


class ReopenStopsTyping(VaultCase):
    config = {"delay": {"type": 20}}

    def test_reopening_the_panel_terminates_a_running_type(self):
        self.s.chord("shift", "Return")
        self.s.wait(lambda: self.s.helper_calls("type"), "a type call")
        self.s.wait_state("panel closed", lambda st: not st["opened"])
        self.s.open_panel()
        self.s.wait(lambda: any(c.get("event") == "terminated" for c in self.s.calls()),
                    "the type helper to be terminated")


class GeneratedPasswordRace(VaultCase):
    # A line far larger than a pipe buffer: the helper exits only after the
    # panel has read it, and the exit can be reported before the last bytes
    # are handled. The reply must wait for the end of the output.
    BIG = "G" * 200000
    config = {"generated": BIG}

    def generate(self):
        self.focus_password()
        self.s.chord("ctrl", "g")

    def test_a_large_line_arrives_whole(self):
        self.generate()
        st = self.s.wait_state("generated password set", lambda st: st["addPasswordGenerated"])
        # The field caps its text at 32767 characters: a shorter value would
        # mean the line was cut.
        self.assertEqual(st["addPasswordLength"], 32767)

    def test_nothing_is_delivered_after_the_panel_closed(self):
        self.s.set_config({"generated": "Gen#Pass-0123456789abcdef", "delay": {"generate-password": 1.0}})
        self.generate()
        self.s.wait(lambda: self.s.helper_calls("generate-password"), "a generate call")
        self.s.close_panel()
        self.s.wait(lambda: any(c.get("event") == "exit" for c in self.s.calls()), "the helper to exit")
        self.s.settle()
        self.s.open_panel()
        self.s.chord("ctrl", "n")
        self.s.wait_state("form", lambda st: st["view"] == "add")
        self.assertEqual(self.s.state()["addPasswordLength"], 0)
        self.assertEqual(self.s.field("Password")["text"], "")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(in_qml_sandbox(), "run through scripts/test-qml (needs the QML sandbox)")
class ReopenStopsTypingFromAnotherInstance(unittest.TestCase):
    """Each screen's bar has its own Vault; a reopen stops a running type
    started by any of them (adv5 R10). Here the "other instance" is a stub
    `type` started with this plugin's helper path, outside the panel."""

    def test_open_terminates_a_type_it_did_not_start(self):
        s = Session({"delay": {"type": 30}})
        self.addCleanup(s.stop)
        s.start()
        helper = os.path.join(s.dir, "plugin", "bin", "omapass-keyring")
        other = subprocess.Popen(["/usr/bin/python3", "-I", helper, "type", "--account=x"],
                                 env=dict(os.environ, OMAPASS_STUB_DIR=s.stub_dir))
        self.addCleanup(other.kill)
        s.wait(lambda: s.helper_calls("type"), "the other instance's type call")
        s.open_panel()
        s.wait(lambda: any(c.get("event") == "terminated" for c in s.calls()), "the type to be terminated")
        self.assertEqual(other.wait(5), 143)
