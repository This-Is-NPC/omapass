"""The one loader for bin/omapass-keyring and its omapass_lib package.

load_helper() returns a facade over the entrypoint and every package module.
Reading a name finds it in the first module that has it. Setting a name (a
plain assignment or mock.patch.object) sets it on every module that defines
it, so a patch reaches all callers. Deleting restores the originals, which
is what mock.patch does on exit. Each call imports fresh module objects.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "bin" / "omapass-keyring"
LIB_DIR = HELPER_PATH.parent
PACKAGE = "omapass_lib"
MODULES = ("common", "keyring_store", "keyfile_guard", "secret_io", "nostr")


class Helper(types.ModuleType):
    def __init__(self, modules):
        super().__init__("omapass_keyring")
        object.__setattr__(self, "_modules", modules)
        object.__setattr__(self, "_saved", {})

    def __getattr__(self, name):
        for mod in self._modules:
            if name in mod.__dict__:
                return mod.__dict__[name]
        for mod in self._modules:  # imported modules such as subprocess
            if hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        owners = [m for m in self._modules if name in m.__dict__]
        if not owners:
            raise AttributeError(f"no helper module defines {name}")
        saved = self._saved.setdefault(name, {})
        for mod in owners:
            saved.setdefault(mod, mod.__dict__[name])
            setattr(mod, name, value)

    def __delattr__(self, name):
        for mod, value in self._saved.pop(name, {}).items():
            setattr(mod, name, value)


def load_helper() -> Helper:
    for key in [k for k in sys.modules if k == PACKAGE or k.startswith(PACKAGE + ".")]:
        del sys.modules[key]
    if str(LIB_DIR) not in sys.path:
        sys.path.insert(0, str(LIB_DIR))
    loader = importlib.machinery.SourceFileLoader("omapass_keyring_entry", str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    entry = importlib.util.module_from_spec(spec)
    loader.exec_module(entry)
    libs = [importlib.import_module(f"{PACKAGE}.{name}") for name in MODULES]
    return Helper([entry, *libs])
