# omapass

omapass is 100% local. It lists, stores, copies, and types logins from the native gnome-keyring. Optional nsec stays in the same keyring. Not a 1Password/Bitwarden client and not Nostr sync.

## Install

```sh
omarchy plugin add https://github.com/This-Is-NPC/omapass.git --enable
```

## Dependencies

omapass uses the gnome-keyring, clipboard, and typing tools that already ship with Omarchy. No extra packages or daemons.

**No sudo or pkexec is required.**


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
omapass copy -- <account>          # wl-copy
omapass type -- <account>          # wtype into focus

omapass nostr new [--account <id>] [--folder <name>]
omapass nostr show-npub [--account <id>]
omapass nostr show-nsec [--account <id>]   # asks for confirmation
omapass nostr rm [--account <id>]
```

`nostr new` defaults to `account=nostr:default` and `folder=Nostr` when flags are omitted.

Secrets never appear in the list UI.

## Remove

```sh
omarchy plugin remove io.github.this-is-npc.omapass
```

Removal does not delete keyring entries.

## License

MIT. See LICENSE.
