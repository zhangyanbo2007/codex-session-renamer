import re
import unittest
from pathlib import Path

from session_renamer import __version__


class VersionTest(unittest.TestCase):
    def test_release_version_is_consistent_across_metadata_and_docs(self):
        project_root = Path(__file__).resolve().parents[1]
        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        project_section = re.search(
            r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", pyproject
        )
        self.assertIsNotNone(project_section)
        version_match = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', project_section.group(1)
        )
        self.assertIsNotNone(version_match)
        project_version = version_match.group(1)

        self.assertEqual(__version__, project_version)
        self.assertIn(
            f"> Current version: v{project_version}",
            (project_root / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            f"> 当前版本：v{project_version}",
            (project_root / "README.zh-CN.md").read_text(encoding="utf-8"),
        )
        changelog = (project_root / "CHANGELOG.md").read_text(encoding="utf-8")
        first_release = re.search(r"(?m)^## v([^ ]+) - \d{4}-\d{2}-\d{2}$", changelog)
        self.assertIsNotNone(first_release)
        self.assertEqual(first_release.group(1), project_version)


if __name__ == "__main__":
    unittest.main()
