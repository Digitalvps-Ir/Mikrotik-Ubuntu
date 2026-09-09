#!/usr/bin/env bash
# Experimental RAM-boot path; the existing script.sh remains the offline path.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/ram_installer.py" "$@"
