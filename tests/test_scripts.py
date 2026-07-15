import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ScriptReleaseTest(unittest.TestCase):
    def make_fake_frp_environment(self, root: Path) -> dict[str, str]:
        config = root / "frpc.toml"
        config.write_text(
            '[[proxies]]\nname = "codex-session-renamer"\n',
            encoding="utf-8",
        )
        fake_bin = root / "bin"
        fake_bin.mkdir()
        for name, body in {
            "frpc": "#!/usr/bin/env bash\nexit 0\n",
            "curl": "#!/usr/bin/env bash\nexit 0\n",
            "pgrep": "#!/usr/bin/env bash\nexit 0\n",
            "lsof": "#!/usr/bin/env bash\nprintf '12345\\n'\n",
        }.items():
            path = fake_bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        return {
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "HOME": os.environ.get("HOME", ""),
            "SESSION_RENAMER_ENV_FILE": str(root / "missing.env"),
            "SESSION_RENAMER_FRP_CONFIG": str(config),
            "SESSION_RENAMER_PUBLIC_HOST": "example.test",
            "SESSION_RENAMER_PUBLIC_URL": "https://renamer.example.test",
        }

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

    def test_frp_status_treats_protected_public_401_as_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "frpc.toml"
            config.write_text("# test config\n", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "frpc").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "frpc").chmod(0o755)
            (fake_bin / "curl").write_text(
                """#!/usr/bin/env bash
has_fail=0
has_write=0
target=""
for arg in "$@"; do
  [[ "$arg" == *f* && "$arg" == -* ]] && has_fail=1
  [[ "$arg" == "-w" ]] && has_write=1
  [[ "$arg" == http* ]] && target="$arg"
done
if [[ "$target" == http://127.0.0.1:* ]]; then
  exit 7
fi
if [[ "$has_fail" == "1" ]]; then
  exit 22
fi
if [[ "$has_write" == "1" ]]; then
  printf '401'
fi
exit 0
""",
                encoding="utf-8",
            )
            (fake_bin / "curl").chmod(0o755)
            env = {
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                "HOME": os.environ.get("HOME", ""),
                "SESSION_RENAMER_ENV_FILE": str(root / "missing.env"),
                "SESSION_RENAMER_FRP_CONFIG": str(config),
                "SESSION_RENAMER_PUBLIC_HOST": "example.test",
                "SESSION_RENAMER_PUBLIC_URL": "https://renamer.example.test",
            }
            result = subprocess.run(
                ["bash", "frp-tunnel.sh", "status"],
                cwd=PROJECT_DIR,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Public health: reachable (HTTP 401)", result.stdout)

    def test_frp_status_fallback_bypasses_proxy_and_treats_401_as_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.make_fake_frp_environment(root)
            env.pop("SESSION_RENAMER_PUBLIC_URL")
            curl_args = root / "curl-args"
            env["CURL_ARGS_FILE"] = str(curl_args)
            fake_curl = root / "bin" / "curl"
            fake_curl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$@" > "$CURL_ARGS_FILE"
target=""
has_write=0
for arg in "$@"; do
  [[ "$arg" == "-w" ]] && has_write=1
  [[ "$arg" == http* ]] && target="$arg"
done
if [[ "$target" == http://127.0.0.1:* ]]; then
  exit 7
fi
[[ "$has_write" == "1" ]] && printf '401'
exit 0
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            result = subprocess.run(
                ["bash", "frp-tunnel.sh", "status"],
                cwd=PROJECT_DIR,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            args = curl_args.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Public health: reachable (HTTP 401)", result.stdout)
        self.assertIn("--noproxy\n*\n", args)
        self.assertIn("http://example.test:8887/health", args)

    def test_frp_status_reports_public_network_failure_as_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.make_fake_frp_environment(root)
            fake_curl = root / "bin" / "curl"
            fake_curl.write_text(
                """#!/usr/bin/env bash
for arg in "$@"; do
  [[ "$arg" == http://127.0.0.1:* ]] && exit 7
done
printf '000'
exit 7
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            result = subprocess.run(
                ["bash", "frp-tunnel.sh", "status"],
                cwd=PROJECT_DIR,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Public health: unreachable", result.stdout)

    def test_frp_start_prints_token_placeholder_without_leaking_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.make_fake_frp_environment(Path(tmp))
            env["SESSION_RENAMER_TOKEN"] = "do-not-print-this-secret"
            result = subprocess.run(
                ["bash", "frp-tunnel.sh", "start"],
                cwd=PROJECT_DIR,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("http://127.0.0.1:8891/?token=<SESSION_RENAMER_TOKEN>", result.stdout)
        self.assertIn(
            "https://renamer.example.test/?token=<SESSION_RENAMER_TOKEN>",
            result.stdout,
        )
        self.assertNotIn("do-not-print-this-secret", result.stdout)


if __name__ == "__main__":
    unittest.main()
