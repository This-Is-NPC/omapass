"""The one check for "this process runs inside the disposable sandbox".

An environment variable alone proves nothing: anyone can export it on the
host. The image also bakes a root-owned marker file the host does not have.
`tests/run.sh` runs this file as a script (exit 0 = inside the sandbox) and
every sandbox-only test uses `sandbox_only`, so there is a single definition.
"""

from __future__ import annotations

import os
import stat
import sys
import unittest

MARKER = "/opt/sandbox/IN_SANDBOX"

# Shell helper for tests that run a private D-Bus session: stop only the
# keyring daemons started on this session's bus, never the sandbox's own, and
# return once they have exited (a daemon still running would be reused by the
# next --start). Fails after about 5 s.
STOP_OWN_KEYRING = r"""
stop_keyring() {
  # A zombie has exited; only its parent has not reaped it yet.
  alive() {
    local s
    s=$(sed -n 's/^State:[[:space:]]*\(.\).*/\1/p' "/proc/$1/status" 2>/dev/null)
    [ -n "$s" ] && [ "$s" != Z ]
  }
  local p n
  local -a stopped=()
  for p in $(pgrep -u "$(id -u)" -x gnome-keyring-d); do
    # Bus-activated daemons only get DBUS_STARTER_ADDRESS.
    if tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null \
        | grep -qxE "DBUS_(SESSION_BUS|STARTER)_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"; then
      kill "$p" && stopped+=("$p")
    fi
  done
  for p in ${stopped[@]+"${stopped[@]}"}; do
    for n in $(seq 100); do
      alive "$p" || break
      sleep 0.05
    done
    if alive "$p"; then
      echo "keyring daemon $p did not exit" >&2
      return 1
    fi
  done
  return 0
}
"""


def in_sandbox() -> bool:
    if os.environ.get("OMAPASS_SANDBOX") != "1":
        return False
    try:
        st = os.stat(MARKER)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == 0


sandbox_only = unittest.skipUnless(in_sandbox(), "needs the keyring sandbox")

if __name__ == "__main__":
    sys.exit(0 if in_sandbox() else 1)
