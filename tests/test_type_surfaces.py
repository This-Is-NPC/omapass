"""Autotype fails closed when another surface could take the keyboard.

Matrix cells S13 (E3 own layer fading, E4 overlay, E14 reopened panel, E16 lock)
and adversarial findings A1, A2 and A10.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from tests.test_type_safety import TYPE_ARGV, HyprlandCase, reply

QUIET = reply(json.dumps([{"name": "m", "solitaryBlockedBy": ["WINDOWED"]}]))
BAR = {"address": "0x5", "namespace": "omarchy-bar", "pid": 1, "x": 0, "y": 0, "w": 100, "h": 30}
PANEL = {"address": "0x9", "namespace": "omarchy-keyboard-panel", "pid": 1, "x": 0, "y": 0, "w": 100, "h": 80}
DISMISS = {**PANEL, "address": "0xa", "namespace": "omarchy-keyboard-panel-dismiss"}


def layers(*entries):
    return reply(json.dumps({"DP-1": {"levels": {"2": list(entries)}}}))


class TypeSurfaces(HyprlandCase):
    def type_with(self, secret, sequence, monitors=QUIET):
        """Type while `hyprctl layers` answers the sequence, then repeats its last answer."""
        answers = list(sequence)
        typed = []

        def exec_abs(path, args, input=None, capture=False, **kw):
            if path == self.mod.WTYPE:
                typed.append(input)
                return reply()
            if args[:1] == ["activewindow"]:
                return reply('{"address":"0x1"}')
            if args[:1] == ["monitors"]:
                return monitors
            return answers.pop(0) if len(answers) > 1 else answers[0]

        from tests.test_helper_security import FakeBackend, invoke_main

        self.mod.BACKEND = FakeBackend(secret=secret)
        self.addCleanup(setattr, self.mod, "BACKEND", None)
        with (
            mock.patch.object(self.mod, "wtype_tmp_problem", return_value=None),
            mock.patch.object(self.mod, "exec_abs", side_effect=exec_abs),
            mock.patch.object(self.mod, "PANEL_UNMAP_TIMEOUT_S", 0.3),
        ):
            code, _out, err = invoke_main(self.mod, TYPE_ARGV)
        return code, err, typed


class TestBaselineLayerChanges(TypeSurfaces):
    def test_a_baseline_layer_that_resizes_stops_the_typing(self) -> None:
        """A2: same address, namespace and pid, other geometry: not the same layer."""
        code, err, typed = self.type_with("abc", [layers(BAR), layers(BAR), layers({**BAR, "w": 400})])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, ["a"]), err)

    def test_a_baseline_layer_that_vanishes_stops_the_typing(self) -> None:
        """A1: a surface that gives the keyboard back is a change too."""
        other = {**BAR, "address": "0x6", "namespace": "omarchy-notifications"}
        code, err, typed = self.type_with("abc", [layers(BAR, other), layers(BAR, other), layers(BAR)])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, ["a"]), err)

    def test_unchanged_layers_let_the_whole_secret_through(self) -> None:
        code, err, typed = self.type_with("abc", [layers(BAR)])
        self.assertEqual((code, "".join(typed)), (0, "abc"), err)

    def test_layers_without_a_stable_id_are_keyed_by_geometry_too(self) -> None:
        keys = {self.mod.layer_key({**BAR, **change}) for change in ({}, {"x": 1}, {"y": 1}, {"w": 1}, {"h": 1})}
        self.assertEqual(len(keys), 5)
        self.assertEqual(self.mod.layer_key(BAR)[0], "omarchy-bar")


class TestOwnPanelFadeOut(TypeSurfaces):
    def test_the_baseline_waits_until_the_panel_layer_is_gone(self) -> None:
        """A2: a baseline that holds the fading panel could hide the next panel."""
        code, err, typed = self.type_with("abc", [layers(BAR, PANEL, DISMISS), layers(BAR, PANEL), layers(BAR)])
        self.assertEqual((code, "".join(typed)), (0, "abc"), err)

    def test_a_panel_that_opens_at_the_freed_slot_stops_the_typing(self) -> None:
        """A2: the same address, namespace, pid and geometry came back after the baseline."""
        code, err, typed = self.type_with("abc", [layers(BAR, PANEL), layers(BAR), layers(BAR), layers(BAR, PANEL)])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, ["a"]), err)

    def test_a_panel_that_never_unmaps_types_nothing(self) -> None:
        code, err, typed = self.type_with("abc", [layers(BAR, PANEL)])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)
        self.assertIn("keyboard panel still open", err)

    def test_the_dismiss_twin_alone_counts_as_an_open_panel(self) -> None:
        code, err, typed = self.type_with("abc", [layers(BAR, DISMISS)])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)

    def test_unreadable_layers_while_waiting_type_nothing(self) -> None:
        code, err, typed = self.type_with("abc", [reply("not json")])
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)
        self.assertIn("layers unavailable", err)


class TestLockStateUnknown(TypeSurfaces):
    def monitors(self, *blockers):
        return reply(json.dumps([{"name": "m", "solitaryBlockedBy": b} for b in blockers]))

    def test_monitors_blocked_only_by_workspace_are_undetermined(self) -> None:
        """A10: Hyprland stops at WORKSPACE before it reaches the lock."""
        code, err, typed = self.type_with("abc", [layers(BAR)], self.monitors(["WORKSPACE"], ["WORKSPACE", "WINDOWED"]))
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)
        self.assertIn("lock state unknown", err)

    def test_one_readable_monitor_is_enough_to_say_unlocked(self) -> None:
        code, err, typed = self.type_with("abc", [layers(BAR)], self.monitors(["WORKSPACE"], ["WINDOWED"]))
        self.assertEqual((code, "".join(typed)), (0, "abc"), err)

    def test_a_lock_wins_over_an_unreadable_monitor(self) -> None:
        code, err, typed = self.type_with("abc", [layers(BAR)], self.monitors(["WORKSPACE"], ["LOCK"]))
        self.assertEqual((code, typed), (self.mod.EXIT_FOCUS_CHANGED, []), err)
        self.assertIn("session locked", err)


if __name__ == "__main__":
    unittest.main()
