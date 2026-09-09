#!/usr/bin/env bash
# Compatibility entry point for the previously documented filename.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/script.sh" "$@"
