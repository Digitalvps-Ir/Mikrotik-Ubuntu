"""RAM-path tests: synthetic archive, mocks and shell syntax; never boot/write disks."""
import gzip
import importlib.util
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ram_installer as ram


def info():
    return {"disk": "/dev/vda", "disk_size": 50 * 1024 * ram.MIB, "mbr_sha256": "a" * 64,
            "boot_uuid": "1234-abcd", "kernel": "6.8.0-111-generic"}


def read_cpio(data):
    result = {}
    offset = 0
    while offset < len(data):
        assert data[offset:offset + 6] == b"070701"
        fields = [int(data[offset + 6 + n * 8:offset + 14 + n * 8], 16) for n in range(13)]
        offset += 110
        name = data[offset:offset + fields[11] - 1].decode()
        offset += fields[11]
        offset = (offset + 3) & ~3
        payload = data[offset:offset + fields[6]]
        offset += fields[6]
        offset = (offset + 3) & ~3
        if name == "TRAILER!!!":
            return result
        result[name] = (fields, payload)
    raise AssertionError("Missing CPIO trailer")


class RamTests(unittest.TestCase):
    def test_builtin_kernel_required(self):
        text = "\n".join("CONFIG_" + name + "=y" for name in ram.REQUIRED_CONFIG)
        ram.validate_kernel_config(text)
        for value in ("m", "n"):
            with self.assertRaises(ram.InstallError):
                ram.validate_kernel_config(text.replace("CONFIG_VIRTIO_BLK=y", "CONFIG_VIRTIO_BLK=" + value))

    def test_missing_kernel_config(self):
        with self.assertRaises(ram.InstallError):
            ram.validate_kernel_config("")

    def test_grub_uuid_injection_rejected(self):
        for uuid in ("$(reboot)", "abc\nreboot", "abc'", "../abc"):
            with self.assertRaises(ram.InstallError):
                ram.grub_entry(uuid)

    def test_grub_entry_has_no_root_mount(self):
        value = ram.grub_entry("1234-abcd")
        self.assertIn("rdinit=/init", value)
        self.assertNotIn(" root=/dev/", value)
        self.assertIn("--id digitalvps-chr-ram", value)

    def test_bad_disk_rejected_in_template(self):
        value = dict(info(), disk="/dev/vda;reboot")
        with self.assertRaises(ram.InstallError):
            ram.render_init(value, True)

    def test_bad_hash_rejected_in_template(self):
        with self.assertRaises(ram.InstallError):
            ram.render_init(info(), False, "bad", ram.MIB)

    def test_probe_branch_exits_before_writer(self):
        value = ram.render_init(info(), True).decode()
        self.assertIn("if [ 'probe' = probe ]", value)
        self.assertLess(value.index("RAM PROBE PASS"), value.index("STARTING IRREVERSIBLE"))
        self.assertLess(value.index('fail "reboot failed"'), value.index('dd if=/chr.img'))
        self.assertNotIn("@DISK@", value)

    def test_installer_checks_before_write(self):
        value = ram.render_init(info(), False, "b" * 64, ram.MIB).decode()
        writer = value.index("dd if=/dev/zero")
        for text in ("disk size changed", "disk boot-sector fingerprint changed", "active disk holder", "RAM image SHA256 mismatch"):
            self.assertLess(value.index(text), writer)
        self.assertGreater(value.index("read-back SHA256 mismatch"), writer)

    def test_probe_and_install_shell_syntax(self):
        for probe in (True, False):
            value = ram.render_init(info(), probe, "b" * 64, ram.MIB)
            result = subprocess.run(["bash", "-n"], input=value, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cpio_alignment_modes_and_streamed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            busybox = folder / "busybox"
            busybox.write_bytes(b"synthetic-busybox")
            image = folder / "chr.img"
            image.write_bytes(b"abcde" * 19)
            output = folder / "ram.gz"
            ram.build_initramfs(output, busybox, b"#!/bin/sh\nexit 0\n", image)
            entries = read_cpio(gzip.decompress(output.read_bytes()))
            self.assertEqual(entries["chr.img"][1], image.read_bytes())
            self.assertEqual(entries["bin/sh"][1], b"busybox")
            self.assertEqual(stat.S_IFMT(entries["bin/sh"][0][1]), stat.S_IFLNK)
            self.assertEqual(entries["dev/console"][0][9:11], [5, 1])
            self.assertEqual(stat.S_IFMT(entries["dev/console"][0][1]), stat.S_IFCHR)
            self.assertEqual(stat.S_IFMT(entries["init"][0][1]), stat.S_IFREG)

    def test_probe_archive_has_no_image(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            busybox = folder / "busybox"
            busybox.write_bytes(b"fixture")
            out = folder / "ram.gz"
            ram.build_initramfs(out, busybox, ram.render_init(info(), True))
            self.assertNotIn("chr.img", read_cpio(gzip.decompress(out.read_bytes())))

    def test_cpio_traversal_rejected(self):
        with self.assertRaises(ram.InstallError):
            ram.cpio_entry(io.BytesIO(), "../bad", stat.S_IFREG | 0o600)

    def test_check_mode_never_prepares_or_arms(self):
        with patch.object(ram.os, "geteuid", return_value=0), patch.object(ram, "preflight", return_value=info()), \
                patch.object(ram, "prepare") as prepare, patch.object(ram, "arm") as arm, \
                patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(ram.main(["--check", "--disk", "/dev/vda"]), 0)
        prepare.assert_not_called()
        arm.assert_not_called()

    def test_no_console_cannot_arm(self):
        with self.assertRaises(ram.InstallError):
            ram.arm(Mock(console_ready=False))

    def test_confirmation_refuses_piped_input(self):
        with patch.object(ram.sys.stdin, "isatty", return_value=False), self.assertRaises(ram.InstallError):
            ram.confirm_text("ARM RAM PROBE")

    def test_nonroot_rejected_before_preflight(self):
        with patch.object(ram.os, "geteuid", return_value=1000), patch.object(ram, "preflight") as preflight:
            with self.assertRaises(ram.InstallError):
                ram.main(["--check"])
        preflight.assert_not_called()

    def test_help_entrypoint(self):
        result = subprocess.run(["bash", str(ROOT / "ram-install.sh"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--prepare-probe", result.stdout)

    def test_prepare_probe_stages_without_arming(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            busybox, kernel, config = root / "busybox", root / "vmlinuz", root / "grub.cfg"
            busybox.write_bytes(b"fixture-busybox")
            kernel.write_bytes(b"fixture-kernel")
            config.write_text("old boot config")
            state = dict(info(), busybox=str(busybox), kernel_path=str(kernel))
            args = Mock(prepare_probe=True, disk="/dev/vda", version=None)
            calls = []
            def fake_run(*argv):
                calls.append(argv)
                if argv[0] == "grub-mkconfig":
                    Path(argv[2]).write_text("menuentry digitalvps-chr-ram {}")
                return ""
            with patch.object(ram, "STAGE", root / "stage"), patch.object(ram, "HOOK", root / "hook"), \
                    patch.object(ram, "CONFIG", config), patch.object(ram, "preflight", return_value=state), \
                    patch.object(ram, "available_memory", return_value=2 * 1024 * ram.MIB), \
                    patch.object(ram, "confirm_text"), patch.object(ram, "run", side_effect=fake_run), \
                    patch.object(ram.os, "sync"), patch("sys.stdout", new=io.StringIO()):
                ram.prepare(args, state)
                manifest = ram.load_manifest()
                self.assertEqual(manifest["mode"], "probe")
                self.assertEqual((ram.STAGE / "grub.cfg.before").read_text(), "old boot config")
                self.assertNotIn("chr.img", read_cpio(gzip.decompress((ram.STAGE / "initramfs.gz").read_bytes())))
            self.assertNotIn("grub-reboot", [call[0] for call in calls])

    def test_prepare_validation_failure_keeps_old_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            busybox, kernel, config = root / "busybox", root / "vmlinuz", root / "grub.cfg"
            busybox.write_bytes(b"fixture")
            kernel.write_bytes(b"kernel")
            config.write_text("old boot config")
            state = dict(info(), busybox=str(busybox), kernel_path=str(kernel))
            def fail_check(*argv):
                if argv[0] == "grub-mkconfig":
                    Path(argv[2]).write_text("bad")
                else:
                    raise ram.InstallError("invalid GRUB syntax")
                return ""
            with patch.object(ram, "STAGE", root / "stage"), patch.object(ram, "HOOK", root / "hook"), \
                    patch.object(ram, "CONFIG", config), patch.object(ram, "preflight", return_value=state), \
                    patch.object(ram, "available_memory", return_value=2 * 1024 * ram.MIB), \
                    patch.object(ram, "confirm_text"), patch.object(ram, "run", side_effect=fail_check):
                with self.assertRaises(ram.InstallError):
                    ram.prepare(Mock(prepare_probe=True, disk="/dev/vda", version=None), state)
                self.assertFalse(ram.STAGE.exists())
                self.assertFalse(ram.HOOK.exists())
                self.assertEqual(config.read_text(), "old boot config")


if __name__ == "__main__":
    unittest.main()
