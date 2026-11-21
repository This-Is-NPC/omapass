# Keyboard

This page lists every key in the omapass panel, grouped by where you are. It
answers "which key does this?". For what each screen looks like, see
[Screens](screens.md).

Only explicit actions copy or type a secret: Enter, Shift+Enter, Ctrl+Enter,
a click on a row, and the row menu. No single letter and no Space copies or
types a secret (tested).

## Opening and closing

- Click the bar icon with the left button. It opens the panel, or closes it
  when it is already open.
- Run `omarchy-shell shell summon io.github.this-is-npc.omapass '{}'`.
- Press **Escape** to close the panel. It first backs out of the open dialog,
  menu, form or search text (see the sections below). It closes the panel only
  when none of those is open (tested).
- A click outside the panel, `hide`, `toggle`, or another bar panel taking
  over also closes it. Closing closes the row menu and the confirm dialog and
  wipes the search, the selection, the folder filter and the form (tested).
  The next open shows the plain list.

Summoning a panel that is already open:

- With the Remove dialog or the row menu showing, the dialog or menu and its
  keyboard focus stay as they are (tested). The list refresh waits until the
  dialog or menu is closed, because a refresh rebuilds the rows and would
  destroy the menu (tested).
- A refresh that does rebuild the row with the open menu closes the menu and
  returns the keyboard to the panel (tested).
- With the add form open, the focus stays on the field you are editing
  (tested). A later Enter acts on that field and never copies or types a
  password behind it.
- Every summon of an open panel asks the compositor for the keyboard again,
  because a notification, an overlay or the lock may have taken it. The
  panel primes exclusive keyboard focus for 75 ms. Tests cover only that the
  prime is requested. Whether the compositor then yields the keyboard needs a
  live Hyprland.

Opening the panel also stops any autotype that is still running. See
[Autotype](autotype.md#stopping-typing).

## Panel position

- **Ctrl+P** toggles between centered on the bar and under the bar icon. It
  works while the list is showing, not in the add form. See
  [Screens](screens.md#panel-position).

## The search field and the list

The search field has the keyboard when the panel opens.

In the search field:

- Type to filter by name. The first match is selected.
- **Enter** copies the selected password. When nothing matches, it opens the
  add form and never saves by itself.
- **Shift+Enter** or **Ctrl+Enter** types the selected password into the window
  that was focused when the panel opened. It never copies.
- **Ctrl+U** copies the selected account name.
- **Down** moves to the list.
- **Up** moves to the folder chips. With no folders yet, it selects the last
  row.
- **Ctrl+N** opens the add form.
- **Escape** clears the search text. With the field already empty, **Escape**
  leaves the search field. Once more closes the panel (tested).

In the list (after Down, or after leaving the search field):

- **Up** and **Down**, or `k` and `j`, move the selection. It wraps from the
  last row to the first. In "All" the order is the order of the folder cards.
- **Enter** copies the password. **Shift+Enter** or **Ctrl+Enter** types it.
- **Space** does nothing on a row (tested).
- `u` copies the account name.
- **Right** or `l`, or `m`, opens the row menu.
- **Delete** or `x` asks to remove the item.
- `/` goes back to the search field.
- `+` or **Ctrl+N** opens the add form. Both do nothing until the first list
  has arrived, and while a dialog or menu is open (tested).
- **Tab** or **Shift+Tab** switches to another bar panel, if the bar has one.

While the first list is still loading, Enter, `+` and **Ctrl+N** do not open
the add form (tested). The selected row is tracked by account, kind and
folder, not by position. A refresh does not move the selection to another
item. See [Screens](screens.md#the-list).

## Folder chips

Press **Up** from the search field to reach the chips.

- **Left** and **Right**, or `h` and `l`, move between the chips. The strip
  scrolls sideways when there are more folders than fit.
- **Enter** or **Space** filters by the chip. Space on a chip filters but never
  copies (tested).
- **Down** returns to the list. With no rows, it returns to the search field.

## The add form

Open it with `+` or **Ctrl+N**. It starts with the open folder and, after a
search with no match, the searched name.

- **Ctrl+N** starts a fresh form from any field. The typed password is wiped
  (tested). While a dialog or the row menu is open, it does nothing.
- **Ctrl+1** selects Account. **Ctrl+2** selects Nostr.
- **Left** and **Right** switch between Account and Nostr while the
  Account | Nostr switch itself has the keyboard. **Shift+Tab** from Folder
  reaches the switch, and **Enter** or **Tab** leaves it for Folder.
- **Tab** and **Shift+Tab** move between Folder, Account and Password. For
  Nostr, Account is the last field.
- **Enter** moves from Folder to Account. In Account it moves to Password, or,
  for Nostr, generates the key. In Password it saves.
- **Ctrl+G** generates a password, or a Nostr key for the Nostr form. It works
  from any field.
- **Ctrl+E** shows or hides the password. It works from the Password field and
  from the Account | Nostr switch, not from Folder or Account.
- **Escape** cancels from any field and wipes the form.

## The row menu

Open it with `m`, **Right** or `l` on the selected row, or with the `⋯` button.
It starts on its first option, "Copy account".

- **Up** and **Down**, or `k` and `j`, move through the options. They wrap.
- **Enter** or a click runs the highlighted option. **Space** does nothing here
  (tested).
- `u` copies the account.
- **Shift+Enter** or **Ctrl+Enter** types the password (or the key).
- **Delete** or `x` removes, after a confirmation.
- **Escape** closes the menu and leaves the panel open (tested).
- No other key copies or types a secret while the menu is open.

## The confirm dialog

The Remove dialog, the Replace question and the keyring-damaged message use the
same keys. The dialog starts on Cancel (Dismiss for the damaged message), so
Enter never confirms by accident (tested).

- **Left**, **Right**, **Tab** and **Shift+Tab** switch between the two buttons.
  The damaged message has one button, Dismiss, so they do nothing there.
- **Enter** runs the highlighted button.
- **Escape** cancels (tested). The panel stays open.

## Mouse and keyboard together

The mouse and the keyboard share one highlight in the list, the chips, the
search field, the row menu and the dialog. Only real pointer motion moves it.
A pointer resting where a row, chip, menu option or button appears does not.
After the panel opens, the first pointer position only sets a baseline, so a
mouse user may need one more small movement before the highlight follows. Both
are tested with a virtual pointer.
