import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer import qwen_title
from session_renamer.qwen_title import ExistingTitleGenerator, QwenTitleGenerator
from session_renamer.store import SessionMessage


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    def __init__(self, payload):
        self.payloads = payload if isinstance(payload, list) else [payload]
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        index = min(len(self.requests) - 1, len(self.payloads) - 1)
        return FakeResponse(self.payloads[index])


class QwenTitleTest(unittest.TestCase):
    def test_api_key_is_not_loaded_from_parent_project_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_file = Path(tmp) / "a" / "b" / "c" / "qwen_title.py"
            package_file.parent.mkdir(parents=True)
            (Path(tmp) / ".env").write_text("DASHSCOPE_API_KEY=private-key\n")
            with (
                patch.object(qwen_title, "__file__", str(package_file)),
                patch.dict("os.environ", {}, clear=True),
            ):
                self.assertEqual(qwen_title._env_value("DASHSCOPE_API_KEY"), "")

    def test_qwen_generator_returns_model_title(self):
        opener = FakeOpener(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "content": "整理浏览器书签任务"
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "message": {
                                "content": "按项目分组书签；确认分类方案"
                            }
                        }
                    ]
                },
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        title = generator.suggest(
            [
                SessionMessage(
                    role="user",
                    text="系统记录：加载环境上下文和权限，不是真实用户任务",
                    timestamp=None,
                ),
                SessionMessage(
                    role="user",
                    text="帮我整理 Chrome 书签，按项目和用途分组",
                    timestamp=None,
                ),
                SessionMessage(
                    role="assistant",
                    text="我会按项目、用途和阅读状态拆分。",
                    timestamp=None,
                ),
            ],
            fallback="旧标题",
        )

        self.assertEqual(title, "整理浏览器书签任务｜按项目分组书签；确认分类方案")
        self.assertEqual(len(opener.requests), 3)
        overall_body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        recent_body = json.loads(opener.requests[1][0].data.decode("utf-8"))
        self.assertEqual(overall_body["model"], "qwen3.5-flash")
        self.assertFalse(overall_body["enable_thinking"])
        self.assertIn("具体对象+工作动作或目标+任务", overall_body["messages"][0]["content"])
        self.assertIn("Codex插件故障排查任务", overall_body["messages"][0]["content"])
        self.assertIn("Codex使用咨询任务", overall_body["messages"][0]["content"])
        self.assertIn("附件名", overall_body["messages"][0]["content"])
        self.assertIn("不能单独作为任务对象", overall_body["messages"][0]["content"])
        self.assertIn("旧标题", overall_body["messages"][1]["content"])
        self.assertNotIn("/home/example", overall_body["messages"][1]["content"])
        self.assertNotIn("系统记录", overall_body["messages"][1]["content"])
        self.assertIn("整理浏览器书签任务", recent_body["messages"][1]["content"])
        self.assertIn("最近2轮", recent_body["messages"][1]["content"])
        self.assertIn("不能照抄", recent_body["messages"][0]["content"])

    def test_overall_request_includes_recent_assistant_screenshot_evidence(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "远程桌面输入法状态评估任务"}}]},
                {"choices": [{"message": {"content": "确认控制端输入法归属"}}]},
                {"choices": [{"message": {"content": "确认控制端输入法归属"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(
                    role="user", text="screenshot-20260714-024720.png", timestamp=None
                ),
                SessionMessage(
                    role="assistant",
                    text="截图显示目标机输入法正常，问题属于控制端输入法归属。",
                    timestamp=None,
                ),
            ],
            fallback="截图",
        )

        overall_body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        overall_evidence = overall_body["messages"][1]["content"]
        self.assertIn("screenshot-20260714-024720.png", overall_evidence)
        self.assertIn("问题属于控制端输入法归属", overall_evidence)

    def test_filename_dominated_overall_title_retries_once_with_same_evidence(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "screenshot-20260714-024720.png任务"}}]},
                {"choices": [{"message": {"content": "远程桌面输入法状态评估任务"}}]},
                {"choices": [{"message": {"content": "确认控制端输入法归属"}}]},
                {"choices": [{"message": {"content": "确认控制端输入法归属"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)
        messages = [
            SessionMessage(role="user", text="系统记录", timestamp=None),
            SessionMessage(
                role="user", text="screenshot-20260714-024720.png", timestamp=None
            ),
            SessionMessage(
                role="assistant",
                text="截图显示目标机输入法正常，问题属于控制端输入法归属。",
                timestamp=None,
            ),
        ]

        title = generator.suggest(messages, fallback="截图")

        self.assertEqual(
            title,
            "远程桌面输入法状态评估任务｜确认控制端输入法归属",
        )
        self.assertEqual(len(opener.requests), 4)
        first_body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        retry_body = json.loads(opener.requests[1][0].data.decode("utf-8"))
        self.assertIn("文件名", retry_body["messages"][0]["content"])
        self.assertIn("screenshot-20260714-024720.png任务", retry_body["messages"][1]["content"])
        self.assertIn(
            first_body["messages"][1]["content"],
            retry_body["messages"][1]["content"],
        )

    def test_two_invalid_overall_titles_return_no_recommendation_without_recent_calls(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "截图分析任务"}}]},
                {"choices": [{"message": {"content": "report.log检查任务"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        title = generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(role="user", text="screen.png", timestamp=None),
                SessionMessage(
                    role="assistant", text="日志说明鉴权失败。", timestamp=None
                ),
            ],
            fallback="附件",
        )

        self.assertEqual(title, "暂无推荐")
        self.assertEqual(len(opener.requests), 2)

    def test_overall_title_validation_rejects_generic_carriers_and_filename_shapes(self):
        invalid_titles = (
            "任务",
            "截图任务",
            "图片转换任务",
            "schema.sql迁移任务",
            "/tmp/schema.sql迁移任务",
            r"C:\logs\schema.sql迁移任务",
        )

        for title in invalid_titles:
            with self.subTest(title=title):
                self.assertTrue(qwen_title._overall_title_failure(title))

        self.assertEqual(
            qwen_title._overall_title_failure("应急评测泛化优化任务"),
            "",
        )

    def test_model_rewrites_path_bearing_recent_draft(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "WorkspaceHub文件共享与权限配置任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": "修改 WorkspaceHub 共享目录为/srv/workspace并重启验证"
                            }
                        }
                    ]
                },
                {"choices": [{"message": {"content": "共享目录修改与服务验证"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        title = generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(role="user", text="安装 WorkspaceHub", timestamp=None),
                SessionMessage(
                    role="user",
                    text="共享目录改为/srv/workspace并重启验证",
                    timestamp=None,
                ),
            ],
            fallback="workspace｜WorkspaceHub配置与功能分析｜目录修改与服务验证",
        )

        self.assertEqual(
            title,
            "WorkspaceHub文件共享与权限配置任务｜共享目录修改与服务验证",
        )
        self.assertEqual(len(opener.requests), 3)
        rewrite_body = json.loads(opener.requests[2][0].data.decode("utf-8"))
        self.assertIn("修改 WorkspaceHub 共享目录", rewrite_body["messages"][1]["content"])
        self.assertIn("只保留抽象工作状态", rewrite_body["messages"][0]["content"])

    def test_no_model_configuration_keeps_existing_title_without_local_rules(self):
        generator = ExistingTitleGenerator()

        title = generator.suggest(
            [SessionMessage(role="user", text="会话改名", timestamp=None)],
            fallback="现有标题",
        )

        self.assertEqual(title, "现有标题")


if __name__ == "__main__":
    unittest.main()
