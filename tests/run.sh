#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
exec /usr/bin/python3 -m unittest discover -s tests -t "$ROOT" -v
