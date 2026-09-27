#!/usr/bin/env bash
# Replace an unmounted VM disk with the official MikroTik CHR RAW image.
set -Eeuo pipefail

REPOSITORY='https://download.mikrotik.com/routeros'
VERSION=''
DISK=''
WORK_BASE='/tmp'
EXPECTED_SHA256=''
YES_ERASE=0
WRITE_STARTED=0
WORK_DIR=''

usage() {
    cat <<'USAGE'
Usage: sudo bash script.sh --disk /dev/vda [--version 7.24.4] [options]

Run from a Linux rescue system with the target disk unmounted. All data on the
selected disk will be destroyed. The script never chooses a disk automatically.

Options:
  --disk DEVICE       Whole target disk, e.g. /dev/vda, /dev/sda or /dev/nvme0n1
  --version VERSION   Official CHR version; prompted for when omitted
  --workdir DIR       Download/extraction parent directory (default: /tmp)
  --sha256 HASH       Expected SHA-256 of the downloaded ZIP, if known
  --yes-erase         Skip the interactive exact-disk confirmation
  -h, --help          Show this help

After installation, disable rescue mode and power cycle from the provider panel.
The script does not configure RouterOS networking or reboot automatically.
USAGE
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*" >&2; }
cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf -- "$WORK_DIR"
    fi
}
on_error() {
    local status=$1
    if (( WRITE_STARTED )); then
        log 'Disk writing or verification failed. Do not boot this disk; recover from the provider rescue environment.'
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'on_error $?' ERR

while (($#)); do
    case "$1" in
        --disk|--version|--workdir|--sha256)
            (($# >= 2)) || die "Missing value for $1"
            case "$1" in
                --disk) DISK=$2 ;;
                --version) VERSION=$2 ;;
                --workdir) WORK_BASE=$2 ;;
                --sha256) EXPECTED_SHA256=$2 ;;
            esac
            shift 2 ;;
        --yes-erase) YES_ERASE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

(( EUID == 0 )) || die 'Run as root (sudo bash script.sh ...).'
[[ $(uname -m) == x86_64 ]] || die 'This installer supports x86_64 CHR only.'

for command in curl unzip sfdisk lsblk blockdev readlink wipefs dd cmp sync sha256sum stat cut grep tr mktemp rm; do
    command -v "$command" >/dev/null 2>&1 || die "Missing $command. Install curl, unzip, util-linux and coreutils in the rescue environment."
done

if [[ -d /sys/firmware/efi ]]; then
    die 'This VM booted in UEFI mode. This RAW CHR workflow requires Legacy BIOS; change the VM firmware or use a provider-supported CHR image.'
fi

if [[ -z "$VERSION" ]]; then
    cat >&2 <<'VERSIONS'
Suggested official releases (verified 2026-09-27):
  7.24.4  stable
  7.23.7  long-term
  6.49.22 long-term (legacy)
Older or newer official release numbers may also be entered.
VERSIONS
    read -r -p 'CHR version: ' VERSION
fi
[[ $VERSION =~ ^(6|7)\.[0-9]+(\.[0-9]+)?$ ]] || die 'Version must be a numeric RouterOS 6.x or 7.x release.'
[[ -n "$DISK" ]] || { lsblk -d -o NAME,SIZE,TYPE,MODEL >&2; die 'Pass the exact whole disk with --disk.'; }
[[ $DISK == /dev/* ]] || die 'The disk must be an absolute /dev path.'
DISK=$(readlink -f -- "$DISK")
[[ -b "$DISK" ]] || die "Not a block device: $DISK"
[[ $(lsblk -dn -o TYPE -- "$DISK" | tr -d '[:space:]') == disk ]] || die 'Select a whole disk, not a partition or logical volume.'
[[ $(lsblk -dn -o RO -- "$DISK" | tr -d '[:space:]') == 0 ]] || die 'The target disk is read-only.'
if lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -q '[^[:space:]]'; then
    die 'The target disk or one of its children is mounted or in use. Boot a rescue system and unmount it first.'
fi

[[ -d "$WORK_BASE" && -w "$WORK_BASE" ]] || die "Work directory is not writable: $WORK_BASE"
WORK_BASE=$(readlink -f -- "$WORK_BASE")
[[ -n "$WORK_BASE" && "$WORK_BASE" != / ]] || die 'Invalid work directory.'
if [[ -n "$EXPECTED_SHA256" && ! $EXPECTED_SHA256 =~ ^[[:xdigit:]]{64}$ ]]; then
    die '--sha256 requires exactly 64 hexadecimal characters.'
fi

log 'Target disk:'
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL -- "$DISK" >&2
log "Firmware: Legacy BIOS; CHR version: $VERSION"
log 'The current Linux system and all data on the selected disk will be erased.'
if (( ! YES_ERASE )); then
    [[ -t 0 ]] || die 'Interactive confirmation requires a terminal; use --yes-erase only after reviewing the disk.'
    read -r -p "Type ERASE $DISK to continue: " CONFIRMATION
    [[ $CONFIRMATION == "ERASE $DISK" ]] || die 'Confirmation did not match; disk unchanged.'
fi

WORK_DIR=$(mktemp -d -- "$WORK_BASE/chr-install.XXXXXXXX")
ARCHIVE="$WORK_DIR/chr-$VERSION.img.zip"
IMAGE="$WORK_DIR/chr-$VERSION.img"
URL="$REPOSITORY/$VERSION/chr-$VERSION.img.zip"
log "Downloading official CHR image: $URL"
curl --fail --location --retry 3 --connect-timeout 20 --max-time 900 --proto '=https' --tlsv1.2 --output "$ARCHIVE" "$URL"
[[ -s "$ARCHIVE" ]] || die 'The downloaded ZIP is empty.'

if [[ -n "$EXPECTED_SHA256" ]]; then
    printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum --check --status || die 'ZIP SHA-256 does not match.'
fi
unzip -tq "$ARCHIVE" >/dev/null || die 'The downloaded ZIP failed its integrity check.'
mapfile -t ZIP_ENTRIES < <(unzip -Z -1 "$ARCHIVE")
[[ ${#ZIP_ENTRIES[@]} -eq 1 && ${ZIP_ENTRIES[0]} == "chr-$VERSION.img" ]] || die 'Unexpected ZIP contents; refusing to extract.'
unzip -p "$ARCHIVE" "chr-$VERSION.img" > "$IMAGE"
[[ -s "$IMAGE" ]] || die 'Extracted RAW image is empty.'
sfdisk -d "$IMAGE" >/dev/null 2>&1 || die 'RAW image has no readable partition table.'
IMAGE_SIZE=$(stat -c '%s' -- "$IMAGE")
DISK_SIZE=$(blockdev --getsize64 "$DISK")
(( IMAGE_SIZE <= DISK_SIZE )) || die 'RAW image is larger than the selected disk.'
log "Image size: $IMAGE_SIZE bytes; disk size: $DISK_SIZE bytes."
log "ZIP SHA-256: $(sha256sum "$ARCHIVE" | cut -d' ' -f1)"

# Recheck immediately before the irreversible write; rescue systems may automount.
if lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -q '[^[:space:]]'; then
    die 'The target disk became mounted; refusing to write.'
fi
WRITE_STARTED=1
log 'Removing old disk signatures, including any backup GPT metadata ...'
wipefs --all --force "$DISK"
log "Writing CHR to $DISK ..."
dd if="$IMAGE" of="$DISK" bs=4M conv=fsync status=progress
sync
log 'Comparing every image byte with the target disk ...'
cmp -n "$IMAGE_SIZE" "$IMAGE" "$DISK"
WRITE_STARTED=0
log 'Image write and byte-for-byte verification succeeded.'
log 'Disable rescue mode and power cycle the VM from the provider panel.'
log 'Use the provider console for first login and set a strong admin password immediately.'

