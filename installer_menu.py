#!/usr/bin/env python3
"""One entry point for the offline and experimental RAM installation paths."""
from pathlib import Path
import subprocess
import sys
from chr_installer import InstallError, disk_candidates, version_value

ROOT = Path(__file__).resolve().parent


def launch(method, arguments):
    target = {"offline": "chr_installer.py", "ram": "ram_installer.py"}[method]
    return subprocess.run([sys.executable, str(ROOT / target), *arguments], check=False).returncode


def prompt(label):
    value = input(label + ": ").strip()
    if not value:
        raise ValueError("مقدار خالی مجاز نیست / A value is required.")
    return value


def console_ack():
    print("کنسول مستقل پنل و امکان بازیابی آماده است؟ RAM دسترسی SSH ندارد.")
    if input("Independent console/recovery ready? Type yes: ").strip() != "yes":
        raise ValueError("لغو شد / Console readiness was not confirmed.")
    return ["--console-ready"]


VERSION_CHOICES = ("7.23.5", "7.14.3", "7.9", "7.7", "6.49.15", "6.49.13")


def choose_version():
    print("نسخه‌های قابل انتخاب / Version presets:")
    for number, version in enumerate(VERSION_CHOICES, 1):
        label = "official download-page snapshot: 2026-09-09" if number == 1 else "legacy / قدیمی؛ بررسی امنیتی لازم است"
        print(f"{number}) {version} — {label}")
    print("0) نسخه دلخواه / Custom exact version")
    print("فهرست ثابت است؛ جدیدترین نسخه را تضمین نمی‌کند. موجودبودن دانلود هنگام اجرا بررسی می‌شود.")
    choice = input("Version [1]: ").strip() or "1"
    if choice == "0":
        return version_value(prompt("Exact RouterOS version"))
    if not choice.isdigit() or not 1 <= int(choice) <= len(VERSION_CHOICES):
        raise ValueError("Invalid version selection.")
    return VERSION_CHOICES[int(choice) - 1]


def choose_disk(method):
    eligible, rejected = disk_candidates(method)
    for disk, reason in rejected:
        print(f"Unavailable: {disk.get('path')} — {reason}")
    if not eligible:
        raise ValueError("No eligible disk. Mounted system disks need the RAM path; never remove disk guards.")
    for number, disk in enumerate(eligible, 1):
        print(f"{number}) {disk['path']} | {int(disk['size']) / (1024 ** 3):.1f} GiB | "
              f"{disk.get('model') or '-'} | serial: {disk.get('serial') or '-'}")
    if len(eligible) == 1:
        print("تنها دیسک کاندید خودکار انتخاب شد؛ کنترل‌ها و تأیید نهایی همچنان اجرا می‌شوند.")
        return eligible[0]["path"]
    choice = prompt("Disk number (no default)")
    if not choice.isdigit() or not 1 <= int(choice) <= len(eligible):
        raise ValueError("Invalid disk selection.")
    return eligible[int(choice) - 1]["path"]


def image_options():
    print("SHA256 خودکار از دانلود HTTPS رسمی محاسبه می‌شود؛ مقدار دستی لازم نیست.")
    return ["--version", choose_version()]


def menu():
    print("\nDigitalVPS | نصب MikroTik CHR")
    print("1) نصب روی دیسک آفلاین / Rescue or Live")
    print("2) نصب با بوت از RAM / Without provider Rescue (experimental)")
    print("0) خروج / Exit")
    method = prompt("انتخاب / Choice")
    if method == "0":
        return 0
    if method == "1":
        print("1) بررسی بدون نوشتن / Dry-run\n2) نصب مخرب / Install\n0) خروج / Exit")
        action = prompt("انتخاب / Choice")
        if action == "0":
            return 0
        if action not in {"1", "2"}:
            raise ValueError("انتخاب نامعتبر / Invalid choice.")
        args = ["--disk", choose_disk("offline")] + image_options()
        args += ["--dry-run"] if action == "1" else console_ack()
        return launch("offline", args)
    if method == "2":
        print("1) بررسی پیش‌نیازها / Read-only check")
        print("2) آماده‌سازی تست بوت بدون پاک‌کردن / Prepare RAM probe")
        print("3) آماده‌سازی نصب واقعی / Prepare destructive install")
        print("4) زمان‌بندی بوت آماده‌شده / Arm prepared boot")
        print("5) لغو و حذف آماده‌سازی / Cancel staging")
        print("0) خروج / Exit")
        action = prompt("انتخاب / Choice")
        if action == "0":
            return 0
        flags = {"1": "--check", "2": "--prepare-probe", "3": "--prepare", "4": "--arm", "5": "--cancel"}
        if action not in flags:
            raise ValueError("انتخاب نامعتبر / Invalid choice.")
        args = [flags[action]]
        if action in {"1", "2", "3"}:
            args += ["--disk", choose_disk("ram")]
        if action == "3":
            args += image_options()
        if action == "4":
            print("پس از Arm، ریبوت بعدی وارد مرحله آماده‌شده می‌شود؛ حالت Install دیسک را پاک می‌کند.")
            args += console_ack()
        if action == "5":
            if input("Remove this tool's RAM staging and GRUB entry? Type yes: ").strip() != "yes":
                raise ValueError("لغو شد / Cancel not confirmed.")
        return launch("ram", args)
    raise ValueError("انتخاب نامعتبر / Invalid choice.")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        if not sys.stdin.isatty():
            print("Interactive terminal required for menu. Use --method ram/offline with explicit options, or --help.", file=sys.stderr)
            return 2
        return menu()
    method = "offline"
    if arguments[0] == "--method":
        if len(arguments) < 2 or arguments[1] not in {"offline", "ram"}:
            raise ValueError("Use --method offline or --method ram before backend options.")
        method = arguments[1]
        arguments = arguments[2:] or ["--help"]
    if arguments == ["--help"] or arguments == ["-h"]:
        print("Menu: bash script.sh (interactive)\nDirect: bash script.sh --method ram|offline [options]", flush=True)
    return launch(method, arguments)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (InstallError, OSError, ValueError, EOFError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
