#!/bin/sh
# Compatibility wrapper for self-improving-agent v3.
set -eu
exec python3 /var/minis/skills/self-improving-agent/scripts/self_improving.py "$@"
