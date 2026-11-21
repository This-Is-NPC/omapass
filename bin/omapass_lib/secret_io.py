"""Input checks, the clipboard helper and autotype: everything that handles a plain secret."""

import collections
import ctypes
import json
import os
import resource
import select
import signal
import stat
import subprocess
import sys
import time
import unicodedata

from omapass_lib import common, keyring_store

PR_SET_DUMPABLE = 4
PR_SET_PDEATHSIG = 1

CLIPBOARD_TTL_S = 30
# How long to watch for wl-copy failing right after it starts.
CLIPBOARD_START_S = 0.1

TYPE_TIMEOUT_MS = 500
TYPE_POLL_MS = 50
# The longest wait for omapass's own panel layer (120 ms fade-out) to unmap.
PANEL_UNMAP_TIMEOUT_S = 1.0
PANEL_NAMESPACE = "omarchy-keyboard-panel"
TYPE_CHUNK = 1

MEMORY_FS = ("tmpfs", "ramfs")


def name_problem(value):
    """Why a name could mislead the reader, as a short code, or None.

    Codes: control, invisible.
    """
    if common.unsafe_chars(value):
        return "control"
    if common.deceptive_chars(value):
        return "invisible"
    return None


def validate_entry(account, folder, secret, kind=""):
    """Reject values that would corrupt the keyring file or mistype later.

    Secrets are stored base64-encoded, so only control characters matter
    (typing and clipboard semantics). Account, folder and kind are attributes
    and a label, which gnome-keyring escapes itself; they must not hide
    characters that spoof the panel. Returns the values with account, folder
    and kind normalized to NFC.
    """
    account, folder, kind = (
        unicodedata.normalize("NFC", v) for v in (account, folder, kind)
    )
    for name, value, limit in (
        ("account", account, common.MAX_ATTR_LEN),
        ("folder", folder, common.MAX_ATTR_LEN),
        ("kind", kind, common.MAX_ATTR_LEN),
        ("secret", secret, common.MAX_SECRET_LEN),
    ):
        if name != "kind" and not value:
            common.die(f"{name} must not be empty")
        if len(value) > limit:
            common.die(f"{name} is too long (max {limit} characters)")
        if common.unsafe_chars(value):
            common.die(f"{name} must not contain control characters or line breaks")
        if name == "secret":
            continue
        if name_problem(value) == "invisible":
            common.die(f"{name} must not contain invisible characters (bidi, zero-width, fillers, variation selectors)")
    return account, folder, secret, kind


def strip_one_newline(text):
    return text[:-1] if text.endswith("\n") else text


def read_secret_value():
    if sys.stdin.isatty():
        import getpass

        secret = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if secret != confirm:
            common.die("passwords do not match")
        return secret
    return strip_one_newline(sys.stdin.read())


ITEM_FIELDS = {"account", "kind", "folder", "compositor", "expect_id"}
# Same facts on the command line. Checked on the raw argv: --kind defaults to
# "" and an explicit empty --folder= is indistinguishable from "not passed"
# once argparse has filled the defaults.
_ITEM_ARGV_FLAGS = ("--account", "--folder", "--kind", "--compositor", "--expect-id")


def _item_named_on_argv(argv):
    """True if argv names the item beside --item-stdin (a flag or a positional)."""
    args = list(argv or [])
    if args and not args[0].startswith("-"):
        args = args[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return bool(args[i + 1:])
        if arg == "--item-stdin":
            i += 1
            continue
        for flag in _ITEM_ARGV_FLAGS:
            if arg == flag or arg.startswith(flag + "="):
                return True
        if not arg.startswith("-"):
            return True
        i += 1
    return False


def read_item_stdin(args, argv):
    """Fill args from the JSON object on stdin (--item-stdin).

    The panel names its item this way, so account names and window ids stay out
    of the command line, which other users can read in /proc. Fields it omits
    keep their argparse defaults. Anything else is refused. A per-item flag or
    a positional name on argv is refused before stdin is read and before the
    keyring is used.
    """
    if _item_named_on_argv(argv):
        common.die("--item-stdin takes the item from stdin, not from arguments")
    try:
        item = json.loads(sys.stdin.read(65536))
    except (ValueError, OSError):
        item = None
    if (
        not isinstance(item, dict)
        or not item.keys() <= ITEM_FIELDS
        or not all(isinstance(v, str) for v in item.values())
        or not item.get("account")
        or item.get("compositor", "hyprland") not in ("hyprland", "niri")
    ):
        common.die("--item-stdin expects a JSON object of strings with an account")
    for key, value in item.items():
        setattr(args, key, value)



def harden_process():
    """Keep secrets out of core dumps and away from same-user ptrace (best effort)."""
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (OSError, ValueError):
        pass
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def mount_fstype(path):
    """Filesystem type of the mount holding path (innermost mount wins)."""
    best, fstype = "", ""
    with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as f:
        for line in f:
            left, _, right = line.partition(" - ")
            fields = left.split()
            if len(fields) < 5 or not right:
                continue
            point = fields[4].encode().decode("unicode_escape")
            inside = path == point or path.startswith(point.rstrip("/") + "/")
            if inside and len(point) >= len(best):
                best, fstype = point, right.split()[0]
    return fstype


def runtime_dir_problem(real, runtime):
    """Why real (the resolved runtime) cannot hold a secret buffer, or None."""
    try:
        st = os.stat(real)
        fstype = mount_fstype(real)
    except OSError as exc:
        return f"cannot inspect XDG_RUNTIME_DIR {runtime}: {exc.strerror}"
    if not stat.S_ISDIR(st.st_mode):
        return f"XDG_RUNTIME_DIR {runtime} is not a directory"
    if st.st_uid != os.getuid():
        return f"XDG_RUNTIME_DIR {runtime} is not owned by the current user"
    if st.st_mode & 0o077:
        return f"XDG_RUNTIME_DIR {runtime} is accessible to other users (needs mode 0700)"
    if fstype not in MEMORY_FS:
        return f"XDG_RUNTIME_DIR {runtime} is on {fstype or 'an unknown filesystem'}, not tmpfs"
    return None


def private_runtime_dir():
    """The resolved XDG_RUNTIME_DIR, or common.die if it cannot hold a secret buffer.

    wl-copy buffers stdin in a temp file there, so it must be private and
    memory-backed. Callers use the returned path, not the variable, so a
    swapped symlink cannot escape the check.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not os.path.isabs(runtime):
        common.die("refusing to copy: XDG_RUNTIME_DIR is required to copy without writing to disk")
    real = os.path.realpath(runtime)
    problem = runtime_dir_problem(real, runtime)
    if problem:
        common.die(f"refusing to copy: {problem}")
    return real


def clipboard_copy(text):
    """Hand text to a detached clipboard-serve helper and wait until it serves it."""
    private_runtime_dir()
    helper = common.ENTRYPOINT
    if not os.path.isabs(helper):
        common.die(f"refusing non-absolute helper path: {helper!r}")
    proc = subprocess.Popen(
        ["/usr/bin/python3", "-I", helper, "clipboard-serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=common.child_env(),
        start_new_session=True,
    )
    try:
        proc.stdin.write(text.encode())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    status = proc.stdout.readline()
    proc.stdout.close()
    if status != b"ok\n":
        common.die("wl-copy failed")


def refuse_control_chars(secret, verb):
    """Exit 13 for a secret with control characters (not made by omapass)."""
    if common.unsafe_chars(secret):
        common.die(f"stored secret has control characters or line breaks; not {verb}", common.EXIT_CONTROL_SECRET)


def cmd_copy(args):
    account = args.account or common.take_account(args.rest)
    secret = keyring_store.get_backend().get_secret(account, args.kind, args.folder)
    refuse_control_chars(secret, "copied")
    clipboard_copy(secret)


def cmd_copy_text(_args):
    clipboard_copy(sys.stdin.read())


def die_with_parent():
    """Child setup: SIGTERM this process when its parent dies (survives exec)."""
    try:
        ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        pass



def cmd_clipboard_serve(args):
    """Internal: own wl-copy until another copy replaces it or the TTL passes.

    The secret arrives on stdin and goes to wl-copy's stdin only. wl-copy
    exits by itself when another client takes the selection. Killing it
    empties the clipboard. Prints "ok" once the selection is served.
    """
    real = private_runtime_dir()
    secret = sys.stdin.buffer.read()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    proc = subprocess.Popen(
        [common.WL_COPY, "--foreground", "--sensitive", "--type", "text/plain"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**common.child_env(), "TMPDIR": real},
        preexec_fn=die_with_parent,
    )
    pidfd = -1
    try:
        try:
            proc.stdin.write(secret)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        del secret
        pidfd = os.pidfd_open(proc.pid)
        started = time.monotonic()
        select.select([pidfd], [], [], CLIPBOARD_START_S)
        code = proc.poll()
        print("fail" if code else "ok", flush=True)
        if code is not None:
            return
        select.select([pidfd], [], [], max(0.0, args.ttl - (time.monotonic() - started)))
    finally:
        if pidfd >= 0:
            os.close(pidfd)
        proc.terminate()
        try:
            proc.wait(2)
        except subprocess.TimeoutExpired:
            proc.kill()


def query_compositor(path, args):
    """Stdout of a compositor command, or None if it is missing, fails or hangs."""
    try:
        result = common.exec_abs(path, args, capture=True, timeout=common.SUBPROCESS_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout


def read_hyprland_focus():
    out = query_compositor(common.HYPRCTL, ["activewindow", "-j"])
    if out is None:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    # stableId is never reused; an address is a pointer that can be.
    ident = (data.get("stableId") or data.get("address")) if isinstance(data, dict) else None
    if not ident:
        return None
    return {"compositor": "hyprland", "id": str(ident)}


def read_niri_focus():
    out = query_compositor(common.NIRI, ["msg", "--json", "focused-window"])
    if out is None:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    wid = data.get("id") if isinstance(data, dict) else None
    if wid is None:
        return None
    return {"compositor": "niri", "id": str(wid)}


def layer_key(layer):
    """Identity of a Hyprland layer: (namespace, id).

    The id is the stableId. Without one, an address alone can be reused, and
    every Omarchy panel shares one namespace and pid, so the id also holds the
    pid and the geometry.
    """
    if layer.get("stableId"):
        ident = ("stable", str(layer["stableId"]))
    else:
        ident = tuple(
            str(layer.get(k)) for k in ("address", "pid", "x", "y", "w", "h")
        )
    return (layer.get("namespace"), ident)


def read_layers(compositor):
    """Return a Counter of layer-shell surfaces that could take keyboard focus.

    Keys are (namespace, id). Hyprland's IPC JSON has no interactivity field,
    so every layer counts.
    niri reports keyboard_interactivity, so only non-"none" layers count.
    None means unreadable.
    """
    if compositor == "hyprland":
        out = query_compositor(common.HYPRCTL, ["layers", "-j"])
    elif compositor == "niri":
        out = query_compositor(common.NIRI, ["msg", "--json", "layers"])
    else:
        return None
    if out is None:
        return None
    try:
        data = json.loads(out)
        found = collections.Counter()
        if compositor == "hyprland":
            for mon in data.values():
                for level in mon["levels"].values():
                    for layer in level:
                        found[layer_key(layer)] += 1
        else:
            for layer in data:
                if layer.get("keyboard_interactivity") != "none":
                    found[(layer.get("namespace"), (layer.get("layer"),))] += 1
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return found


def session_locked(compositor):
    """True when Hyprland reports a session lock (hyprlock, Omarchy's lock).

    A lock is an ext-session-lock surface, not a layer, and the focused window
    does not change. Hyprland lists it as LOCK in a monitor's
    `solitaryBlockedBy`, as Omarchy's own omarchy-hyprland-session-locked does.
    None means unknown: the query failed, hung or answered something other
    than a non-empty list of monitor objects, or every monitor is blocked by
    WORKSPACE: Hyprland stops at that reason before it reaches the lock, so
    nothing was asked (Omarchy's script calls this "undetermined" too). False
    means "no lock seen" on a monitor that was asked.
    """
    if compositor != "hyprland":
        return False
    out = query_compositor(common.HYPRCTL, ["monitors", "-j"])
    if out is None:
        return None
    try:
        monitors = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(monitors, list) or not monitors:
        return None
    blocked = []
    for mon in monitors:
        reasons = mon.get("solitaryBlockedBy") if isinstance(mon, dict) else False
        if reasons is not None and not isinstance(reasons, list):
            return None
        blocked.append(reasons or [])
    if any("LOCK" in reasons for reasons in blocked):
        return True
    if all("WORKSPACE" in reasons for reasons in blocked):
        return None
    return False


def wtype_tmp_problem(tmp="/tmp"):
    """Why wtype's keymap file in /tmp could reach a disk, or None.

    wtype 0.4 writes the keymap for each typed character to a hard-coded
    /tmp/wtype-XXXXX and ignores TMPDIR.
    """
    real = os.path.realpath(tmp)
    try:
        st = os.stat(real)
        fstype = mount_fstype(real)
    except OSError as exc:
        return f"cannot inspect {tmp}: {exc.strerror}"
    if not stat.S_ISDIR(st.st_mode):
        return f"{tmp} is not a directory"
    if fstype not in MEMORY_FS:
        return f"{tmp} is on {fstype or 'an unknown filesystem'}, not tmpfs"
    if not st.st_mode & stat.S_ISVTX and st.st_mode & 0o022:
        return f"{tmp} is writable by other users without the sticky bit"
    return None


def focus_snapshot():
    return read_hyprland_focus() or read_niri_focus()


def read_focus_for(compositor):
    if compositor == "hyprland":
        return read_hyprland_focus()
    if compositor == "niri":
        return read_niri_focus()
    return None


def focus_matches(snapshot):
    if not snapshot:
        return False
    current = read_focus_for(snapshot["compositor"])
    return bool(current and current.get("id") == snapshot.get("id"))


def wait_for_focus(snapshot):
    deadline = time.monotonic() + (TYPE_TIMEOUT_MS / 1000.0)
    while time.monotonic() < deadline:
        if focus_matches(snapshot):
            return True
        time.sleep(TYPE_POLL_MS / 1000.0)
    return focus_matches(snapshot)


def wait_for_panel_unmap(compositor):
    """Layers once no keyboard-panel surface is mapped; common.die if one stays.

    omapass closes its panel just before it types, and the layer stays mapped
    for the fade-out. A baseline taken then would hold it, and another panel
    could reuse its slot unseen. Every Omarchy panel shares this namespace,
    so another open one also stops the typing.
    """
    deadline = time.monotonic() + PANEL_UNMAP_TIMEOUT_S
    while True:
        layers = read_layers(compositor)
        if layers is None:
            common.die("layers unavailable", common.EXIT_FOCUS_CHANGED)
        if not any(str(ns).startswith(PANEL_NAMESPACE) for ns, _ in layers):
            return layers
        if time.monotonic() >= deadline:
            common.die("keyboard panel still open", common.EXIT_FOCUS_CHANGED)
        time.sleep(TYPE_POLL_MS / 1000.0)


def cmd_focus_snapshot(_args):
    snap = focus_snapshot()
    if not snap:
        common.die("no compositor focus available", 3)
    print(json.dumps(snap))


def cmd_type(args):
    account = args.account or common.take_account(args.rest)
    if not account:
        common.die("type requires --account or positional account")
    compositor = args.compositor
    expect_id = args.expect_id
    if expect_id is None or compositor is None:
        snap = focus_snapshot()
        if not snap:
            common.die("no compositor focus available", 3)
        compositor = snap["compositor"]
        expect_id = snap["id"]
    target = {"compositor": compositor, "id": str(expect_id)}
    problem = wtype_tmp_problem()
    if problem:
        common.die(f"refusing to type: {problem}", common.EXIT_WTYPE_FAILED)
    if not wait_for_focus(target):
        common.die("focus changed", common.EXIT_FOCUS_CHANGED)
    secret = keyring_store.get_backend().get_secret(account, args.kind, args.folder)
    refuse_control_chars(secret, "typed")
    # One character per wtype call. Before each one, abort if focus changed or
    # any layer-shell surface appeared, vanished or was replaced since the start.
    layers = wait_for_panel_unmap(target["compositor"])
    for i in range(0, len(secret), TYPE_CHUNK):
        current = read_focus_for(target["compositor"])
        if current is None:
            common.die("focus unavailable", common.EXIT_FOCUS_CHANGED)
        if current.get("id") != target.get("id"):
            common.die("focus changed", common.EXIT_FOCUS_CHANGED)
        now = read_layers(target["compositor"])
        if now is None:
            common.die("layers unavailable", common.EXIT_FOCUS_CHANGED)
        if now != layers:
            common.die("focus changed", common.EXIT_FOCUS_CHANGED)
        locked = session_locked(target["compositor"])
        if locked is None:
            common.die("session lock state unknown", common.EXIT_FOCUS_CHANGED)
        if locked:
            common.die("session locked", common.EXIT_FOCUS_CHANGED)
        try:
            result = common.exec_abs(
                common.WTYPE, ["-"], input=secret[i : i + TYPE_CHUNK], timeout=common.SUBPROCESS_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            common.die("wtype timed out", common.EXIT_WTYPE_FAILED)
        if result.returncode != 0:
            common.die("wtype failed", common.EXIT_WTYPE_FAILED)
