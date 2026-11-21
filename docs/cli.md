# CLI reference

`omapass` is the command-line face of the helper. The panel calls the same
commands.

- `bin/omapass` is a small wrapper. It runs
  `/usr/bin/python3 -I bin/omapass-keyring "$@"`.
- `bin/omapass-keyring` is the entrypoint that parses the arguments (its
  `build_parser`) and prints the usage text (`usage()`).
- Run `omapass` with no arguments and it prints the usage and exits 1.
  `omapass -h` or `omapass --help` prints it and exits 0.

Put `bin/omapass` on your `PATH`, or call it by its full path. For the
installed plugin that path is
`~/.config/omarchy/plugins/io.github.this-is-npc.omapass/bin/omapass`.

The examples below use synthetic names. They are written by hand from the
code's format strings, not captured from a keyring. To try commands without
touching your own keyring, use the disposable one that `scripts/test-sandbox`
provides (see [Testing](testing.md)).

Related pages: [Storage](storage.md), [Names and identity](names.md),
[Security](security.md), [Clipboard](clipboard.md), [Autotype](autotype.md).

## Commands at a glance

```
omapass list [--json]
omapass doctor
omapass get [--kind K] [--folder F] [--yes] (--account <id> | [--] <account>)
omapass add --account <id> --folder <name> [--kind K] [--replace]
omapass store --account <id> --folder <name> [--kind K] [--replace]
omapass exists --account <id> [--kind K] [--folder F]
omapass clear [--kind K] [--folder F] (--account <id> | [--] <account>)
omapass rm [--kind K] [--folder F] [--] <account>
omapass copy [--kind K] [--folder F] (--account <id> | [--] <account>)
omapass copy-text
omapass type [--kind K] [--folder F] [--compositor hyprland|niri --expect-id ID] (--account <id> | [--] <account>)
omapass focus-snapshot
omapass generate-password
omapass generate-nostr [--account <id>] [--folder <name>] [--replace]
omapass nostr new [--account <id>] [--folder <name>]
omapass nostr show-npub [--account <id> | [--] <account>]
omapass nostr show-nsec [--account <id> | [--] <account>]
omapass nostr rm [--account <id> | [--] <account>]
omapass clipboard-serve [--ttl <seconds>]       # internal
```

`copy`, `type` and `clear` also take `--item-stdin`; see
[Security](security.md#item-on-stdin).

## Rules for all commands

- **A name that starts with `-`:** write `--account=-name`, or put `--` before
  the positional account (`omapass get -- -name`).
- **Identity:** an item is its account plus its kind. `--kind` defaults to a
  plain login. Several items with the same account and kind in different
  folders are never guessed between; the command exits 12 and does nothing. Pick
  one with `--folder`. See [Names and identity](names.md#identity-and-overwrite).
- **Writes:** `add`, `store`, `clear`, `rm`, `generate-nostr` and the Nostr
  `new` and `rm` take the [write lock](storage.md#write-lock) and run the
  [write guard](storage.md#write-guard).
- **Errors:** a failure prints one line on stderr and exits non-zero. An
  unreachable keyring prints `keyring unavailable: ...` and exits 10, never a
  traceback. Any other unexpected failure prints `internal error: <ClassName>`
  and exits 1.
- **Secrets:** they never appear in a command line, an environment or the
  messages.

## Listing and checking

### `omapass list`

Lists the saved logins: account and folder, never secrets.

```sh
omapass list
```

```
alice@example.org	Work
bob	Home
```

Each line is the account, a tab, and the folder. Control and invisible
characters are printed as escapes (`\x1b`, `ㅤ`). Rows are sorted by
account.

| Option | Effect |
| --- | --- |
| `--json` | Prints one JSON array. Each row has `account`, `folder`, `kind` and `warn`. Names stay as stored. |

```sh
omapass list --json
```

```
[{"account": "alice@example.org", "folder": "Work", "kind": "", "warn": ""}, {"account": "demo", "folder": "Nostr", "kind": "nostr", "warn": ""}]
```

`warn` is `control`, `invisible`, `duplicate` or empty; see
[Names](names.md#items-made-by-other-apps). A keyring that cannot be read exits
10; it is never shown as an empty list.

### `omapass exists`

Asks whether one item exists. It prints nothing.

```sh
omapass exists --account alice@example.org --folder Work
echo $?
```

| Option | Effect |
| --- | --- |
| `--account ID` | Required. `exists` has no positional account. |
| `--kind K` | The kind. Default: a plain login. |
| `--folder F` | Only an item in this folder. |

Exit 0 means it exists, 1 means it does not. Exit 10 means the keyring cannot
be reached, and 12 means several items match (pass `--folder`). Only 0 and 1
are definite answers.

### `omapass doctor`

Checks the keyring and changes nothing. It never writes and never unlocks the
keyring. It prints counts and item ids, never secrets. What it checks is on
[Storage](storage.md#what-omapass-doctor-checks).

```sh
omapass doctor
```

Example of a healthy plaintext keyring:

```
OK   file Default_keyring.keyring: parses, 3 items
OK   pointer default -> 'Default_keyring'
OK   alias default -> /org/freedesktop/secrets/collection/Default_5fkeyring
OK   item 1
OK   item 2
OK   item 3
OK   items: 3 read back, safe to rewrite
```

Example of a keyring with a problem (exit 1):

```
OK   file Default_keyring.keyring: parses, 3 items
OK   pointer default -> 'Default_keyring'
OK   alias default -> /org/freedesktop/secrets/collection/Default_5fkeyring
OK   item 1
OK   item 2
OK   item 3
FAIL items: 1 item(s) are not safe to rewrite (see the helper's rule)
```

An encrypted keyring file shows as `OK   file NAME: encrypted (not parsed)`, and
the last line says `encrypted file not compared`.

| Exit | Meaning |
| --- | --- |
| 0 | Healthy. |
| 1 | A problem. The lines that explain it start with `FAIL`. This includes a file that does not parse (even if the keyring is also locked), no default keyring, an unreadable item, and a Secret Service error. |
| 10 | The default keyring is locked. `doctor` does not unlock it. Unlock it and run `doctor` again. |

See [How to check the keyring after an omapass write error](how-to-check-the-keyring.md).

## Reading a secret

### `omapass get`

Prints the secret on stdout, with no trailing newline added.

```sh
omapass get -- alice@example.org | wl-copy
omapass get --yes --account alice@example.org
```

| Option | Effect |
| --- | --- |
| `--account ID` or `[--] ACCOUNT` | The account. |
| `--kind K` | The kind. Default: a plain login. |
| `--folder F` | Picks one of several items that share account and kind. |
| `--yes` | Allows printing to an interactive terminal. |

On a terminal without `--yes`, `get` exits 1 ("refusing to print a secret to a
terminal; pipe the output or pass --yes"). `get` prints a secret that has
control characters; `copy` and `type` refuse it (exit 13). Exit 1 also
covers a missing item ("no secret for account: ...").

### `omapass copy`

Copies the secret to the clipboard through a detached helper. The copy lasts
until another copy replaces it, or 30 seconds. See [Clipboard](clipboard.md).

```sh
omapass copy -- alice@example.org
```

Options: `--account`, `--kind`, `--folder`, `--item-stdin`. Exit 13 for a stored
secret with control characters. It refuses (exit 1) unless `$XDG_RUNTIME_DIR`
is a private tmpfs directory, or if `wl-copy` fails.

### `omapass copy-text`

Copies standard input to the clipboard, with the same lifetime as `copy`. It
takes no options.

```sh
printf 'text' | omapass copy-text
```

### `omapass type`

Types the secret into the focused window, one character per `wtype` call. See
[Autotype](autotype.md) and
[How to type into a window](how-to-type-into-a-window.md).

```sh
omapass type -- alice@example.org
```

| Option | Effect |
| --- | --- |
| `--account ID` or `[--] ACCOUNT` | The account. |
| `--kind K`, `--folder F` | As for `get`. |
| `--compositor hyprland\|niri` | The compositor of the target window. Any other value is a bad argument (2). |
| `--expect-id ID` | The window the secret is for. The panel passes it with `--compositor`. |
| `--item-stdin` | Take the item from one JSON object on stdin. |

When `--compositor` or `--expect-id` is missing, `type` takes the focused
window now and exits 3 if there is none. Typing stops with exit 8 when focus,
the layer-shell surfaces or the session lock change or cannot be read, and with
exit 9 when `wtype` fails or `/tmp` is not safe for it.

### `omapass focus-snapshot`

Prints the focused window as JSON. The panel calls it when it opens.

```sh
omapass focus-snapshot
```

```
{"compositor": "hyprland", "id": "42"}
```

Exit 3 ("no compositor focus available") when neither `hyprctl` nor `niri`
reports one.

## Writing

### `omapass add` and `omapass store`

Create one item. Both refuse (exit 4) to replace an existing account and kind
unless `--replace` is given. The difference is where the secret comes from:

- `store` reads the secret from standard input until the end.
- `add` asks "Password:" and "Confirm:" on a terminal, and otherwise reads
  standard input like `store`.

Both drop one trailing newline and validate the values; see
[Input limits](names.md#input-limits).

```sh
printf 'example-secret' | omapass store --account alice@example.org --folder Work
printf 'new-secret' | omapass store --account alice@example.org --folder Home --replace
omapass add --account bob --folder Home
```

| Option | Effect |
| --- | --- |
| `--account ID` | Required. |
| `--folder NAME` | Required. The folder is the item's label. `--label` is a synonym. |
| `--kind K` | The kind. Default: a plain login. |
| `--replace` | Replace an existing item with this account and kind. |

Without `--account` or a folder the command exits 1 ("store requires
--account", "store requires --folder or --label"). Messages and codes for
refusals: exit 4 (exists), 5 (unsafe keyring or write lock), 6 (write not
confirmed), 11 (NFC and NFD twins), 12 (items in several folders); see
[Exit codes](#exit-codes).

### `omapass clear` and `omapass rm`

Remove one item. `rm` and `clear` do the same; `rm` takes only the positional
account.

```sh
omapass rm -- alice@example.org
omapass rm --folder Work -- alice@example.org
omapass clear --account bob --kind note
```

Options: `--kind`, `--folder`, and for `clear` `--account` or a positional
account and `--item-stdin`. A missing item exits 1 ("no such item: ...").
Copies of one item in the same folder are all removed; items in several folders
exit 12 unless `--folder` picks one.

### `omapass generate-password`

Prints one random password (`secrets.token_urlsafe(18)`, 24 characters) and
stores nothing.

```sh
omapass generate-password
```

## Nostr

omapass stores an optional Nostr secret key (nsec) in the same keyring, as an
item of kind `nostr`.

| Command | Default account | Default folder |
| --- | --- | --- |
| `generate-nostr` | `nostr:default` | `Nostr` |
| `nostr new` | `nostr:default` | `Nostr` |
| `nostr show-npub` | `nostr:default` | |
| `nostr show-nsec` | `nostr:default` | |
| `nostr rm` | `nostr:default` | |

### `omapass generate-nostr`

Generates a key and stores it. It prints one JSON object with no secret.

```sh
omapass generate-nostr --account demo --folder Nostr
```

```
{"ok": true, "account": "demo", "npub": "npub1..."}
```

The `npub` field is left out when no Nostr crypto package is installed.
Options: `--account`, `--folder`, `--replace`. Without `--replace`, an existing
item exits 4.

### `omapass nostr new`

Generates a key, stores it and prints the npub.

```sh
omapass nostr new
```

Options: `--account`, `--folder`. It never replaces; an existing item exits 4.
Without `python-coincurve` or `python-secp256k1`, it prints a note to install
one instead of the npub. The key is stored either way.

### `omapass nostr show-npub`

Prints the public key. It needs `python-coincurve` or `python-secp256k1` (the
PyPI packages `coincurve` and `secp256k1`); without them it exits 1 ("npub
requires python-coincurve or python-secp256k1"). The account is `--account` or
one positional argument.

### `omapass nostr show-nsec`

Prints the secret key after you type `yes`. It needs a terminal on both stdin
and stdout, and refuses otherwise ("nostr show-nsec requires an interactive
terminal"). A different answer exits 1 ("confirmation failed").

### `omapass nostr rm`

Removes the Nostr item. The account is `--account` or one positional argument.

## Internal command

`omapass clipboard-serve [--ttl SECONDS]` is the detached helper that `copy` and
`copy-text` start. It reads the secret on stdin, keeps it on the clipboard until
another copy replaces it or `--ttl` seconds pass (default 30), and prints `ok`
or `fail`. Do not call it yourself.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | Other errors, including a bad value, a missing item, and for `exists` that the item does not exist. |
| 2 | Bad arguments (argparse), including an unknown command. |
| 3 | No compositor focus, including a missing, failing or hung `hyprctl` or `niri`. Raised by `focus-snapshot`, and by `type` without both `--compositor` and `--expect-id`. The panel always passes both, so it gets 8 instead, shown as "Focus changed". |
| 4 | The item already exists (`add`, `store`, `generate-nostr` and `nostr new` without `--replace`), including when another omapass store of the same new name held the write lock first. |
| 5 | Nothing was written because the keyring is not safe to write (the message says "retry" when another app may have been writing), or because the write lock could not be had ("another omapass write is running; retry." after 10 seconds, or "cannot open a safe omapass write lock"). See [Write guard](storage.md#write-guard). |
| 6 | The write could not be confirmed or the file is damaged. The message says to run `omapass doctor` and points to [How to check the keyring after an omapass write error](how-to-check-the-keyring.md). |
| 7 | Unused. It was the look-alike refusal, which no longer exists. |
| 8 | `type` aborted because focus or the layer-shell surfaces changed, an omapass or other keyboard panel stayed open, a session lock was seen, or any of those could not be read or determined. Nothing more is typed. |
| 9 | `wtype` failed or timed out, or `/tmp` is not safe for it. |
| 10 | The keyring or D-Bus cannot be reached, the default keyring is locked (the unlock was refused or dismissed) or there is none. Any command that needs the keyring, including `exists`, which returns 0 or 1 only for a definite answer. The message is one line, `keyring unavailable: ...`. For `doctor`, 10 means the default keyring is locked. |
| 11 | `add` or `store` with `--replace` found items whose names differ only in Unicode normalization. |
| 12 | Several items share the account and kind, and the command would have to guess. Pass `--folder`. |
| 13 | `copy` or `type` refused a stored secret with control characters. |

The helper never passes `wtype`'s own status through.
