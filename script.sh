#!/usr/bin/env bash
# Replace an Ubuntu VM disk with the official MikroTik CHR RAW image.
set -Eeuo pipefail

REPOSITORY='https://download.mikrotik.com/routeros'
VERSION=''
DISK=''
MODE='live'
WORK_BASE='/tmp'
EXPECTED_SHA256=''
YES_ERASE=0
WRITE_STARTED=0
WORK_DIR=''
STAGE_ACTIVE=0
STAGE_DIR='/var/lib/chr-install'
GRUB_ENTRY='/etc/grub.d/42_chr_install'
LIVE_INITRD='/boot/chr-install.img'

usage() {
    cat <<'USAGE'
Usage: sudo bash script.sh [--disk /dev/vda] [--version 7.24.4] [options]

Default live mode starts from Ubuntu and installs on the next boot, before the
root filesystem is mounted. Rescue mode writes an unmounted disk immediately.
All data on the selected disk will be destroyed.

Options:
  --disk DEVICE       Whole target disk; live mode auto-detects a single root disk
  --mode MODE         live (default) or rescue
  --version VERSION   Official CHR version; prompted for when omitted
  --workdir DIR       Download/extraction parent directory (default: /tmp)
  --sha256 HASH       Expected SHA-256 of the downloaded ZIP, if known
  --yes-erase         Skip the interactive exact-disk confirmation
  --cancel-live      Remove a staged live installer before reboot
  -h, --help          Show this help

Live mode stages a one-time GRUB boot and reboots automatically. Rescue mode
requires disabling rescue and power cycling from the provider panel afterward.
Neither mode configures RouterOS networking.
USAGE
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    if (( STAGE_ACTIVE )); then
        STAGE_ACTIVE=0
        rollback_live || true
    fi
    exit 1
}
log() { printf '%s\n' "$*" >&2; }
cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf -- "$WORK_DIR"
    fi
}
on_error() {
    local status=$1
    if (( STAGE_ACTIVE )); then
        log 'Staging failed; removing the one-time boot entry and installer image.'
        rollback_live || true
    fi
    if (( WRITE_STARTED )); then
        log 'Disk writing or verification failed. Do not boot this disk; recover from the provider rescue environment.'
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'on_error $?' ERR

rollback_live() {
    if [[ -e "$STAGE_DIR" && ! -f "$STAGE_DIR/marker" ]]; then
        die "Refusing to remove an unrecognized staging directory: $STAGE_DIR"
    fi
    if command -v grub-editenv >/dev/null 2>&1; then
        grub-editenv - unset next_entry >/dev/null 2>&1 || true
    fi
    rm -f -- "$GRUB_ENTRY" "$LIVE_INITRD"
    if [[ -f "$STAGE_DIR/marker" ]]; then
        rm -rf -- "$STAGE_DIR"
    fi
    if command -v grub-mkconfig >/dev/null 2>&1 && [[ -d /boot/grub ]]; then
        grub-mkconfig -o /boot/grub/grub.cfg >/dev/null
    fi
}

write_rescue() {
    # Recheck immediately before the irreversible write; rescue systems may automount.
    if lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep '[^[:space:]]' >/dev/null; then
        die 'The target disk became mounted; refusing to write.'
    fi
    WRITE_STARTED=1
    log 'Clearing the last MiB to remove stale backup GPT metadata ...'
    dd if=/dev/zero of="$DISK" bs=512 seek="$((DISK_SIZE / 512 - 2048))" count=2048 conv=fsync status=none
    log "Writing CHR to $DISK ..."
    dd if="$IMAGE" of="$DISK" bs=4M conv=fsync status=progress
    sync
    log 'Comparing every image byte with the target disk ...'
    cmp -n "$IMAGE_SIZE" "$IMAGE" "$DISK"
    WRITE_STARTED=0
    log 'Image write and byte-for-byte verification succeeded.'
    log 'Disable rescue mode and power cycle the VM from the provider panel.'
    log 'Use the provider console for first login and set a strong admin password immediately.'
}

stage_live() {
    local kernel boot_uuid boot_prefix kernel_args image_hash disk_head_hash
    kernel=$(uname -r)
    [[ -f "/boot/vmlinuz-$kernel" ]] || die "Running kernel image not found: /boot/vmlinuz-$kernel"
    boot_uuid=$(grub-probe --target=fs_uuid /boot)
    [[ $boot_uuid =~ ^[A-Za-z0-9-]+$ ]] || die 'Could not obtain a safe GRUB boot filesystem UUID.'
    if mountpoint -q /boot; then
        boot_prefix=''
    else
        boot_prefix='/boot'
    fi
    kernel_args=$(cat /proc/cmdline)
    printf '%s\n' "$kernel_args" | grep -Eq '^[A-Za-z0-9_./:=,@+%?! -]+$' || die 'Kernel command line contains unsupported characters; use rescue mode.'
    [[ " $kernel_args " != *' chr_install_once='* ]] || die 'A CHR installer boot argument is already present.'
    image_hash=$(sha256sum "$IMAGE" | cut -d' ' -f1)
    disk_head_hash=$(dd if="$DISK" bs=4096 count=1 status=none | sha256sum | cut -d' ' -f1)

    mkdir -m 700 -- "$STAGE_DIR"
    printf 'chr-install\n' > "$STAGE_DIR/marker"
    STAGE_ACTIVE=1
    cp -- "$IMAGE" "$STAGE_DIR/chr.img"
    mkdir -p -- "$STAGE_DIR/config"
    cp -a /etc/initramfs-tools/. "$STAGE_DIR/config/"
    mkdir -p -- "$STAGE_DIR/config/hooks" "$STAGE_DIR/config/scripts/local-premount"

    cat > "$STAGE_DIR/plan" <<PLAN
TARGET_DISK=$DISK
DISK_SIZE=$DISK_SIZE
IMAGE_SIZE=$IMAGE_SIZE
IMAGE_HASH=$image_hash
DISK_HEAD_HASH=$disk_head_hash
PLAN

    cat > "$STAGE_DIR/config/hooks/chr-install" <<'HOOK'
#!/bin/sh
PREREQ=''
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
. /usr/share/initramfs-tools/hook-functions
mkdir -p "$DESTDIR/chr-install"
cp /var/lib/chr-install/chr.img "$DESTDIR/chr-install/chr.img"
cp /var/lib/chr-install/plan "$DESTDIR/chr-install/plan"
for binary in dd cmp blockdev sha256sum cut sync; do
    copy_exec "$(command -v "$binary")"
done
copy_exec "$(command -v busybox)" /bin/busybox
HOOK
    chmod 700 "$STAGE_DIR/config/hooks/chr-install"

    cat > "$STAGE_DIR/config/scripts/local-premount/chr-install" <<'BOOT'
#!/bin/sh
PREREQ=''
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac
case " $(/bin/busybox cat /proc/cmdline) " in
    *' chr_install_once=1 '*) ;;
    *) exit 0 ;;
esac
. /scripts/functions
. /chr-install/plan
fail_install() {
    echo "CHR INSTALL FAILED: $*" > /dev/console
    panic "CHR install failed: $*"
    while :; do /bin/busybox sleep 60; done
}
echo 'CHR installer: verifying embedded image and target disk ...' > /dev/console
echo "$IMAGE_HASH  /chr-install/chr.img" | sha256sum -c - >/dev/null 2>&1 || fail_install 'image checksum mismatch'
i=0
while [ ! -b "$TARGET_DISK" ] && [ "$i" -lt 30 ]; do
    /bin/busybox sleep 1
    i=$((i + 1))
done
[ -b "$TARGET_DISK" ] || fail_install 'target disk did not appear'
actual_size=$(blockdev --getsize64 "$TARGET_DISK") || fail_install 'cannot read disk size'
[ "$actual_size" = "$DISK_SIZE" ] || fail_install 'target disk size changed'
actual_head=$(dd if="$TARGET_DISK" bs=4096 count=1 2>/dev/null | sha256sum | cut -d' ' -f1) || fail_install 'cannot read disk identity'
[ "$actual_head" = "$DISK_HEAD_HASH" ] || fail_install 'target disk identity changed'
echo 'CHR installer: writing image before root mount ...' > /dev/console
tail_seek=$((DISK_SIZE / 512 - 2048))
dd if=/dev/zero of="$TARGET_DISK" bs=512 seek="$tail_seek" count=2048 conv=fsync status=none || fail_install 'cannot clear old GPT metadata'
dd if=/chr-install/chr.img of="$TARGET_DISK" bs=4M conv=fsync status=none || fail_install 'disk write failed'
sync
cmp -n "$IMAGE_SIZE" /chr-install/chr.img "$TARGET_DISK" || fail_install 'disk verification failed'
sync
echo 'CHR installer: verified. Rebooting into RouterOS.' > /dev/console
/bin/busybox reboot -f
fail_install 'reboot failed'
BOOT
    chmod 700 "$STAGE_DIR/config/scripts/local-premount/chr-install"

    log 'Building dedicated one-time initramfs with the verified CHR image ...'
    mkinitramfs -d "$STAGE_DIR/config" -o "$LIVE_INITRD" "$kernel"
    lsinitramfs "$LIVE_INITRD" | grep -Fx 'chr-install/chr.img' >/dev/null || die 'CHR image is missing from the generated initramfs.'
    lsinitramfs "$LIVE_INITRD" | grep -Fx 'scripts/local-premount/chr-install' >/dev/null || die 'CHR boot script is missing from the generated initramfs.'
    rm -f -- "$STAGE_DIR/chr.img"

    cat > "$GRUB_ENTRY" <<GRUB
#!/bin/sh
cat <<'ENTRY'
menuentry 'Install MikroTik CHR (one time)' --id chr-install-once {
    search --no-floppy --fs-uuid --set=root $boot_uuid
    linux $boot_prefix/vmlinuz-$kernel $kernel_args chr_install_once=1
    initrd $boot_prefix/chr-install.img
}
ENTRY
GRUB
    chmod 700 "$GRUB_ENTRY"
    grub-mkconfig -o /boot/grub/grub.cfg >/dev/null
    grep -Fq -- '--id chr-install-once' /boot/grub/grub.cfg || die 'GRUB installer entry was not generated.'
    grub-reboot chr-install-once
    grub-editenv - list | grep -Fx 'next_entry=chr-install-once' >/dev/null || die 'GRUB one-time boot could not be verified.'
    log 'One-time offline installer staged. Rebooting now; use the provider console to observe the result.'
    reboot
    STAGE_ACTIVE=0
}

while (($#)); do
    case "$1" in
        --disk|--version|--workdir|--sha256|--mode)
            (($# >= 2)) || die "Missing value for $1"
            case "$1" in
                --disk) DISK=$2 ;;
                --version) VERSION=$2 ;;
                --workdir) WORK_BASE=$2 ;;
                --sha256) EXPECTED_SHA256=$2 ;;
                --mode) MODE=$2 ;;
            esac
            shift 2 ;;
        --yes-erase) YES_ERASE=1; shift ;;
        --cancel-live) CANCEL_LIVE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

(( EUID == 0 )) || die 'Run as root (sudo bash script.sh ...).'
[[ $MODE == live || $MODE == rescue ]] || die '--mode must be live or rescue.'
if (( ${CANCEL_LIVE:-0} )); then
    rollback_live
    log 'Staged live installer removed.'
    exit 0
fi
[[ $(uname -m) == x86_64 ]] || die 'This installer supports x86_64 CHR only.'

for command in curl unzip sfdisk lsblk blockdev readlink dd cmp sync sha256sum stat cut grep tr mktemp rm awk mountpoint findmnt sort cat cp chmod mkdir busybox; do
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
if [[ -z "$DISK" && $MODE == live ]]; then
    ROOT_SOURCE=$(findmnt -n -o SOURCE /)
    ROOT_SOURCE=${ROOT_SOURCE%%\[*}
    if [[ $ROOT_SOURCE == /dev/* ]]; then
        mapfile -t ROOT_DISKS < <(lsblk -snr -o PATH,TYPE "$ROOT_SOURCE" | awk '$2 == "disk" {print $1}' | sort -u)
        if (( ${#ROOT_DISKS[@]} == 1 )); then
            DISK=${ROOT_DISKS[0]}
            log "Detected Ubuntu root disk: $DISK"
        fi
    fi
fi
[[ -n "$DISK" ]] || { lsblk -d -o NAME,SIZE,TYPE,MODEL >&2; die 'Pass the exact whole disk with --disk.'; }
[[ $DISK == /dev/* ]] || die 'The disk must be an absolute /dev path.'
DISK=$(readlink -f -- "$DISK")
[[ -b "$DISK" ]] || die "Not a block device: $DISK"
[[ $(lsblk -dn -o TYPE -- "$DISK" | tr -d '[:space:]') == disk ]] || die 'Select a whole disk, not a partition or logical volume.'
[[ $(lsblk -dn -o RO -- "$DISK" | tr -d '[:space:]') == 0 ]] || die 'The target disk is read-only.'
case "$MODE" in
    rescue)
        if lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep '[^[:space:]]' >/dev/null; then
            die 'The target disk or one of its children is mounted or in use. Boot a rescue system and unmount it first.'
        fi ;;
    live)
        command -v findmnt >/dev/null 2>&1 || die 'Missing findmnt (util-linux).'
        lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -Fx '/' >/dev/null || die 'Live mode requires the selected disk to contain the current Ubuntu root filesystem.'
        if mountpoint -q /boot; then
            lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -Fx '/boot' >/dev/null || die 'The /boot filesystem is on another disk; this live workflow cannot replace only the root disk.'
        fi
        [[ -d /etc/initramfs-tools && -d /boot/grub ]] || die 'Live mode requires Ubuntu with initramfs-tools and GRUB.'
        for command in mkinitramfs lsinitramfs grub-mkconfig grub-reboot grub-editenv grub-probe reboot; do
            command -v "$command" >/dev/null 2>&1 || die "Missing $command; live mode requires initramfs-tools and GRUB."
        done
        (( $(awk '/MemTotal:/ {print $2}' /proc/meminfo) >= 1048576 )) || die 'Live mode requires at least 1 GiB RAM to carry the image in initramfs.'
        [[ ! -e "$STAGE_DIR" && ! -e "$GRUB_ENTRY" && ! -e "$LIVE_INITRD" ]] || die 'A live installation is already staged. Use --cancel-live to remove it first.' ;;
esac

[[ -d "$WORK_BASE" && -w "$WORK_BASE" ]] || die "Work directory is not writable: $WORK_BASE"
WORK_BASE=$(readlink -f -- "$WORK_BASE")
[[ -n "$WORK_BASE" && "$WORK_BASE" != / ]] || die 'Invalid work directory.'
if [[ -n "$EXPECTED_SHA256" && ! $EXPECTED_SHA256 =~ ^[[:xdigit:]]{64}$ ]]; then
    die '--sha256 requires exactly 64 hexadecimal characters.'
fi

log 'Target disk:'
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL -- "$DISK" >&2
log "Mode: $MODE; firmware: Legacy BIOS; CHR version: $VERSION"
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

if [[ $MODE == live ]]; then
    stage_live
else
    write_rescue
fi

