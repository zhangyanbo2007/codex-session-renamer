import os
import re
import subprocess
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ScriptReleaseTest(unittest.TestCase):
    def test_frp_script_contains_no_private_deployment_values(self):
        script = (PROJECT_DIR / "frp-tunnel.sh").read_text(encoding="utf-8")

        self.assertNotRegex(script, r"/home/[^/$\{]+/")
        public_ipv4 = re.compile(
            r"(?<![\d.])(?!(?:127|10|192\.168)\.)"
            r"(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"
        )
        self.assertIsNone(public_ipv4.search(script))
        self.assertNotRegex(script, r"node\d+-")

    def test_frp_validate_reports_missing_configuration(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "SESSION_RENAMER_ENV_FILE": "/nonexistent/session-renamer.env",
        }
        result = subprocess.run(
            ["bash", "frp-tunnel.sh", "validate"],
            cwd=PROJECT_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SESSION_RENAMER_FRP_CONFIG", result.stderr)


if __name__ == "__main__":
    unittest.main()
