#!/usr/bin/env bash
# DigitalVPS CHR installer. Run from a complete checkout, never via curl | bash.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Missing python3. Install the documented prerequisites first.' >&2
    exit 1
fi
if [[ ! -f "$SCRIPT_DIR/chr_installer.py" ]]; then
    printf '%s\n' 'Missing chr_installer.py. Clone/download the complete repository.' >&2
    exit 1
fi
exec python3 "$SCRIPT_DIR/chr_installer.py" "$@"
