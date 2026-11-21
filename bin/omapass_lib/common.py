"""Constants and helpers shared by every omapass-keyring module."""

import os
import subprocess
import sys
import unicodedata

SERVICE = "omapass"

# Named by the exit-6 messages, which appear when the keyring may be damaged.
HOWTO_CHECK = "run omapass doctor (docs/how-to-check-the-keyring.md in the omapass folder)"

# The entrypoint, which clipboard_copy runs as `clipboard-serve`.
ENTRYPOINT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "omapass-keyring"
)

WL_COPY = "/usr/bin/wl-copy"
WTYPE = "/usr/bin/wtype"
HYPRCTL = "/usr/bin/hyprctl"
NIRI = "/usr/bin/niri"

# Exit status when a write would replace an existing item without --replace.
EXIT_EXISTS = 4

# Exit status when the keyring file holds items a rewrite would corrupt, or
# when another omapass write holds the write lock.
EXIT_UNSAFE_KEYRING = 5

# Exit status when the keyring file no longer parses after a write.
EXIT_DAMAGED_KEYRING = 6

# Exit 7 is unused (it was the look-alike refusal); the other codes keep
# their numbers.

# Exit status of `type` when it aborted because focus or the layer-shell
# surfaces changed or cannot be read, and when wtype itself failed. Distinct
# from argparse's 2 and from 3 (no focus) and 4 to 6 above.
EXIT_FOCUS_CHANGED = 8
EXIT_WTYPE_FAILED = 9

# Exit status when the keyring or D-Bus cannot be reached. Never 1, so
# `exists` cannot mistake "unavailable" for "absent".
EXIT_KEYRING_UNAVAILABLE = 10

# Exit status when --replace would have to choose between items whose names
# differ only in Unicode normalization (NFC vs NFD).
EXIT_AMBIGUOUS = 11

# Exit status when a command that must act on one item finds several with the
# same account and kind (different folders): pass --folder.
EXIT_DUPLICATE = 12

# Exit status when `copy` or `type` refuses a stored secret that has control
# characters (a line break would be typed as Return).
EXIT_CONTROL_SECRET = 13

# Bound on every hyprctl, niri and wtype call, so a hung one cannot keep
# `type` holding the secret or stall the panel.
SUBPROCESS_TIMEOUT_S = 2

# Secrets are stored base64-encoded and tagged with this attribute. gnome-keyring
# writes plaintext secrets raw but reads them with key-file unescaping, so
# backslashes, leading spaces and the like would not survive a restart. Items
# without the tag are legacy: raw values, possibly with a trailing newline.
ENC_ATTR = "enc"
ENC_B64 = "b64"

MAX_ATTR_LEN = 256
MAX_SECRET_LEN = 4096

_CHILD_ENV_KEYS = (
    "HOME",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "WAYLAND_DISPLAY",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "NIRI_SOCKET",
    "LANG",
    "LC_ALL",
    "XDG_SESSION_TYPE",
)


def child_env():
    env = {"PATH": "/usr/bin:/bin"}
    for key in _CHILD_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


def one_line(text):
    return " ".join(str(text).split())


def die(msg, code=1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def unsafe_chars(value):
    """True if value has control characters (C0, DEL, C1, line/paragraph separators)."""
    return any(
        c < " " or "\x7f" <= c <= "\x9f" or c in "\u2028\u2029" for c in value
    )


# Unicode Default_Ignorable_Code_Point and blank characters outside Cf and Cs.
# The stdlib has no such property, so list them (Cf and Cs are checked by
# category): fillers, grapheme joiner, Khmer inherent vowels, Mongolian and
# other variation selectors, the unassigned slots inside the ignorable
# blocks, and the blank Braille pattern.
INVISIBLE_RANGES = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x2060, 0x206F),
    (0x2800, 0x2800),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0xE0000, 0xE0FFF),
)


def is_invisible(char):
    """True for an invisible format, surrogate, filler or blank character.

    Cf covers bidi controls, zero-width characters, soft hyphen, tag
    characters and the like. Private-use characters are visible glyphs, so
    they are allowed.
    """
    code = ord(char)
    return unicodedata.category(char) in ("Cf", "Cs") or any(
        lo <= code <= hi for lo, hi in INVISIBLE_RANGES
    )


def deceptive_chars(value):
    """True if value has an invisible character (see is_invisible)."""
    return any(is_invisible(c) for c in value)



def exec_abs(path, args, input=None, capture=False, env_extra=None, timeout=None):
    if not path or not os.path.isabs(path):
        die(f"refusing non-absolute executable path: {path!r}")
    cmd = [path] + list(args)
    env = child_env()
    if env_extra:
        env.update(env_extra)
    kwargs = {
        "env": env,
        "check": False,
        "timeout": timeout,
    }
    if input is not None:
        kwargs["input"] = input
        kwargs["text"] = True
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)



def take_account(argv, flag_name="--account"):
    if not argv:
        die("expected account argument")
    if argv[0] == "--":
        argv = argv[1:]
    if len(argv) != 1 or not argv[0]:
        die("expected exactly one account argument")
    return argv[0]


def take_optional_account(argv, default):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        return default
    if len(argv) != 1 or not argv[0]:
        die("expected at most one account argument")
    return argv[0]


def printable(text):
    """text with control and invisible characters shown as escapes, for a terminal."""
    return "".join(
        c.encode("unicode_escape").decode() if unsafe_chars(c) or is_invisible(c) else c
        for c in text
    )

