# Storage

This page explains how omapass keeps a secret in the gnome-keyring, how it
serializes and checks every write, and what happens when a write is cut short.
Read it when you script omapass, when a write fails with exit 5 or 6, or when
you want to know what the keyring file holds.

Related pages: [Names and identity](names.md), [Security](security.md),
[CLI reference](cli.md), and the guide
[How to check the keyring after an omapass write error](how-to-check-the-keyring.md).

## Storage format

omapass stores each login as one item in the default keyring, with the
attributes `service=omapass`, `account` and, for a Nostr key, `kind=nostr`.
The item label is the folder.

gnome-keyring writes a plaintext (empty-password) keyring's secrets raw. It
reads them back with key-file unescaping. A literal `\n`, `\\`, a leading space
or a trailing backslash would therefore change after a restart, and a `\n`
could corrupt the file on the next write.

omapass avoids this:

- It stores each secret base64-encoded and tags the item with the attribute
  `enc=b64`.
- Every read (`get`, `copy`, `type`, the Nostr commands) decodes it. A value
  that is not valid base64 of UTF-8 text stops the command with "stored secret
  is corrupt".
- Account, folder (the label) and kind are escaped by gnome-keyring itself and
  come back unchanged.
- The test `test_secret_round_trips_after_restart` stores secrets such as
  `a\nb`, `a\\b`, a leading space, a trailing space, a trailing backslash and
  non-ASCII text, restarts the daemon, and reads them back.

### Items from older versions and other apps

An item without the `enc` attribute is a legacy item. omapass reads it as a
raw value and drops one trailing newline. The next `--replace` of that item
rewrites it in the encoded form (tested: `test_legacy_items_stay_readable_and_get_upgraded`).

An item made by another app is raw too. omapass never edits it in place; see
[Identity and overwrite](names.md#identity-and-overwrite) for how a replace
works.

## Write lock

`store`, `add`, `generate-nostr`, `nostr new`, `rm`, `clear` and `nostr rm`
take an exclusive `fcntl.flock` before they touch the keyring. One omapass
write runs at a time.

- **Where:** `$XDG_RUNTIME_DIR/omapass.lock`, but only if that directory is
  absolute, owned by you and mode 0700. Otherwise `/tmp/omapass-<uid>.lock`.
- **How it is opened:** with `O_NOFOLLOW` and mode 0600. The file must be a
  regular file you own. A symlink, a file of another user or a path that
  cannot be opened is refused.
- **How long it is held:** from the existence check through create, delete and
  verify. The kernel releases it when the helper exits, even if the helper is
  killed.
- **How long it waits:** up to 10 seconds for another omapass write.
- **Order:** invalid input is refused before the lock is taken.

Two stores of the same new name therefore run one after the other. One creates
the item and the other exits 4, "already exists". Four parallel stores over
six rounds leave exactly one item each round (tested: `tests/test_write_lock.py`).

When the lock cannot be had, nothing is written and the helper exits 5:

| Message | Meaning |
| --- | --- |
| `another omapass write is running; retry. Nothing was written.` | Another omapass write held the lock for 10 seconds. |
| `cannot open a safe omapass write lock; retry. Nothing was written.` | The lock file is a symlink, belongs to another user, is not a regular file or cannot be opened. |

The lock orders omapass processes only. Another app is not bound by it; see
[Residual race](#residual-race).

## Write guard

Before every write, with the lock held, the helper checks the default keyring
and writes only if it is healthy. If it is not, it exits 5, writes nothing and
prints counts, never values.

### Finding the file

The helper finds the keyring file from the daemon's own environment: the
`XDG_DATA_HOME` or `HOME` in `/proc/<pid>/environ` of the owner of
`org.freedesktop.secrets`. If the file cannot be located, read or parsed, the
helper exits 5 and writes nothing. The guard reads the file once. It does not
wait or read again.

### Plaintext keyring

A plaintext keyring is a GLib.KeyFile. One rule decides whether it is safe to
rewrite: `rewrite_risks` in `bin/omapass_lib/keyfile_guard.py`. The same rule
runs three times:

1. before the write,
2. after the write,
3. in `omapass doctor`, which the sandbox health check
   (`tests/sandbox/keyring-health.py`) runs.

The three cannot disagree. Items count as in the daemon: every group except
`[keyring]` and groups containing `:` (attributes and ACLs).

The rule asks, per item, whether the rewrite makes the item worse than it
already is. The daemon rewrites the value it serves as a raw `secret=` line,
or as hex in `binary-secret=` if the value is not UTF-8. An item is unsafe
if any of these holds:

- the raw line would break the file,
- the line would reload to a different value than the current lines reload to
  without the write,
- the reloaded value would not itself survive the next rewrite. The daemon
  watches the file and may reload it at any time, for example right after
  the write.

A value the daemon already loses on reload is not blocked, because the rewrite
does not make it worse:

- leading spaces or CR (`"  pad  "` reloads as `pad  `, before or after a
  restart),
- an invalid escape such as `a\b`, whose bytes the rewrite leaves unchanged.

A literal `\n` is always unsafe. Once the daemon reloads the file it serves a
newline, and the next rewrite would break the file.

The guard also refuses (exit 5) when:

- a group is not served by the daemon,
- a `binary-secret=` is not hex,
- a group has both `secret=` and `binary-secret=` (the daemon keeps one and
  drops the other),
- a group repeats either line,
- the file holds a different number of items than the daemon serves.

The daemon omits `secret=` for an empty secret and keeps a non-UTF-8 secret as
hex. Both reload intact and are allowed.

The unsafe item belongs to whichever app stored it. omapass cannot fix it.
Remove or re-save the item in that app, then retry. The message says "retry"
when another app may have been writing.

| Message (exit 5) | Cause |
| --- | --- |
| `refusing to write: cannot read the default keyring file, so it cannot be checked. Nothing was written.` | The file could not be located or read. |
| `refusing to write: the default keyring file does not parse. Nothing was written.` | The file is not a valid key file. |
| `refusing to write: N item(s) in the default keyring would be corrupted or lost by a rewrite (...). Nothing was written.` | The rule flagged N items. A count mismatch adds "the daemon serves a different number of items than the file has (another app may be writing: retry)". |

Checks that need no write run first. A name that already exists (exit 4),
normalization twins (exit 11) and duplicates in several folders (exit 12)
are reported before the guard looks at the file.

### Encrypted keyring

An encrypted keyring file starts with the magic bytes `GnomeKeyring\n\r\0\n`.
The plaintext hazard does not apply to it. The helper does not parse its
header and does not run the file checks. The write is confirmed only by reading
it back through the Secret Service.

### After the write

The Secret Service may save the file after the D-Bus call returns, so the
helper polls for up to 2 seconds (every 50 ms) until the keyring reflects the
change.

For a plaintext keyring, all of these must hold:

- After a store, the file holds exactly one item with the same service,
  account and kind, tagged `enc=b64`, with the new base64 secret and label.
  After a clear, it holds none.
- Every item in the file passes the same `rewrite_risks` rule.
- The item count is the count before the write plus or minus what the command
  did. An item another app lost or damaged in the meantime is caught.

For an encrypted keyring, the file is not read. The Secret Service must show
the target:

- After a store, exactly one item with our attributes (the daemon may add its
  own; attributes only the old item had are not copied), the expected label
  and the expected base64 secret.
- After a clear, none. A duplicate in another folder may remain.

### Exit 6 messages

| Message start | Meaning |
| --- | --- |
| `THE WRITE FAILED (...). The daemon could not save the change.` | The daemon refused the write, for example because the keyring directory is read-only or full. Check the directory, then check the keyring. |
| `THE KEYRING FILE MAY BE DAMAGED: it no longer parses after this write` | The file stopped parsing after the write. Do not log out or reboot. Back up the keyring file now. |
| `THE WRITE COULD NOT BE CONFIRMED (reason). Do not trust it` | The check failed otherwise. The change may exist only in the daemon's memory and be lost on restart, or another item may have been altered. |

Each message ends with a pointer to `omapass doctor` and to
[How to check the keyring after an omapass write error](how-to-check-the-keyring.md).
Tests: `tests/test_write_guard.py` (guard, race, encrypted keyring, damaged
file) and `tests/test_doctor.py` (the pointer in the messages).

Two other write failures exit 1 instead. A `create` that returns no item stops
before any old copy is deleted ("could not create item"). If only the delete of
an old copy fails, the message says the new value is stored and an old copy
remains; see [Identity and overwrite](names.md#identity-and-overwrite).

### Residual race

The Secret Service has no lock, and the write lock binds only omapass. Another
app can still store a raw value between the check and the daemon's write.

The post-write check detects such damage but cannot prevent it. It cannot see:

- a value the daemon already normalized or dropped cleanly, for example a
  malformed `binary-secret=` line,
- an unrelated item another app added in that window. That one is reported
  as a count mismatch.

For an encrypted keyring there is no file check at all. Only the daemon's
memory view confirms the write.

## What `omapass doctor` checks

`omapass doctor` checks the keyring and changes nothing. It never writes and
never unlocks. It prints counts and item ids, never secrets or account names.

It does these steps, in this order:

1. Parses each `*.keyring` file in `~/.local/share/keyrings`. An encrypted
   file is reported as "encrypted (not parsed)" and does not fail.
2. Prints the `default` pointer file, if there is one.
3. Asks the Secret Service for the `default` alias. An alias that points to
   nothing fails.
4. Stops with exit 1 if a file did not parse, even when the keyring is also
   locked.
5. Stops with exit 10 if the default keyring is locked. Unlock it and run
   `doctor` again.
6. Reads every item back through the Secret Service. For an `enc=b64` item it
   checks that the value is base64 of UTF-8 text.
7. For a plaintext keyring, applies the write guard's rule and compares the
   item count of the file with the daemon's.
8. For an encrypted default keyring, only checks that the items read back.
   The final line says "encrypted file not compared".

Exit 0 means healthy. Exit 1 is a problem; its lines start with `FAIL`. See
[CLI reference](cli.md#omapass-doctor) for the output. The guide
[How to check the keyring after an omapass write error](how-to-check-the-keyring.md)
shows what to do with the result.

## Limitations

- **Reload or kill during a store.** Reload, disable and monitor unplug
  destroy the panel without closing it. Quickshell then kills the helper it
  started (SIGKILL; no handler runs; observed in
  `tests/qml/test_data_runtime.py`). The helper has no SIGTERM handler for
  `store` or `type`.
  - A `type` stops with part of the secret already typed and no Enter.
  - A `store` stops wherever it is. The helper creates the new item before it
    deletes an old copy, so the worst case is a duplicate, never a half-written
    item. After a kill the old and the new item both exist whole (tested in
    the sandbox: `tests/test_replace_kill.py`). `get` may return either.
    `--replace` merges them if they share a folder; otherwise
    `rm --folder` removes the unwanted one. The daemon, not the helper, writes
    the file.
  - A killed shell (`omarchy-restart-shell`) does not run this path. Its
    helpers may outlive it (orphaned child processes of a restarted shell
    were seen on the development host), and the next panel open stops a
    `type` it finds.
- **Another app can write at the same time.** See
  [Residual race](#residual-race).
