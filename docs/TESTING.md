# Verification report and release acceptance

RAM-path update: [experimental RAM boot](RAM-INSTALL.md) has been added alongside the offline path. It has separate check/prepare/arm/cancel actions and a non-writing boot probe. Real RAM/GRUB/CHR boot is still **untested**. The original 46-test result below is historical; the expanded suite now includes RAM packaging, staging and safety tests.

## Scope / محدوده

The rewritten installer is **not production-certified**. Automated tests exercise validation, orchestration and file I/O without accessing a real block device or downloading RouterOS. Some validation functions are tested with mocks; success does not certify real-device kernel locking, CHR boot, image layout, controller compatibility or networking.

تست‌های خودکار روی دیسک سرور یا ایمیج واقعی RouterOS اجرا نشده‌اند. موفقیت تست واحد به‌معنای تأیید بوت و شبکه نیست؛ قبل از استفاده برای مشتریان، تست پذیرش روی VM مستقل لازم است.

## Reproduce locally

From the repository root on Linux with Bash, Python 3 and util-linux:

```bash
bash -n script.sh install.sh
python3 -m unittest discover -s tests -v
```

The tests use `unittest`, not a third-party framework. The read-only integration check runs real `lsblk` and `swapon` inventory commands. Disk-copy tests operate only on regular files created inside temporary directories; the public installer rejects regular-file targets.

## Executed checks (2026-09-09)

| Check | Result / meaning |
|---|---|
| Bash syntax, both entry points | Passed |
| Python unit / workflow / documentation tests | 85 tests passed, including 12 automatic-default tests |
| Real Linux inventory-command syntax | Passed on the available runtime only |
| Official archive download | Not executed in this restricted runtime |
| Official CHR image extraction | Not executed; synthetic ZIP fixtures tested |
| Real block device exclusive lock / write / read-back | Not executed; regular-file surrogate and mocks only |
| CHR boot on KVM / VMware | Not executed; no QEMU binary or `/dev/kvm` available |
| Ubuntu / Debian release matrix | Not executed; accepted releases are code policy, not certified results |
| RouterOS login, IP, SSH, Winbox, routing | Not executed |
| GitHub Actions CI | No workflow added or remote CI result claimed |

## Automated coverage

- Exact numeric version parsing; URL/path/command injection rejected.
- ZIP SHA256 syntax/match, single-file layout, traversal/name/symlink rejection, corrupt ZIP, space and boot signature checks.
- Explicit disk selection, mounted root/child rejection, missing metadata, small/read-only/removable/4Kn targets, complex storage layouts.
- Active swap and missing device identity fail closed; canonical paths only.
- Non-root and missing-console acknowledgement rejection; terminal/exact-phrase confirmation.
- Dry-run never calls the deployment writer; failed downloads clean temporary files.
- Confirmation precedes deployment in the mocked complete workflow.
- Target identity and image digest rechecked before opening; exclusive-open flag and descriptor cleanup after write errors.
- Short-write handling, image copy, final-1-MiB cleanup and read-back hash mismatch detection on regular-file surrogates.
- Both shell entry points, CLI help, local Markdown links, Farsi TOC anchors and bilingual option/reference consistency.

## Disposable-VM acceptance checklist — required before production

1. Create a NEW expendable KVM VM, with no attached production disks, snapshots or customer data. Provide independent console access. Do not run these tests on a host node.
2. Record hypervisor, guest firmware, disk/NIC controller, rescue ISO release, Python/util-linux versions, CHR release and trusted official ZIP SHA256.
3. Use BIOS and a supported controller. Boot Ubuntu/Debian rescue. Confirm the selected disk is expendable, unused, not mounted and has no active swap/holders.
4. Run `--dry-run` against that disk; verify a before/after checksum of the disposable disk is identical. Check that network/download failures and incorrect SHA256 stop before target writes.
5. In separate negative scenarios, mount a disposable child partition, enable disposable swap, or select a partition path; confirm rejection. Never manufacture these conditions on a live customer's system.
6. Run the installer with console acknowledgement and exact confirmation. Record successful image-range read-back verification. Test cancellation before confirmation separately.
7. Detach rescue media and boot CHR. Confirm disk visibility and console login. Immediately set a password while the upstream firewall is restrictive.
8. Configure the provider's production network manually. Test static IPv4, DHCP if applicable, `/32`/off-subnet gateway if required, and IPv6 separately. Check SSH/Winbox from the allowed administrator IP and rejection from elsewhere.
9. Reboot once from RouterOS, confirm persistence, then validate licensing and the actual routing use case. A listening TCP port alone is not a complete acceptance result.
10. Repeat for the actual deployment matrix (Ubuntu 20.04/22.04/24.04, Debian 11/12/13, KVM/VMware and chosen CHR releases). Record pass/fail/untested per combination. Test interrupted writes only on a disposable disk; recovery is reinstall or external restore, not rollback.

Do not label every accepted version "supported/tested" based on one successful VM. Publish sanitized evidence with dates and exact versions; omit credentials, private addresses and customer identifiers.

## Known limitations

- `script.sh` remains offline-only. The separate experimental `ram-install.sh` stages from running Ubuntu and boots into RAM before raw disk writes; its probe must be validated first.
- No network migration/config injection. Production addresses must be recorded before rescue and configured via console after boot.
- Auto mode computes SHA256 after official HTTPS download; this is not independent vendor authentication. Optional trusted `--sha256` pinning still fails closed on mismatch. Automatic disk selection requires one candidate. Version presets are fixed and dated, not live discovery.
- Only basic image format checks; an MBR signature alone cannot prove CHR correctness or bootability.
- Read-back occurs through the OS after `fsync`; it is not independent storage-hardware certification.
- No automatic backup, rollback, filesystem expansion, UEFI enablement or secure erase. The offline path never reboots; the RAM path requires manual initial reboot after arming, then automatically reboots on successful probe or verified installation.
- Kernel/device enumeration differs between environments. Safety checks intentionally reject uncertain/unsupported layouts rather than auto-deactivate them.
- A private mount namespace/container is unsupported. Use the VM's normal rescue environment, with no concurrent storage management or automount operations.
- The existing DigitalVPS knowledge-base article links the old one-line installer. Coordinate its documentation update before merging this breaking change; this repository change does not edit the website.

Return to [فارسی](../README.md) / [English](../README.en.md).
