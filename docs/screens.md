# Screens

This page walks the omapass panel in the order you use it: the list, the row
menu, the add form, and the dialogs. For the keys on each screen, see
[Keyboard](keyboard.md).

The panel is one small window that opens from the bar icon. It has two views:
the list and the add form. The panel is as tall as its content, and the list
scrolls past about eight rows.

## Opening

Click the bar icon, or run
`omarchy-shell shell summon io.github.this-is-npc.omapass '{}'`.

The panel captures the focused window when it opens. That is the window
**Shift+Enter** types into (see [Autotype](autotype.md)). The panel shows after
the capture ends. The capture is bounded at 8 s. If it fails or times out,
the panel still opens, but typing is unavailable ("Type unavailable").

Each monitor's bar widget declares the IPC target
`io.github.this-is-npc.omapass`. The shell routes summon, hide and toggle
through the live bar. `omarchy-shell shell summon` picks the instance on the
focused monitor. This repository has no test that two `IpcHandler`s share one
target.

## The list

Logins are grouped into one card per folder. Each card header shows the folder
name and the number of logins it holds. In "All", the arrow keys go through the
cards in the order shown.

- The chips above the list filter by folder. Each shows how many logins its
  folder holds. With more folders than fit, the chips scroll sideways (mouse
  wheel or Left/Right).
- When one folder is selected, its card omits the repeated folder header. A
  folder may even be named "all".
- Only the selected row shows its buttons, so names get the full width. The
  buttons are Copy and the `⋯` menu.
- A name too long for its row is cut off with an ellipsis. The Remove and
  Replace dialogs wrap the whole name, so two names that differ only at the end
  can be told apart there.
- In "All", the height allows for up to three card headers on top of eight
  rows. The list scrolls beyond that.
- Nostr keys show a key icon and an `nsec` tag. Their buttons and menu read
  "Copy key" and "Type key". See [Names](names.md) for how Nostr items differ.
- Secrets never appear in the list.

### The selected row

The selected row is tracked as one item (account, kind and folder), not by
position. When a refresh (every open, save or remove) moves or changes rows,
the highlight stays on the same item. Enter or Shift+Enter acts on it. If the
item is gone, the first row is highlighted and Enter acts on that one (tested
with a refresh that inserts a row before the selected one).

A refresh asked for while a list is running (after a save or a remove, or a
second summon) runs again when that list ends. The rows never keep a removed
item.

### Mouse and keyboard

Mouse and keyboard share one highlight in the list, the chips, the search
field, the row menu and the confirm dialog. Only real pointer motion moves it.
A pointer resting where a row, chip, menu option or button appears does not,
so Enter acts on what the keyboard chose. After the panel opens, the first
pointer position only sets a baseline, so a mouse user may need one more small
movement before the highlight follows.

A click on a row copies its password. The copy button on the row turns into a
check mark on the copied item only. Two rows with the same account in
different folders are told apart by folder.

### The footer strip

A fixed strip at the bottom never changes the panel's height. At rest it shows
the key hints:

```
↵ Copy   ·   ⇧↵ Type   ·   + Add   ·   ⋯ More
```

After an action it shows the result for about 1.2 s: "Copied password", "Copied
key", "Copied account", "Saved", "Removed", "Generated password", or an error.
A good result has a check mark. An error has a warning icon and the theme's
urgent color. A copy failure shows the helper's message. A copy that takes more
than 20 s shows "Copy timed out".

Other errors stay a short line in the footer. The exception is exit 6
(see below).

### Warning signs

A warning sign (⚠) next to a name means one of these:

- The name has control characters or invisible characters. Another app stored
  it. omapass does not store such names.
- The same account and kind exists more than once.

Two items with the same account and kind in different folders show as two rows,
both with a warning sign. Copy, Type and Remove pass the row's folder to the
helper (`--folder=`), and the Remove dialog names the folder ("Remove dup from
Work?"). See [Names](names.md) and [Storage](storage.md) for how names and
duplicates work.

### Loading and empty states

- While the first list is loading, the panel says "Loading…". No key opens the
  add form (Enter, `+`, Ctrl+N; tested).
- Once the list has arrived empty, it says "No logins yet".
- When a search or folder shows nothing, it says "No matches". A
  "+ Add login" button, with the hint "Enter or Ctrl+N to add", opens the add
  form. It never saves by itself.
- When the list cannot be read, the panel shows the helper's message in place
  of the rows, for example "The keyring did not answer in time" or
  "Keyring unavailable". If rows were already loaded, the error appears in the
  footer instead and the old rows stay. An error is not shown as an empty
  keyring.
- While the list shows an error, the add form does not open. The panel
  refreshes the list instead, because the keyring's state is unknown and adding
  could overwrite existing logins.

### Time bounds for helpers

Helpers that only read are stopped if they run too long:

| Helper | Bound | Result |
|---|---|---|
| list | 60 s | "The keyring did not answer in time" |
| copy | 20 s | "Copy timed out" |
| focus snapshot | 8 s | Type is then unavailable |

`type` and `store` have no bound. Cutting `type` would leave half a secret in
the target window. Cutting `store` could leave an unfinished write.

## The row menu

Open the menu with `m`, Right, or the `⋯` button on the selected row. It is
compact and lists its shortcuts:

| Option | Shortcut | What it does |
|---|---|---|
| Copy account | `u` | Copies the account name |
| Type password (Type key for Nostr) | `⇧↵` | Types the secret into the captured window |
| Remove | `Del` | Asks to remove the item |

All the shortcuts work while the menu is open. The menu opens below the row, or
above it when there is no room, without covering the search. A short list grows
to make room. Remove is in the theme's urgent color and has a divider above it.

See [Keyboard](keyboard.md#the-row-menu) for the keys inside the menu.

## The add form

Open it with `+`, Ctrl+N, or the `+` button next to the search field. It has
two kinds, chosen by the Account | Nostr switch at the top.

- **Account** has Folder, Account or nickname, and Password. Save stays dimmed
  until all three are filled.
- **Nostr** has Folder (the placeholder says "Nostr (default)"; an empty folder
  becomes Nostr) and Nickname. The button reads "Generate key". The key is
  generated and stored by the helper. Without a nickname the form says "Need a
  nickname in Account".

The form starts with the open folder and, after a search with no match, the
searched name.

The generate button (or Ctrl+G) fills the password field. A generated password
is always masked, even if the field was revealed. The form then shows only
"Generated · N chars". Edit the field and the label goes away. The eye button
(or Ctrl+E) shows or hides the password.

A failed save keeps the typed or generated password in the form, so it can be
retried. The password is wiped only by:

- a successful save,
- cancelling the form,
- starting a fresh form with Ctrl+N,
- closing the panel.

A late reply from the helper after the form was closed never puts a secret back
(tested).

If the same account already exists, the Replace question opens.

The generated password passes through the shell (QML) before it is saved. The
helper does not generate and store it in one step, because the form lets you
reveal and edit it first. A crash of the shell in that time can leave it in a
system core dump. See [Security](security.md).

## The dialogs

All dialogs start on Cancel, so Enter never confirms a destructive action.

### Remove

"Remove github?" with Cancel and Remove. When the same account and kind exist in
several folders, it names the folder: "Remove dup from Work?". The confirmation
button uses the theme's urgent color. A removed item shows "Removed" in the
footer.

### Replace

Saving an account or generating a Nostr key that already exists asks first:
"Replace the secret for github in Work?" (for Nostr: "Replace the Nostr key
nick in Nostr?"). The question names the item from the loaded list, in every
folder that holds it (exact or NFC-equal name).

- When the form's folder differs from the stored one, it adds that the item
  moves there.
- It says the old password (for a Nostr key, the old key) is lost for good.
- It names no folder for an item the list does not show. It then says where the
  item will be stored.

Replace uses the theme's urgent color.

### Keyring may be damaged

A write that fails with exit 6 (the keyring file may be damaged) opens a dialog
with the helper's full message and a Dismiss button. It stays until dismissed.
The panel also sends a notification, in case the panel closes first. See
[How to check the keyring](how-to-check-the-keyring.md).

## Panel position

The panel opens centered on the bar by default. The button next to Add (or
Ctrl+P) switches it: `󰉣` moves the panel under the icon, `󰉠` centers it again.

The choice is saved as the `centerPanel` setting for this widget in
`~/.config/omarchy/shell.json`. The same setting can be set from the command
line:

```sh
omarchy bar set io.github.this-is-npc.omapass centerPanel false --json
```

Use `true` to center it again. If saving fails, the panel logs a warning and
keeps its position.

## Border and rounding on Hyprland

The panel frame uses your Hyprland window border. Each time the panel opens, it
reads the width (`general:border_size`) and the color or gradient
(`general:col.active_border`) with `hyprctl`. Corners, cards, chips and buttons
follow `decoration:rounding` through the shell's `Style.cornerRadius`.

On other compositors, or when `hyprctl` fails, the panel keeps the shell's
default border. The QML runtime tests run under sway, so they show the default
border and the warnings from the missing `hyprctl`.
