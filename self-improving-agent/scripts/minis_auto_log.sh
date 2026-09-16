#!/bin/sh
# Compatibility wrapper for self-improving-agent v3.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/self_improving.py" "$@"
