#!/bin/bash
# Tests always run inside the disposable keyring sandbox, never against the
# host keyring. tests/sandbox_env.py is the single "am I in the sandbox" check.
set -euo pipefail
SELF=$(/usr/bin/readlink -f -- "${BASH_SOURCE[0]}")
ROOT=$(cd "${SELF%/*}/.." && pwd)
if ! /usr/bin/python3 -I "$ROOT/tests/sandbox_env.py"; then
  exec "$ROOT/scripts/test-sandbox" ./tests/run.sh "$@"
fi
cd "$ROOT"
exec /usr/bin/python3 -m unittest discover -s tests -t "$ROOT" -v "$@"
