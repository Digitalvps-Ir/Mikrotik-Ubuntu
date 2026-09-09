"""Small documentation contract checks; no external requests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_local_links_exist(self):
        for name in ("README.md", "README.en.md", "docs/TESTING.md"):
            path = ROOT / name
            text = path.read_text()
            for link in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in link and not link.startswith("#"):
                    self.assertTrue((path.parent / link.split("#")[0]).exists(), (name, link))

    def test_both_languages_document_all_options_and_warnings(self):
        for name in ("README.md", "README.en.md"):
            text = (ROOT / name).read_text()
            for option in ("--version", "--disk", "--sha256", "--dry-run", "--console-ready"):
                self.assertIn(option, text)
            for link in ("https://client.digitalvps.ir/", "https://client.digitalvps.ir/store/mikrotik-vps",
                         "https://client.digitalvps.ir/knowledgebase", "https://client.digitalvps.ir/supporttickets.php"):
                self.assertIn(link, text)
            self.assertIn("REPLACE_WITH_TRUSTED_ZIP_SHA256", text)
            self.assertIn("allow-remote-requests=no", text)
            self.assertNotIn("allow-remote-requests=yes", text)
            self.assertEqual(text.count("```" ) % 2, 0)

    def test_farsi_toc_anchors_exist(self):
        text = (ROOT / "README.md").read_text()
        for anchor in re.findall(r"\]\(#([^)]+)\)", text):
            self.assertIn(f'id="{anchor}"', text)


if __name__ == "__main__":
    unittest.main()
