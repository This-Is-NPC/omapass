# How to check the keyring after an omapass write error

**The question:** omapass said the keyring may be damaged, or that a write could
not be confirmed (exit 6). How do I check that my logins are still safe, and
what do I do first?

This guide stands alone. It reads the keyring and changes nothing.

## Prerequisites

- omapass installed (`omarchy plugin add`). That command clones the whole
  plugin repository, so `docs/` and `tests/` are in the installed folder; a
  folder copied by hand can omit them. The check is `omapass doctor`, part
  of the helper, so no separate repository copy is needed to run it. It only
  reads the keyring and never writes, unlocks or modifies anything.
- gnome-keyring running and the default keyring unlocked (your normal session).
  `omapass doctor` does not unlock it; if it is locked the check says so and
  exits 10.
- `omapass` on your path, or run the file `bin/omapass` of the plugin folder
  (`~/.config/omarchy/plugins/io.github.this-is-npc.omapass/bin/omapass`).

## Steps

1. **Do not log out or reboot.** After a failed write the running daemon may hold
   the only good copy of your items in memory.

2. **Back up the keyring files now.**

   ```sh
   cp -a ~/.local/share/keyrings ~/keyrings-backup-$(date +%F-%H%M)
   ```

   Expected: no output. The copy holds your encrypted or plaintext keyring
   files exactly as they are. Treat it like the keyring itself.

3. **Run the check.**

   ```sh
   omapass doctor
   ```

   It parses each keyring file, checks that the `default` alias points at a
   real keyring, reads every item back through the Secret Service and applies
   the rule the omapass write guard uses. It prints counts and item ids, never
   secrets, and exits 0 when everything is healthy.

   Healthy output, as the check printed it in the test sandbox (an empty
   keyring, so 0 items):

   ```
   OK   file Default_keyring.keyring: parses, 0 items
   OK   pointer default -> 'Default_keyring'
   OK   alias default -> /org/freedesktop/secrets/collection/Default_5fkeyring
   OK   items: 0 read back, safe to rewrite
   ```

   A line that starts with `FAIL` names what is wrong: a file that does not
   parse, no default keyring, an item that cannot be read back, or an item
   that is not safe to rewrite.

4. **Read the result.**

   - All lines `OK`: the write that failed did not damage the keyring. Run
     `omapass list` and check that the item you changed is as you expect.
     Retry the write.
   - A `FAIL` line: write nothing more with omapass. Keep the backup from step
     2. The items the daemon still serves can be listed with `omapass list`
     (read only), so you can note them down before you restart anything.
     Restoring a keyring file is a manual step outside omapass.

## Troubleshooting

- `ModuleNotFoundError: No module named 'gi'`: install `python-gobject`.
- `FAIL items: the default keyring is locked` (exit 10): doctor never unlocks.
  Unlock the keyring in your keyring manager, then run it again.
- An encrypted keyring file is reported as `encrypted (not parsed)`. For it, the
  check only reads items back through the Secret Service. The write guard
  does the same: it does not read an encrypted file, and confirms a write only
  by reading the item back through the Secret Service.

## Next steps

- The write guard that produces these errors: README, "Write guard".
- Exit codes 5 and 6: README, "Exit codes".
