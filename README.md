# omapass

omapass is 100% local. It lists, stores, copies, and types logins from the native gnome-keyring. Optional nsec stays in the same keyring. Not a 1Password/Bitwarden client and not Nostr sync.

## Install

```sh
omarchy plugin add https://github.com/This-Is-NPC/omapass.git --enable
```

## Dependencies

omapass uses the gnome-keyring, clipboard, and typing tools that already ship with Omarchy. The Python helper needs **PyGObject** (`python-gobject`) for `gi.repository.Secret`. No extra daemon runs in the background.

**No sudo or pkexec is required.**

### Git hooks

Unit tests run on `git push` when hooks are enabled:

```sh
git config core.hooksPath hooks
```

Or run them manually: `./tests/run.sh`


## Keyboard

- **Open:** click the widget or `omarchy-shell shell summon io.github.this-is-npc.omapass '{}'`
- **Search:** `/`; list with arrow keys or `j`/`k`; **Enter** copies password; **Shift+Enter** types into the focused window; **Escape** closes or clears
- **Add:** `+` or **Ctrl+N**
- **Add form:** **Left/Right** switches Account | Nostr; **Ctrl+G** generates password or Nostr key; **Ctrl+E** show/hide password; **Enter** saves (Account) or generates key (Nostr); **Escape** cancels
- **Row menu:** `m` or **Right** opens overflow; **Delete** or `x` removes (with confirmation); in confirm dialog: **Enter**, **Escape**, **Tab**

CLI:

```
omapass list
omapass get -- <account>
omapass add --account <id> --folder <name>
omapass rm -- <account>
omapass copy -- <account>          # clipboard
omapass type -- <account>          # type into focused window

omapass nostr new [--account <id>] [--folder <name>]
omapass nostr show-npub [--account <id>]
omapass nostr show-nsec [--account <id>]   # asks for confirmation
omapass nostr rm [--account <id>]
```

`nostr new` defaults to `account=nostr:default` and `folder=Nostr` when flags are omitted.

Secrets never appear in the list UI.

**Autotype:** the panel captures the focused window when it opens. Typing runs after the panel closes; if focus changes before typing starts, the operation aborts with an error instead of typing into the wrong window. Immediately before typing, the helper re-reads focus; if focus cannot be read, typing aborts.

**Clipboard:** `copy` uses `wl-copy --paste-once` and schedules a 30-second expiry that clears the clipboard only if the pasted content is still the copied secret.

**CLI secrets:** `get` refuses to print a secret to an interactive terminal unless you pass `--yes`; piping stdout is fine.

**Popout switch:** switching the panel to a popout wipes any in-progress add-form password fields.

## Remove

```sh
omarchy plugin remove io.github.this-is-npc.omapass
```

Removal does not delete keyring entries.

## License

MIT. See LICENSE.
