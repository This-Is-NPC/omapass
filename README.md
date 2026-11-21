# omapass

100% local logins for the Omarchy shell: omapass lists, stores, copies and types them from the native gnome-keyring, and keeps an optional Nostr `nsec` in the same keyring. It is not a 1Password or Bitwarden client and it does not sync over Nostr.

## Install

```sh
omarchy plugin add https://github.com/This-Is-NPC/omapass.git --enable
```

This clones the plugin into `~/.config/omarchy/plugins/` and enables it; the shell picks it up by itself. [How to install and remove](docs/how-to-install-and-remove.md) covers updates by hand and removal.

## Start here

- Click the bar widget — open the panel
- `/` — search
- `Enter` — copy the password
- `Shift+Enter` — type it into the focused window (never copies)
- `+` — add a login
- `m` — row menu (copy account, type, remove)
- `Ctrl+P` — panel under the icon or centered on the bar
- `Esc` — clear the search, close a menu, then close the panel

## Big ideas

**[Keyboard](docs/keyboard.md)** — every key in the list, the search, the add form and the row menu.

**[Screens](docs/screens.md)** — what the panel looks like, folder cards and chips, the status strip, and where the panel sits.

**[Autotype](docs/autotype.md)** — how typing into a window checks focus, layers and the lock screen before each character, and what risk is left.

**[Type into a window](docs/how-to-type-into-a-window.md)** — the steps to type a login into another application.

**[Clipboard](docs/clipboard.md)** — a copy lives for at most 30 seconds, and a detached helper drops it.

**[Storage](docs/storage.md)** — how logins sit in the keyring (`enc=b64`), the write lock, the write guard and `doctor`.

**[Check the keyring](docs/how-to-check-the-keyring.md)** — what to do first after a write error.

**[Names](docs/names.md)** — input limits, Unicode normalization, invisible characters, identity, duplicates and `--replace`.

**[Security](docs/security.md)** — secrets on stdin, core dumps, process hardening and CLI secrets.

**[CLI](docs/cli.md)** — the `omapass` command: commands, options and exit codes.

## Interface

The panel is keyboard first; a click works wherever a key does. Keys are in [docs/keyboard.md](docs/keyboard.md). The same keyring is reachable from the `omapass` command, documented in [docs/cli.md](docs/cli.md).

## What it does not do

- It runs no daemon. A copy starts a detached helper that exits after the clipboard clears.
- It does not sync, and it does not talk to any server.
- It needs no `sudo` or `pkexec`.
- It never creates a missing keyring; it stops with an error instead.
- Secrets never appear in the list UI or in a command's argv. `copy`, `type` and `clear` also keep item names off argv (they read them on stdin); `store` and `generate-nostr` still pass the account and folder as arguments. See [Security](docs/security.md#item-on-stdin).
- Only an explicit action copies or types a secret: no single letter or Space does.

## Known limitations

**Clipboard.** A copied password stays until another copy replaces it or 30 seconds pass. See [Clipboard](docs/clipboard.md).

**Autotype focus gap.** Focus can change between the check and a keystroke, so one character can reach another window. Do not switch windows while it types. See [Autotype](docs/autotype.md).

## Contributing

[docs/design.md](docs/design.md) explains how omapass is built; [docs/testing.md](docs/testing.md) covers the test sandbox, the QML runtime tests and the git hooks.

## Requirements

- `python-gobject` (PyGObject) and `libsecret`, for `gi.repository.Secret`
- `gnome-keyring`
- `wl-clipboard` for copying
- `wtype` for typing, with `/tmp` on tmpfs or ramfs (the Omarchy default)
- `hyprctl` (Hyprland) or niri, for the focus, layer and lock checks
- Optional: `python-coincurve` or `python-secp256k1` to show a Nostr key's npub; without them the key is stored and no npub is shown
- Optional: Docker, to run the tests

## License

MIT. See [LICENSE](LICENSE).
