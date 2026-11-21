#!/bin/bash
# Start a private D-Bus session + gnome-keyring with a plaintext (empty
# password) Default_keyring, run the given command, then restart the daemon
# and check the keyring still loads. Exit 91 = the run broke the keyring.
set -euo pipefail

KR="$HOME/.local/share/keyrings"
mkdir -p "$KR"
if [ ! -f "$KR/Default_keyring.keyring" ]; then
  cat > "$KR/Default_keyring.keyring" <<'EOF'
[keyring]
display-name=Default keyring
ctime=0
mtime=0
lock-on-idle=false
lock-after=false
EOF
  printf 'Default_keyring' > "$KR/default"
fi

# Bound the whole run from inside: killing the docker client does not stop us.
fg=()
[ -t 0 ] && fg=(--foreground)  # a tty shell cannot run in timeout's background group
set -- timeout "${fg[@]}" -k 10 "${OMAPASS_RUN_TIMEOUT:-0}" "$@"
exec dbus-run-session -- bash -c '
  set -u
  start() { gnome-keyring-daemon --start --components=secrets >/dev/null; }
  start
  python3 -I /opt/sandbox/keyring-health.py || { echo "sandbox keyring unhealthy before run"; exit 90; }
  "$@"; rc=$?
  echo "--- keyring health after run (daemon restarted, file re-parsed) ---"
  old=$(pgrep -u "$(id -u)" -x gnome-keyring-d)
  for p in $old; do kill "$p"; done
  # Wait until the old daemon has exited (a zombie has): `--start` would
  # otherwise reuse it and the check below would not re-parse the file.
  for p in $old; do
    for _ in $(seq 100); do
      s=$(sed -n "s/^State:[[:space:]]*\(.\).*/\1/p" "/proc/$p/status" 2>/dev/null)
      { [ -n "$s" ] && [ "$s" != Z ]; } || break
      sleep 0.05
    done
    if [ -n "$s" ] && [ "$s" != Z ]; then echo "old keyring daemon $p did not exit"; exit 92; fi
  done
  start
  for p in $(pgrep -u "$(id -u)" -x gnome-keyring-d); do
    case " $old " in *" $p "*) echo "old keyring daemon $p still serving"; exit 92 ;; esac
  done
  python3 -I /opt/sandbox/keyring-health.py || exit 91
  exit $rc
' sandbox "$@"
