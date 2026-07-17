import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.codex_app_server import CodexAppServerThreadRenamer


class CodexAppServerThreadRenamerTest(unittest.TestCase):
    @staticmethod
    def write_fake_codex(path: Path, calls_path: Path) -> None:
        path.write_text(
            "#!/usr/bin/env python3\n"
            + textwrap.dedent(
                f"""
                import json
                import sys

                calls_path = {str(calls_path)!r}
                for line in sys.stdin:
                    message = json.loads(line)
                    method = message.get("method")
                    if method == "initialize":
                        print(json.dumps({{"id": message["id"], "result": {{}}}}), flush=True)
                    elif method == "thread/name/set":
                        with open(calls_path, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(message["params"], ensure_ascii=False) + "\\n")
                        print(json.dumps({{"id": message["id"], "result": {{}}}}), flush=True)
                """
            ),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def test_set_names_uses_initialize_then_thread_name_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls_path = root / "calls.jsonl"
            fake_codex = root / "codex"
            self.write_fake_codex(fake_codex, calls_path)

            renamer = CodexAppServerThreadRenamer(
                root / ".codex",
                binary_path=fake_codex,
                timeout=2,
            )
            renamer.set_names({"thread-1": "新标题一", "thread-2": "新标题二"})

            calls = [
                json.loads(line)
                for line in calls_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                calls,
                [
                    {"threadId": "thread-1", "name": "新标题一"},
                    {"threadId": "thread-2", "name": "新标题二"},
                ],
            )

    def test_auto_discovered_binary_is_refreshed_after_extension_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls_path = root / "calls.jsonl"
            old_codex = root / "old-codex"
            new_codex = root / "new-codex"
            self.write_fake_codex(old_codex, calls_path)
            self.write_fake_codex(new_codex, calls_path)

            with patch(
                "session_renamer.codex_app_server._find_codex_binary",
                side_effect=[old_codex, new_codex],
            ):
                renamer = CodexAppServerThreadRenamer(root / ".codex", timeout=2)
                old_codex.unlink()
                renamer.set_names({"thread-1": "升级后标题"})

            call = json.loads(calls_path.read_text(encoding="utf-8"))
            self.assertEqual(
                call,
                {"threadId": "thread-1", "name": "升级后标题"},
            )


if __name__ == "__main__":
    unittest.main()
