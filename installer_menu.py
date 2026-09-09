#!/usr/bin/env python3
"""One entry point for the offline and experimental RAM installation paths."""
from pathlib import Path
import subprocess
import sys

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


def image_options():
    return ["--version", prompt("RouterOS version (e.g. 7.23.5)"),
            "--sha256", prompt("Trusted ZIP SHA256 (64 hex characters; not IMG)")]


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
        args = ["--disk", prompt("Whole disk (e.g. /dev/vda)")] + image_options()
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
            args += ["--disk", prompt("Whole disk (e.g. /dev/vda)")]
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
    except (ValueError, EOFError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
