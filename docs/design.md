# omapass Design

For contributors. It describes how omapass is built: the model, the parts, the
state on disk and the protocols between them. For what the program does, read
the [README](../README.md) and the user pages it links. For how to run the
checks, read [testing.md](testing.md).

Numbered section identifiers (`design.md` section 5, for example) are used as
references and stay stable.

## 1. What omapass is and is not

omapass is an Omarchy shell bar widget with a panel. It lists, stores, copies
and types logins held in the native gnome-keyring, and it can keep a Nostr
secret key (`nsec`) in the same keyring. It is 100% local.

It is not a password manager of its own and not a client of 1Password or
Bitwarden. It has no sync, no vault file, no account and no network access.
It is not a Nostr client: the Nostr support only stores and shows keys.

omapass runs no daemon. The panel runs inside the Omarchy shell (quickshell).
Every action starts a short-lived helper process, `bin/omapass-keyring`, that
talks to the keyring through the Secret Service (libsecret). The only helper
that outlives its caller is `clipboard-serve`, which owns `wl-copy` for up to
30 seconds (section 5).

## 2. The model

An **item** is one secret with three names:

- **account**: the identifier shown and searched (for example `github`).
- **kind**: the type of secret. Empty for a plain login, `nostr` for a Nostr
  key. An account and a kind together identify an item: a login and an `nsec`
  with the same account are different items.
- **folder**: the group the panel shows the item under. It is stored as the
  item's label.

The Secret Service attributes of an item are `{service: omapass, account,
kind, enc}`:

| Attribute | Value |
| --- | --- |
| `service` | always `omapass`; every search filters on it |
| `account` | the account, NFC-normalized |
| `kind` | only present when not empty |
| `enc` | `b64`: the secret is stored base64-encoded. Items from older versions lack it and are read raw |

Account, folder and kind are normalized to NFC on write. The names, the
duplicate rule and the validation limits are in [names.md](names.md). The
reasons for the base64 encoding are in [storage.md](storage.md).

Only the **default collection** (the keyring behind the `default` alias) is
read or written. Other collections, such as the ephemeral session collection,
are never searched, because any local client can write to them. If the default
keyring is locked or missing, the helper exits with status 10 and never
unlocks it by itself. Unlocking is the user's action in the keyring prompt.

A Nostr item defaults to account `nostr:default` and folder `Nostr`, with kind
`nostr` (`bin/omapass_lib/nostr.py`).

## 3. Architecture

```
manifest.json
  └─ qml/BarWidget.qml ── loads ──> qml/Panel.qml ──> components in qml/
                                      └─ qml/Vault.qml
                                           └─ /usr/bin/python3 -I ../bin/omapass-keyring
                                                └─ bin/omapass_lib/*  ──> Secret Service,
                                                                           wl-copy, wtype, hyprctl
```

### The plugin and the QML

`manifest.json` declares one `bar-widget` plugin, id
`io.github.this-is-npc.omapass`, with the entry point `qml/BarWidget.qml`.
`allowMultiple` is false and the default bar section is `right`.

`qml/BarWidget.qml` is the bar icon. Each monitor's bar creates one. It loads
`Panel.qml` with a `Loader`, hands it the bar, the settings and the icon as
anchor, and registers the `IpcHandler` target
`io.github.this-is-npc.omapass` (`open`, `close`, `show`, `hide`, `toggle`).
Its left click toggles the panel.

`qml/Panel.qml` is the panel: it owns the view state (list or add form, the
search text, the selected item, the confirm dialog) and the keyboard handling.
It delegates the drawing and the flows to the components below.

| File | Role |
| --- | --- |
| `qml/BarWidget.qml` | The bar icon, the IPC target and the loader of the panel |
| `qml/Panel.qml` | The panel window: state, keyboard, open and close, the `centerPanel` setting |
| `qml/Vault.qml` | The only code that runs the helper; owns one `Process` per helper command, the time bounds and the failure notifications |
| `qml/Model.js` | Pure JavaScript without Qt: display names, search, grouping by folder, the identity of a row, duplicates, the Hyprland border parser. Imported as `Model` and tested without a UI (`tests/test_model_js.py`) |
| `qml/LoginListView.qml` | Search field, folder chips, the scrolling list, the add and position buttons |
| `qml/FolderCard.qml` | One folder as a card: header with name and count, then its rows |
| `qml/LoginRow.qml` | One login row with its copy button and `⋯` menu |
| `qml/MenuRow.qml` | One option of the row menu |
| `qml/AddLoginForm.qml` | The Account and Nostr form, the password generator and the save and replace flows |
| `qml/FormField.qml` | Text field with the accent focus ring |
| `qml/ConfirmCard.qml` | The confirm dialog (Remove, Replace) and the alert for a keyring that may be damaged |
| `qml/FooterStrip.qml` | The fixed strip with key hints and the result of the last action |
| `qml/Pill.qml` | Folder chip and segmented-control option |
| `qml/SolidButton.qml` | Full-width action button |
| `qml/PointerTracker.qml` | Tells real pointer motion from hover that Qt re-delivers when items move under a resting pointer |
| `qml/HyprBorder.qml` | Reads the active border from `hyprctl` (`general:border_size`, `general:col.active_border`) each time the panel opens |

Every component except `Vault.qml`, `BarWidget.qml`, `HyprBorder.qml` and
`Model.js` declares `required property var panel` and is created with
`panel: root` (or `panel: list.panel`). Panel state and actions are reached
through that property, never through an id of `Panel.qml`, so a component can
be read and tested on its own terms.

`Vault.qml` reaches the helper as
`/usr/bin/python3 -I <qml dir>/../bin/omapass-keyring`, with the path resolved
from its own URL. The interpreter and the helper are absolute paths; no
`PATH` lookup happens. `-I` is isolated mode: it ignores `PYTHON*` variables
and the user site directory.

### The wrapper and the entrypoint

`bin/omapass` is the command-line wrapper. It resolves its own path through
`readlink -f` and runs `/usr/bin/python3 -I bin/omapass-keyring "$@"`. It is
the file to put on the `PATH` for the CLI described in [cli.md](cli.md).

`bin/omapass-keyring` is the entrypoint: the argument parser, the usage text,
the handlers for `list`, `get`, `store`, `add`, `clear`/`rm`, `exists` and
`generate-password`, and the error wrapper. It pins `PATH` to `/usr/bin:/bin`
and inserts its own directory into `sys.path` itself, because `python3 -I`
implies `-P` on Python 3.11 and later, which leaves the script directory off
the path. Without that line `import omapass_lib` fails when the helper is run
from any other directory. `tests/test_structure.py` runs it from another
directory and through a symlink.

The wrapper around every handler turns an unreachable keyring (a `GLib.Error`)
into one line and exit 10, and any other exception into
`internal error: <class name>`, never a traceback. The class name only,
because other messages could echo user input.

### The `bin/omapass_lib` modules

| Module | Holds |
| --- | --- |
| `common.py` | Constants (service name, absolute tool paths, exit codes, limits, the 2 s subprocess bound), `die`, `exec_abs` (run an absolute path with a minimal environment), the invisible-character tables and checks, `printable` |
| `keyring_store.py` | The libsecret backend `GiKeyring` (list, find, get, store, clear, exists), `enc=b64` encoding, the write lock, the post-write verification and the create-before-delete replace |
| `keyfile_guard.py` | `rewrite_risks`, the one rule for "is this keyring file safe to rewrite", the lookup of the daemon's keyring file, and `doctor` |
| `secret_io.py` | Input validation, `--item-stdin`, process hardening, the clipboard (`clipboard_copy`, `clipboard-serve`), and autotype (focus, layers, session lock, `wtype`) |
| `nostr.py` | bech32 and `nsec` encoding, the Nostr commands, and the optional `npub` derivation through `coincurve` or `secp256k1` |

`common` imports no other module. `keyfile_guard` imports `common`. `nostr`
imports `common` and `keyring_store`. `keyring_store` and `secret_io` import
each other and import `common`; `keyring_store` also imports `keyfile_guard`. The entrypoint imports
all five. The tests load the entrypoint and every module through
`tests/helper_loader.py` (see [testing.md](testing.md)).

### The 700-line cap

No QML file and no Python file of the helper may exceed 700 lines.
`test_source_files_stay_small_and_guarded` in `tests/test_static_guards.py`
checks every `qml/*.qml` file, `bin/omapass-keyring` and every
`bin/omapass_lib/*.py`. The same test requires that:

- no `.qml` file sits in the repository root;
- every file in `qml/` is in the guarded list, so a new component cannot skip
  the other static guards (no bare `python3`, `wl-copy`, `wtype` or
  `secret-tool` in a QML command, no `secret-tool search`, the pinned
  interpreter in `Vault.qml` and `bin/omapass`).

`qml/Model.js` is not in the list. When a file grows toward the cap, split it
by responsibility, as `Panel.qml` and the helper were split. Raising the cap is
not a fix.

## 4. State

omapass keeps its state in three places and nowhere else.

| State | Where | Written by |
| --- | --- | --- |
| The secrets, with their names | The default keyring file, normally `~/.local/share/keyrings/<name>.keyring` (the one the `default` alias in `~/.local/share/keyrings/default` names) | The gnome-keyring daemon only. omapass asks the daemon through the Secret Service. It reads the file, never writes it |
| The write lock | `$XDG_RUNTIME_DIR/omapass.lock`, only if that directory is absolute, owned by you and mode 0700; otherwise `/tmp/omapass-<uid>.lock` | The helper. Opened with `O_NOFOLLOW` and mode 0600; it must be a regular file you own. An exclusive `fcntl.flock`; the kernel releases it when the helper exits, even if killed |
| `centerPanel` | `~/.config/omarchy/shell.json`, as this widget's setting | `omarchy-bar set io.github.this-is-npc.omapass centerPanel <true|false> --json`, run by the panel's position button and Ctrl+P. Absent means `true` (centered on the bar) |

The helper reads the keyring file for the write guard and for `doctor`. It
finds the file from the environment of the process that owns
`org.freedesktop.secrets`, because that can differ from its own. The rules and
checks are in [storage.md](storage.md) and
[how-to-check-the-keyring.md](how-to-check-the-keyring.md).

Transient files exist only while an action runs:

- `wl-copy` buffers its input in a temporary file in `$XDG_RUNTIME_DIR`, which
  the helper requires to be absolute, owned by you, mode 0700 and on tmpfs or
  ramfs. See [clipboard.md](clipboard.md).
- `wtype` 0.4 writes a keymap file `/tmp/wtype-XXXXX`, unlinked at once. The
  path is compiled into the binary. `type` refuses unless `/tmp` is tmpfs or
  ramfs. See [autotype.md](autotype.md).

The panel keeps no cache of the list or of a secret across closes. Closing
the panel wipes the search, the selection and the form
(`wipeSensitiveState`), and `Vault.forgetSecrets` clears the pending payloads.

## 5. Protocols between the panel and the helper

Each helper command is one process started by `Vault.qml`. `HelperProcess`
(a component in `Vault.qml`) reports the result only after the process has
exited and every attached output stream has been read to the end, because
quickshell can report the exit before the output is complete.

### Argv, stdin and stdout

| Panel action | Helper command | Item or secret goes in via | Result read from |
| --- | --- | --- | --- |
| Refresh | `list --json` | nothing | stdout: a JSON array of `{account, folder, kind, warn}`; stderr on failure |
| Capture focus on open | `focus-snapshot` | nothing | stdout: `{"compositor": ..., "id": ...}` |
| Copy | `copy --item-stdin` | stdin: the item JSON | exit code; stderr |
| Copy a generated password | `copy-text` | stdin: the text | exit code; stderr |
| Type | `type --item-stdin` | stdin: the item JSON plus `compositor` and `expect_id` | exit code; stderr |
| Remove | `clear --item-stdin` | stdin: the item JSON | exit code; stderr |
| Save | `store --account=A --folder=F [--kind=K] [--replace]` | argv: the names. stdin: the secret | exit code; stderr |
| Generate a password | `generate-password` | nothing | stdout |
| Generate a Nostr key | `generate-nostr --account=A --folder=F [--replace]` | argv: the names | exit code; stderr |

A secret is never on the command line or in the environment. The names of the
items that are read, copied, typed or removed also stay off the command line:
other local users can read a process's arguments in `/proc` (a host mounted
without `hidepid` shows them), so these commands take the item on stdin. A
save has to name the account and folder on argv; the secret itself is on
stdin. `tests/qml/test_item_stdin.py` checks the panel side and
`tests/test_item_stdin.py` the helper side.

### `--item-stdin`

`copy`, `type` and `clear` take one JSON object on stdin:

```json
{"account": "...", "folder": "...", "kind": "...", "compositor": "...", "expect_id": "..."}
```

All values are strings. `account` is required; `kind` and `folder` are
optional; `compositor` (`hyprland` or `niri`) and `expect_id` are used by
`type`. `read_item_stdin` in `secret_io.py` reads at most 65536 characters and
refuses the call (exit 1, `--item-stdin expects a JSON object of strings with
an account`) for a missing account, an unknown field or a value that is not a
string. It also refuses, before it reads stdin or the keyring, any
`--account`, `--folder`, `--kind`, `--compositor` or `--expect-id` flag (even
an empty `--folder=`) or a positional name beside `--item-stdin`. The panel
sends the `folder` of the row it acts on (an empty string for an item without
a label), so the helper acts on exactly one item (see [names.md](names.md) for
exit 12). The CLI flags still work without
`--item-stdin`.

### Exit codes

[cli.md](cli.md) lists every exit code. The panel acts on these:

| Exit | What the panel does |
| --- | --- |
| 0 | Success |
| 4 on save | The item exists: ask the Replace question; saving again uses `--replace` |
| 6 on a write | Open a dialog with the helper's full message and send a notification |
| 8, 9 or any other from `type` | Show an Omarchy notification titled "omapass" with the helper's error text. The panel is closed by then |
| 3 from `focus-snapshot` | No snapshot: Type is unavailable |
| anything else | A short line in the footer, or in the list's error state for `list` |

`Vault.qml` sends notifications through
`/usr/share/omarchy/bin/omarchy-notification-send` (`-u critical --app-name
omapass`), cut to 400 characters. The message is only ever the helper's error
text.

### The clipboard-serve handshake

`copy` and `copy-text` call `clipboard_copy` (`secret_io.py`). It checks the
runtime directory, then starts
`/usr/bin/python3 -I bin/omapass-keyring clipboard-serve` as a detached
process (`start_new_session=True`) with the secret on its stdin and a minimal
environment. The caller then blocks on one line of the child's stdout.

`clipboard-serve` reads the secret, starts
`wl-copy --foreground --sensitive --type text/plain` as its own child with
`TMPDIR` set to the checked runtime directory, writes the secret to wl-copy's
stdin and waits `CLIPBOARD_START_S` (0.1 s) for wl-copy to exit. It then
prints `ok` (wl-copy is still running) or `fail` (it has exited) and flushes.
The caller exits 0 on `ok` and with `wl-copy failed` otherwise.

After the handshake `clipboard-serve` waits until wl-copy exits by itself
(another copy took the selection) or until the TTL (`--ttl`, default
`CLIPBOARD_TTL_S` = 30 s), then terminates wl-copy, which empties the
clipboard. It also stops on SIGTERM. wl-copy is started with `PR_SET_PDEATHSIG`
set to SIGTERM, so it dies with `clipboard-serve`. The user-facing behavior and
its limits are in [clipboard.md](clipboard.md).

### The type pkill pattern

Opening the panel stops any running autotype. `Vault.cancelType` ends the
panel's own `type` process, then runs
`/usr/bin/pkill -TERM -f -- "^/usr/bin/python3 -I <helper path> type "` with
the helper path regex-escaped. Every monitor's bar has its own `Vault`, so the
pattern matches by command line and also stops a `type` that another screen's
panel started. It matches `type --item-stdin` as well, because the pattern
ends at `type `. At most the character already handed to `wtype` is still
typed. See [autotype.md](autotype.md).

### Time bounds

On the panel side, `Vault.qml` checks every 100 ms and stops a read-only helper
that runs too long. The exit then takes the normal path with `timedOut` set.

| Helper | Bound | Message |
| --- | --- | --- |
| `list --json` | 60 s | "The keyring did not answer in time" |
| `copy`, `copy-text` | 20 s | "Copy timed out" |
| `focus-snapshot` | 8 s | Type is unavailable |
| `type`, `store`, `clear`, `generate-*` | none | cutting `type` leaves half a secret in the target window; cutting `store` can leave a duplicate |

In the helper:

| Bound | Value | Where |
| --- | --- | --- |
| Every `hyprctl`, `niri` and `wtype` call | 2 s (`SUBPROCESS_TIMEOUT_S`); on timeout `type` stops with exit 8 (compositor) or 9 (`wtype`) | `common.py` |
| Wait for the target window to be focused | 500 ms, polled every 50 ms | `TYPE_TIMEOUT_MS`, `TYPE_POLL_MS` |
| Wait for every `omarchy-keyboard-panel` layer to unmap | 1 s, then exit 8 "keyboard panel still open" | `PANEL_UNMAP_TIMEOUT_S` |
| Wait for another omapass write | 10 s, then exit 5 | `LOCK_TIMEOUT_S` |
| Wait for the keyring to show a write | 2 s, polled every 50 ms, then exit 6 | `VERIFY_TIMEOUT_S` |
| wl-copy start check | 0.1 s | `CLIPBOARD_START_S` |
| Clipboard lifetime | 30 s | `CLIPBOARD_TTL_S` |

A reload of the shell, disabling the widget or unplugging a monitor destroys
the panel without closing it, and quickshell then kills the helpers it
started. The helper has no SIGTERM handler for `store` or `type`. What that
leaves behind is in [storage.md](storage.md) and [autotype.md](autotype.md).

## 6. Constraints and measurements

**Constraints**

- The helper needs PyGObject (`python-gobject`) for `gi.repository.Secret`.
  `nostr show-npub` additionally needs `python-coincurve` or
  `python-secp256k1`. Isolated mode skips only the user site, so a package in
  the system site-packages is trusted: install them from the distribution.
- Absolute tool paths only: `/usr/bin/python3`, `/usr/bin/wl-copy`,
  `/usr/bin/wtype`, `/usr/bin/hyprctl`, `/usr/bin/niri`, `/usr/bin/pkill`. The
  child environment is reduced to a short allow-list (`common.child_env`).
- `type` writes one character per `wtype` call, so a failed check stops it
  with the rest of the secret unsent. The focus check and the keystroke are not
  atomic: up to one character can reach another window. Only compositor
  support for targeting a surface would remove that. See
  [autotype.md](autotype.md) and [security.md](security.md).
- Hyprland's layer JSON has no keyboard-interactivity field and, on this host,
  no `stableId`; the layer key then falls back to namespace, `address`, `pid`
  and geometry. niri reports `keyboard_interactivity`, so only layers that can
  take the keyboard count there.
- The helper sets `RLIMIT_CORE` to 0 and marks itself non-dumpable. The shell
  does not, so a shell crash while the add form holds a password can put it in
  a core file. See [security.md](security.md).

**Per-character autotype query cost**

Before each character `type` asks the compositor for the focused window and
for the layer-shell surfaces, and on Hyprland whether a session lock is
active: three `hyprctl` queries (`activewindow -j`, `layers -j`,
`monitors -j`). The `wtype` spawn is not included in these numbers.

| Condition | Result |
| --- | --- |
| Idle Hyprland machine, the first two queries | 4 to 7 ms each. Median of 40 runs: 4.6 ms and 6.4 ms in two measurements |
| Load average 33, each of the three queries | About 13 ms each. Median of 40 runs of each: 12.0, 13.2 and 13.1 ms |

These are the author's measurements, carried over from the previous README.
They were not repeated for this page. For a password of N characters, add roughly `N * 3 * query time` to the
typing time. The cost is the price of checking before every character instead
of once.
