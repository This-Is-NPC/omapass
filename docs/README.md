# Documentation map

This is every page in the omapass documentation, in the order you are likely to meet it.

## The shortest useful path

1. Read [../README.md](../README.md) for what omapass is and how to install it.
2. Learn the keys in [Keyboard](keyboard.md).
3. Before you type a login into a window, read [How to type into a window](how-to-type-into-a-window.md).
4. Use the "When you know what you want" table below for anything else.

## In order you'll meet them

**Getting started:**
- [How to install and remove](how-to-install-and-remove.md) — add the plugin, update it, take it off.
- [Keyboard](keyboard.md) — which key does what in each part of the panel.
- [Screens](screens.md) — what the panel shows and where it sits.

**Using logins:**
- [Clipboard](clipboard.md) — how long a copied password lives and who can read it.
- [Autotype](autotype.md) — how typing into a window stays safe, and what risk remains.
- [How to type into a window](how-to-type-into-a-window.md) — type a login into another application.
- [Names](names.md) — what a name may contain, and how duplicates and `--replace` work.

**Keyring and safety:**
- [Storage](storage.md) — the stored format, the write lock, the write guard and `doctor`.
- [How to check the keyring](how-to-check-the-keyring.md) — what to do after a write error.
- [Security](security.md) — secrets on stdin, core dumps, process hardening, CLI secrets.

**Reference:**
- [CLI](cli.md) — every command, option and exit code.

**Development and testing:**
- [Design](design.md) — architecture, modules and state.
- [Testing](testing.md) — the test sandbox, QML runtime tests and hooks.

## When you know what you want

| You want to… | Start with… |
|---|---|
| Install, update or remove omapass | [How to install and remove](how-to-install-and-remove.md) |
| Type a login into another window | [How to type into a window](how-to-type-into-a-window.md) |
| Check your logins after a write error | [How to check the keyring](how-to-check-the-keyring.md) |
| Find a key | [Keyboard](keyboard.md) |
| Move the panel | [Screens](screens.md) |
| Know how long a password stays on the clipboard | [Clipboard](clipboard.md) |
| Understand why typing stopped | [Autotype](autotype.md) |
| Know what name characters are refused | [Names](names.md) |
| Script omapass | [CLI](cli.md) |
| Judge the security model | [Security](security.md) |
| Contribute or run the tests | [Design](design.md), [Testing](testing.md) |

## Conventions

- **Facts only.** Nothing is promised that is not in the code.
- **One question per page.** Other pages link to the explanation instead of repeating it.
- **Keyboard first.** Pointer actions are mentioned only to show they exist.
- **Observed or inferred.** Pages say whether a behavior was tested, read in source, or not reproduced on a live desktop.
