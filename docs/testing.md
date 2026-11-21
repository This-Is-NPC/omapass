# Testing omapass

For contributors. The tests run in disposable Docker containers and never touch your keyring, your D-Bus session or your compositor. The architecture they exercise is in [design.md](design.md).

There are two suites, each with its own image:

| Suite | Command | Runs | Needs |
| --- | --- | --- | --- |
| Helper and security tests | `./tests/run.sh` | Python `unittest` against `bin/omapass-keyring`, in the keyring sandbox | Docker |
| Panel runtime tests | `scripts/test-qml` | The real QML panel in quickshell under a headless sway, in the QML sandbox | Docker |

`hooks/pre-push` runs both. No sudo or pkexec is needed. The images are built
on first use, so the first run needs network access: the build downloads the
base image from the Docker registry, packages from `archive.archlinux.org` and
the `coincurve` source from `files.pythonhosted.org`. The runs themselves use
`--network none`. A later run reuses the cached image until the image
directory changes.

## Git hooks

Unit and QML tests run on `git push` when hooks are enabled:

```sh
git config core.hooksPath hooks
```

`hooks/pre-push` runs `tests/run.sh`, then `scripts/test-qml`, and stops at the first failure. To run them by hand:

```sh
./tests/run.sh
scripts/test-qml
```

## The keyring sandbox

`./tests/run.sh` runs the tests in a Docker container through
`scripts/test-sandbox`. The container has its own D-Bus session and its own
gnome-keyring with a throwaway, empty-password `Default_keyring`, the layout
Omarchy uses. The host keyring and the host D-Bus are never mounted, so a test
that breaks the keyring breaks only that one.

If `run.sh` is started outside the sandbox it re-runs itself through
`scripts/test-sandbox`. Inside, it runs
`python3 -m unittest discover -s tests -t <repo> -v`.

### How the tests know they are in the sandbox

The tests trust a marker file baked into the image, `/opt/sandbox/IN_SANDBOX`
(a regular file owned by root), together with `OMAPASS_SANDBOX=1`.
Exporting the variable on the host does not skip the sandbox, because the host
has no marker. The one check is `in_sandbox()` in `tests/sandbox_env.py`. Every
test that needs the keyring uses its `sandbox_only` decorator, and `run.sh`
runs the file as a script (exit 0 means inside the sandbox).

### Health check and exit codes

`tests/sandbox/entrypoint.sh` starts a private D-Bus session and the keyring
daemon, then checks the keyring with `tests/sandbox/keyring-health.py`
before and after the run. The sandbox daemon starts locked and `doctor` never unlocks, so the script unlocks the sandbox collection first and then runs the same `doctor` code.

| Exit | Meaning |
| --- | --- |
| the command's own | The run passed or failed on its own |
| 90 | The sandbox keyring was unhealthy before the run |
| 91 | The run left the keyring unhealthy: after the command, the daemon was restarted and the file re-parsed, and the check failed |
| 92 | The old daemon did not exit after the command, or was still serving after the restart, so the check would not have re-parsed the file |

After the run the entrypoint stops gnome-keyring, waits until the old daemon
has exited (a zombie counts as exited), restarts it and checks that the
keyring still loads.

### An interactive shell

Run any command in the sandbox, for example an interactive shell:

```sh
scripts/test-sandbox bash
```

Another example: `scripts/test-sandbox python3 -I bin/omapass-keyring list --json`
lists the sandbox keyring, which starts empty. The repository is mounted
read-only at `/src`. Only `/tmp` is a tmpfs. Unlike the QML sandbox,
this one keeps Docker's default root filesystem and capabilities.

### The reproducible image

`tests/sandbox/Containerfile` is reproducible:

- It pins the `archlinux` base by digest (`BASE`).
- It points pacman at a dated Arch Linux Archive snapshot (`SNAPSHOT`,
  currently `2026/11/09`, the base image's creation date), so the packages are
  pinned too.
- It builds `coincurve` 19.0.1 in a first stage from the PyPI source tarball,
  checked against a pinned sha256, because Arch has no package for it. The
  final image receives only the built package. The tests check
  `nostr show-npub` against the BIP-340 public keys of secret keys 1 and 3
  (`tests/test_nostr_backends.py`). The `secp256k1` backend is not exercised.
- It installs `wtype`, so the test that `wtype` ignores `TMPDIR` runs
  (`tests/test_type_guards.py`).
- The image tag is a hash of the files in `tests/sandbox/`, so an edit
  triggers a rebuild.

To bump the base and the snapshot:

1. Run `docker pull archlinux:latest`.
2. Copy the digest from
   `docker inspect --format '{{index .RepoDigests 0}}' archlinux:latest`
   into `BASE` in `tests/sandbox/Containerfile`.
3. Set `SNAPSHOT` to the image's creation date (`YYYY/MM/DD`).
4. Make the same change in `tests/qml-sandbox/Containerfile`, which pins the
   same base by digest and the same snapshot in its own `FROM` and `SNAPSHOT`
   lines.
5. Run `./tests/run.sh` and `scripts/test-qml`.

## The QML runtime tests

The panel (`qml/Panel.qml` and the components it delegates to, see
[design.md](design.md) section 3) is also tested running. `scripts/test-qml`:

1. builds or reuses the image `omapass-qml-sandbox:<hash of tests/qml-sandbox/>`;
2. starts a container with a headless sway (`tests/qml-sandbox/entrypoint.sh`:
   no input devices, the pixman software renderer, one 1280x800 output);
3. for each test, stages a fresh copy of the panel and starts the real panel in
   quickshell;
4. sends keys with `wtype` and pointer events with a virtual pointer, and checks
   the panel state and the helper commands it ran.

Run all the tests with `scripts/test-qml`; the count and time are printed at
the end. The command inside the container is
`python3 -I -m unittest discover -s tests/qml -v`.

### What the tests cover

- Keys: Enter and Shift+Enter, Space and single letters, the confirm dialog,
  the row menu, the masked generated password and the lit row on the folder
  chips, and a late save reply after the form was closed.
- The pointer (`tests/qml/vptr.py`, a minimal Wayland client for a
  `zwlr_virtual_pointer_v1`): a pointer at rest never changes the selected
  row, the confirm button, the row menu's option, the chips or the search
  field, and only real motion does. These tests wait until the panel reports
  the hover on the item under the pointer before they assert that nothing
  happened.
- The helper contract: padded and dash-leading account names reach the helper
  unchanged, "Copied account" reports the helper's result, closing or
  cancelling wipes the form, and no secret appears in the helper's arguments
  (the item goes on stdin; see [design.md](design.md) section 5).
- Data paths (`tests/qml/test_data_runtime.py`): failed saves, queued
  refreshes, helper timeouts, a `Vault` destroyed with a helper running,
  duplicate rows and the Replace question.

Files: `test_panel_runtime.py`, `test_modal_runtime.py`,
`test_coverage_runtime.py`, `test_pointer_runtime.py`,
`test_vault_runtime.py`, `test_data_runtime.py`, `test_item_stdin.py` and
`test_session_bounds.py`, all in `tests/qml/`. They share `session.py`.

### How a test is staged

One `Session` (`tests/qml/session.py`) is one quickshell process in a private
temporary directory:

- `harness.qml` is copied as `shell.qml`. It hosts the real `Panel`, exposes the
  panel's public properties and an item tree walk over IPC
  (`quickshell ipc call harness state`), and gives the panel a notification
  command that only logs.
- The repository's `qml/` is copied to `plugin/qml`, so the staged layout
  mirrors the repository: `plugin/qml` and `plugin/bin`.
- `plugin/bin/omapass-keyring` is `tests/qml/stub-helper`, and
  `plugin/bin/notify-stub` is `tests/qml/stub-notify`.
- Omarchy's `Commons` and `Ui` come from the vendored `tests/qml/shell/`.

The panel therefore calls the stub, never `bin/omapass-keyring`. The stub only
logs its arguments (and stdin for `store`, `copy-text` and `--item-stdin`
calls) as JSON lines and answers from a per-test `config.json` that sets delays,
exit codes and stderr. The sandbox has no keyring and no D-Bus. Secrets in the
tests are dummy values.

The tests wait for panel state or a logged helper call, with a 15 second
timeout (`TIMEOUT` in `session.py`). They contain no fixed sleeps. Where a test
asserts that nothing happens, it polls the state for a bounded window and fails
at the first poll that differs.

### Mutation checks with `--panel`

`scripts/test-qml --panel FILE` replaces only `Panel.qml` in the staged copy;
the components stay as they are. It runs the tests against that file, for
example a copy with one behavior broken, to check that a test can fail:

```sh
cp qml/Panel.qml /tmp/Panel.mutant.qml
# edit /tmp/Panel.mutant.qml to break one behavior
scripts/test-qml --panel /tmp/Panel.mutant.qml
```

A test that still passes against the mutant does not test that behavior.
Behavior that lives in a component, not in `Panel.qml`, needs the component
changed in a scratch copy of the repository instead (see the lock practice
below for the same idea on the helper).

### Vendored Commons and Ui

Omarchy's `Commons` and `Ui` modules are vendored, unmodified, in
`tests/qml/shell/`. `tests/qml/shell/SOURCE.md` records the version
(`omarchy 4.5.0-3`), the license and how to bump it. A pinned copy was chosen
over mounting `/usr/share/omarchy/shell`, so results do not depend on the
Omarchy version installed on the machine and a shell update cannot change them
silently. No theme is vendored, so `Commons/Color.qml` uses its built-in
palette.

### The Qt 6.11 import shim

The sandbox's stock quickshell resolves `Color` to Qt 6.12's own `Color` type,
unlike Omarchy's patched build. `Session._shim_imports` therefore rewrites
`import QtQuick` to `import QtQuick 6.11` in every `.qml` file of the staged
copy. The repository's files are not changed.

### The container and its bounds

`scripts/test-qml` starts the container with `--network none`, `--read-only`,
`--cap-drop ALL`, `--security-opt no-new-privileges` and a tmpfs `/tmp`
(`HOME=/tmp/home`). The repository is mounted read-only at `/src`. The image
(`tests/qml-sandbox/Containerfile`) is pinned like the keyring sandbox: base
digest and Arch Archive snapshot. It adds `sway`, `quickshell`,
`qt6-wayland` and `wtype`, and a plain copy of `/usr/bin/sway` because the
packaged binary carries file capabilities that an unprivileged container user
cannot use.

An interactive shell in this sandbox is `scripts/test-qml bash`.

### Hang bounds

Hangs are bounded at three levels:

| Level | Bound | Behavior |
| --- | --- | --- |
| Test | 90 s watchdog (`OMAPASS_QML_WATCHDOG`) | A timer in each `Session` kills quickshell and fails the test (`watchdog killed quickshell after 90 s`). `tests/qml/test_session_bounds.py` checks it |
| Run | 1500 s (`OMAPASS_RUN_TIMEOUT`; `0` for no limit) | The container entrypoint wraps the command in `timeout`, with a 10 s kill grace. A shell opened with `scripts/test-qml bash` is bound too |
| Container | `scripts/run-container` | Starts the container with `--rm --init`, a unique name, and a trap that removes it when the script exits or is interrupted with Ctrl-C or SIGTERM |

Both runners start the container through `scripts/run-container`, so
`scripts/test-sandbox` has the same run bound and the same trap. A `kill -9` of
the script cannot run the trap; the run bound then ends the container. With a
terminal on stdin and stdout the container runs with `-it`; otherwise it runs in
the background of the script so a signal runs the trap at once.

### Limits

- sway stands in for Hyprland, so `hyprctl` is absent. The panel logs warnings
  and keeps its default border.
- `wtype` types into the panel only. The tests do not cover the clipboard or
  typing into another window. Those are covered by the keyring sandbox's
  `tests/test_clipboard_wayland.py` (headless sway and `wl-paste`) and by the
  helper's unit tests with mocked compositor calls.
- Whether a notification, overlay or lock screen yields the keyboard to the
  panel needs a live Hyprland, so the tests check only that the panel asks for
  it.
- The QML suite is not part of `./tests/run.sh`, because it needs its own
  image. `hooks/pre-push` runs both.

## Patching the split helper in tests

The helper is an entrypoint plus the `bin/omapass_lib` package. Tests that
patch it use `tests/helper_loader.py`. `load_helper()` returns a facade over
the entrypoint and every package module (`common`, `keyring_store`,
`keyfile_guard`, `secret_io`, `nostr`). Each call imports fresh module objects.

- Reading a name finds it in the first module that defines it.
- Setting a name, by plain assignment or `mock.patch.object`, sets it on every
  module that defines it, so a patch reaches all callers. A name no module
  defines raises `AttributeError`.
- Deleting restores the originals, which is what `mock.patch` does on exit.

Patch through the facade, not on a single module: after the split, the same
name (for example a timeout constant) can be bound in more than one module. When you add a
module to `bin/omapass_lib`, add it to `MODULES` in the loader and keep it
under the 700-line cap ([design.md](design.md) section 3).

## Mutation checks for the write lock

A lock test that never fails proves nothing. The lock tests are
`tests/test_write_lock.py`: the lock file's safety checks, a holder in another
process, and four parallel stores of one new name over six rounds that must
leave one item and exit 4 for the losers.

To prove they detect the original defect, break the lock in a scratch copy of
the repository and run the tests there. The sandbox mounts the repository it is
started from, so a copy mutates nothing of yours:

```sh
cp -r . /tmp/omapass-mutant
cd /tmp/omapass-mutant
# edit bin/omapass_lib/keyring_store.py: for example, make write_lock yield
# without taking the flock
scripts/test-sandbox python3 -m unittest -v tests.test_write_lock
```

The tests must fail. Delete the copy afterwards. The same practice applies to
other safety checks of the helper: mutate the check, expect the named test to
fail, restore. This page records the practice. The commands above were not run
as part of writing it.

## Adding tests

- Helper tests go in `tests/test_*.py` and use `load_helper()`. Mark any test
  that needs a keyring daemon, D-Bus or the sandbox's tools with `sandbox_only`.
- A test that stores or clears items must use the sandbox. Never point a test
  at the host keyring.
- Panel tests go in `tests/qml/` and use `Session`. They skip themselves
  outside the QML sandbox (`in_qml_sandbox()`).
- Tests wait for observable state, output or signals. Timeouts only bound a
  failure.
- Static guards (`tests/test_static_guards.py`) cover forbidden patterns and
  the line cap. A new QML file must be added to the guarded list there.
