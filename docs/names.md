# Names and identity

This page explains what omapass accepts as an account, folder, kind and
secret, how it decides that two items are the same, and what it does when
several items match. Read it when `add` or `store` refuses a value, when a
command exits 4, 11 or 12, or when you move items between folders.

Related pages: [Storage](storage.md), [Security](security.md),
[CLI reference](cli.md).

## Input limits

`add` and `store` take the secret from standard input. They drop one trailing
newline, then refuse:

- an empty account, folder or secret (a kind may be empty),
- control characters in any value, including line breaks and NUL,
- a secret longer than 4096 characters,
- an account, folder or kind longer than 256 characters (counted after NFC
  normalization).

When `add` reads from a terminal, it asks twice, "Password:" and "Confirm:",
and refuses if they differ.

Account, folder and kind also refuse invisible Unicode characters and
surrogates, which could spoof what the panel shows. See
[Invisible characters](#invisible-characters).

These are allowed:

- Backslashes and leading or trailing spaces in secrets.
- Leading and trailing spaces and non-ASCII spaces (NBSP, the U+2000 range,
  U+3000) in account, folder and kind. They are not control or invisible
  characters.
- Private-use characters in names. They are visible glyphs.

The refusals exit 1 with a message such as "account must not contain control
characters or line breaks" (tested: `tests/test_secret_validation.py`).

## Names

Account, folder and kind are normalized to NFC before they are stored.

### Control characters

`add` and `store` refuse control characters: C0, DEL, C1 and U+2028 and
U+2029.

### Invisible characters

`add` and `store` also refuse the characters in Unicode category Cf (bidi
controls, zero-width characters including U+200D, soft hyphen, tag characters)
and category Cs (surrogates). The standard library cannot classify the other
default-ignorable and blank code points, so `INVISIBLE_RANGES` in
`bin/omapass_lib/common.py` lists them:

| Range | What it holds |
| --- | --- |
| U+034F | combining grapheme joiner |
| U+115F, U+1160 | Hangul fillers |
| U+17B4, U+17B5 | Khmer inherent vowels |
| U+180B to U+180F | Mongolian variation selectors |
| U+2060 to U+206F | invisible operators and unassigned slots |
| U+2800 | blank braille pattern |
| U+3164, U+FFA0 | Hangul fillers |
| U+FE00 to U+FE0F | variation selectors |
| U+FFF0 to U+FFF8 | unassigned slots |
| U+E0000 to U+E0FFF | tag characters and variation selector supplement |

Tests: `tests/test_names.py`.

### No look-alike check

omapass has no look-alike check. It does not compare a new name with existing
ones by skeleton, script or case. It does not refuse leading or trailing
spaces, non-ASCII spaces or mixed scripts. `paypal`, `PayPal` and `pаypal`
(Cyrillic `а`) are three different accounts. Exit 7 was the old look-alike
refusal and is no longer used.

Check the name before you copy it. The panel copies, types and removes the
account exactly as stored, including edge spaces.

### Items made by other apps

Another app can store an item with a control or invisible character in its
name. `list --json` adds a `warn` field to every row, one of:

| Value | Meaning |
| --- | --- |
| `control` | The account or the folder has a control character. |
| `invisible` | The account or the folder has an invisible character. |
| `duplicate` | Several items share this account and kind. |
| empty | Nothing to warn about. |

The panel shows a warning sign next to exactly those rows. Plain `list` prints
control and invisible characters as escapes (`\x1b`, `ㅤ`) instead of
sending them to the terminal. `list --json` keeps the names as stored.

### Limitation

The invisible-character check uses Cf and Cs plus the built-in list above. It
does not use the full Unicode `Default_Ignorable_Code_Point` data, so rarer
invisible characters can pass. Look-alike names are not detected at all (see
[No look-alike check](#no-look-alike-check)).

## Control characters in a stored secret

`add` and `store` never store control characters in a secret. An item made by
another app can hold a line break, tab or escape sequence.

`type` would send a line break as Return and submit the form. `type` and
`copy` therefore refuse such a secret with exit 13 and send nothing:

- `stored secret has control characters or line breaks; not typed`
- `stored secret has control characters or line breaks; not copied`

The secret is not trimmed or changed. `get` still prints it, for scripts.

The check covers C0, DEL, C1 and U+2028 and U+2029, the same set `add`
rejects. For a legacy raw item, the one trailing newline is dropped before the
check.

## Identity and overwrite

An item is identified by its account plus its kind. A login and an nsec with
the same account are different items. The folder is not part of the identity.

### Overwrite

`add` and `store` exit 4, "already exists: ...", instead of replacing an
existing item, whatever its folder. Pass `--replace` to overwrite it. The
panel asks "Replace the secret for ...?" first. Because of this rule, omapass
never creates a duplicate (tested: `tests/test_duplicates.py`,
`tests/test_no_overwrite.py`).

Every replace creates a new encoded item and then deletes the old copies. The
daemon takes a secret and a label as two calls, so an in-place update could
stop between them and leave the new secret in the old folder. This order
cannot:

- A kill leaves the old and the new item, each whole (tested in the sandbox by
  killing the helper after the create: `tests/test_replace_kill.py`).
- It never leaves a base64 secret without its tag.
- If only the delete fails, the message says the new value is stored and an old
  copy remains. `get` prefers the encoded copy, and rerunning `--replace`
  removes the leftover.

`--folder` on `add` and `store` names the folder the item ends up in. Replacing
with another folder moves the item there.

### Several items with one identity

Two items can share account and kind in different folders, because another app
or an older version stored one. Then `get`, `copy`, `type`, `clear`, `rm` and
`exists` refuse with exit 12 and do nothing:

```
ambiguous: 2 items in folders 'Home', 'Work'; pass --folder
```

`--folder VALUE` picks one. The value is the item's folder, its label.
`rm --folder VALUE -- <account>` removes only that item. `--kind` picks the
kind; the default is a plain login. Each of these commands acts on exactly one
item.

`list --json` marks all rows that share an account and kind with
`warn: "duplicate"`, in one folder or in several.

With `--replace`, copies merge only when all of them have the same folder.
Copies in several folders exit 12 and nothing is changed:

```
refusing to replace: 2 items share this account in folders 'Home', 'Work'; remove the unwanted ones with rm --folder
```

Copies in the same folder count as one item:

- `get` prefers the encoded one.
- `rm` removes them all.
- `store --replace` collapses them.

### NFC and NFD

Names are stored in NFC. An item an older version stored in decomposed (NFD)
form counts as the same account as its NFC name, so `--replace` with either
spelling updates it and stores it in NFC.

`get`, `copy`, `type`, `clear` and `exists` look a name up in this order and
stop at the first spelling that finds an item:

1. exactly as given,
2. with the account in NFC, the kind in NFC, then both,
3. under any stored spelling that differs only in normalization.

A decomposed or composed spelling therefore finds the stored item, and an
older item stored as typed stays reachable. An exact match always wins, so a
lookup never returns a different item than the one named. A `--folder` matches
the label as given or in NFC.

If a legacy keyring holds the same name in NFC and in NFD as two items,
`--replace` exits 11 and changes nothing, because the two may hold different
secrets:

```
refusing to replace: 2 items differ only in Unicode normalization ('caf\xe9', 'cafe\u0301'); remove the one you do not want with rm, then retry
```

Remove the one you do not want with `rm -- <exact spelling>`, then retry
(tested: `tests/test_nfd_twins.py`).

### Names that start with a dash

A name that starts with `-` can be written `--account=-name`, or after `--`
for the commands that take the account as an argument:

```sh
omapass get -- -name
omapass rm -- -name
omapass store --account=-name --folder=-f
```

The panel passes `--account=-name`. Tested: `test_dash_leading_name_round_trip`
in `tests/test_lookup_args.py`.

### Concurrent stores

Two stores of the same new name run one after the other because of the
[write lock](storage.md#write-lock). The first creates the item and exits 0.
The others exit 4, "already exists", so exactly one item is left. Four parallel
stores of one name over six rounds are tested (`tests/test_write_lock.py`).

Another app is not bound by the lock, so it can still create a duplicate. The
rules above are how omapass copes with one.

## Limitation

omapass does not detect look-alike names: homoglyphs such as Cyrillic `а` for
Latin `a`, mixed scripts, leading or trailing spaces and non-ASCII spaces.
They are stored and shown as typed. Only control characters and invisible
characters are refused (see [Input limits](#input-limits)).
