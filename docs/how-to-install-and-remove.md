# How to install and remove omapass

**The question:** How do I install omapass in the Omarchy shell, update it by
hand, and take it off again? This page is enough on its own.

## Before you start

- Omarchy with its shell, which provides the `omarchy` command.
- The tools listed under [Requirements](../README.md#requirements).
- To work on the code instead, see [design.md](design.md) and [testing.md](testing.md).

## Install

1. Add the plugin and enable it:

   ```sh
   omarchy plugin add https://github.com/This-Is-NPC/omapass.git --enable
   ```

   The command clones the repository into
   `~/.config/omarchy/plugins/io.github.this-is-npc.omapass/`, so `docs/` and
   `tests/` come with it.

2. Click the omapass widget in the bar, or run:

   ```sh
   omarchy-shell shell summon io.github.this-is-npc.omapass '{}'
   ```

   The panel opens with your logins. Press `Esc` to close it.

## Update by hand

After you change files in the plugin folder, the shell notices by itself. It
watches `~/.config/omarchy/plugins` and ignores hidden entries, `.git` and
`__pycache__`. On a change it clears its QML cache and rebuilds the plugin's
widget, so the next panel runs the new QML and the new helper.

This comes from reading the installed shell source
(`/usr/share/omarchy/shell/services/PluginRegistry.qml` and `shell.qml`). It was
not tried on a live shell.

The rebuild destroys a panel that is on screen without closing it:

- An unsaved add form is lost.
- A helper that is still running is killed. A `type` stops part-way; a `store`
  can leave a duplicate but never a half-written item. See [Storage](storage.md)
  and [Autotype](autotype.md).

If the panel does not change, run:

```sh
omarchy-restart-shell
```

## Remove

```sh
omarchy plugin remove io.github.this-is-npc.omapass
```

Removal does not delete keyring entries. Your logins stay in the gnome-keyring.

## What can go wrong

- **The panel shows old behavior after an update.** Run `omarchy-restart-shell`.
  A restarted shell can leave an orphaned helper; the next panel open stops a
  `type` it finds.
- **The panel vanished while you were typing or saving.** A reload, a disable or
  a monitor unplug destroys the panel. Check the result with
  [How to check the keyring](how-to-check-the-keyring.md) if a save was running.

## Where to go next

- [Start here](../README.md#start-here) for the first keys.
- [Keyboard](keyboard.md) for every key.
- [How to type into a window](how-to-type-into-a-window.md).
