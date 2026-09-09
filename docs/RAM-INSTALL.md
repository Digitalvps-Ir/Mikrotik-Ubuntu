# نصب بدون Rescue پنل | Experimental RAM-boot installation

[فارسی](../README.md) · [English](../README.en.md) · [DigitalVPS support](https://client.digitalvps.ir/supporttickets.php)

## وضعیت / Status

**آزمایشی؛ فقط برای VPS خالی و قابل Rebuild. بوت واقعی هنوز تأیید نشده است.** این مسیر برخلاف روش قدیمی، دیسک Ubuntu در حال اجرا را بازنویسی نمی‌کند. یک کرنل و Initramfs مستقل در `/boot/digitalvps-chr-ram` آماده می‌کند؛ سپس با بوت یک‌باره GRUB وارد RAM می‌شود. Rescue یا ISO خارجی لازم نیست، اما **کنسول پنل برای مشاهده نتیجه، تنظیم شبکه و رسیدگی به خطا لازم است**. در RAM هیچ SSH یا شبکه‌ای راه‌اندازی نمی‌شود.

**Experimental, disposable/rebuildable VPS only. Real boot has not been verified.** Staging copies the running kernel and builds a standalone gzip/newc initramfs. A one-shot GRUB entry boots into RAM. No provider Rescue/ISO is required, but an independent console is required for evidence, recovery and RouterOS network/password setup. The RAM environment has no SSH or network service.

## محدوده اولیه / Initial scope

- KVM/QEMU, x86-64, legacy BIOS; not UEFI or VMware for this first RAM revision.
- Exactly one disk named `/dev/vd…`, writable, non-removable, 512-byte logical sectors.
- Root is a direct ext4 partition of that disk; `/boot` is on the same filesystem. No RAID/LVM, separate `/boot`, active swap or additional disks.
- Matching `/boot/vmlinuz-$(uname -r)` and kernel config. Required features must be built-in (`=y`), not modules: initrd/gzip, devtmpfs, ELF/script executables and VirtIO PCI/block.
- Static BusyBox with required applets, binutils/readelf, GRUB tools and Python 3.
- At least 1 GiB available RAM for preflight. Actual preparation requires 768 MiB + three times extracted image size; free `/boot` must exceed image size + 128 MiB.
- A working GRUB environment/one-shot loader is required. Static checks cannot prove firmware behavior; **run the probe first**.

اطلاعات تولیدی IP/Prefix/Gateway/MAC را قبل از نصب یادداشت کنید؛ شبکه خودکار منتقل نمی‌شود. فایروال ارائه‌دهنده را قبل از بوت CHR محدود کنید. هیچ رمز عبوری در فایل‌های Stage ذخیره نمی‌شود.

Record production IP/prefix/gateway/MAC and restrict the provider firewall before CHR boots. No passwords are stored in staging. The disk fingerprint uses path, exact size and SHA256 of its first sector; it is a change detector, not globally unique hardware identity. Multiple disks are rejected.

## ۱. دریافت نسخه / Fetch the branch

If you already cloned the testing branch, update without overwriting local edits:

```bash
cd /root/Mikrotik-Ubuntu-test
git pull --ff-only
```

Install missing prerequisites only, then run the read-only check:

```bash
apt-get update
apt-get install -y busybox-static binutils
bash ram-install.sh --check --disk /dev/vda
```

`--check` does not download an image or change files, boot settings or the target disk. A pass is not a successful boot test. If it fails, do not bypass the condition; send sanitized output.

## ۲. تست بوت بدون پاک‌کردن / Non-writing RAM probe

```bash
bash ram-install.sh --prepare-probe --disk /dev/vda
```

Confirmation:

```text
PREPARE RAM PROBE
```

این مرحله در `/boot` فایل می‌سازد و یک گزینه به GRUB اضافه می‌کند؛ دیسک را به‌صورت خام نمی‌نویسد، بوت پیش‌فرض را تغییر نمی‌دهد و ریبوت نمی‌کند. قبل از مرحله بعد کنسول پنل را باز کنید. نبود کنسول را با دادن Flag پنهان نکنید.

This writes staging files and adds a GRUB entry, but leaves the default boot unchanged and does not reboot. Open the provider console before arming.

```bash
bash ram-install.sh --arm --console-ready
```

Type `ARM RAM PROBE`. **Only after checking the confirmation output**, manually reboot:

```bash
systemctl reboot
```

SSH قطع می‌شود. در کنسول باید `DIGITALVPS RAM PROBE PASS` دیده شود؛ سپس پس از ۳۰ ثانیه سرور دوباره ریبوت می‌شود و باید به Ubuntu برگردد. در Probe هیچ آرشیو CHR وجود ندارد و مسیر نوشتن اجرا نمی‌شود. اگر خطا دیده شود، برنامه در کنسول متوقف می‌ماند. برگشت موفق Ubuntu به‌تنهایی اثبات ورود به RAM نیست؛ پیام کنسول را ثبت کنید.

SSH disconnects. Record `DIGITALVPS RAM PROBE PASS` in the console; it waits 30 seconds and reboots back to the normal boot entry. Failure stops in RAM for console inspection. Returning to Ubuntu alone is not proof that the RAM entry ran. A working GRUB one-shot reset is part of this test.

After returning to Ubuntu, remove only the probe artifacts:

```bash
bash ram-install.sh --cancel
```

## ۳. آماده‌سازی نصب واقعی / Prepare the destructive install

**Only after a successful probe, off-server backup and explicit acceptance of erasing this VPS.** Choose an exact release and supply a trusted SHA256 of the official x86-64 RAW **ZIP** (not the IMG). There is no checksum bypass. See the checksum discussion in the main README.

```bash
bash ram-install.sh --prepare --disk /dev/vda \
  --version 7.23.5 --sha256 REPLACE_WITH_TRUSTED_ZIP_SHA256
```

`7.23.5` is an example, not a current-version guarantee. You can omit `--sha256` to be prompted for the trusted hash, not to disable verification. Type the requested `PREPARE RAM INSTALL /dev/vda 7.23.5` phrase. The image is downloaded and verified BEFORE scheduling any reboot. Preparation checks RAM/space, kernel/disk identity and GRUB syntax.

When prepared, open the console and arm:

```bash
bash ram-install.sh --arm --console-ready
```

Destructive authorization phrase for this example:

```text
ERASE /dev/vda INSTALL 7.23.5 ON NEXT BOOT
```

**از این لحظه ریبوت بعدی نصب مخرب را شروع می‌کند.** اگر آماده نیستید `--cancel` را اجرا کنید؛ در غیر این صورت ریبوت را خودتان انجام دهید:

```bash
systemctl reboot
```

**The next reboot is now destructive.** In RAM, the script checks PID 1, disk presence/size/sector/first-sector fingerprint, no extra disks/holders/swap/block mounts, then the image hash and size. It clears the disk's final 1 MiB to remove stale backup GPT, writes CHR, syncs and verifies the image range. Successful verification triggers a reboot after 15 seconds. Failure stops without reboot; after a partial write there is no rollback, so use panel rebuild/restore.

This first RAM writer relies on being the only userspace writer in its minimal initramfs; unlike the Python offline path, it does not claim `O_EXCL` block-device locking. It does not securely erase remaining old data. Successful read-back is not proof of RouterOS boot/networking.

## لغو قبل از ریبوت / Cancel before reboot

```bash
bash ram-install.sh --cancel
```

Removes this tool's staging directory and GRUB hook, regenerates GRUB from current other scripts, and clears this tool's pending one-shot entry if set. It refuses to clear another tool's next-entry value. This is not rollback after installing CHR. Do not manually delete `/boot` or GRUB files.

## آزمون‌های محلی / Local tests

```bash
bash -n script.sh install.sh ram-install.sh ram-init.sh.in
python3 -m unittest discover -s tests -v
```

Automated coverage includes newc headers/alignment, file types/console device, synthetic initramfs contents, shell syntax, interpolation validation and guard ordering. These tests do **not** emulate a kernel, GRUB, BusyBox PID 1 execution or real disk writes. Follow the probe on a disposable VM before attempting installation.

## منابع / References

- [Linux initramfs format](https://docs.kernel.org/driver-api/early-userspace/buffer-format.html)
- [Linux rootfs and initramfs](https://docs.kernel.org/filesystems/ramfs-rootfs-initramfs.html)
- [DigitalVPS client portal](https://client.digitalvps.ir/)

No website content, provider boot settings or actual VPS disk has been changed by publishing this code.
