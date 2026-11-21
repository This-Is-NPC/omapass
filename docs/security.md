# Security

This page lists how the omapass helper protects a secret while it handles it,
and where that protection ends. Read it when you need to know what another
process of your user can see.

The clipboard and autotype have their own protections:

- [Clipboard](clipboard.md): the 30-second lifetime, `--sensitive`, the
  `$XDG_RUNTIME_DIR` buffer.
- [Autotype](autotype.md): focus, layer and session-lock checks, the `/tmp`
  rule.

Related pages: [Storage](storage.md), [Names and identity](names.md),
[CLI reference](cli.md).

## Pinned PATH and Python

The helper does not look programs up on `PATH`.

- `bin/omapass` runs `/usr/bin/python3 -I bin/omapass-keyring`. The `-I`
  (isolated) flag ignores `PYTHON*` variables and the user site directory.
- `bin/omapass-keyring` sets `PATH` to `/usr/bin:/bin` at startup.
- It runs `wl-copy`, `wtype`, `hyprctl` and `niri` by absolute path
  (`/usr/bin/...`) and refuses a non-absolute path.
- Child processes get a small environment, not yours: `PATH` and, if set,
  `HOME`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`,
  `HYPRLAND_INSTANCE_SIGNATURE`, `NIRI_SOCKET`, `LANG`, `LC_ALL` and
  `XDG_SESSION_TYPE`.
- On Python 3.11 and later, `-I` implies `-P`, which leaves the script's
  directory off the import path. The entrypoint therefore adds its own
  directory to `sys.path`.

Tests: `test_list_subprocess_ignores_path_poison` in
`tests/test_helper_security.py`, `tests/test_static_guards.py`.

Isolated mode skips only the user site. A Python package of the right name in
the system site-packages is trusted. This matters for the optional Nostr
backends (`coincurve`, `secp256k1`): install them from your distribution.

## Item on stdin

The panel passes the item it acts on to `copy`, `type` and `clear` as one JSON
object on stdin, with `--item-stdin`. Account names and the window id stay out
of the process's command line, which other local users can read in `/proc`
(this host mounts `/proc` without `hidepid`).

```sh
printf '{"account": "alice@example.org", "folder": "Work"}' | omapass copy --item-stdin
```

The object holds strings only:

| Field | Required | Used by |
| --- | --- | --- |
| `account` | yes | `copy`, `type`, `clear` |
| `folder` | no | `copy`, `type`, `clear` |
| `kind` | no | `copy`, `type`, `clear` |
| `compositor` | no, `hyprland` or `niri` | `type` |
| `expect_id` | no | `type` |

A field the object omits keeps its default. At most 65536 characters are read.

These cases exit 1 before the keyring is read:

- Any of `--account`, `--folder`, `--kind`, `--compositor` or `--expect-id`
  on the command line next to `--item-stdin`, even an empty `--folder=`.
- A positional account next to `--item-stdin`.
- A missing or empty account.
- An unknown field.
- A value that is not a string.
- A `compositor` other than `hyprland` or `niri`.
- Input that is not a JSON object.

The flags `--account`, `--folder`, `--kind`, `--compositor` and `--expect-id`
still work for the command line without `--item-stdin`. `store` and
`copy-text` already take their secret on stdin.

Tests: `tests/test_item_stdin.py`.

## Core dumps

At startup the helper sets `RLIMIT_CORE` to 0 and marks itself non-dumpable
(`PR_SET_DUMPABLE`). The `clipboard-serve` helper runs the same startup code.

What this gives:

- A crash writes no core file.
- The kernel refuses same-user `ptrace` and `/proc/<pid>/mem` reads of the
  helper.
- Child processes inherit the core limit.

Tests: `tests/test_core_dumps.py` (the limit and the flag, in the sandbox
also on a real process and its child).

What it does not give:

- The non-dumpable flag does not survive `exec`. `wl-copy`, `wtype` and
  `wl-paste` are dumpable again. They write no core file, but their memory is
  not protected from other processes of your user.
- Any process of your user can read a running `wl-copy`'s buffer through
  `/proc/<pid>/fd/<n>`. Yama's `ptrace_scope` does not restrict that (the
  sandbox test `test_same_user_process_can_read_the_buffer` checks it). That
  process can also run `wl-paste`.
- A same-user process can read the whole unlocked keyring through the Secret
  Service.

omapass therefore does not try to harden same-user memory further. It shortens
how long `wl-copy` holds the secret instead: until another copy replaces it,
or 30 seconds. See [Clipboard](clipboard.md).

A crash of the shell while the add form holds a password can put it in a core
file if the shell's core limit allows one. On a default Omarchy session the
limit is unlimited and `systemd-coredump` stores the dump. The helper cannot
prevent that.

## CLI secrets

`get` refuses to print a secret to an interactive terminal unless you pass
`--yes`. Piping stdout is fine.

```sh
omapass get -- alice@example.org | wl-copy
omapass get --yes -- alice@example.org
```

Without `--yes` on a terminal, `get` exits 1 and prints "refusing to print a
secret to a terminal; pipe the output or pass --yes". `nostr show-nsec` also
needs a terminal on both stdin and stdout and asks you to type `yes`. Tests:
`test_get_refuses_tty_without_yes`, `test_get_allows_pipe_without_yes` and
`test_show_nsec_*` in `tests/test_helper_security.py`.

`generate-nostr` prints no nsec. Secrets never appear in the panel's list.

## No sudo or pkexec

omapass needs no `sudo` or `pkexec`. It runs as your user, with the
gnome-keyring, clipboard and typing tools that already ship with Omarchy, and
it starts no daemon of its own.

## Limitations

- **A generated password passes through the shell.** The add form's generated
  password goes through the shell (QML) before it is saved, so a crash of the
  shell can leave it in a system core dump. The helper does not generate and
  store it in one step, because the form lets you reveal and edit the password
  before saving. `omapass generate-password` itself prints the password on
  stdout.
- **The IPC target is declared by each monitor's bar widget.** Each monitor's
  bar widget declares the IPC target `io.github.this-is-npc.omapass`. The shell
  routes summon, hide and toggle for a bar widget through the live bar,
  because a fixed IPC target only ever routes to one of the per-monitor
  instances (`shell.qml`). This repository has no test that two `IpcHandler`s
  share one target. `omarchy-shell shell summon` picks the instance on the
  focused monitor.
- **Same-user processes are not a boundary.** See [Core dumps](#core-dumps).
