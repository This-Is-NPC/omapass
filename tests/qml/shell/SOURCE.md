# Vendored Omarchy shell modules

`Commons/` and `Ui/` are unmodified copies of the files from the `omarchy`
package that `Panel.qml` needs through `import qs.Commons` and `import qs.Ui`
(the import closure of `Ui/Panel.qml`, `KeyboardPanel.qml`, `PanelKeyCatcher.qml`,
`BorderSurface.qml`, `CursorSurface.qml`, `PanelActionButton.qml` and
`TextField.qml`).

- Source: `/usr/share/omarchy/shell/{Commons,Ui}` of `omarchy 4.5.0-3`
  (https://github.com/omacom/omarchy, MIT license).
- License: the files are MIT-licensed. `LICENSE` here is upstream's `LICENSE`
  (copyright notice and permission notice), copied unchanged from the
  repository root; keep it with the copies. The `omarchy` package ships no
  license file, so `LICENSE` comes from the upstream repository, not from the
  package, and could not be compared byte for byte with an installed copy.
- Only the two `qmldir` files differ: they list just the files kept here.
- No theme is vendored. `Commons/Color.qml` falls back to its built-in
  palette when no theme files exist, which is what the sandbox has.

Pinned here, not read from the host, so the tests give the same result on any
machine and a shell update cannot change them silently. To bump, copy the
same files from a newer `/usr/share/omarchy/shell`, update the version above,
and run `scripts/test-qml`.
