"""Menu routing tests. Backends are mocked; no staging/disk operations."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installer_menu as ui


class MenuTests(unittest.TestCase):
    def choose(self, answers):
        disks = ([{"path": "/dev/vda", "size": 50 * 1024 ** 3}], [])
        with patch("builtins.input", side_effect=answers), patch("builtins.print"), \
                patch.object(ui, "disk_candidates", return_value=disks), patch.object(ui, "launch", return_value=0) as launch:
            ui.menu()
        return launch

    def test_ram_check(self):
        self.choose(["2", "1"]).assert_called_once_with("ram", ["--check", "--disk", "/dev/vda"])

    def test_ram_probe(self):
        self.choose(["2", "2"]).assert_called_once_with("ram", ["--prepare-probe", "--disk", "/dev/vda"])

    def test_ram_install_uses_version_menu_without_hash_prompt_or_arming(self):
        call = self.choose(["2", "3", "1"]).call_args.args
        self.assertEqual(call, ("ram", ["--prepare", "--disk", "/dev/vda", "--version", "7.23.5"]))

    def test_offline_dry_run(self):
        call = self.choose(["1", "1", "1"]).call_args.args
        self.assertEqual(call[0], "offline")
        self.assertIn("--dry-run", call[1])
        self.assertNotIn("--console-ready", call[1])

    def test_arm_requires_console_ack(self):
        with self.assertRaises(ValueError):
            self.choose(["2", "4", "no"])

    def test_exit_starts_no_backend(self):
        self.choose(["0"]).assert_not_called()

    def test_old_cli_still_routes_offline(self):
        with patch.object(ui, "launch", return_value=0) as launch:
            ui.main(["--dry-run", "--version", "7.23.5"])
        launch.assert_called_once_with("offline", ["--dry-run", "--version", "7.23.5"])

    def test_explicit_ram_cli(self):
        with patch.object(ui, "launch", return_value=0) as launch:
            ui.main(["--method", "ram", "--check", "--disk", "/dev/vda"])
        launch.assert_called_once_with("ram", ["--check", "--disk", "/dev/vda"])


if __name__ == "__main__":
    unittest.main()
