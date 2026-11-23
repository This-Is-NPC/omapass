# Autotype

This page explains how omapass types a stored secret into another window, what
it checks before every character, and where it can still go wrong. To do it
step by step, see [How to type into a window](how-to-type-into-a-window.md).

Autotype is the `type` command of the helper. The panel starts it with
**Shift+Enter** or **Ctrl+Enter**, or with "Type password" in the row menu. It
never copies. Typing needs Hyprland or niri, and `wtype`.

## How it works

1. The panel captures the focused window when it opens. It is a window id from
   `hyprctl activewindow -j` or `niri msg --json focused-window`.
2. When you start typing, the panel closes. Then the helper starts.
3. Before it reads the secret, the helper checks `/tmp` (see
   [Typing and /tmp](#typing-and-tmp)).
4. It waits up to 0.5 s for the captured window to be focused. If it is not
   focused in that time, it aborts (exit 8, "focus changed").
5. It reads the secret from the keyring. A secret with control characters or
   line breaks is refused (exit 13).
6. It waits up to 1 s until no `omarchy-keyboard-panel` layer is mapped. The
   panel's own layer stays mapped for its 120 ms fade-out. The wait also covers
   the panel's `-dismiss` twins on other screens, and any other Omarchy panel
   that is open. If one stays, it aborts (exit 8, "keyboard panel still open").
   The layers it sees then are the starting set.
7. It types one character per `wtype` call. Before each character it checks
   focus, layers and the lock (see below). If any check fails, it stops and the
   rest of the secret is not sent.

If focus changes before typing starts, the operation aborts with an error
instead of typing into the wrong window.

## What is checked before each character

- **Focus.** The focused window is read again. If it differs from the captured
  one, or cannot be read, typing stops.
- **Layer-shell surfaces** (launcher, menu). If any layer appeared, vanished or
  was replaced since typing started, or if the layers cannot be read, typing
  stops.
- **Session lock** (Hyprland only). The helper runs `hyprctl monitors -j` and
  stops (exit 8, "session locked") when a monitor lists `LOCK` in
  `solitaryBlockedBy`. This is the signal Omarchy's own
  `omarchy-hyprland-session-locked` uses. It stops with "session lock state
  unknown" when the query fails, hangs, answers something other than a
  non-empty list of monitor objects, or every monitor is blocked only by
  `WORKSPACE`. Hyprland stops at that reason before it reaches the lock, and
  Omarchy's own script calls this "undetermined".

Every `hyprctl`, `niri` and `wtype` call has a 2 s timeout. If one hangs, `type`
stops: exit 8 for a compositor query, exit 9 for `wtype`. The rest of the
secret is not sent.

### How a window or layer is identified

On Hyprland, a window is identified by its `stableId`, which is never reused. A
layer is identified by its `stableId` too. When Hyprland does not report one,
the window falls back to its `address`. A layer then falls back to its
namespace, `address`, `pid` and geometry (`x`, `y`, `w`, `h`). This host's
`hyprctl layers -j` has no `stableId`, and `activewindow -j` has.

Every Omarchy panel shares one namespace and one pid. The geometry and the wait
in step 6 are what tell a panel that reuses a freed address apart from the one
that was there. Tests cover a reused address, a layer that resizes or vanishes,
and a panel that opens at the freed slot.

On Hyprland, every layer counts, because its IPC JSON has no
keyboard-interactivity field. It gives `address`, `x`, `y`, `w`, `h`, `alpha`,
`namespace` and `pid` (checked on this host). niri reports
`keyboard_interactivity`, so only layers that can take the keyboard count.

niri is not asked about a session lock.

### Cost

Each query costs 4 to 7 ms per character on an idle Hyprland machine. The
median of 40 runs of the first two queries was 4.6 ms and 6.4 ms in two
measurements. At a load average of 33, each cost about 13 ms (median of 40 runs
of each of the three queries: 12.0, 13.2 and 13.1 ms). The `wtype` spawn is not
included.

## Typing and /tmp

`wtype` 0.4 writes a keymap that names each typed character to a file
`/tmp/wtype-XXXXX`. The path is compiled into the binary and ignores `TMPDIR`
(checked with `strings`, and by a sandbox test). The file is mode 0600 and
unlinked at once. On a disk-backed `/tmp`, the characters could still reach the
disk.

Before it reads the secret, `type` therefore refuses (exit 9, "refusing to type:
...") unless `/tmp` is:

- a directory on tmpfs or ramfs, and
- if other users can write to it, sticky (the sticky bit is set).

Stock Omarchy mounts `/tmp` as tmpfs. `TMPDIR` cannot move `wtype`'s file.

## Stopping typing

The panel closes when typing starts, and the target window keeps focus, so
Escape cannot reach omapass.

To stop typing, reopen the panel on any screen. Opening sends SIGTERM to every
running `type` of this plugin: the panel's own, and, through `pkill` on the
helper's command line, one started from another screen's panel (tested). At
most the character already handed to `wtype` is still typed. A stopped typing
shows no notification.

Switching to another window or workspace also stops typing, but one character
can still reach the wrong window (see below).

## When typing fails

The panel is closed by then, so a failure is shown as an Omarchy notification.
It comes from `omarchy-notification-send`, with the app name "omapass" and the
text "Autotype failed: " followed by the helper's message. It never carries the
secret. The message is cut to 400 characters. A space is inserted after any
`<` or `&` that touches the next character, so tags and entities show as text.

| Exit | Meaning |
|---|---|
| 8 | Focus or the layer-shell surfaces changed, a keyboard panel stayed open, a session lock was seen, or any of those could not be read or determined. Nothing more is typed. |
| 9 | `wtype` failed or timed out, or `/tmp` is not safe for it. |
| 13 | The stored secret has control characters or line breaks. Nothing is typed. |

The panel always passes the captured window, so it gets exit 8 instead of 3
("no compositor focus"). When the helper gives no message, the notification says
"Focus changed" for 8, "Typing failed" for 9, and "Type aborted" otherwise. The
helper never passes `wtype`'s own status through. For the full list of exit
codes, see [CLI](cli.md).

`type --compositor` accepts `hyprland` or `niri`. Anything else is a bad
argument (exit 2).

Control characters: `add` and `store` never store them, but an item made by
another app can hold a line break, tab or escape sequence. `type` would send a
line break as Return and submit the form. So `type` and `copy` refuse such a
secret (exit 13, "stored secret has control characters or line breaks; not
typed") and send nothing. The secret is not trimmed or changed. `get` still
prints it, for scripts. The check covers C0, DEL, C1 and U+2028 and U+2029 (the
same set `add` rejects). One trailing newline of a legacy raw item is dropped
before the check.

## Residual risk

The focus check and the keystrokes are not atomic. `wtype` sends to whichever
surface is focused when it sends. Focus can still change in the short gap after
a check, and up to one character can reach the wrong window. Avoid switching
windows or workspaces while autotype runs. Only compositor support for
targeting a specific surface would remove this.

A lock taken in the gap between the check and the keystroke can also still
receive one character.

Not detected:

- **A launcher or menu already open before the panel's layer unmapped.** The
  layer check compares against the layers present once omapass's own panel has
  unmapped. Whatever was open then is part of the starting set.
- **Notification keyboard mode.** Omarchy's notification surface is one
  fixed-size layer per screen that stays mapped. Super+Ctrl+comma ("Control
  notifications with the keyboard") only changes that layer's keyboard focus to
  exclusive. That is a layer-shell property none of the IPC fields carries. No
  layer appears and the focused window does not change. If you enter that mode
  while omapass types, the remaining characters go to the notification deck,
  whose key handler selects, dismisses and invokes notifications. This follows
  from the shell source (`plugins/notifications/Service.qml`) and the IPC
  fields. It was not reproduced on a live desktop. Do not use it while autotype
  runs. A notification popup does not abort typing on Omarchy, because it is a
  card on the existing layer. The layer does unmap while a fullscreen window is
  shown and no notification is on screen, and that does abort typing.
- **Some lock screens.** A lock (hyprlock, Omarchy's lock) is an
  ext-session-lock surface, not a layer, and the focused window does not change,
  so the layer check cannot see it. The `LOCK` signal above covers Hyprland
  only. Hyprland stops listing reasons early on a monitor with no workspace, so
  a lock can go unseen there while another monitor can be read. The signal also
  stays set after a lock's client dies, which only makes `type` refuse (it fails
  safe). It is missing on other Hyprland versions. niri is not asked at all.

Not done: one in-compositor Lua request that checks focus and sends all keys
would close the gap. It would have to map characters to keycodes for the user's
layout (dead keys on us-intl) and refuse before typing if a character is
unreachable.

## When the panel is destroyed while typing

Reload, disable and monitor unplug destroy the panel without closing it.
Quickshell then kills the helper it started (observed in
`tests/qml/test_data_runtime.py`: SIGKILL, no handler runs). A `type` stops,
with part of the secret already typed and no Enter. The helper has no SIGTERM
handler for `type`.

A killed shell (`omarchy-restart-shell`) does not run this. Its helpers may
outlive it (orphaned child processes of a restarted shell were seen on the
development host). The next panel open stops a `type` it finds.

## Related

- [How to type into a window](how-to-type-into-a-window.md)
- [Keyboard](keyboard.md)
- [Security](security.md)
- [CLI](cli.md)
