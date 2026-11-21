"""The libsecret backend: items in the default collection, guarded writes."""

import base64
import binascii
import collections
import contextlib
import errno
import fcntl
import os
import stat
import sys
import time
import unicodedata

from omapass_lib import common, keyfile_guard, secret_io

BACKEND = None

# The daemon may write the file after the D-Bus call returns.
VERIFY_TIMEOUT_S = 2.0
VERIFY_POLL_S = 0.05

# One omapass write at a time: store and clear hold this lock throughout.
LOCK_NAME = "omapass.lock"
LOCK_TIMEOUT_S = 10.0
LOCK_POLL_S = 0.05


def lock_path():
    """$XDG_RUNTIME_DIR/omapass.lock if that is a private directory of ours, else /tmp."""
    uid = os.getuid()
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if os.path.isabs(runtime):
        try:
            st = os.stat(runtime)
        except OSError:
            st = None
        if (
            st is not None
            and stat.S_ISDIR(st.st_mode)
            and st.st_uid == uid
            and st.st_mode & 0o777 == 0o700
        ):
            return os.path.join(runtime, LOCK_NAME)
    return f"/tmp/omapass-{uid}.lock"


@contextlib.contextmanager
def write_lock():
    """Hold an exclusive flock on the lock file; exit 5 if it cannot be had.

    Waits up to LOCK_TIMEOUT_S for another omapass write. The file must be a
    regular file owned by us (no symlinks).
    """
    fd = -1
    try:
        fd = os.open(
            lock_path(),
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise OSError(errno.EPERM, "unsafe lock file")
    except OSError:
        if fd >= 0:
            os.close(fd)
        common.die(
            "cannot open a safe omapass write lock; retry. Nothing was written.",
            common.EXIT_UNSAFE_KEYRING,
        )
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN) or time.monotonic() >= deadline:
                os.close(fd)
                common.die(
                    "another omapass write is running; retry. Nothing was written.",
                    common.EXIT_UNSAFE_KEYRING,
                )
        time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        os.close(fd)


def encode_secret(secret):
    return base64.b64encode(secret.encode()).decode("ascii")


def is_encoded(item):
    return (item.get_attributes() or {}).get(common.ENC_ATTR) == common.ENC_B64


def decode_secret(item, stored):
    """Plain secret from a stored value; legacy items keep their raw value."""
    if not is_encoded(item):
        return secret_io.strip_one_newline(stored)
    try:
        return base64.b64decode(stored, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        common.die("stored secret is corrupt")



@contextlib.contextmanager
def daemon_write():
    """Turn a failed daemon write (GLib.Error, e.g. the disk is read-only) into exit 6."""
    from gi.repository import GLib

    try:
        yield
    except GLib.Error as exc:
        common.die(
            f"THE WRITE FAILED ({exc.message}). The daemon could not save the "
            "change. Check that the keyring directory is writable and has "
            f"space, then check the keyring before relying on it ({common.HOWTO_CHECK}).",
            common.EXIT_DAMAGED_KEYRING,
        )


class GiKeyring:
    def __init__(self):
        try:
            import gi

            gi.require_version("Secret", "1")
            from gi.repository import Secret
        except (ImportError, ValueError) as exc:
            print(
                "omapass-keyring requires PyGObject (python-gobject) and libsecret",
                file=sys.stderr,
            )
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        self._Secret = Secret

    def _attrs(self, account, kind=None):
        attrs = {"service": common.SERVICE, "account": account}
        if kind:
            attrs["kind"] = kind
        return attrs

    def list_items(self):
        Secret = self._Secret
        flags = Secret.SearchFlags.ALL
        flags &= ~Secret.SearchFlags.LOAD_SECRETS
        flags &= ~Secret.SearchFlags.UNLOCK
        from gi.repository import GLib

        # An unreadable keyring must fail, not look like an empty one.
        try:
            service = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION, None)
            default = Secret.Collection.for_alias_sync(
                service, "default", Secret.CollectionFlags.NONE, None
            )
            if default is None:
                common.die("keyring unavailable: no default collection", common.EXIT_KEYRING_UNAVAILABLE)
            results = default.search_sync(None, {"service": common.SERVICE}, flags, None)
        except GLib.Error as exc:
            common.die(f"keyring unavailable: {common.one_line(exc.message)}", common.EXIT_KEYRING_UNAVAILABLE)
        items = []
        for item in results:
            attrs = item.get_attributes() or {}
            account = attrs.get("account", "")
            if not account:
                continue
            items.append(
                {
                    "account": account,
                    "folder": item.get_label() or "",
                    "kind": attrs.get("kind", ""),
                }
            )
        identities = collections.Counter((row["account"], row["kind"]) for row in items)
        for row in items:
            row["warn"] = (
                secret_io.name_problem(row["account"])
                or secret_io.name_problem(row["folder"])
                or ("duplicate" if identities[(row["account"], row["kind"])] > 1 else "")
            )
        items.sort(key=lambda row: row["account"])
        return items

    def _find(self, account, kind="", secrets=False):
        """Items whose identity is exactly (account, kind).

        A search on {service, account} also matches items that carry extra
        attributes such as kind, so filter on kind explicitly. Only the default
        collection is searched: other ones (e.g. the ephemeral session
        collection) are writable by any local client.
        """
        Secret = self._Secret
        flags = Secret.SearchFlags.ALL
        flags &= ~Secret.SearchFlags.UNLOCK
        flags &= ~Secret.SearchFlags.LOAD_SECRETS
        if secrets:
            flags |= Secret.SearchFlags.UNLOCK | Secret.SearchFlags.LOAD_SECRETS
        results = self._default_collection().search_sync(
            None, {"service": common.SERVICE, "account": account}, flags, None
        )
        matches = [
            item
            for item in results
            if (item.get_attributes() or {}).get("kind", "") == kind
        ]
        # Encoded items first: callers read items[0].
        return sorted(matches, key=lambda item: not is_encoded(item))

    def _lookup(self, account, kind="", secrets=False, folder=None):
        """Items for a name typed by a user: exactly as given, else in NFC.

        Names are stored in NFC, so a decomposed spelling finds them. The
        exact spelling goes first, so an older item stored as typed stays
        reachable and is never shadowed by a different NFC item. Last, a
        stored spelling that differs from the name only in normalization (a
        legacy NFD item, which `store` also counts as the same account).
        """
        nfc = unicodedata.normalize
        seen = []

        def pairs():
            yield from (
                (account, kind),
                (nfc("NFC", account), kind),
                (account, nfc("NFC", kind)),
                (nfc("NFC", account), nfc("NFC", kind)),
            )
            for row in self.list_items():
                stored = row["account"]
                if nfc("NFC", stored) == nfc("NFC", account) and nfc("NFC", row["kind"]) == nfc(
                    "NFC", kind
                ):
                    yield stored, row["kind"]

        for pair in pairs():
            if pair in seen:
                continue
            seen.append(pair)
            items = self._find(*pair, secrets=secrets)
            if folder is not None:
                labels = {folder, nfc("NFC", folder)}
                items = [i for i in items if i.get_label() in labels]
            if items:
                return items
        return []

    def _group(self, account, kind="", secrets=False, folder=None):
        """The items of one identity: account, kind and, if given, folder.

        Items in one folder count as one (a leftover copy after a failed
        replace; the encoded one is first). Items in several folders are never
        guessed between: exit 12.
        """
        items = self._lookup(account, kind, secrets=secrets, folder=folder)
        labels = {i.get_label() or "" for i in items}
        if len(labels) > 1:
            names = ", ".join(sorted(repr(common.printable(label)) for label in labels))
            common.die(
                f"ambiguous: {len(items)} items in folders {names}; pass --folder",
                common.EXIT_DUPLICATE,
            )
        return items

    def get_secret(self, account, kind="", folder=None):
        items = self._group(account, kind, secrets=True, folder=folder)
        value = items[0].get_secret() if items else None
        secret = value.get_text() if value is not None else None
        if secret is None:
            common.die(f"no secret for account: {common.printable(account)}")
        return decode_secret(items[0], secret)

    def default_collection_path(self):
        return self._default_collection().get_object_path()

    def _default_collection(self):
        # Never let libsecret create a missing default keyring: that would
        # mask a real keyring that failed to load.
        Secret = self._Secret
        service = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION, None)
        collection = Secret.Collection.for_alias_sync(
            service, "default", Secret.CollectionFlags.NONE, None
        )
        if collection is None:
            common.die(
                "no default keyring found; refusing to create one",
                common.EXIT_KEYRING_UNAVAILABLE,
            )
        if collection.get_locked():
            service.unlock_sync([collection], None)
            if collection.get_locked():
                common.die(
                    "default keyring is locked; unlock it and retry",
                    common.EXIT_KEYRING_UNAVAILABLE,
                )
        return collection

    def _guard_write(self, collection):
        """Refuse a write that would make the daemon corrupt the keyring file.

        A plaintext keyring is written with raw `secret=` values but read with
        key-file unescaping. The write is allowed only if every item group in
        the file has a secret that the daemon serves unchanged and that
        survives that round trip, and the daemon serves every group. Nothing
        is written when the file cannot be located or read.
        """
        path = keyfile_guard.daemon_keyring_path(collection)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, TypeError):
            common.die(
                "refusing to write: cannot read the default keyring file, so it "
                "cannot be checked. Nothing was written.",
                common.EXIT_UNSAFE_KEYRING,
            )
        if data.startswith(keyfile_guard.ENCRYPTED_MAGIC):
            return None  # not readable here; _write_problem reads the write back
        kf = keyfile_guard.load_keyfile(data)
        if kf is None:
            common.die(
                "refusing to write: the default keyring file does not parse. "
                "Nothing was written.",
                common.EXIT_UNSAFE_KEYRING,
            )
        bad, count_differs = keyfile_guard.rewrite_risks(
            kf, data.decode(), keyfile_guard.served_secrets(collection)
        )
        if bad or count_differs:
            common.die(
                f"refusing to write: {bad} item(s) in the default keyring "
                "would be corrupted or lost by a rewrite (raw secret missing, "
                "differs from its unescaped or served value, not UTF-8, or an "
                "invalid or conflicting binary-secret, stored by another app or "
                "an older omapass; if another app was writing, retry)"
                + (
                    "; the daemon serves a different number of items than the "
                    "file has (another app may be writing: retry)"
                    if count_differs
                    else ""
                )
                + ". Nothing was written.",
                common.EXIT_UNSAFE_KEYRING,
            )
        return sum(keyfile_guard.is_item(g) for g in kf.get_groups()[0])

    def _write_problem(self, collection, path, account, kind, folder, encoded, expected_items, left=0):
        """Why the write is not confirmed, "damaged", or None.

        Plaintext keyring: the file must hold the target change, every item
        must pass `rewrite_risks`, and the item count must be the expected
        one. Encrypted keyring: only the Secret Service can show the target.
        """
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except (OSError, TypeError):
            return "the keyring file cannot be read"
        if data.startswith(keyfile_guard.ENCRYPTED_MAGIC):
            return self._service_problem(account, kind, folder, encoded)
        kf = keyfile_guard.load_keyfile(data)
        if kf is None:
            return "damaged"
        problem = keyfile_guard.file_problem(kf, account, kind, folder, encoded, left)
        if problem:
            return problem
        bad, count_differs = keyfile_guard.rewrite_risks(kf, data.decode(), keyfile_guard.served_secrets(collection))
        if bad:
            return f"{bad} item(s) in the file are not safe to rewrite"
        if count_differs:
            return "the daemon serves a different number of items than the file has"
        count = sum(keyfile_guard.is_item(g) for g in kf.get_groups()[0])
        if expected_items is not None and count != expected_items:
            return f"the file has {count} items, expected {expected_items}"
        return None

    def _service_problem(self, account, kind, folder, encoded):
        """Why the Secret Service does not show the write to the target, or None."""
        items = self._find(account, kind, secrets=True)
        if encoded is None:
            # `folder` is the removed item's label: a duplicate in another
            # folder is expected to remain.
            return (
                "the removed item is still served"
                if any(folder is None or (i.get_label() or "") == folder for i in items)
                else None
            )
        if len(items) != 1:
            return f"the daemon serves {len(items)} items with this identity, expected 1"
        item = items[0]
        value = item.get_secret()
        text = value.get_text() if value is not None else None
        # The daemon may add attributes (xdg:schema). A replace creates a new
        # item, so attributes only the old item had are not copied. Only ours
        # must match.
        attrs = item.get_attributes() or {}
        expected = {**self._attrs(account, kind if kind else None), common.ENC_ATTR: common.ENC_B64}
        if (
            any(attrs.get(k) != v for k, v in expected.items())
            or attrs.get("kind", "") != kind
            or item.get_label() != folder
            or text != encoded
        ):
            return "the item served differs from what was written"
        return None

    def _verify_written(
        self, collection, account, kind="", folder=None, encoded=None, expected_items=None, left=0
    ):
        """Confirm the write or die with 6.

        After a store (`encoded` and `folder` given) the target must carry the
        new secret and label; after a clear, be gone. `expected_items` is the
        item count the plaintext file must have. The daemon may write late, so
        poll briefly.
        """
        path = keyfile_guard.daemon_keyring_path(collection)
        deadline = time.monotonic() + VERIFY_TIMEOUT_S
        while True:
            problem = self._write_problem(
                collection, path, account, kind, folder, encoded, expected_items, left
            )
            if problem is None:
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(VERIFY_POLL_S)
        if problem == "damaged":
            common.die(
                "THE KEYRING FILE MAY BE DAMAGED: it no longer parses after this "
                "write (another app probably wrote at the same time). Do not log "
                f"out or reboot. Back up the keyring file now ({common.HOWTO_CHECK}).",
                common.EXIT_DAMAGED_KEYRING,
            )
        common.die(
            f"THE WRITE COULD NOT BE CONFIRMED ({problem}). Do not trust it: the "
            "change may exist only in the daemon's memory and be lost on "
            "restart, or another item may have been altered. Check the keyring "
            f"before relying on it ({common.HOWTO_CHECK}).",
            common.EXIT_DAMAGED_KEYRING,
        )

    def store(self, account, folder, secret, kind="", replace=False):
        """Create an item; replace the same (account, kind) only if asked.

        Avoids libsecret's replace-on-match store: it matches by attribute
        subset, so a login could clobber a Nostr item with the same account.
        """
        account, folder, secret, kind = secret_io.validate_entry(account, folder, secret, kind)
        with write_lock():
            self._store_locked(account, folder, secret, kind, replace)

    def _store_locked(self, account, folder, secret, kind, replace):
        Secret = self._Secret
        collection = self._default_collection()
        names = [row["account"] for row in self.list_items()]
        # Legacy items may be stored in NFD: the same item as its NFC name.
        spellings = {account} | {
            n for n in names if unicodedata.normalize("NFC", n) == account
        }
        existing = [i for sp in sorted(spellings) for i in self._find(sp, kind)]
        existing.sort(key=lambda item: not is_encoded(item))
        if existing and not replace:
            common.die(f"already exists: {common.printable(account)}", common.EXIT_EXISTS)
        # NFC and NFD spellings may hold different secrets: never merge them.
        stored_as = {(i.get_attributes() or {}).get("account", "") for i in existing}
        if len(stored_as) > 1:
            names = ", ".join(sorted(ascii(n) for n in stored_as))
            common.die(
                f"refusing to replace: {len(stored_as)} items differ only in "
                f"Unicode normalization ({names}); remove the one you do not "
                "want with rm, then retry",
                common.EXIT_AMBIGUOUS,
            )
        # Replace may merge copies that share one folder, never ones in several.
        labels = {i.get_label() for i in existing}
        if len(labels) > 1:
            names = ", ".join(sorted(repr(common.printable(label or "")) for label in labels))
            common.die(
                f"refusing to replace: {len(existing)} items share this account "
                f"in folders {names}; remove the unwanted ones with rm --folder",
                common.EXIT_DUPLICATE,
            )
        before = self._guard_write(collection)
        encoded = encode_secret(secret)
        value = Secret.Value.new(encoded, len(encoded), "text/plain")
        attrs = self._attrs(account, kind if kind else None)
        attrs[common.ENC_ATTR] = common.ENC_B64
        # Every replace creates a new item, then deletes the old copies. A
        # legacy spelling is replaced too, so the item ends up in NFC.
        # libsecret cannot set the secret and the label in one call, so an
        # in-place update can be killed between them and leave the new secret
        # in the old folder, with the old secret gone. A kill here leaves two
        # whole items instead.
        with daemon_write():
            created = Secret.Item.create_sync(
                collection,
                None,
                attrs,
                folder,
                value,
                Secret.ItemCreateFlags.NONE,
                None,
            )
            if created is None:
                common.die(f"could not create item: {common.printable(account)}")
            for item in existing:
                if not item.delete_sync(None):
                    common.die(
                        f"new value stored, but an old copy of {common.printable(account)} remains in "
                        f"folder {common.printable(item.get_label() or '')!r}; remove it with "
                        "rm --folder, or rerun with --replace if the folder is the same"
                    )
        expected = None if before is None else before + 1 - len(existing)
        self._verify_written(collection, account, kind, folder, encoded, expected)

    def clear(self, account, kind="", folder=None):
        with write_lock():
            self._clear_locked(account, kind, folder)

    def _clear_locked(self, account, kind, folder):
        items = self._group(account, kind, folder=folder)
        if not items:
            common.die(f"no such item: {common.printable(account)}")
        # Verify the item found, which may differ from the spelling given.
        attrs = items[0].get_attributes() or {}
        account, kind = attrs.get("account", account), attrs.get("kind", "")
        label = items[0].get_label() or ""
        left = len(self._find(account, kind)) - len(items)
        collection = self._default_collection()
        before = self._guard_write(collection)
        with daemon_write():
            for item in items:
                if not item.delete_sync(None):
                    common.die(f"could not remove: {common.printable(account)}")
        expected = None if before is None else before - len(items)
        self._verify_written(collection, account, kind, label, None, expected, left)

    def exists(self, account, kind="", folder=None):
        return bool(self._group(account, kind, folder=folder))


def get_backend():
    global BACKEND
    if BACKEND is not None:
        return BACKEND
    return GiKeyring()
