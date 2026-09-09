# MikroTik CHR Installer for Ubuntu and Debian | DigitalVPS

**Deploy an official RouterOS CHR image to an offline VPS disk from Linux rescue/live mode.**

## Choose your installation path

| Starting environment | Entry point |
|---|---|
| Running Ubuntu, no provider Rescue | **[Experimental RAM boot path](docs/RAM-INSTALL.md)**: `ram-install.sh` |
| Rescue/live with an unused offline disk | `script.sh`; the remaining installation sections below |

The RAM path stages inside Ubuntu, then writes the disk from a separate RAM environment after explicit confirmation and manual reboot. Initial scope: KVM/QEMU, BIOS, one VirtIO disk, plain ext4 root and required built-in kernel drivers. No automatic network migration. A non-writing probe is provided. **Real RAM boot has not yet been tested.**

[فارسی — راهنمای نصب میکروتیک](README.md) · [DigitalVPS MikroTik VPS](https://client.digitalvps.ir/store/mikrotik-vps) · [Client area](https://client.digitalvps.ir/) · [Support](https://client.digitalvps.ir/supporttickets.php)

This open-source **DigitalVPS (دیجیتال وی پی اس)** project helps Linux and network administrators prepare a virtual server disk for **MikroTik RouterOS Cloud Hosted Router**. The installer provides explicit disk selection, mandatory archive SHA256 verification, a non-writing dry run, and image-range read-back verification.

> [!CAUTION]
> This is a destructive fresh installation, not an application installed inside Ubuntu. Existing partitions and the OS on the selected disk are replaced. Keep an off-server backup and a working provider console. Never run it on a Virtualizor host node, physical hypervisor, active customer server or valuable disk.

> [!IMPORTANT]
> Breaking change: `script.sh` writes offline disks only. Use the separate RAM path above if provider Rescue is unavailable; do not remove the mounted-disk guard. **Networking is not migrated automatically. Real CHR boot has not yet been certified.** Complete the [disposable-VM acceptance checklist](docs/TESTING.md) before production use. The remaining installation instructions below describe the offline path.

## Contents

- [Capabilities](#capabilities)
- [Requirements](#requirements)
- [Install MikroTik CHR](#install-mikrotik-chr)
- [First boot and networking](#first-boot-and-networking)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [About DigitalVPS](#about-digitalvps)

## Capabilities

| Feature | Implemented behavior |
|---|---|
| Official download | HTTPS from `download.mikrotik.com`, with no redirect following |
| Version selection | Explicit numeric RouterOS 6/7 release; no implicit latest |
| Download verification | Mandatory user-supplied trusted SHA256 of the ZIP archive |
| Archive checks | One correctly named regular image, size limits, ZIP CRC and basic boot signature |
| Disk safeguards | Explicit whole disk, mounted-child/swap/topology checks and identity revalidation |
| Dry run | Host, disk, download and image checks; no destination writes |
| Confirmation | Interactive exact disk/version phrase; no unattended `--yes` |
| Write verification | Exclusive disk open, copy, `fsync`, then image-range SHA256 read-back |
| Cleanup | Private temporary directory; no CHR filesystem mounts or loop devices |
| Reboot | Manual provider-panel action only |

Not implemented: automatic network migration, RouterOS password/firewall setup, backup, rollback, in-place upgrades, partition resizing, secure erase, or boot/performance guarantees. Old bytes outside the image may remain recoverable. The final 1 MiB of the disk is zeroed to clear stale backup GPT metadata, **not to sanitize all old data**.

## Requirements

The following is the code's accepted scope, **not a tested boot-compatibility matrix**:

| Component | Requirement |
|---|---|
| Linux userspace | Ubuntu 20.04/22.04/24.04 or Debian 11/12/13 rescue/live |
| Virtualization | KVM, QEMU or VMware guest; no containers or host nodes |
| Architecture / firmware | x86-64 and legacy BIOS rescue boot; UEFI is rejected in this revision |
| Target | Unused whole disk, 512-byte logical sectors, at least 1 GiB and image size + 1 MiB |
| Temporary space | At least 576 MiB before downloading, then extracted image size + 64 MiB free |
| Size bounds | ZIP up to 512 MiB; image up to 2 GiB |
| Access | Root, HTTPS connectivity to MikroTik, independent console and external backup |
| Tools | Bash, Python 3, curl, util-linux, systemd, CA certificates; Git to fetch the project |

OpenVZ/LXC/Docker, loop/mapper targets, RAID/LVM/LUKS/ZFS/Btrfs, removable disks and 4Kn are rejected. Canonical names such as `/dev/vda`, `/dev/sda` and `/dev/nvme0n1` are accepted; this does not certify RouterOS controller support. Acceptance of older Linux or RouterOS releases is not a production/security recommendation.

## Install MikroTik CHR

### 1. Save production network settings before rescue

Record your production IP, prefix, gateway, DNS, MAC and NIC type from the provider panel. Rescue networking may be different. Check external backup restoration and actual VNC/serial/console access. Restrict the provider firewall before CHR boots; expose management only to your administrator IP.

These read-only commands can help record the current Ubuntu network:

```bash
ip -br address
ip -4 route show table all
ip -6 route show table all
ip -d link show
```

### 2. Boot rescue/live and fetch the entire repository

To replace your system disk, boot provider rescue/live media. The target and its children must not be mounted or used by active storage stacks. The installer does not unmount filesystems, disable swap, or deactivate LVM for you.

```bash
sudo apt-get update
sudo apt-get install -y git python3 curl ca-certificates util-linux systemd
git clone https://github.com/Digitalvps-Ir/Mikrotik-Ubuntu.git
cd Mikrotik-Ubuntu
bash script.sh --help
lsblk -o NAME,TYPE,SIZE,MODEL,SERIAL,MOUNTPOINT
```

Review code before running as root; use a reviewed commit for repeatable deployment. Both `script.sh` and compatibility entry point `install.sh` need `chr_installer.py` beside them. Downloading a single script or using `curl | bash` is no longer supported.

### 3. Select an exact release and trusted ZIP checksum

Choose an appropriate release and **x86-64 RAW disk** archive from [MikroTik CHR downloads](https://mikrotik.com/download/chr). Supply the SHA256 of the **ZIP**, not the extracted IMG. Release number, archive type and checksum must match.

Obtain the digest from a trusted source for that release. If no vendor digest is available for your archive, obtain and inspect a reference copy from the official origin on a trusted machine, then record its hash. Hashing the same suspect download does not independently establish authenticity. The installer does not discover a trusted digest for you or provide a fabricated default.

```bash
# On your trusted reference archive only:
sha256sum chr-7.23.5.img.zip
```

`7.23.5` is an explicit example, not an evergreen latest-version promise. Review release notes/security status before deploying. Accepting numeric 6/7 versions does not certify every release's boot behavior.

### 4. Run a non-writing validation

`/dev/vda` is only an example; select the correct disk yourself. Replace the checksum placeholder with the trusted 64-character digest; leaving it unchanged fails closed.

```bash
sudo bash script.sh \
  --version 7.23.5 \
  --disk /dev/vda \
  --sha256 REPLACE_WITH_TRUSTED_ZIP_SHA256 \
  --dry-run
```

Dry-run downloads and removes temporary files. It does not write the target or certify boot/networking. Final installation downloads and verifies again.

### 5. Perform the destructive installation

Only after a successful dry run, verified disk selection, backup and console access:

```bash
sudo bash script.sh \
  --version 7.23.5 \
  --disk /dev/vda \
  --sha256 REPLACE_WITH_TRUSTED_ZIP_SHA256 \
  --console-ready
```

Type the requested phrase exactly:

```text
ERASE /dev/vda INSTALL 7.23.5
```

`--console-ready` acknowledges readiness; it does not bypass the interactive confirmation. After write and read-back succeed, detach rescue media and boot the target through the panel. If writing fails, do not boot the incomplete disk; remain in rescue and restore or reinstall after diagnosing the failure. There is no automatic rollback or reboot.

## First boot and networking

Use the independent console and set a strong password immediately. MikroTik documents `admin` with no initial password for a fresh official raw image; do not depend on passwordless public SSH. `/password` prompts interactively instead of embedding the secret in a command.

```routeros
/password
/interface print
/ip address print
/ip route print
/ip dhcp-client print
```

Use the actual production interface/IP/gateway from your provider. Do not assume `ether1`, DHCP, `/24` or an in-subnet gateway. `/32`, off-subnet gateways, VLANs and multi-NIC configurations require provider-specific setup, not generated/imported configuration from this installer.

For **an ordinary static network only**, replace all placeholders and inspect for existing/duplicate configuration first:

```routeros
/ip address add address=YOUR_IP/PREFIX interface=YOUR_INTERFACE
/ip route add dst-address=0.0.0.0/0 gateway=YOUR_GATEWAY
/ip dns set servers=YOUR_DNS_IP allow-remote-requests=no
```

These are RouterOS commands, not Bash. Do not enable NAT/VPN without a designed need. Before public exposure, disable unused services, restrict SSH/Winbox to your administrator IP and configure appropriate **IPv4 and IPv6** firewall policies. Test new access in a second session while keeping the console open. The old conflicting SSH/firewall and open-DNS examples have been removed.

## Troubleshooting

| Symptom | Action |
|---|---|
| Missing chr_installer.py | Fetch the whole checkout, not one shell file |
| Target/child mounted | Boot rescue, inspect and manually unmount as appropriate; never bypass the guard |
| Active swap | Inspect and safely disable swap yourself in rescue |
| SHA256 mismatch | Check exact version, x86-64 RAW ZIP type and trusted ZIP digest; do not replace the hash merely to pass |
| Download/404 | Verify that release exists and official HTTPS works; there is no mirror fallback |
| Unsupported host/UEFI/topology | Use the accepted environment or provider image installation |
| Write/read-back failed | Target may be incomplete; restore/reinstall from rescue after fixing the cause |
| Boots without network | Use console to check production MAC, interface, IP/prefix and gateway |
| Does not boot | Check BIOS/controller against CHR documentation, then restore if needed |

For bug reports include sanitized output, release and virtualization type. Remove public IPs, serials, credentials and account data before posting. The installer creates no persistent log or automatic backup.

## FAQ

### Does this install MikroTik inside Ubuntu?

No. Linux prepares a replacement disk. To keep Ubuntu, deploy CHR in a separate VM using your hypervisor; this tool does not create VMs.

### Is the existing IP automatically preserved?

No. The previous script did not actually migrate networking either. This revision explicitly requires console configuration and production network details saved before rescue.

### Does DigitalVPS install or bypass a CHR license?

No. RouterOS licensing is separate from this code's MIT license. Consult the [official CHR licensing documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR) for current tiers, limits and trial conditions.

### Can I run this again to upgrade RouterOS?

No. This is fresh destructive installation. Back up off-device and use RouterOS's official package upgrade procedure for an existing router.

### How do I run the tests?

```bash
bash -n script.sh install.sh
python3 -m unittest discover -s tests -v
```

Tests use mocks and regular temporary files; they do not access the network or real disks. See [testing and acceptance](docs/TESTING.md) for results and limitations.

## About DigitalVPS

**DigitalVPS — دیجیتال وی پی اس** publishes this tool alongside its server services and Linux/network learning resources. Visit the client portal to explore MikroTik VPS options and ask about CHR compatibility. Confirm current pricing, availability and rescue/console access with the provider; this README promises no independent pricing or SLA.

| Official DigitalVPS reference | Purpose |
|---|---|
| [MikroTik VPS](https://client.digitalvps.ir/store/mikrotik-vps) | MikroTik virtual server product linked by the official navigation |
| [DigitalVPS client portal](https://client.digitalvps.ir/) | Account access |
| [Knowledge base](https://client.digitalvps.ir/knowledgebase) | Linux and networking learning resources |
| [Support tickets](https://client.digitalvps.ir/supporttickets.php) | Compatibility, console and service questions |

Links were taken from the public client-site navigation on 2026-09-09. Product/support pages may require login or a transfer step. The existing Ubuntu installation article still contains the legacy one-line command; follow this README for **this rewrite**. The website itself was not edited.

## References and license

- [Official CHR downloads](https://mikrotik.com/download/chr)
- [CHR documentation and hypervisors](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR)
- [GitHub issues](https://github.com/Digitalvps-Ir/Mikrotik-Ubuntu/issues)
- Project code: [MIT License](LICENSE). MikroTik software and trademarks belong to their owners; no official MikroTik affiliation is implied.
