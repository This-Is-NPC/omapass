#!/bin/bash
# Start a headless sway (no input devices, software renderer, 1280x800
# output), wait for its Wayland socket, then run the given command.
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/rt
mkdir -m 700 -p "$XDG_RUNTIME_DIR"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
export WAYLAND_DISPLAY=wayland-1 QT_QPA_PLATFORM=wayland
printf 'output HEADLESS-1 resolution 1280x800\n' > /tmp/sway.cfg
sway-nocap -c /tmp/sway.cfg > /tmp/sway.log 2>&1 &
for _ in $(seq 100); do
  [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && break
  sleep 0.1
done
[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] || { cat /tmp/sway.log; echo "sway did not start" >&2; exit 1; }
# Bound the whole run from inside: killing the docker client does not stop us.
fg=()
[ -t 0 ] && fg=(--foreground)  # a tty shell cannot run in timeout's background group
exec timeout "${fg[@]}" -k 10 "${OMAPASS_RUN_TIMEOUT:-0}" "$@"
