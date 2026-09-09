#!/usr/bin/env python3
"""Conservative offline-disk CHR deployment; standard library only.

Never installs over a running OS. No automatic network migration or reboot.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

MIB = 1024 * 1024
MAX_ARCHIVE = 512 * MIB
MAX_IMAGE = 2 * 1024 * MIB
CHUNK = 4 * MIB
SUPPORTED_OS = {"ubuntu": {"20.04", "22.04", "24.04"}, "debian": {"11", "12", "13"}}


class InstallError(Exception):
    """An unsafe or unsupported operation, or failed verification."""


def require(condition, message):
    if not condition:
        raise InstallError(message)


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    require(result.returncode == 0, "Command failed: " + " ".join(args) + "\n" + result.stderr.strip())
    return result.stdout


def version_value(value):
    require(bool(re.fullmatch(r"[67]\.[0-9]{1,3}(?:\.[0-9]{1,3})?", value)),
            "Use an exact numeric RouterOS 6/7 release, not latest, a URL or a testing suffix.")
    return value


def digest_value(value):
    require(bool(re.fullmatch(r"[0-9a-fA-F]{64}", value)), "SHA256 must contain exactly 64 hex characters.")
    return value.lower()


def image_url(version):
    version_value(version)
    return f"https://download.mikrotik.com/routeros/{version}/chr-{version}.img.zip"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_reference(archive, expected=None):
    """Automatic transport-trusted digest, or an explicitly pinned reference.

    The auto hash is not a vendor signature/independent authenticity check.
    Both callers invoke this only after download_archive from the official origin.
    """
    actual = sha256_file(archive)
    print("Downloaded ZIP SHA256: " + actual)
    if expected is not None:
        require(actual == digest_value(expected), "Archive SHA256 mismatch; stopping before disk writes.")
        print("Verification: matched the supplied trusted ZIP checksum.")
    else:
        print("Verification: official HTTPS download + computed SHA256 (NOT an independent vendor checksum).")
    return actual


def discover_disks():
    data = json.loads(run("lsblk", "--json", "--bytes", "--paths", "--tree", "--output",
                         "PATH,TYPE,SIZE,MODEL,SERIAL,MOUNTPOINT"))
    require(isinstance(data.get("blockdevices"), list), "Missing disk inventory.")
    return [node for node in data["blockdevices"] if node.get("type") == "disk"]


def disk_candidates(method):
    disks = discover_disks()
    eligible, rejected = [], []
    for disk in disks:
        path = disk.get("path", "")
        try:
            if method == "offline":
                check_target(path)
            else:
                require(len(disks) == 1 and re.fullmatch(r"/dev/vd[a-z]+", path),
                        "RAM currently needs exactly one VirtIO disk; full preflight still required.")
            eligible.append(disk)
        except (InstallError, OSError, ValueError) as error:
            rejected.append((disk, str(error)))
    return eligible, rejected


def auto_disk(method):
    eligible, rejected = disk_candidates(method)
    require(len(eligible) == 1, "Automatic disk selection requires exactly one candidate; use the menu or --disk. "
            + " | ".join(reason for _, reason in rejected))
    disk = eligible[0]
    print(f"Automatic disk: {disk['path']} ({int(disk['size']) / (1024 ** 3):.1f} GiB); final checks/confirmation still apply.")
    return disk["path"]


def check_host():
    require(os.geteuid() == 0, "Run with sudo/root (including --dry-run).")
    require(os.uname().machine == "x86_64", "Only x86-64 guests are supported.")
    for command in ("lsblk", "swapon", "systemd-detect-virt", "curl"):
        require(shutil.which(command), f"Missing prerequisite: {command}")
    require(os.readlink("/proc/self/ns/mnt") == os.readlink("/proc/1/ns/mnt"),
            "Private mount namespaces are unsupported; use the VM rescue console.")
    virt = run("systemd-detect-virt").strip()
    require(virt in {"kvm", "qemu", "vmware"}, "Only KVM/QEMU/VMware guests are accepted; no containers or host nodes.")
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    require(release.get("VERSION_ID") in SUPPORTED_OS.get(release.get("ID"), set()),
            "Use Ubuntu 20.04/22.04/24.04 or Debian 11/12/13 rescue/live userspace.")
    require(not Path("/sys/firmware/efi").exists(),
            "This conservative installer accepts legacy BIOS rescue boots only; UEFI is not validated.")


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get("children", []))


def validate_inventory(inventory, disk):
    require(isinstance(inventory, dict) and isinstance(inventory.get("blockdevices"), list),
            "Invalid lsblk inventory.")
    matches = [node for node in inventory["blockdevices"] if node.get("path") == disk]
    require(len(matches) == 1, "Target must resolve to exactly one top-level disk.")
    target = matches[0]
    require(target.get("type") == "disk", "Target must be a whole disk, not a partition/mapper/loop device.")
    require(target.get("ro") in (False, 0), "Disk is read-only or its state is unknown.")
    require(target.get("rm") in (False, 0), "Removable disks are not accepted.")
    require(int(target.get("log-sec", 0)) == 512, "Only 512-byte logical sectors are supported.")
    require(int(target.get("size", 0)) >= 1024 * MIB, "Target must be at least 1 GiB.")
    for node in flatten([target]):
        require(node.get("type") in {"disk", "part"}, "Active RAID/LVM/crypt/device-mapper topology is unsupported.")
        require("mountpoints" in node, "Missing mountpoint data; refusing to guess.")
        require(not any(node["mountpoints"] or []), "Target or a child is mounted; boot rescue and unmount it first.")
        fs = node.get("fstype") or ""
        require(fs not in {"LVM2_member", "linux_raid_member", "zfs_member", "crypto_LUKS", "btrfs"},
                "RAID/LVM/ZFS/LUKS/Btrfs targets are unsupported.")
    return target


def check_target(disk):
    require(bool(re.fullmatch(r"/dev/(?:vd[a-z]+|sd[a-z]+|nvme[0-9]+n[0-9]+)", disk)),
            "Specify a canonical whole disk such as /dev/vda, /dev/sda or /dev/nvme0n1; aliases are rejected.")
    info = os.lstat(disk)
    require(stat.S_ISBLK(info.st_mode), "Target is not a block device (symlinks/files are rejected).")
    inventory = json.loads(run("lsblk", "--json", "--bytes", "--paths", "--tree", "--output",
                               "PATH,TYPE,SIZE,RO,RM,LOG-SEC,MOUNTPOINT,FSTYPE,MAJ:MIN,MODEL,SERIAL"))
    # MOUNTPOINT (singular) also exists on Ubuntu 20.04's util-linux.
    # Any reported mount is sufficient for rejection; we never unmount anything.
    for node in flatten(inventory.get("blockdevices", [])):
        require("mountpoint" in node, "Missing mountpoint information.")
        node["mountpoints"] = [node.pop("mountpoint")]
    target = validate_inventory(inventory, disk)
    swaps = run("swapon", "--show", "--noheadings", "--raw", "--output", "NAME")
    require(not swaps.strip(), "Active swap detected. Disable it yourself in rescue before continuing.")
    for node in flatten([target]):
        devno = node.get("maj:min")
        require(devno and re.fullmatch(r"[0-9]+:[0-9]+", devno), "Missing block device identity.")
        holders = Path("/sys/dev/block") / devno / "holders"
        require(holders.is_dir(), "Cannot inspect kernel device holders.")
        require(not list(holders.iterdir()), "Target has active kernel holders.")
    target["device_number"] = info.st_rdev
    return target


def fingerprint(target):
    return tuple(target.get(key) for key in ("path", "size", "maj:min", "model", "serial", "device_number"))


def download_archive(version, path):
    # No redirects: a mirror or redirect must never silently replace the official origin.
    run("curl", "--fail", "--silent", "--show-error", "--proto", "=https", "--tlsv1.2",
        "--connect-timeout", "20", "--max-time", "600", "--retry", "2",
        "--max-filesize", str(MAX_ARCHIVE), "--output", str(path), image_url(version))
    require(0 < path.stat().st_size <= MAX_ARCHIVE, "Empty or oversized archive.")


def extract_verified(archive, image, version, expected):
    require(sha256_file(archive) == digest_value(expected), "Archive SHA256 mismatch; nothing was written to the target.")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        require(len(members) == 1, "Expected exactly one CHR image in the ZIP.")
        item = members[0]
        require(item.filename == f"chr-{version}.img", "Unexpected archive entry/path.")
        require(not item.is_dir() and not item.flag_bits & 1, "Directories/encrypted ZIPs are unsupported.")
        mode = item.external_attr >> 16
        require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "Non-regular ZIP entry rejected.")
        require(MIB <= item.file_size <= MAX_IMAGE and item.file_size % 512 == 0, "Unexpected image size.")
        require(shutil.disk_usage(image.parent).free >= item.file_size + 64 * MIB, "Insufficient temporary space.")
        count = 0
        with bundle.open(item) as source, image.open("xb") as out:
            for data in iter(lambda: source.read(CHUNK), b""):
                count += len(data)
                require(count <= item.file_size, "Image exceeded declared size.")
                out.write(data)
        require(count == item.file_size, "Truncated image.")
    with image.open("rb") as stream:
        stream.seek(510)
        require(stream.read(2) == b"\x55\xaa", "Missing boot-sector signature; image layout is unsupported.")
    return sha256_file(image)


def confirmation_text(disk, version):
    return f"ERASE {disk} INSTALL {version}"


def confirm(disk, version):
    require(sys.stdin.isatty(), "Installation requires an interactive terminal; no unattended --yes mode.")
    expected = confirmation_text(disk, version)
    print("ALL partitions/data on this disk will become inaccessible. This is NOT an upgrade or secure erase.")
    print("Have an off-server backup, provider console and the production IP/prefix/gateway ready.")
    require(input("Type exactly: " + expected + "\n> ") == expected, "Confirmation did not match; cancelled.")


def write_all(fd, data):
    while data:
        written = os.write(fd, data)
        require(written > 0, "Short disk write.")
        data = data[written:]


def copy_and_verify(image, fd, disk_size, expected):
    """fd must already be an exclusively opened, revalidated offline block device."""
    size = image.stat().st_size
    require(size + MIB <= disk_size, "Image does not fit with backup-GPT cleanup space.")
    # Remove stale backup GPT metadata; this is NOT sanitization of the old data.
    os.lseek(fd, disk_size - MIB, os.SEEK_SET)
    write_all(fd, b"\0" * MIB)
    os.lseek(fd, 0, os.SEEK_SET)
    done = 0
    with image.open("rb") as source:
        for data in iter(lambda: source.read(CHUNK), b""):
            write_all(fd, data)
            done += len(data)
            print(f"\rWriting: {done}/{size} bytes", end="", flush=True)
    os.fsync(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        data = os.read(fd, min(CHUNK, remaining))
        require(data, "Unexpected EOF during target verification.")
        digest.update(data)
        remaining -= len(data)
    require(digest.hexdigest() == expected, "Target read-back SHA256 mismatch. DO NOT boot this disk.")
    print("\nImage range read-back SHA256 verified.")


def deploy(image, disk, original, expected):
    require(fingerprint(check_target(disk)) == fingerprint(original), "Disk identity changed; aborting.")
    require(sha256_file(image) == expected, "Prepared image changed; aborting.")
    # Linux O_EXCL on a block device refuses already-held devices and reserves this device.
    fd = os.open(disk, os.O_RDWR | os.O_EXCL)
    try:
        opened = os.fstat(fd)
        require(stat.S_ISBLK(opened.st_mode) and opened.st_rdev == original["device_number"], "Opened disk identity changed.")
        require(fingerprint(check_target(disk)) == fingerprint(original), "Disk state changed after opening.")
        copy_and_verify(image, fd, int(original["size"]), expected)
    finally:
        os.close(fd)


def parser():
    result = argparse.ArgumentParser(description="DigitalVPS MikroTik CHR offline-disk installer (rescue/live only).")
    result.add_argument("--version", required=True, help="Exact RouterOS version; no implicit latest")
    result.add_argument("--disk", default="auto", help="Unused whole disk; auto selects only a sole eligible disk")
    result.add_argument("--sha256", help="Optional trusted ZIP checksum; otherwise compute digest after official HTTPS download")
    result.add_argument("--dry-run", action="store_true", help="Validate host/disk/download/image without writing the target")
    result.add_argument("--console-ready", action="store_true", help="Acknowledge tested provider console, backup and manual network setup")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    version_value(args.version)
    if args.sha256 is not None:
        digest_value(args.sha256)
    require(args.dry_run or args.console_ready, "Installation requires --console-ready after verifying console and backup access.")
    check_host()
    if args.disk == "auto":
        args.disk = auto_disk("offline")
    original = check_target(args.disk)
    print("DigitalVPS | https://client.digitalvps.ir/")
    print(f"Target: {args.disk} | bytes: {original['size']} | model: {original.get('model')} | serial: {original.get('serial')}")
    print("Source: " + image_url(args.version))
    print("Network is NOT automatically migrated. Capture production settings BEFORE entering rescue.")
    os.umask(0o077)
    # Private directory; no loop mounts, no modification of the CHR filesystem.
    with tempfile.TemporaryDirectory(prefix="digitalvps-chr-") as work:
        work = Path(work)
        require(shutil.disk_usage(work).free >= MAX_ARCHIVE + 64 * MIB, "Need at least 576 MiB free temporary space before download.")
        archive, image = work / "chr.zip", work / "chr.img"
        download_archive(args.version, archive)
        reference = archive_reference(archive, args.sha256)
        digest = extract_verified(archive, image, args.version, reference)
        require(image.stat().st_size + MIB <= int(original["size"]), "Image does not fit on target.")
        print("Archive SHA256, ZIP integrity and basic boot-sector checks passed.")
        print("Prepared image SHA256: " + digest)
        if args.dry_run:
            print("DRY RUN: no target writes, no reboot. This is not a boot/network certification.")
            return 0
        confirm(args.disk, args.version)
        print("Starting irreversible write. On failure restore your external snapshot; no automatic rollback exists.")
        deploy(image, args.disk, original, digest)
    print("Disk write completed. Boot and network have NOT been verified.")
    print("Keep provider firewall restrictive. Detach rescue media, boot target via panel, set password and network via console.")
    print("No automatic reboot was performed. Help: https://client.digitalvps.ir/supporttickets.php")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (InstallError, OSError, ValueError, zipfile.BadZipFile, EOFError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted. If writing had started, the target may be incomplete; restore/reinstall from rescue.", file=sys.stderr)
        sys.exit(130)
