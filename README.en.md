# Install MikroTik CHR on an Ubuntu VPS | Digitalvps.ir

This project writes the official MikroTik Cloud Hosted Router (CHR) RAW image to the disk of an x86_64 virtual machine. It has two installation modes:

1. **From a running Ubuntu system (default):** Prepare the image in a dedicated initramfs. A one-time GRUB entry writes the disk at the next boot, before the Ubuntu root filesystem is mounted. Virtualizor Rescue is not required.
2. **From Rescue:** Write an unmounted target disk directly from an independent rescue environment.

[راهنمای فارسی](README.md) · [Digitalvps.ir](https://digitalvps.ir)

> [!CAUTION]
> Both modes erase all data on the selected disk. Keep an external backup and verify that the provider console is accessible before starting. Review the disk name yourself.

## Versions

Suggested releases as of 27 September 2026:

| Version | Channel | Use |
| --- | --- | --- |
| `7.24.4` | Stable | New installations |
| `7.23.7` | Long-term | Long-term channel |
| `6.49.22` | Long-term | Legacy compatibility only |

The `--version` option also accepts any numeric official 6.x or 7.x release, including newer releases when MikroTik publishes their CHR RAW archive. Beta and development labels are rejected. Check the [official CHR download page](https://mikrotik.com/download/chr) before selecting a release. A syntactically valid version does not guarantee that its archive exists; an unavailable download stops before any disk write.

## Requirements

- An x86_64 VPS or VM with a bootable virtual disk. Containers are not supported.
- Legacy BIOS and root access. The installer refuses UEFI boot for this workflow.
- Provider console or VNC access for first boot and network troubleshooting.
- For the default mode: Ubuntu with GRUB, initramfs-tools, BusyBox and at least 1 GiB RAM. This path does not support systemd-boot.
- `curl`, `unzip`, `util-linux`, and `coreutils`. On Ubuntu or Debian-based Rescue:

```bash
apt-get update
apt-get install -y curl unzip util-linux coreutils busybox initramfs-tools grub2-common
```

The work directory (`/tmp` by default) needs space for both the archive and extracted image. The default mode also needs room in `/boot` for its dedicated initramfs. Use `--workdir` when `/tmp` is too small.

## Install from a running Ubuntu system

This is the option for a Virtualizor VPS without Rescue access. If there is one root disk, the installer detects it and displays its name for confirmation. With multiple disks, inspect `lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL` and pass the whole target disk with `--disk`; a partition such as `/dev/vda1` is invalid.

```bash
curl -fsSL https://raw.githubusercontent.com/Digitalvps-Ir/Mikrotik-Ubuntu/main/script.sh -o script.sh
less script.sh
sudo bash script.sh --version 7.24.4
```

Enter the exact confirmation phrase shown by the installer, for example `ERASE /dev/vda`. The image is downloaded and validated, then the installer creates a one-time GRUB entry and reboots the VM. Before Ubuntu mounts its root disk, the next boot writes and verifies the CHR image and reboots to RouterOS. Watch both reboots through the provider console; Ubuntu SSH disconnects.

If needed, use `--disk /dev/vda` with the disk's actual name. Exact confirmation is still required after automatic disk detection.

Before the first reboot, you can remove a staged installation:

```bash
sudo bash script.sh --cancel-live
```

If initramfs creation or GRUB setup fails, the staging files are removed and Ubuntu remains. If the offline disk write fails, the VM stops in initramfs; diagnose through the console and do not boot a partially written disk.

## Install from Rescue

Boot an independent Rescue system and leave the target disk unmounted:

```bash
sudo bash script.sh --mode rescue --disk /dev/nvme0n1 --version 7.23.7
```

After the `byte-for-byte verification succeeded` message, disable Rescue in the provider panel and power cycle the VM. If `/tmp` is small, use `--workdir` on a disk other than the target.

`--yes-erase` bypasses interactive confirmation for automation. If you have a trusted SHA-256 digest for the ZIP archive, pass it with `--sha256 HASH`. A digest computed from the same download is not an independent authenticity check.

## First boot and network

Open the provider console, set a strong password for `admin`, and configure network and management services for your provider's actual network. The installer does not inject an IP address, gateway, DNS, firewall rules or a RouterOS password. Ubuntu's static network configuration is not transferred to CHR. For a VPS without DHCP or accessible console, arrange a CHR network setup path with the provider before erasing Ubuntu.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Target disk mounted or in use | In Rescue, unmount the target's partitions. From Ubuntu, use the default `live` mode. |
| Live mode requires Ubuntu root | Check that the target is the disk containing the current Ubuntu root filesystem. |
| GRUB entry cannot be verified | Check GRUB and the provider console; staging is removed before reboot. |
| UEFI mode | This workflow requires Legacy BIOS; change the VM firmware or use a provider-supported image method. |
| ZIP integrity or archive contents error | Check the version and official download. No disk write has started. |
| RAW image larger than disk | Select a larger target disk. |
| Disk write or comparison failed | The disk may be incomplete. Recover using the provider console or Rescue. |
| CHR boots without network | Check interface, IP, prefix and gateway through the provider console. |
| VM does not boot | Check Rescue status, boot order and VM firmware in the provider panel. |

## Scope and references

This is a fresh replacement of Ubuntu with CHR, not an in-place RouterOS upgrade. For an existing CHR installation, use RouterOS's own upgrade process and a backup. CHR licensing is separate from this project's [MIT License](LICENSE).

- [Official CHR downloads](https://mikrotik.com/download/chr)
- [Official CHR installation guide](https://manual.mikrotik.com/docs/getting-started/installation-and-upgrade/install/chr-installation/)
- [Official CHR licensing guide](https://manual.mikrotik.com/docs/getting-started/routeros-licensing/chr/chr-licensing/)

## Digitalvps.ir

[Digitalvps.ir](https://digitalvps.ir) provides hosting and virtual server services. Check the [website](https://digitalvps.ir) or [client area](https://client.digitalvps.ir) for current services, prices and availability. This README intentionally does not freeze prices or promotional claims.
