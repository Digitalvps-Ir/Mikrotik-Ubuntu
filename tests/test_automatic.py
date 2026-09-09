"""Automatic defaults must not turn ambiguous disks or bad hashes into success."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chr_installer as core
import installer_menu as ui
import ram_installer as ram


class AutomaticTests(unittest.TestCase):
    def test_computed_hash_is_not_claimed_as_vendor_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "download.zip"
            archive.write_bytes(b"official-download-fixture")
            with patch("sys.stdout", new=io.StringIO()) as output:
                actual = core.archive_reference(archive)
            self.assertEqual(actual, hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertIn("NOT an independent vendor checksum", output.getvalue())

    def test_supplied_hash_mismatch_still_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "download.zip"
            archive.write_bytes(b"fixture")
            with patch("sys.stdout", new=io.StringIO()), self.assertRaises(core.InstallError):
                core.archive_reference(archive, "0" * 64)

    def test_matching_supplied_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "download.zip"
            archive.write_bytes(b"fixture")
            digest = hashlib.sha256(b"fixture").hexdigest()
            with patch("sys.stdout", new=io.StringIO()) as output:
                self.assertEqual(core.archive_reference(archive, digest), digest)
            self.assertIn("matched the supplied", output.getvalue())

    def test_cli_disk_and_sha_can_be_omitted(self):
        args = core.parser().parse_args(["--version", "7.23.5", "--dry-run"])
        self.assertEqual(args.disk, "auto")
        self.assertIsNone(args.sha256)

    def test_sole_disk_auto_selected(self):
        disks = [{"path": "/dev/vda", "size": 50 * 1024 ** 3}]
        with patch.object(core, "disk_candidates", return_value=(disks, [])), patch("builtins.print"):
            self.assertEqual(core.auto_disk("offline"), "/dev/vda")

    def test_multiple_disks_never_auto_selected(self):
        disks = [{"path": "/dev/vda"}, {"path": "/dev/vdb"}]
        with patch.object(core, "disk_candidates", return_value=(disks, [])), self.assertRaises(core.InstallError):
            core.auto_disk("offline")

    def test_unsafe_disk_filtered_not_selected(self):
        disks = [{"path": "/dev/vda"}, {"path": "/dev/vdb"}]
        def check(path):
            if path == "/dev/vda":
                raise core.InstallError("mounted")
        with patch.object(core, "discover_disks", return_value=disks), patch.object(core, "check_target", side_effect=check):
            candidates, rejected = core.disk_candidates("offline")
        self.assertEqual(candidates, [{"path": "/dev/vdb"}])
        self.assertEqual(rejected[0][1], "mounted")

    def test_ram_multi_disk_still_rejected(self):
        with patch.object(core, "discover_disks", return_value=[{"path": "/dev/vda"}, {"path": "/dev/vdb"}]):
            self.assertEqual(core.disk_candidates("ram")[0], [])

    def test_multiple_disks_menu_requires_number(self):
        disks = [{"path": name, "size": 50 * 1024 ** 3} for name in ("/dev/vda", "/dev/vdb")]
        with patch.object(ui, "disk_candidates", return_value=(disks, [])), patch("builtins.print"), patch("builtins.input", return_value="2"):
            self.assertEqual(ui.choose_disk("offline"), "/dev/vdb")

    def test_version_preset_default(self):
        with patch("builtins.print"), patch("builtins.input", return_value=""):
            self.assertEqual(ui.choose_version(), ui.VERSION_CHOICES[0])

    def test_custom_version_validated(self):
        with patch("builtins.print"), patch("builtins.input", side_effect=["0", "7.14.3"]):
            self.assertEqual(ui.choose_version(), "7.14.3")
        with patch("builtins.print"), patch("builtins.input", side_effect=["0", "7.1;reboot"]), self.assertRaises(core.InstallError):
            ui.choose_version()

    def test_ram_check_uses_auto_disk_before_preflight(self):
        with patch.object(ram.os, "geteuid", return_value=0), patch.object(ram, "auto_disk", return_value="/dev/vda") as auto, \
                patch.object(ram, "preflight", return_value={}) as preflight, patch("builtins.print"):
            ram.main(["--check"])
        auto.assert_called_once_with("ram")
        preflight.assert_called_once_with("/dev/vda")


if __name__ == "__main__":
    unittest.main()
