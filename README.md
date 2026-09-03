# omapass

omapass is 100% local. It lists, stores, copies, and types logins from the native gnome-keyring. Optional nsec stays in the same keyring. Not a 1Password/Bitwarden client and not Nostr sync.

## Install

```sh
omarchy plugin add https://github.com/This-Is-NPC/omapass.git --enable
```

## Dependencies

omapass uses the gnome-keyring, clipboard, and typing tools that already ship with Omarchy. No extra packages or daemons.

**No sudo or pkexec is required.**

## Usage

Click the Passwords widget to open the panel. Search; Enter copies the password; Shift+Enter types it into the focused window. `+` or Ctrl+N opens the add form with Account | Nostr tabs. Account tab: Folder, Account, Password (eye toggle + generate password). Nostr tab: nickname and folder (empty folder becomes Nostr); Generate key stores nsec locally with kind=nostr and never shows it or uploads it to a relay. Overflow Remove asks for confirmation.

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
