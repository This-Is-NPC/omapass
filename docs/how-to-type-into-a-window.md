# How to type into a window

**The question:** How do I make omapass type a stored password into the window I
am working in, instead of copying it? This page is enough on its own. For how
typing is checked and what it cannot catch, see [Autotype](autotype.md).

## Before you start

- `/tmp` is on tmpfs. Stock Omarchy mounts it that way. Check it with:

  ```sh
  findmnt -no FSTYPE /tmp
  ```

  Expected output: `tmpfs` (or `ramfs`). If other users can write to `/tmp`,
  it must also have the sticky bit.
- You run Hyprland or niri. Autotype uses the compositor to find the focused
  window.
- `wtype` is installed at `/usr/bin/wtype`.
- The login is already stored. See [Storage](storage.md) for adding one.
- The window you want to type into is focused, with the cursor in the right
  field.

## Steps

1. Focus the window and put the cursor in the password field.
2. Open the omapass panel from the bar icon, or run
   `omarchy-shell shell summon io.github.this-is-npc.omapass '{}'`. The panel
   remembers the focused window when it opens.
3. Find the login. Type part of its name in the search field, or move with the
   arrow keys.
4. Press **Shift+Enter** (or **Ctrl+Enter**). You can also open the row menu
   with `m` and choose "Type password".
5. The panel closes and the password appears in the field, one character at a
   time. Nothing is copied to the clipboard and no Enter is sent. Press Enter
   yourself.

Do not switch windows or workspaces, and do not open a launcher, while it
types.

## Stop typing

Reopen the panel on any screen. Opening stops every running `type` of the
plugin. At most one more character is typed.

## Troubleshooting

When typing fails, the panel is already closed, so omapass shows a critical
notification titled "omapass". Its text starts with "Autotype failed:" and
continues with the reason. It never contains the secret.

| Exit | Notification text | What happened and what to do |
|---|---|---|
| 8 | `focus changed` | The window was not focused within 0.5 s, or focus changed while typing. Do not switch windows while it types. Focus the target again and retry. |
| 8 | `keyboard panel still open` | Another Omarchy panel was still open 1 s after the panel closed. Close it and retry. |
| 8 | `focus unavailable`, `layers unavailable` | The compositor query failed or timed out. Check that `hyprctl` or `niri` answers, then retry. |
| 8 | `session locked` | A lock screen was seen on Hyprland. Unlock and retry. |
| 8 | `session lock state unknown` | The lock query failed or could not decide. Retry. If it keeps happening, see [Autotype](autotype.md#what-is-checked-before-each-character). |
| 9 | `refusing to type: ...` | `/tmp` is not safe for `wtype`. Mount `/tmp` as tmpfs. See [Autotype](autotype.md#typing-and-tmp). |
| 9 | `wtype failed`, `wtype timed out` | `wtype` could not send the key. Check that it is installed and that the compositor supports virtual keyboards. |
| 13 | `stored secret has control characters or line breaks; not typed` | Another app stored a secret with a line break or control character. omapass will not type it. Re-save it in omapass. |

Other cases:

- **The footer says "Type unavailable".** The panel could not capture the
  focused window when it opened (the capture is bounded at 8 s). Close the panel,
  focus the window, and open the panel again.
- **Nothing happens and no notification appears.** You may have reopened the
  panel, which stops typing without a notification.
- **Characters went to the wrong window.** Up to one character can reach another
  window if focus changes just after a check. See
  [Residual risk](autotype.md#residual-risk).
- **Part of the password was typed, with no error.** The shell was reloaded or
  restarted while typing, which kills the helper. See
  [Autotype](autotype.md#when-the-panel-is-destroyed-while-typing).
- **Do not use "Control notifications with the keyboard"** (Super+Ctrl+comma)
  while it types. omapass cannot see that mode, and the rest of the password
  would go to the notifications.

For the full list of exit codes, see [CLI](cli.md).

## Next steps

- [Autotype](autotype.md): what is checked, measurements, and residual risk.
- [Keyboard](keyboard.md): every key in the panel.
- [Clipboard](clipboard.md): copy a password instead of typing it.
- [Security](security.md): what omapass protects and what it does not.
