#!/usr/bin/env bash
# Digitalvps.ir: install the official MikroTik CHR RAW image on an Ubuntu VM.
set -Eeuo pipefail
umask 077

REPOSITORY='https://download.mikrotik.com/routeros'
VERSION=''
DISK=''
MODE='auto'
WORK_BASE=''
EXPECTED_SHA256=''
YES_ERASE=0
LIST_VERSIONS=0
WRITE_STARTED=0
WORK_DIR=''
STAGE_ACTIVE=0
STAGE_DIR='/var/lib/chr-install'
GRUB_ENTRY='/etc/grub.d/42_chr_install'
LIVE_INITRD='/boot/chr-install.img'

usage() {
    cat <<'USAGE'
Digitalvps.ir | MikroTik CHR installer

Usage: sudo bash script.sh [options]

Run without arguments for guided, automatic setup. Running Ubuntu uses a
one-time offline boot; a RAM-based rescue system writes an unmounted disk.
All data on the selected disk will be destroyed.

Options:
  --disk DEVICE       Whole target disk; detected or selected when omitted
  --mode MODE         auto (default), live, or rescue
  --version VERSION   Numeric official CHR version; menu when omitted
  --list-versions     Show official stable and long-term releases and exit
  --workdir DIR       Download/extraction parent (auto-selected when omitted)
  --sha256 HASH       Expected SHA-256 of the downloaded ZIP, if known
  --yes-erase         Skip the interactive exact-disk confirmation
  --cancel-live      Remove a staged live installer before reboot
  -h, --help          Show this help

Missing packages are installed on Ubuntu/Debian automatically. Live mode
stages a one-time GRUB boot and reboots. Rescue mode requires disabling rescue
and power cycling from the provider panel afterward.
Neither mode configures RouterOS networking.
USAGE
}

# Used only when the official download page is unavailable. Refresh this list
# when the project is released; normal interactive runs read the live catalog.
FALLBACK_RELEASES=(
    'stable|7.24.4' 'stable|7.24.3' 'stable|7.24.2'
    'stable|7.24.1' 'stable|7.24'
    'longTerm|7.23.7' 'longTerm|7.23.6' 'longTerm|7.23.5'
    'longTerm|7.23.4' 'longTerm|7.21.5' 'longTerm|7.21.4'
    'longTerm|7.20.8' 'longTerm|7.20.7'
    'longTerm|6.49.22' 'longTerm|6.49.21' 'longTerm|6.49.20'
    'longTerm|6.49.19' 'longTerm|6.49.18'
)
RELEASES=()
STABLE_SERIES=''

ensure_commands() {
    local command package
    local packages=()
    for command in "$@"; do
        command -v "$command" >/dev/null 2>&1 && continue
        case "$command" in
            curl) package=curl ;;
            python3) package=python3 ;;
            unzip) package=unzip ;;
            sfdisk) package=fdisk ;;
            lsblk|blockdev|mountpoint|findmnt|swapon) package=util-linux ;;
            grep) package='grep' ;;
            awk) package=mawk ;;
            busybox) package=busybox ;;
            mkinitramfs|lsinitramfs) package=initramfs-tools ;;
            grub-mkconfig|grub-mkrelpath|grub-reboot|grub-editenv|grub-probe) package=grub-common ;;
            reboot) package=systemd-sysv ;;
            *) package=coreutils ;;
        esac
        if [[ ! " ${packages[*]} " == *" $package "* ]]; then
            packages+=("$package")
        fi
    done
    ((${#packages[@]})) || return 0
    [[ -r /etc/os-release ]] || die "Missing ${packages[*]}; automatic package setup needs Ubuntu/Debian."
    # shellcheck disable=SC1091
    . /etc/os-release
    [[ " ${ID:-} ${ID_LIKE:-} " == *' ubuntu '* || " ${ID:-} ${ID_LIKE:-} " == *' debian '* ]] ||
        die "Missing ${packages[*]}; automatic package setup supports Ubuntu/Debian only."
    command -v apt-get >/dev/null 2>&1 || die 'apt-get is unavailable in this environment.'
    log "Installing missing tools: ${packages[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}"
    for command in "$@"; do
        command -v "$command" >/dev/null 2>&1 || die "Package installation did not provide $command."
    done
}

load_releases() {
    local html_file
    RELEASES=("${FALLBACK_RELEASES[@]}")
    CATALOG_SOURCE='fallback'
    command -v curl >/dev/null 2>&1 || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    html_file=$(mktemp)
    if curl --fail --silent --show-error --location --connect-timeout 10 --max-time 25 \
        --proto '=https' --tlsv1.2 'https://mikrotik.com/download/chr' -o "$html_file"; then
        local online=()
        mapfile -t online < <(python3 - "$html_file" <<'PY'
import html
import json
import re
import sys

page = open(sys.argv[1], encoding='utf-8').read()
results = []
for raw in re.findall(r'wire:snapshot="([^"]+)"', page):
    data = json.loads(html.unescape(raw)).get('data', {})
    if not isinstance(data, dict):
        continue
    if data.get('channel') != 'longTerm' or 'releases' not in data:
        continue
    for wrapped in data['releases'][0]:
        release = wrapped[0]
        version = release.get('version', '')
        if release.get('archived') or not re.fullmatch(r'[67]\.\d+(?:\.\d+)?', version):
            continue
        channels = release['channels'][0]
        for channel in ('stable', 'longTerm'):
            if channels.get(channel):
                results.append(f'{channel}|{version}')
                break
    break
for result in results:
    print(result)
PY
)
        if ((${#online[@]} >= 10)); then
            RELEASES=("${online[@]}")
            CATALOG_SOURCE='online'
        else
            CATALOG_SOURCE='fallback'
        fi
    else
        CATALOG_SOURCE='fallback'
    fi
    rm -f -- "$html_file"
}

show_releases() {
    local record channel version index=1 previous=''
    MENU_VERSIONS=()
    for record in "${RELEASES[@]}"; do
        IFS='|' read -r channel version <<< "$record"
        if [[ ${1:-featured} == featured && $channel == stable &&
              $version != "$STABLE_SERIES" && $version != "$STABLE_SERIES".* ]]; then
            continue
        fi
        if [[ $channel != "$previous" ]]; then
            printf '\n%s:\n' "$([[ $channel == stable ]] && printf 'Stable' || printf 'Long-term')"
            previous=$channel
        fi
        printf '  %2d) %s%s\n' "$index" "$version" "$([[ $version == 6.* ]] && printf ' (v6 legacy)' || true)"
        MENU_VERSIONS+=("$version")
        ((index += 1))
    done
}

choose_version() {
    local answer
    load_releases
    STABLE_SERIES=''
    DEFAULT_VERSION=''
    for answer in "${RELEASES[@]}"; do
        if [[ $answer == stable\|* ]]; then
            DEFAULT_VERSION=${answer#*|}
            STABLE_SERIES=$DEFAULT_VERSION
            STABLE_SERIES=${STABLE_SERIES%.*}
            break
        fi
    done
    [[ -n $STABLE_SERIES ]] || die 'No stable CHR release was found.'
    log "Official release catalog: ${CATALOG_SOURCE:-fallback}."
    show_releases featured >&2
    printf '\nPress Enter for %s, type a number or version, or a for all releases.\n' "$DEFAULT_VERSION" >&2
    while :; do
        read -r -p 'CHR version: ' answer
        if [[ -z $answer ]]; then VERSION=$DEFAULT_VERSION; return; fi
        if [[ $answer == a || $answer == A ]]; then
            show_releases all >&2
            continue
        fi
        if [[ $answer =~ ^[0-9]+$ && $answer -ge 1 && $answer -le ${#MENU_VERSIONS[@]} ]]; then
            VERSION=${MENU_VERSIONS[answer-1]}
            return
        fi
        if [[ $answer =~ ^(6|7)\.[0-9]+(\.[0-9]+)?$ ]]; then
            VERSION=$answer
            return
        fi
        log 'Choose a listed number, enter a numeric 6.x/7.x version, or a to show all.'
    done
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

assert_rescue_unused() {
    local swap device kernel_name
    if lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep '[^[:space:]]' >/dev/null; then
        die 'The target disk or one of its children is mounted; refusing to write.'
    fi
    while IFS= read -r swap; do
        [[ -n $swap ]] || continue
        if lsblk -nr -o PATH -- "$DISK" | grep -Fx -- "$swap" >/dev/null; then
            die 'A partition on the target disk is active swap; refusing to write.'
        fi
    done < <(swapon --noheadings --raw --show=NAME || true)
    while IFS= read -r kernel_name; do
        [[ -n $kernel_name ]] || continue
        device="/sys/class/block/$kernel_name/holders"
        if [[ -d $device && -n $(ls -A -- "$device") ]]; then
            die "Target disk has an active device-mapper, RAID, or other holder: $kernel_name"
        fi
    done < <(lsblk -nr -o KNAME -- "$DISK")
}

write_rescue() {
    # Recheck immediately before the irreversible write; rescue systems may automount.
    assert_rescue_unused
    WRITE_STARTED=1
    log 'Clearing the last MiB to remove stale backup partition metadata ...'
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

download_archive() {
    local attempt
    for attempt in 1 2 3 4 5; do
        if curl --fail --location --connect-timeout 20 --max-time 900 \
            --proto '=https' --tlsv1.2 \
            --continue-at - --output "$ARCHIVE" "$URL"; then
            if unzip -tq "$ARCHIVE" >/dev/null 2>&1; then
                return 0
            fi
            log 'Downloaded ZIP failed its integrity check; restarting the download.'
            rm -f -- "$ARCHIVE"
        fi
        log "Download attempt $attempt failed; retrying ..."
        sleep "$((attempt * 2))"
    done
    die 'Could not obtain a valid CHR ZIP after five attempts.'
}

stage_live() {
    local kernel boot_uuid kernel_path initrd_path kernel_args image_hash disk_head_hash boot_free
    kernel=$(uname -r)
    [[ -f "/boot/vmlinuz-$kernel" ]] || die "Running kernel image not found: /boot/vmlinuz-$kernel"
    boot_uuid=$(grub-probe --target=fs_uuid /boot)
    [[ $boot_uuid =~ ^[A-Za-z0-9-]+$ ]] || die 'Could not obtain a safe GRUB boot filesystem UUID.'
    kernel_path=$(grub-mkrelpath "/boot/vmlinuz-$kernel")
    [[ $kernel_path =~ ^/[A-Za-z0-9_./+@-]+$ ]] || die 'Could not obtain a safe GRUB kernel path.'
    kernel_args=$(cat /proc/cmdline)
    printf '%s\n' "$kernel_args" | grep -Eq '^[A-Za-z0-9_./:=,@+%?! -]+$' || die 'Kernel command line contains unsupported characters; use rescue mode.'
    [[ " $kernel_args " != *' chr_install_once='* ]] || die 'A CHR installer boot argument is already present.'
    image_hash=$(sha256sum "$IMAGE" | cut -d' ' -f1)
    disk_head_hash=$(dd if="$DISK" bs=4096 count=1 status=none | sha256sum | cut -d' ' -f1)
    boot_free=$(df -B1 --output=avail -- /boot | awk 'NR == 2 {print $1}')
    [[ $boot_free =~ ^[0-9]+$ ]] || die 'Could not measure free space in /boot.'
    (( boot_free >= IMAGE_SIZE + 67108864 )) || die 'Not enough free space in /boot for the one-time installer image.'

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
dd if=/dev/zero of="$TARGET_DISK" bs=512 seek="$tail_seek" count=2048 conv=fsync status=none || fail_install 'cannot clear old backup partition metadata'
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
    initrd_path=$(grub-mkrelpath "$LIVE_INITRD")
    [[ $initrd_path =~ ^/[A-Za-z0-9_./+@-]+$ ]] || die 'Could not obtain a safe GRUB initramfs path.'
    rm -f -- "$STAGE_DIR/chr.img"

    cat > "$GRUB_ENTRY" <<GRUB
#!/bin/sh
cat <<'ENTRY'
menuentry 'Install MikroTik CHR (one time)' --id chr-install-once {
    search --no-floppy --fs-uuid --set=root $boot_uuid
    linux $kernel_path $kernel_args chr_install_once=1
    initrd $initrd_path
}
ENTRY
GRUB
    chmod 700 "$GRUB_ENTRY"
    grub-mkconfig -o /boot/grub/grub.cfg >/dev/null
    grep -Fq -- '--id chr-install-once' /boot/grub/grub.cfg || die 'GRUB installer entry was not generated.'
    grep -Fq 'set default="${next_entry}"' /boot/grub/grub.cfg || die 'GRUB is not configured to honor one-time boot entries.'
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
        --list-versions) LIST_VERSIONS=1; shift ;;
        --cancel-live) CANCEL_LIVE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ $MODE == auto || $MODE == live || $MODE == rescue ]] || die '--mode must be auto, live, or rescue.'
if (( LIST_VERSIONS )); then
    load_releases
    STABLE_SERIES=''
    printf 'Catalog source: %s\n' "$CATALOG_SOURCE"
    show_releases all
    exit 0
fi
(( EUID == 0 )) || die 'Run as root (sudo bash script.sh ...).'
if (( ${CANCEL_LIVE:-0} )); then
    rollback_live
    log 'Staged live installer removed.'
    exit 0
fi
[[ $(uname -m) == x86_64 ]] || die 'This installer supports x86_64 CHR only.'
if [[ -e /.dockerenv || -e /run/.containerenv ]] ||
   { command -v systemd-detect-virt >/dev/null 2>&1 && systemd-detect-virt --container --quiet; }; then
    die 'Run inside the VPS guest, not a container or the virtualization host.'
fi
ensure_commands lsblk findmnt readlink awk sort grep

ROOT_SOURCE=$(findmnt -n -o SOURCE / || true)
ROOT_SOURCE=${ROOT_SOURCE%%\[*}
ROOT_DISKS=()
if [[ $ROOT_SOURCE == /dev/* ]]; then
    mapfile -t ROOT_DISKS < <(lsblk -snr -o PATH,TYPE "$ROOT_SOURCE" | awk '$2 == "disk" {print $1}' | sort -u)
fi
if [[ $MODE == auto ]]; then
    if [[ $ROOT_SOURCE == /dev/* && -r /etc/os-release ]] &&
       grep -Eq '^ID=ubuntu$|^ID="ubuntu"$' /etc/os-release; then
        MODE=live
    else
        MODE=rescue
    fi
    log "Detected installation mode: $MODE"
fi
ensure_commands curl unzip sfdisk lsblk blockdev readlink dd cmp sync sha256sum stat cut grep tr mktemp rm awk mountpoint findmnt sort cat cp chmod mkdir sleep df swapon
if [[ $MODE == live ]]; then
    ensure_commands busybox mkinitramfs lsinitramfs grub-mkconfig grub-mkrelpath grub-reboot grub-editenv grub-probe reboot
fi

if [[ -d /sys/firmware/efi ]]; then
    die 'This VM booted in UEFI mode. This RAW CHR workflow requires Legacy BIOS; change the VM firmware or use a provider-supported CHR image.'
fi

if [[ -z "$VERSION" ]]; then
    ensure_commands python3
    [[ -t 0 ]] || die 'Pass --version for unattended use, or run with an interactive terminal.'
    choose_version
fi
[[ $VERSION =~ ^(6|7)\.[0-9]+(\.[0-9]+)?$ ]] || die 'Version must be a numeric RouterOS 6.x or 7.x release.'
if [[ -z "$DISK" ]]; then
    if [[ $MODE == live && ${#ROOT_DISKS[@]} -eq 1 ]]; then
        DISK=${ROOT_DISKS[0]}
        log "Detected Ubuntu root disk: $DISK"
    elif [[ $MODE == rescue ]]; then
        CANDIDATE_DISKS=()
        while IFS= read -r candidate; do
            [[ -n $candidate ]] || continue
            [[ $(lsblk -dn -o RO -- "$candidate" | tr -d '[:space:]') == 0 ]] || continue
            if ! lsblk -nr -o MOUNTPOINTS -- "$candidate" | grep '[^[:space:]]' >/dev/null; then
                CANDIDATE_DISKS+=("$candidate")
            fi
        done < <(lsblk -dn -o PATH,TYPE | awk '$2 == "disk" {print $1}')
        if ((${#CANDIDATE_DISKS[@]} == 1)); then
            DISK=${CANDIDATE_DISKS[0]}
            log "Detected the only unmounted target disk: $DISK"
        fi
    fi
fi
if [[ -z "$DISK" ]]; then
    lsblk -d -o PATH,SIZE,TYPE,RO,MODEL >&2
    [[ -t 0 ]] || die 'Pass the exact whole target disk with --disk.'
    read -r -p 'Whole target disk (for example /dev/vda): ' DISK
fi
[[ $DISK == /dev/* ]] || die 'The disk must be an absolute /dev path.'
DISK=$(readlink -f -- "$DISK")
[[ -b "$DISK" ]] || die "Not a block device: $DISK"
[[ $(lsblk -dn -o TYPE -- "$DISK" | tr -d '[:space:]') == disk ]] || die 'Select a whole disk, not a partition or logical volume.'
[[ $(lsblk -dn -o RO -- "$DISK" | tr -d '[:space:]') == 0 ]] || die 'The target disk is read-only.'
case "$MODE" in
    rescue)
        assert_rescue_unused ;;
    live)
        (( ${#ROOT_DISKS[@]} == 1 )) || die 'Live mode requires one unambiguous Ubuntu root disk.'
        command -v findmnt >/dev/null 2>&1 || die 'Missing findmnt (util-linux).'
        lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -Fx '/' >/dev/null || die 'Live mode requires the selected disk to contain the current Ubuntu root filesystem.'
        if mountpoint -q /boot; then
            lsblk -nr -o MOUNTPOINTS -- "$DISK" | grep -Fx '/boot' >/dev/null || die 'The /boot filesystem is on another disk; this live workflow cannot replace only the root disk.'
        fi
        [[ -d /etc/initramfs-tools && -d /boot/grub ]] || die 'Live mode requires Ubuntu with initramfs-tools and GRUB.'
        (( $(awk '/MemTotal:/ {print $2}' /proc/meminfo) >= 1048576 )) || die 'Live mode requires at least 1 GiB RAM to carry the image in initramfs.'
        [[ ! -e "$STAGE_DIR" && ! -e "$GRUB_ENTRY" && ! -e "$LIVE_INITRD" ]] || die 'A live installation is already staged. Use --cancel-live to remove it first.' ;;
esac

if [[ -z "$WORK_BASE" ]]; then
    best_free=0
    for candidate in /var/tmp /tmp; do
        [[ -d $candidate && -w $candidate ]] || continue
        available=$(df -B1 --output=avail -- "$candidate" | awk 'NR == 2 {print $1}')
        if [[ $available =~ ^[0-9]+$ ]] && (( available > best_free )); then
            best_free=$available
            WORK_BASE=$candidate
        fi
    done
    (( best_free >= 536870912 )) || die 'Need at least 512 MiB free work space; pass --workdir on another safe filesystem.'
    log "Selected work directory: $WORK_BASE"
fi
[[ -d "$WORK_BASE" && -w "$WORK_BASE" ]] || die "Work directory is not writable: $WORK_BASE"
WORK_BASE=$(readlink -f -- "$WORK_BASE")
[[ -n "$WORK_BASE" && "$WORK_BASE" != / ]] || die 'Invalid work directory.'
available=$(df -B1 --output=avail -- "$WORK_BASE" | awk 'NR == 2 {print $1}')
[[ $available =~ ^[0-9]+$ ]] || die 'Could not measure free work space.'
(( available >= 536870912 )) || die 'Work directory needs at least 512 MiB free space.'
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
download_archive
[[ -s "$ARCHIVE" ]] || die 'The downloaded ZIP is empty.'

if [[ -n "$EXPECTED_SHA256" ]]; then
    printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum --check --status || die 'ZIP SHA-256 does not match.'
fi
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
