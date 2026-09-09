#!/usr/bin/env python3
"""Experimental BIOS/KVM RAM installer: check -> prepare -> arm -> manual reboot.

No raw disk write occurs in the running Ubuntu environment. The destructive
writer exists only inside the generated initramfs. A non-writing probe is provided.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from chr_installer import (InstallError, MIB, check_host, digest_value,
                          download_archive, extract_verified, require, run,
                          sha256_file, version_value, archive_reference, auto_disk)

STAGE = Path("/boot/digitalvps-chr-ram")
HOOK = Path("/etc/grub.d/41_digitalvps_chr_ram")
ENTRY = "digitalvps-chr-ram"
CONFIG = Path("/boot/grub/grub.cfg")
REQUIRED_CONFIG = ("BLK_DEV_INITRD", "RD_GZIP", "DEVTMPFS", "BINFMT_ELF", "BINFMT_SCRIPT", "VIRTIO_BLK", "VIRTIO_PCI")


def available_memory():
    values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(values["MemAvailable"].split()[0]) * 1024


def validate_kernel_config(text):
    settings = dict(line.split("=", 1) for line in text.splitlines() if line.startswith("CONFIG_") and "=" in line)
    for name in REQUIRED_CONFIG:
        require(settings.get("CONFIG_" + name) == "y", f"Kernel needs built-in CONFIG_{name}=y; module loading is not implemented.")


def preflight(disk):
    check_host()
    require(run("systemd-detect-virt").strip() in {"kvm", "qemu"}, "RAM path currently accepts KVM/QEMU only.")
    require(re.fullmatch(r"/dev/vd[a-z]+", disk), "Experimental RAM path requires a VirtIO whole disk, e.g. /dev/vda.")
    require(stat.S_ISBLK(os.lstat(disk).st_mode), "Target must be a real block device, not an alias/file.")
    for command in ("busybox", "readelf", "grub-probe", "grub-mkconfig", "grub-script-check", "grub-editenv", "grub-reboot"):
        require(shutil.which(command), f"Missing {command}; see docs/RAM-INSTALL.md prerequisites.")
    require(not run("swapon", "--show", "--noheadings", "--raw", "--output", "NAME").strip(), "Disable active swap before staging.")
    require(run("findmnt", "-n", "-o", "FSTYPE", "/").strip() == "ext4", "RAM path requires a plain ext4 root filesystem.")
    source = run("findmnt", "-n", "-o", "SOURCE", "/").strip()
    require(re.fullmatch(re.escape(disk) + r"[0-9]+", source), "Root must be a direct partition of the explicit target.")
    require(run("findmnt", "-n", "-o", "SOURCE", "--target", "/boot").strip() == source,
            "Separate /boot is not yet supported by the RAM path.")
    data = json.loads(run("lsblk", "--json", "--bytes", "--paths", "--tree", "--output", "PATH,TYPE,SIZE,RO,RM,LOG-SEC"))
    disks = [node for node in data["blockdevices"] if node.get("type") == "disk"]
    require(len(disks) == 1 and disks[0]["path"] == disk, "RAM path requires exactly one whole disk; detach other disks first.")
    target = disks[0]
    require(target.get("ro") in (0, False) and target.get("rm") in (0, False), "Disk must be writable and non-removable.")
    require(target.get("log-sec") == 512, "Only 512-byte logical sectors supported.")
    size = int(target["size"])
    require(size >= 1024 * MIB and size % 512 == 0, "Unexpected target size.")
    children = target.get("children", [])
    require(children and all(x.get("type") == "part" and not x.get("children") for x in children), "Complex storage topology is unsupported.")
    kernel = os.uname().release
    require(re.fullmatch(r"[A-Za-z0-9_.+-]+", kernel), "Unexpected kernel release.")
    kernel_path = Path("/boot") / ("vmlinuz-" + kernel)
    require(kernel_path.is_file(), "Running kernel is missing from /boot.")
    validate_kernel_config((Path("/boot") / ("config-" + kernel)).read_text())
    busybox = Path(shutil.which("busybox")).resolve()
    require("INTERP" not in run("readelf", "-lW", str(busybox)), "Install busybox-static; dynamically linked BusyBox cannot boot standalone.")
    applets = set(run(str(busybox), "--list").split())
    require({"sh", "mount", "dd", "sha256sum", "head", "sleep", "sync", "reboot", "awk", "cat", "wc"} <= applets,
            "BusyBox lacks required applets.")
    # BusyBox writes usage/help to stderr on several supported releases.
    help_result = subprocess.run([str(busybox), "dd", "--help"], text=True, capture_output=True, check=False)
    require("fsync" in help_result.stdout + help_result.stderr, "BusyBox dd needs conv=fsync.")
    require(available_memory() >= 1024 * MIB, "At least 1 GiB available RAM is required before preparation.")
    uuid = run("grub-probe", "--target=fs_uuid", "/boot").strip()
    require(re.fullmatch(r"[a-fA-F0-9-]+", uuid), "Unexpected boot filesystem UUID.")
    cfg = CONFIG.read_text()
    require("next_entry" in cfg and "save_env next_entry" in cfg, "GRUB configuration does not support clearing a one-shot next_entry.")
    env = run("grub-editenv", "/boot/grub/grubenv", "list")
    require(not re.search(r"^next_entry=.+", env, re.M), "A one-shot boot is already scheduled; resolve it before staging.")
    with open(disk, "rb") as stream:
        mbr = hashlib.sha256(stream.read(512)).hexdigest()
    return {"disk": disk, "disk_size": size, "mbr_sha256": mbr, "kernel": kernel,
            "kernel_path": str(kernel_path), "boot_uuid": uuid, "busybox": str(busybox)}


def cpio_entry(stream, name, mode, payload=b"", inode=1, rmajor=0, rminor=0):
    require(not name.startswith("/") and ".." not in name.split("/"), "Unsafe initramfs entry.")
    raw_name = name.encode() + b"\0"
    size = payload.stat().st_size if isinstance(payload, Path) else len(payload)
    values = [inode, mode, 0, 0, 1, 0, size, 0, 0, rmajor, rminor, len(raw_name), 0]
    header = b"070701" + b"".join(f"{v:08x}".encode() for v in values)
    stream.write(header + raw_name)
    stream.write(b"\0" * (-(len(header) + len(raw_name)) % 4))
    if isinstance(payload, Path):
        with payload.open("rb") as source:
            shutil.copyfileobj(source, stream, 4 * MIB)
    else:
        stream.write(payload)
    stream.write(b"\0" * (-size % 4))


def render_init(info, probe, image_hash="", image_size=0):
    # Only validated numeric/path/digest values are interpolated; no eval or user shell content.
    require(re.fullmatch(r"/dev/vd[a-z]+", info["disk"]), "Invalid disk path.")
    digest_value(info["mbr_sha256"])
    if not probe:
        digest_value(image_hash)
        require(image_size >= MIB and image_size + MIB <= info["disk_size"], "Image does not fit.")
    script = Path(__file__).with_name("ram-init.sh.in").read_text()
    mapping = {"@DISK@": info["disk"], "@SECTORS@": str(info["disk_size"] // 512),
               "@MBR@": info["mbr_sha256"], "@MODE@": "probe" if probe else "install",
               "@IMAGE_HASH@": image_hash, "@IMAGE_SIZE@": str(image_size)}
    for token, value in mapping.items():
        script = script.replace(token, value)
    return script.encode()


def build_initramfs(output, busybox, init, image=None):
    with output.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as archive:
        inode = 1
        for directory in ("bin", "dev", "proc", "sys", "tmp"):
            cpio_entry(archive, directory, stat.S_IFDIR | 0o755, inode=inode)
            inode += 1
        cpio_entry(archive, "dev/console", stat.S_IFCHR | 0o600, inode=inode, rmajor=5, rminor=1)
        cpio_entry(archive, "bin/busybox", stat.S_IFREG | 0o755, Path(busybox), inode=inode + 1)
        cpio_entry(archive, "bin/sh", stat.S_IFLNK | 0o777, b"busybox", inode=inode + 2)
        cpio_entry(archive, "init", stat.S_IFREG | 0o700, init, inode=inode + 3)
        if image is not None:
            cpio_entry(archive, "chr.img", stat.S_IFREG | 0o600, image, inode=inode + 4)
        cpio_entry(archive, "TRAILER!!!", 0, inode=inode + 5)


def grub_entry(uuid):
    require(re.fullmatch(r"[a-fA-F0-9-]+", uuid), "Invalid filesystem UUID.")
    return (f"menuentry 'DigitalVPS CHR RAM (experimental)' --id {ENTRY} {{\n"
            f"  search --no-floppy --fs-uuid --set=root {uuid}\n"
            "  linux /boot/digitalvps-chr-ram/vmlinuz rdinit=/init console=tty0 console=ttyS0,115200n8\n"
            "  initrd /boot/digitalvps-chr-ram/initramfs.gz\n}\n")


def confirm_text(expected):
    require(sys.stdin.isatty(), "An interactive terminal is required.")
    require(input("Type exactly: " + expected + "\n> ") == expected, "Cancelled.")


def prepare(args, info):
    require(not STAGE.exists() and not HOOK.exists(), "RAM staging already exists; use --cancel before preparing again.")
    probe = args.prepare_probe
    if not probe:
        version_value(args.version or "")
        if args.sha256 is not None:
            digest_value(args.sha256)
    confirm_text("PREPARE RAM PROBE" if probe else f"PREPARE RAM INSTALL {info['disk']} {args.version}")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="digitalvps-ram-") as temp:
        work = Path(temp)
        image, digest, size, reference = None, "", 0, None
        if not probe:
            require(shutil.disk_usage(work).free >= 576 * MIB, "Insufficient download workspace.")
            archive, image = work / "chr.zip", work / "chr.img"
            download_archive(args.version, archive)
            reference = archive_reference(archive, args.sha256)
            digest = extract_verified(archive, image, args.version, reference)
            size = image.stat().st_size
        require(available_memory() >= 768 * MIB + 3 * size, "Insufficient RAM for image plus initramfs/kernel headroom.")
        require(shutil.disk_usage("/boot").free >= size + 128 * MIB, "Insufficient free /boot space.")
        init = render_init(info, probe, digest, size)
        bundle = work / "initramfs.gz"
        build_initramfs(bundle, info["busybox"], init, image)
        # Protect against firmware/root/identity changes while downloading/building.
        require(preflight(args.disk) == info, "Host/disk state changed during preparation.")
        old_config = CONFIG.read_bytes()
        installed = False
        try:
            STAGE.mkdir(mode=0o700)
            shutil.copyfile(info["kernel_path"], STAGE / "vmlinuz")
            shutil.copyfile(bundle, STAGE / "initramfs.gz")
            info = dict(info, mode="probe" if probe else "install", version=args.version,
                        image_sha256=digest, image_size=size, archive_sha256=reference,
                        archive_verification="not-applicable" if probe else
                        ("supplied-checksum" if args.sha256 is not None else "official-https-computed"))
            info["artifacts"] = {name: sha256_file(STAGE / name) for name in ("vmlinuz", "initramfs.gz")}
            hook = "#!/bin/sh\ncat <<'DIGITALVPS_RAM_ENTRY'\n" + grub_entry(info["boot_uuid"]) + "DIGITALVPS_RAM_ENTRY\n"
            with HOOK.open("x") as out:
                out.write(hook)
            HOOK.chmod(0o700)
            info["hook_sha256"] = sha256_file(HOOK)
            (STAGE / "manifest.json").write_text(json.dumps(info, indent=2) + "\n")
            candidate = STAGE / "grub.cfg.new"
            run("grub-mkconfig", "-o", str(candidate))
            run("grub-script-check", str(candidate))
            require(ENTRY in candidate.read_text(), "Generated GRUB config is missing the RAM entry.")
            (STAGE / "grub.cfg.before").write_bytes(old_config)
            os.replace(candidate, CONFIG)
            installed = True
        finally:
            if not installed:
                # Only paths owned by this attempt, never the user's existing staging.
                if HOOK.exists():
                    HOOK.unlink()
                if STAGE.exists():
                    shutil.rmtree(STAGE)
        os.sync()
    print("Prepared: " + info["mode"] + ". Default boot unchanged; no raw disk write and no reboot.")
    print("Check provider console access before --arm. RAM stage has NO SSH server.")
    print("Next: sudo bash ram-install.sh --arm --console-ready")


def load_manifest():
    require(STAGE.is_dir() and not STAGE.is_symlink(), "No valid RAM staging directory.")
    require(STAGE.stat().st_uid == 0 and not STAGE.stat().st_mode & 0o077, "Staging directory must be root-owned and private.")
    info = json.loads((STAGE / "manifest.json").read_text())
    require(info.get("mode") in {"probe", "install"}, "Invalid staging mode.")
    for name in ("vmlinuz", "initramfs.gz"):
        require(sha256_file(STAGE / name) == info["artifacts"][name], "Staged artifact changed: " + name)
    require(sha256_file(HOOK) == info["hook_sha256"], "GRUB hook changed.")
    return info


def arm(args):
    require(args.console_ready, "--console-ready is required: RAM has no SSH; failures require panel console/rebuild.")
    info = load_manifest()
    current = preflight(info["disk"])
    require(all(info[key] == value for key, value in current.items()), "Host/disk changed; cancel and prepare again.")
    expected = "ARM RAM PROBE" if info["mode"] == "probe" else f"ERASE {info['disk']} INSTALL {info['version']} ON NEXT BOOT"
    print("Probe writes no disk data. Install erases the OS after reboot. Networking is NOT automatically migrated.")
    confirm_text(expected)
    run("grub-script-check", str(CONFIG))
    require(ENTRY in CONFIG.read_text(), "GRUB RAM entry missing.")
    run("grub-reboot", ENTRY)
    require("next_entry=" + ENTRY in run("grub-editenv", "/boot/grub/grubenv", "list").splitlines(), "Failed to schedule one-shot boot.")
    os.sync()
    print("ARMED: the NEXT reboot boots the RAM " + info["mode"] + ". No reboot performed yet.")
    print("Keep provider console open. Reboot manually when ready: systemctl reboot")
    print("Before reboot, cancel using: sudo bash ram-install.sh --cancel")


def cancel():
    load_manifest()
    env = run("grub-editenv", "/boot/grub/grubenv", "list")
    for line in env.splitlines():
        if line.startswith("next_entry="):
            require(line in {"next_entry=", "next_entry=" + ENTRY}, "Another one-shot boot is set; refusing to unset it.")
            run("grub-editenv", "/boot/grub/grubenv", "unset", "next_entry")
    # Disable our hook, regenerate from CURRENT other scripts; do not restore an obsolete config.
    HOOK.chmod(0o600)
    candidate = STAGE / "grub.cfg.cancel"
    try:
        run("grub-mkconfig", "-o", str(candidate))
        run("grub-script-check", str(candidate))
        require(ENTRY not in candidate.read_text(), "RAM entry still present; inspect GRUB manually.")
        os.replace(candidate, CONFIG)
    except Exception:
        HOOK.chmod(0o700)
        raise
    HOOK.unlink()
    shutil.rmtree(STAGE)
    os.sync()
    print("Removed only DigitalVPS RAM staging and its GRUB hook; no reboot or raw disk write.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Experimental KVM/BIOS RAM boot installer; external Rescue not required.")
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("check", "prepare-probe", "prepare", "arm", "cancel"):
        mode.add_argument("--" + flag, action="store_true")
    parser.add_argument("--disk", default="auto", help="VirtIO target; auto requires exactly one candidate")
    parser.add_argument("--version", help="Exact RouterOS release for --prepare")
    parser.add_argument("--sha256", help="Optional trusted ZIP checksum; otherwise compute after official HTTPS download")
    parser.add_argument("--console-ready", action="store_true")
    args = parser.parse_args(argv)
    require(os.geteuid() == 0, "Run with sudo/root.")
    if args.cancel:
        cancel()
    elif args.arm:
        arm(args)
    else:
        if args.disk == "auto":
            args.disk = auto_disk("ram")
        info = preflight(args.disk)
        print(json.dumps(info, indent=2))
        if args.check:
            print("PREFLIGHT PASS: no files changed. Real RAM boot still untested.")
        else:
            prepare(args, info)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (InstallError, OSError, ValueError, EOFError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Cancelled/interrupted. Inspect staging before reboot; no reboot requested by this tool.", file=sys.stderr)
        sys.exit(130)
