# Clipboard

This page explains how omapass copies a password or an account name, how long
the copy lasts, and what it does not protect. To type a password instead of
copying it, see [How to type into a window](how-to-type-into-a-window.md).

## What copies

- **Enter** (or a click on a row, or the copy button) copies the selected
  password. For a Nostr key it copies the key. The footer says "Copied password"
  or "Copied key".
- `u`, **Ctrl+U** in the search field, or "Copy account" in the row menu copies
  the account name. The footer says "Copied account".
- `omapass copy -- <account>` copies from the command line. See [CLI](cli.md).

All of them use the same mechanism. The helper's `copy` and `copy-text`
commands start a detached `clipboard-serve` helper. omapass runs no daemon of
its own.

## How the copy works

`clipboard-serve` runs this command as its own child:

```
wl-copy --foreground --sensitive --type text/plain
```

It writes the secret to wl-copy's standard input. The secret never goes to argv
or the environment. `--sensitive` is the wl-copy option that marks the text as
sensitive, so it stays out of clipboard managers that honor the hint. The
tests do not check this. They run a history watcher that only reads and
discards.

wl-copy buffers its input in a temporary file. That file lives in
`$XDG_RUNTIME_DIR`, not in `/tmp`. So the helper refuses to copy (with a message
that starts "refusing to copy:") unless `$XDG_RUNTIME_DIR` is:

- an absolute path,
- a directory,
- owned by you,
- mode 0700 (no access for group or others), and
- on tmpfs or ramfs.

The helper resolves the path it checked and hands that resolved path to wl-copy
as `TMPDIR`, not the variable or a symlink. A swapped symlink therefore cannot
move the buffer to disk.

## How long the copy lasts

The helper reports ok or fail to its caller within 0.1 s of starting wl-copy
(`CLIPBOARD_START_S`):

- If wl-copy has already exited with an error, it reports fail. The command then
  exits with "wl-copy failed".
- Otherwise it reports ok.

After that, the helper keeps the copy until the first of these:

- Another copy replaces the selection. wl-copy exits by itself, and the new
  copy keeps its own content.
- 30 seconds pass (`CLIPBOARD_TTL_S`). The helper kills wl-copy, which empties
  the clipboard.
- The helper is killed. wl-copy dies with it, and the clipboard is emptied.
  SIGTERM does the same through a clean exit.

The copy can be pasted any number of times within those 30 seconds. There is no
paste-once: the clipboard is not emptied after a paste.

## What the test checks

`tests/test_clipboard_wayland.py` runs in the Docker sandbox. It starts a
headless sway and a `wl-paste --type text --watch` history watcher with the same
command line as Omarchy's. It starts `clipboard-serve` directly and asserts:

- The copy can be pasted twice, and the watcher does not end the helper.
- An unpasted copy is cleared by the TTL. The test uses `--ttl 3`, waits at
  least 2.5 s, and then expects the clipboard to be empty. The default 30 s is
  not measured.
- Copying something else ends the helper, and the new content is not cleared.
- Killing the helper clears the clipboard.
- The secret is not in the argv of the helper or of wl-copy, and not in
  wl-copy's environment. The helper owns exactly one child, wl-copy.
- A process of the same user can read the secret from wl-copy's buffer through
  `/proc/<pid>/fd/<n>`. This test documents a limit. It also fails if
  wl-clipboard stops buffering stdin in a temporary file, which the design
  relies on (wl-clipboard 2.x).
- `copy-text` works end to end: it exits 0 and the pasted text is the input.

`tests/test_runtime_dir.py` covers the `$XDG_RUNTIME_DIR` checks: a private
tmpfs directory is accepted, and a disk-backed one, a group- or
other-accessible one, one owned by someone else, a missing, relative or
non-directory path, and a symlink to a disk-backed directory are refused. For a
symlink to a tmpfs directory, the resolved target is passed on. A refused
`copy` does not start the helper.

The tests do not cover typing into another window. See
[Testing](testing.md).

## Limits

- **The clipboard is not emptied after a paste.** For up to 30 seconds, any
  process of your user, or any paste, can read the secret again. Any process of
  your user can also read a running wl-copy's buffer through
  `/proc/<pid>/fd/<n>`. Yama's `ptrace_scope` does not restrict that.
- **Only the helper is hardened against core dumps.** It sets `RLIMIT_CORE` to 0
  and marks itself non-dumpable at startup, and `clipboard-serve` runs the same
  startup code. The non-dumpable flag does not survive `exec`, so `wl-copy` and
  `wl-paste` are dumpable again. They write no core file, because child
  processes inherit the core limit. Their memory is not protected from other
  processes of your user.
- **A same-user process can read more than the clipboard.** It can read the
  whole unlocked keyring through the Secret Service. omapass therefore does not
  try to harden same-user memory further. It shortens how long wl-copy holds the
  secret instead.
- **A secret with control characters is not copied.** `copy` refuses it (exit
  13, "stored secret has control characters or line breaks; not copied") and
  the clipboard is untouched.

For the wider threat model, see [Security](security.md).

## Troubleshooting

- **"refusing to copy: XDG_RUNTIME_DIR is required ..."** or another "refusing
  to copy: ..." message: `$XDG_RUNTIME_DIR` is unset, relative, not yours, not
  mode 0700, or not on tmpfs. A normal systemd login session sets it correctly.
- **"wl-copy failed":** wl-copy exited with an error right after starting. Check
  that a Wayland session is running and that `/usr/bin/wl-copy` exists.
- **"Copy timed out":** the panel stops a copy helper that runs longer than
  20 s.
- **The paste is empty:** 30 seconds passed, or something else was copied.
