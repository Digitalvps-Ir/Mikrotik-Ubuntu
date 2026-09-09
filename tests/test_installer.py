"""Offline safety tests. Never open real block devices or contact a network."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "chr_installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def inventory():
    return {"blockdevices": [{
        "path": "/dev/vda", "type": "disk", "size": 4 * 1024 * installer.MIB,
        "ro": False, "rm": False, "log-sec": 512, "mountpoints": [None],
        "maj:min": "252:0", "model": "test", "serial": "test-1", "fstype": None,
        "children": [{"path": "/dev/vda1", "type": "part", "mountpoints": [None],
                      "fstype": "ext4", "maj:min": "252:1"}]}]}


class ArgumentsTests(unittest.TestCase):
    def test_numeric_versions(self):
        for value in ("6.49.15", "7.14.3", "7.23.5", "7.7"):
            self.assertEqual(installer.version_value(value), value)

    def test_reject_version_injection(self):
        for value in ("latest", "../7.1", "7.1;reboot", "7.1\n", "https://other", "8.1", "7.23rc1", ""):
            with self.subTest(value=value), self.assertRaises(installer.InstallError):
                installer.version_value(value)

    def test_digest_validation(self):
        self.assertEqual(installer.digest_value("A" * 64), "a" * 64)
        for value in ("a" * 63, "g" * 64, "a" * 65, "a" * 64 + "\n"):
            with self.assertRaises(installer.InstallError):
                installer.digest_value(value)

    def test_official_url_only(self):
        self.assertEqual(installer.image_url("7.14.3"),
                         "https://download.mikrotik.com/routeros/7.14.3/chr-7.14.3.img.zip")

    def test_both_entrypoints_help(self):
        for path in ("script.sh", "install.sh"):
            result = subprocess.run(["bash", str(ROOT / path), "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--dry-run", result.stdout)

    def test_no_arguments_fail_closed(self):
        result = subprocess.run(["bash", str(ROOT / "script.sh")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


class InventoryTests(unittest.TestCase):
    def validate(self, value):
        return installer.validate_inventory(value, "/dev/vda")

    def test_unused_disk_accepted(self):
        self.assertEqual(self.validate(inventory())["path"], "/dev/vda")

    def test_other_disk_mounts_do_not_block_target(self):
        data = inventory()
        root = copy.deepcopy(data["blockdevices"][0])
        root["path"] = "/dev/vdb"
        root["mountpoints"] = ["/"]
        data["blockdevices"].append(root)
        self.validate(data)

    def test_root_or_child_mounts_rejected(self):
        for location in ("root", "child"):
            for mount in ("/", "/boot", "/mnt", "[SWAP]"):
                data = inventory()
                disk = data["blockdevices"][0]
                node = disk if location == "root" else disk["children"][0]
                node["mountpoints"] = [mount]
                with self.subTest(location=location, mount=mount), self.assertRaises(installer.InstallError):
                    self.validate(data)

    def test_unsafe_disk_attributes(self):
        for key, value in (("type", "part"), ("type", "loop"), ("ro", True), ("rm", True),
                           ("log-sec", 4096), ("size", 512), ("ro", None)):
            data = inventory()
            data["blockdevices"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(installer.InstallError):
                self.validate(data)

    def test_complex_filesystems_rejected(self):
        for fs in ("LVM2_member", "linux_raid_member", "zfs_member", "crypto_LUKS", "btrfs"):
            data = inventory()
            data["blockdevices"][0]["children"][0]["fstype"] = fs
            with self.subTest(fs=fs), self.assertRaises(installer.InstallError):
                self.validate(data)

    def test_mapper_child_rejected(self):
        data = inventory()
        data["blockdevices"][0]["children"][0]["type"] = "crypt"
        with self.assertRaises(installer.InstallError):
            self.validate(data)

    def test_missing_mount_information_rejected(self):
        data = inventory()
        del data["blockdevices"][0]["mountpoints"]
        with self.assertRaises(installer.InstallError):
            self.validate(data)

    def test_absent_or_ambiguous_disk_rejected(self):
        for nodes in ([], inventory()["blockdevices"] * 2):
            with self.assertRaises(installer.InstallError):
                self.validate({"blockdevices": nodes})

    def test_path_validation_before_any_device_lookup(self):
        for value in ("/", "/dev/vda1", "/dev/mapper/root", "/dev/disk/by-id/x", "/tmp/file", "/dev/vda /dev/vdb"):
            with patch.object(installer.os, "lstat") as lookup, self.assertRaises(installer.InstallError):
                installer.check_target(value)
            lookup.assert_not_called()

    def test_symlink_or_regular_file_rejected(self):
        for mode in (stat.S_IFREG, stat.S_IFLNK):
            with patch.object(installer.os, "lstat", return_value=Mock(st_mode=mode)), self.assertRaises(installer.InstallError):
                installer.check_target("/dev/vda")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.archive = self.folder / "chr.zip"
        self.image = self.folder / "chr.img"
        self.payload = b"\0" * 510 + b"\x55\xaa" + b"x" * (installer.MIB - 512)

    def bundle(self, name="chr-7.14.3.img", payload=None, extra=False, symlink=False):
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, self.payload if payload is None else payload)
            if extra:
                bundle.writestr("other.txt", "unexpected")
        return installer.sha256_file(self.archive)

    def extract(self, digest):
        return installer.extract_verified(self.archive, self.image, "7.14.3", digest)

    def test_valid_zip_and_hash(self):
        result = self.extract(self.bundle())
        self.assertEqual(result, hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(self.image.read_bytes(), self.payload)

    def test_wrong_hash_never_creates_image(self):
        self.bundle()
        with self.assertRaises(installer.InstallError):
            self.extract("0" * 64)
        self.assertFalse(self.image.exists())

    def test_traversal_or_wrong_name_rejected(self):
        for name in ("../chr-7.14.3.img", "/chr-7.14.3.img", "chr-6.49.15.img"):
            with self.subTest(name=name), self.assertRaises(installer.InstallError):
                self.extract(self.bundle(name=name))

    def test_multiple_members_rejected(self):
        with self.assertRaises(installer.InstallError):
            self.extract(self.bundle(extra=True))

    def test_symlink_member_rejected(self):
        with self.assertRaises(installer.InstallError):
            self.extract(self.bundle(symlink=True))

    def test_small_image_rejected(self):
        with self.assertRaises(installer.InstallError):
            self.extract(self.bundle(payload=b"tiny"))

    def test_invalid_boot_signature_rejected(self):
        with self.assertRaises(installer.InstallError):
            self.extract(self.bundle(payload=b"0" * installer.MIB))

    def test_disk_space_failure(self):
        digest = self.bundle()
        with patch.object(installer.shutil, "disk_usage", return_value=Mock(free=0)), self.assertRaises(installer.InstallError):
            self.extract(digest)

    def test_corrupt_archive(self):
        self.archive.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            self.extract(installer.sha256_file(self.archive))


class WriteTests(unittest.TestCase):
    def test_readback_mismatch_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "source.img"
            image.write_bytes(b"A" * installer.MIB)
            target = Path(folder) / "target.bin"
            target.write_bytes(b"Z" * (4 * installer.MIB))
            with target.open("r+b") as out, patch("sys.stdout", new=io.StringIO()), self.assertRaises(installer.InstallError):
                installer.copy_and_verify(image, out.fileno(), 4 * installer.MIB, "0" * 64)

    def test_exclusive_open_and_descriptor_closed_on_write_failure(self):
        original = dict(inventory()["blockdevices"][0], device_number=123)
        with patch.object(installer, "check_target", return_value=original), \
                patch.object(installer, "sha256_file", return_value="good"), \
                patch.object(installer.os, "open", return_value=999) as opening, \
                patch.object(installer.os, "fstat", return_value=Mock(st_mode=stat.S_IFBLK, st_rdev=123)), \
                patch.object(installer.os, "close") as closing, \
                patch.object(installer, "copy_and_verify", side_effect=OSError("I/O error")):
            with self.assertRaises(OSError):
                installer.deploy(Path("unused"), "/dev/vda", original, "good")
        self.assertTrue(opening.call_args.args[1] & os.O_EXCL)
        closing.assert_called_once_with(999)

    def test_regular_file_surrogate_copy_and_tail_cleanup(self):
        # Only this low-level helper is exercised on a regular tempfile.
        # The public installer rejects regular files before reaching this helper.
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "source.img"
            image.write_bytes(os.urandom(installer.MIB))
            target = Path(folder) / "target.bin"
            target.write_bytes(b"Z" * (4 * installer.MIB))
            with target.open("r+b") as out, patch("sys.stdout", new=io.StringIO()):
                installer.copy_and_verify(image, out.fileno(), 4 * installer.MIB, installer.sha256_file(image))
            result = target.read_bytes()
            self.assertEqual(result[:installer.MIB], image.read_bytes())
            self.assertEqual(result[installer.MIB:3 * installer.MIB], b"Z" * (2 * installer.MIB))
            self.assertEqual(result[-installer.MIB:], b"\0" * installer.MIB)

    def test_too_small_target_fails_before_write(self):
        image = Mock()
        image.stat.return_value.st_size = installer.MIB
        with patch.object(installer.os, "write") as write, self.assertRaises(installer.InstallError):
            installer.copy_and_verify(image, 999, installer.MIB, "0" * 64)
        write.assert_not_called()

    def test_short_writes_are_completed(self):
        with patch.object(installer.os, "write", side_effect=[2, 1, 1]) as write:
            installer.write_all(999, b"abcd")
        self.assertEqual([call.args[1] for call in write.call_args_list], [b"abcd", b"cd", b"d"])

    def test_zero_write_fails(self):
        with patch.object(installer.os, "write", return_value=0), self.assertRaises(installer.InstallError):
            installer.write_all(999, b"abc")

    def test_changed_target_never_opened(self):
        original = inventory()["blockdevices"][0]
        other = dict(original, serial="different")
        with patch.object(installer, "check_target", return_value=other), patch.object(installer.os, "open") as opening:
            with self.assertRaises(installer.InstallError):
                installer.deploy(Path("unused"), "/dev/vda", original, "unused")
        opening.assert_not_called()

    def test_corrupt_image_never_opens_target(self):
        original = inventory()["blockdevices"][0]
        with patch.object(installer, "check_target", return_value=original), \
                patch.object(installer, "sha256_file", return_value="bad"), \
                patch.object(installer.os, "open") as opening:
            with self.assertRaises(installer.InstallError):
                installer.deploy(Path("unused"), "/dev/vda", original, "good")
        opening.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def test_download_restricts_origin_and_redirects(self):
        target = Mock()
        target.stat.return_value.st_size = 100
        with patch.object(installer, "run") as run:
            installer.download_archive("7.14.3", target)
        args = run.call_args.args
        self.assertIn("--fail", args)
        self.assertIn("--max-filesize", args)
        self.assertNotIn("--location", args)
        self.assertNotIn("-L", args)
        self.assertEqual(args[-1], installer.image_url("7.14.3"))

    def test_nonroot_refused(self):
        with patch.object(installer.os, "geteuid", return_value=1000), self.assertRaises(installer.InstallError):
            installer.check_host()

    def test_full_workflow_calls_confirm_before_deploy(self):
        events = []
        original = inventory()["blockdevices"][0]
        def extract(archive, image, version, digest):
            image.write_bytes(b"fixture")
            return "fixture-digest"
        with patch.object(installer, "check_host"), patch.object(installer, "check_target", return_value=original), \
                patch.object(installer, "download_archive"), patch.object(installer, "archive_reference", return_value="a" * 64), \
                patch.object(installer, "extract_verified", side_effect=extract), \
                patch.object(installer, "confirm", side_effect=lambda *a: events.append("confirm")), \
                patch.object(installer, "deploy", side_effect=lambda *a: events.append("deploy")), \
                patch("sys.stdout", new=io.StringIO()) as output:
            installer.main(["--version", "7.14.3", "--disk", "/dev/vda", "--sha256", "a" * 64, "--console-ready"])
        self.assertEqual(events, ["confirm", "deploy"])
        self.assertIn("NOT been verified", output.getvalue())

    def test_check_target_active_swap_fails_closed(self):
        data = inventory()
        for node in installer.flatten(data["blockdevices"]):
            node["mountpoint"] = None
            del node["mountpoints"]
        with patch.object(installer.os, "lstat", return_value=Mock(st_mode=stat.S_IFBLK, st_rdev=123)), \
                patch.object(installer, "run", side_effect=[json.dumps(data), "/swapfile\n"]) as command, \
                self.assertRaisesRegex(installer.InstallError, "Active swap"):
            installer.check_target("/dev/vda")
        self.assertNotIn("--json", command.call_args.args)
        self.assertIn("--tree", command.call_args_list[0].args)

    def test_check_target_missing_identity_fails_closed(self):
        data = inventory()
        for node in installer.flatten(data["blockdevices"]):
            node["mountpoint"] = None
            del node["mountpoints"]
        del data["blockdevices"][0]["maj:min"]
        with patch.object(installer.os, "lstat", return_value=Mock(st_mode=stat.S_IFBLK, st_rdev=123)), \
                patch.object(installer, "run", side_effect=[json.dumps(data), ""]), \
                self.assertRaisesRegex(installer.InstallError, "identity"):
            installer.check_target("/dev/vda")

    def test_real_linux_read_only_command_syntax(self):
        # Real commands, read-only. Confirm the supported column/flag spelling.
        if not installer.shutil.which("lsblk") or not installer.shutil.which("swapon"):
            self.skipTest("util-linux is not available")
        data = json.loads(installer.run("lsblk", "--json", "--bytes", "--paths", "--tree", "--output",
                                       "PATH,TYPE,SIZE,RO,RM,LOG-SEC,MOUNTPOINT,FSTYPE,MAJ:MIN,MODEL,SERIAL"))
        self.assertIn("blockdevices", data)
        installer.run("swapon", "--show", "--noheadings", "--raw", "--output", "NAME")

    def test_confirmation_requires_tty_and_exact_target(self):
        with patch.object(installer.sys.stdin, "isatty", return_value=False), self.assertRaises(installer.InstallError):
            installer.confirm("/dev/vda", "7.14.3")
        with patch.object(installer.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value="ERASE /dev/vdb INSTALL 7.14.3"), \
                patch("sys.stdout", new=io.StringIO()), self.assertRaises(installer.InstallError):
            installer.confirm("/dev/vda", "7.14.3")

    def test_dry_run_never_calls_confirmation_or_deploy(self):
        original = inventory()["blockdevices"][0]
        def extract(archive, image, version, digest):
            image.write_bytes(b"fixture")
            return "fixture-digest"
        with patch.object(installer, "check_host"), patch.object(installer, "check_target", return_value=original), \
                patch.object(installer, "download_archive"), patch.object(installer, "archive_reference", return_value="a" * 64), \
                patch.object(installer, "extract_verified", side_effect=extract), \
                patch.object(installer, "confirm") as confirm, patch.object(installer, "deploy") as deploy, \
                patch("sys.stdout", new=io.StringIO()) as output:
            result = installer.main(["--version", "7.14.3", "--disk", "/dev/vda", "--sha256", "a" * 64, "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("no target writes", output.getvalue())
        confirm.assert_not_called()
        deploy.assert_not_called()

    def test_no_console_ack_fails_before_host_checks(self):
        with patch.object(installer, "check_host") as host, self.assertRaises(installer.InstallError):
            installer.main(["--version", "7.14.3", "--disk", "/dev/vda", "--sha256", "a" * 64])
        host.assert_not_called()

    def test_failed_download_no_deploy_and_temp_removed(self):
        created = []
        def failing_download(version, path):
            created.append(path.parent)
            path.write_bytes(b"partial")
            raise installer.InstallError("download failed")
        with patch.object(installer, "check_host"), \
                patch.object(installer, "check_target", return_value=inventory()["blockdevices"][0]), \
                patch.object(installer, "download_archive", side_effect=failing_download), \
                patch.object(installer, "deploy") as deploy, patch("sys.stdout", new=io.StringIO()):
            with self.assertRaises(installer.InstallError):
                installer.main(["--version", "7.14.3", "--disk", "/dev/vda", "--sha256", "a" * 64, "--dry-run"])
        deploy.assert_not_called()
        self.assertFalse(created[0].exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
