import re
import unittest
from pathlib import Path

from session_renamer import __version__


class VersionTest(unittest.TestCase):
    def test_package_and_project_versions_match_release(self):
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

        self.assertEqual(__version__, "0.8.0")
        self.assertEqual(project_version, "0.8.0")
        self.assertEqual(__version__, project_version)


if __name__ == "__main__":
    unittest.main()
