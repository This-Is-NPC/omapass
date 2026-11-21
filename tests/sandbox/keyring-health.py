"""Sandbox keyring check. The diagnosis is `omapass doctor`.

The disposable daemon starts locked. `omapass doctor` never unlocks (a locked
keyring is exit 10). This wrapper unlocks the sandbox collection first so the
suite's before/after check can read items, then runs the same command. Prints
counts and item ids only, never secrets.
"""
import importlib.machinery
import importlib.util
import os

_REPO_HELPER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "bin", "omapass-keyring")
HELPER = os.environ.get("OMAPASS_HELPER") or next(
    (p for p in ("/src/bin/omapass-keyring", _REPO_HELPER) if os.path.exists(p)),
    "/src/bin/omapass-keyring",
)
_loader = importlib.machinery.SourceFileLoader("omapass_keyring", HELPER)
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(helper)


def _unlock_sandbox_default():
    """The sandbox daemon starts locked. The doctor command must not unlock."""
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    service = Secret.Service.get_sync(
        Secret.ServiceFlags.OPEN_SESSION | Secret.ServiceFlags.LOAD_COLLECTIONS, None
    )
    collection = Secret.Collection.for_alias_sync(
        service, "default", Secret.CollectionFlags.NONE, None
    )
    if collection is not None and collection.get_locked():
        service.unlock_sync([collection], None)


if __name__ == "__main__":
    _unlock_sandbox_default()
    helper.main(["doctor"])
