"""The plaintext key-file rule (is the keyring safe to rewrite?) and `doctor`."""

import base64
import binascii
import os

from omapass_lib import common

# First bytes of an encrypted keyring file; the plaintext hazard does not apply.
ENCRYPTED_MAGIC = b"GnomeKeyring\n\r\0\n"


def reload_text(data):
    """Value the daemon reloads from a raw `secret=` line of these bytes.

    Returns b"" if the value is lost (an invalid escape) and None if the line
    breaks the file (a raw newline, or text that does not parse).
    """
    from gi.repository import GLib

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\n" in text:
        return None
    raw = f"[x]\nsecret={text}\n"
    kf = GLib.KeyFile()
    try:
        kf.load_from_data(raw, len(raw.encode()), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return None
    try:
        return kf.get_string("x", "secret").encode()
    except GLib.Error:
        return b""


def is_item(group):
    """The daemon's item rule: not [keyring], no ":" (attributes, ACLs)."""
    return group != "keyring" and ":" not in group


def group_of(ident):
    """File group of a D-Bus item id (the same unescaping as collection names)."""
    from gi.repository import GLib

    return GLib.uri_unescape_string(ident.replace("_", "%"), None)


def served_secrets(collection):
    """Group name to the bytes the daemon serves, for items with a readable secret."""
    from gi.repository import Secret

    # A search asks the daemon again; the collection's cached item list can be stale.
    items = collection.search_sync(
        None, {}, Secret.SearchFlags.ALL | Secret.SearchFlags.LOAD_SECRETS, None
    )
    served = {}
    for item in items:
        value = item.get_secret()
        if value is not None:
            served[group_of(os.path.basename(item.get_object_path()))] = value.get()
        del value
    return served


def load_keyfile(data):
    """GLib.KeyFile of the file bytes, or None if they do not parse."""
    from gi.repository import GLib

    kf = GLib.KeyFile()
    try:
        kf.load_from_data(data.decode("utf-8"), len(data), GLib.KeyFileFlags.NONE)
    except (UnicodeDecodeError, GLib.Error):
        return None
    return kf


def rewrite_keeps(kf, group, found, value):
    """True if a rewrite leaves this item no worse than a reload without it.

    The daemon rewrites `value` (hex if not UTF-8, else raw text); `after` is
    what that reloads to, `now` what the current lines reload to. Raises
    ValueError for invalid hex.
    """
    from gi.repository import GLib

    if "binary-secret" in found:
        if "secret" in found:
            return False
        now = bytes.fromhex(found["binary-secret"][0])
    elif "secret" in found:
        try:
            now = kf.get_string(group, "secret").encode()
        except GLib.Error:
            now = b""
    else:
        now = b""
    # The daemon may reload the file at any time (it watches it), so the
    # reloaded value must itself survive the next rewrite: a literal
    # backslash-n served as typed becomes a raw newline after a reload.
    if not survives_cycle(now):
        return False
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        return value == now  # kept as hex, reloaded intact
    return reload_text(value) == now


def survives_cycle(value):
    """True if a value written by the daemon reloads to itself (hex if not UTF-8)."""
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return reload_text(value) == value


def rewrite_risks(kf, text, served):
    """Count item groups a rewrite would alter or drop, and whether counts differ.

    THE rule for "is this keyring file safe to rewrite?", used before and after
    a write and by the sandbox health check. `served` maps a group name to the
    bytes the daemon serves. Counts only, never values.

    A group is safe if the daemon serves it and a rewrite leaves it no worse
    than a plain reload would (`rewrite_keeps`): a value that is already lost
    on reload, such as leading spaces served before a restart, is not made
    worse by writing it again. Not safe: not served, a rewrite that changes the
    reloaded value or breaks the file (a newline), invalid `binary-secret`
    hex, both `secret=` and `binary-secret=` (the daemon drops one), or a
    repeated line.
    """
    groups = [g for g in kf.get_groups()[0] if is_item(g)]
    lines, group = {}, None
    for line in text.split("\n"):
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
        elif group is not None:
            for key in ("secret", "binary-secret"):
                if line.startswith(key + "="):
                    lines.setdefault(group, {}).setdefault(key, []).append(line[len(key) + 1:])
    bad = 0
    for group in groups:
        found, value = lines.get(group, {}), served.get(group)
        ok = value is not None and all(len(v) == 1 for v in found.values())
        if ok:
            try:
                ok = rewrite_keeps(kf, group, found, value)
            except ValueError:  # invalid hex
                ok = False
        bad += not ok
    return bad, len(groups) != len(served)


def item_attrs(kf, group):
    """Attributes of an item group, from its [<group>:attributeN] groups."""
    from gi.repository import GLib

    attrs, n = {}, 0
    while kf.has_group(f"{group}:attribute{n}"):
        try:
            attrs[kf.get_string(f"{group}:attribute{n}", "name")] = kf.get_string(
                f"{group}:attribute{n}", "value"
            )
        except GLib.Error:
            pass
        n += 1
    return attrs


def matching_groups(kf, account, kind):
    """Item groups with this omapass identity (service, account, kind)."""
    found = []
    for group in kf.get_groups()[0]:
        if is_item(group):
            attrs = item_attrs(kf, group)
            if (
                attrs.get("service") == common.SERVICE
                and attrs.get("account") == account
                and attrs.get("kind", "") == kind
            ):
                found.append((group, attrs))
    return found


def daemon_keyring_path(collection):
    """Keyring file of a collection as the daemon sees it, or None.

    Uses the environment of the process that owns org.freedesktop.secrets, not
    this one, because the two can differ.
    """
    from gi.repository import Gio, GLib

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        pid = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetConnectionUnixProcessID",
            GLib.Variant("(s)", ("org.freedesktop.secrets",)),
            None, Gio.DBusCallFlags.NONE, 5000, None,
        ).unpack()[0]
        with open(f"/proc/{pid}/environ", "rb") as fh:
            env = dict(
                entry.split(b"=", 1) for entry in fh.read().split(b"\0") if b"=" in entry
            )
    except (GLib.Error, OSError, ValueError):
        return None
    base = env.get(b"XDG_DATA_HOME", b"").decode(errors="replace")
    if not base:
        home = env.get(b"HOME", b"").decode(errors="replace")
        if not home:
            return None
        base = os.path.join(home, ".local/share")
    name = os.path.basename(collection.get_object_path())
    filename = GLib.uri_unescape_string(name.replace("_", "%"), None)
    if not filename:
        return None
    return os.path.join(base, "keyrings", filename + ".keyring")


def file_problem(kf, account, kind, folder, encoded, left=0):
    """Why the parsed keyring file does not reflect a write to the target, or None.

    After a removal, `left` copies in other folders are expected to remain.
    """
    from gi.repository import GLib

    found = matching_groups(kf, account, kind)
    if encoded is None:
        return "the removed item is still in the file" if len(found) != left else None
    if len(found) != 1:
        return f"the file has {len(found)} items with this identity, expected 1"
    group, attrs = found[0]
    try:
        stored = (kf.get_string(group, "secret"), kf.get_string(group, "display-name"))
    except GLib.Error:
        return "the item in the file has no secret or label"
    if attrs.get(common.ENC_ATTR) != common.ENC_B64 or stored != (encoded, folder):
        return "the item in the file differs from what was written"
    return None


def keyring_file_lines(kr_dir):
    """One line per ``*.keyring`` file. Returns ``(all_ok, lines)``.

    Reads the files and parses them. Encrypted files are reported and not parsed.
    """
    import glob

    from gi.repository import GLib

    ok = True
    lines = []
    for path in sorted(glob.glob(os.path.join(kr_dir, "*.keyring"))):
        name = os.path.basename(path)
        with open(path, "rb") as fh:
            magic = fh.read(len(ENCRYPTED_MAGIC))
        if magic == ENCRYPTED_MAGIC:
            lines.append(f"OK   file {name}: encrypted (not parsed)")
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(path, GLib.KeyFileFlags.NONE)
            n = sum(1 for group in kf.get_groups()[0] if is_item(group))
            lines.append(f"OK   file {name}: parses, {n} items")
        except GLib.Error as exc:
            ok = False
            lines.append(f"FAIL file {name}: {exc.message}")
    return ok, lines


def doctor_items(kr_dir):
    """Read the default collection. Returns ``(exit_code, lines)``.

    A locked collection is reported and left locked: this never asks the
    daemon to open it. Item ids are object-path basenames, never secrets
    or account names.
    """
    from gi.repository import GLib, Secret

    service = Secret.Service.get_sync(
        Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None
    )
    collection = Secret.Collection.for_alias_sync(
        service, "default", Secret.CollectionFlags.NONE, None
    )
    if collection is None:
        return 1, ["FAIL items: default collection missing"]
    if collection.get_locked():
        return common.EXIT_KEYRING_UNAVAILABLE, ["FAIL items: the default keyring is locked"]
    collection = Secret.Collection.for_alias_sync(
        service, "default", Secret.CollectionFlags.LOAD_ITEMS, None
    )
    name = os.path.basename(collection.get_object_path())
    file_path = os.path.join(kr_dir, group_of(name) + ".keyring")
    encrypted = False
    if os.path.exists(file_path):
        with open(file_path, "rb") as fh:
            encrypted = fh.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC
    data = None
    kf = None
    if not encrypted:
        with open(file_path, "rb") as fh:
            data = fh.read()
        kf = load_keyfile(data)
        if kf is None:
            return 1, ["FAIL items: cannot reload file"]
    lines = []
    served_by_group = {}
    count = 0
    healthy = True
    for item in collection.get_items():
        count += 1
        ident = os.path.basename(item.get_object_path())
        try:
            item.load_secret_sync(None)
            value = item.get_secret()
            attrs = item.get_attributes() or {}
            item.get_label()
            if value is None:
                raise ValueError("no secret")
            served = value.get()
        except (GLib.Error, ValueError) as exc:
            lines.append(f"FAIL item {ident}: unreadable ({getattr(exc, 'message', exc)})")
            healthy = False
            continue
        served_by_group[group_of(ident)] = served
        if attrs.get("enc") == "b64":
            try:
                base64.b64decode(served, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                lines.append(f"FAIL item {ident}: enc=b64 but the value is not base64 of UTF-8 text")
                healthy = False
                continue
        lines.append(f"OK   item {ident}")
    if data is not None:
        bad, count_differs = rewrite_risks(kf, data.decode(), served_by_group)
        if bad:
            lines.append(f"FAIL items: {bad} item(s) are not safe to rewrite (see the helper's rule)")
            healthy = False
        if count_differs:
            nfile = sum(map(is_item, kf.get_groups()[0]))
            lines.append(f"FAIL items: file has {nfile} items, daemon serves {count}")
            healthy = False
    if healthy:
        note = "safe to rewrite" if data is not None else "encrypted file not compared"
        lines.append(f"OK   items: {count} read back, {note}")
    return (0 if healthy else 1), lines


def _doctor_report(kr_dir):
    from gi.repository import Gio, GLib

    files_ok, lines = keyring_file_lines(kr_dir)
    for line in lines:
        print(line)
    pointer = os.path.join(kr_dir, "default")
    if os.path.exists(pointer):
        with open(pointer, encoding="utf-8", errors="replace") as fh:
            print(f"OK   pointer default -> {fh.read()!r}")
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    alias = bus.call_sync(
        "org.freedesktop.secrets",
        "/org/freedesktop/secrets",
        "org.freedesktop.Secret.Service",
        "ReadAlias",
        GLib.Variant("(s)", ("default",)),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    ).unpack()[0]
    if alias == "/":
        print("FAIL alias default -> / (no default keyring loaded)")
        return 1
    print(f"OK   alias default -> {alias}")
    # A file that does not parse is exit 1 even when the collection is also locked.
    if not files_ok:
        return 1
    code, item_lines = doctor_items(kr_dir)
    for line in item_lines:
        print(line)
    return code


def cmd_doctor(_args):
    """Read-only keyring check. Never writes or unlocks. Counts and item ids only."""
    from gi.repository import GLib

    kr_dir = os.path.expanduser("~/.local/share/keyrings")
    try:
        code = _doctor_report(kr_dir)
    except GLib.Error as exc:
        print(f"FAIL items: {common.one_line(exc.message)}")
        code = 1
    raise SystemExit(code)
