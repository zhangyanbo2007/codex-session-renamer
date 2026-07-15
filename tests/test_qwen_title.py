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
        if isinstance(self.payload, bytes):
            return self.payload
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
    def test_complete_fails_closed_on_malformed_response_shapes(self):
        malformed_payloads = (
            {},
            {"choices": []},
            {"choices": {}},
            {"choices": None},
            {"choices": [{}]},
            {"choices": [{"message": None}]},
            {"choices": [{"message": []}]},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": 123}}]},
            b"\xff\xfe",
        )

        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                generator = QwenTitleGenerator(
                    api_key="test-key", opener=FakeOpener(payload)
                )
                self.assertEqual(generator._complete("system", "user"), "")

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
                                "content": json.dumps(
                                    {
                                        "acceptable": True,
                                        "title": "整理浏览器书签任务",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                {"choices": [{"message": {"content": "按项目分组书签；确认分类方案"}}]},
                {"choices": [{"message": {"content": "按项目分组书签；确认分类方案"}}]},
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
        self.assertEqual(len(opener.requests), 4)
        overall_body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        review_body = json.loads(opener.requests[1][0].data.decode("utf-8"))
        recent_body = json.loads(opener.requests[2][0].data.decode("utf-8"))
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
        review_prompt = review_body["messages"][0]["content"]
        self.assertIn("严格 JSON", review_prompt)
        self.assertIn("screenshot.png任务", review_prompt)
        self.assertIn("截图分析任务", review_prompt)
        self.assertIn("日志诊断任务", review_prompt)
        self.assertIn("Node.js升级任务", review_prompt)
        self.assertIn("Vue.js迁移任务", review_prompt)
        self.assertIn("代码仓库迁移任务", review_prompt)
        self.assertIn("文件服务器修复任务", review_prompt)
        self.assertIn("图片编辑器开发任务", review_prompt)
        self.assertIn(
            overall_body["messages"][1]["content"],
            review_body["messages"][1]["content"],
        )
        self.assertIn("整理浏览器书签任务", recent_body["messages"][1]["content"])
        self.assertIn("最近2轮", recent_body["messages"][1]["content"])
        self.assertIn("不能照抄", recent_body["messages"][0]["content"])

    def test_overall_request_includes_recent_assistant_screenshot_evidence(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "远程桌面输入法状态评估任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": true, "title": "远程桌面输入法状态评估任务"}'
                            }
                        }
                    ]
                },
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

    def test_overall_and_review_requests_share_one_bounded_evidence_budget(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "输入法故障排查任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": false, "title": ""}'
                            }
                        }
                    ]
                },
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(
                    role="user",
                    text="首个任务：调查远程输入法故障" + "甲" * 90_000,
                    timestamp=None,
                ),
                SessionMessage(
                    role="user", text="最新意图：验证修复结果", timestamp=None
                ),
                SessionMessage(
                    role="assistant",
                    text="最近结论：问题属于控制端输入法归属" + "乙" * 120_000,
                    timestamp=None,
                ),
            ],
            fallback="输入法",
        )

        overall_body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        review_body = json.loads(opener.requests[1][0].data.decode("utf-8"))
        overall_prompt = overall_body["messages"][1]["content"]
        review_prompt = review_body["messages"][1]["content"]
        for prompt in (overall_prompt, review_prompt):
            self.assertLessEqual(len(prompt), 100_000)
            self.assertIn("首个任务：调查", prompt)
            self.assertIn("最新意图：验证修复结果", prompt)
            self.assertIn("最近结论：问题属于控制端输入法归属", prompt)

    def test_recent_generation_context_is_bounded(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "输入法故障排查任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": true, "title": "输入法故障排查任务"}'
                            }
                        }
                    ]
                },
                {"choices": [{"message": {"content": "确认输入法归属"}}]},
                {"choices": [{"message": {"content": "确认输入法归属"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(role="user", text="排查输入法", timestamp=None),
                SessionMessage(
                    role="assistant",
                    text="结论：控制端输入法归属" + "乙" * 120_000,
                    timestamp=None,
                ),
            ],
            fallback="输入法",
        )

        recent_body = json.loads(opener.requests[2][0].data.decode("utf-8"))
        self.assertLessEqual(len(recent_body["messages"][1]["content"]), 100_000)
        self.assertIn("结论：控制端输入法归属", recent_body["messages"][1]["content"])

    def test_filename_dominated_overall_title_retries_once_with_same_evidence(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "screenshot-20260714-024720.png任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": true, "title": "远程桌面输入法状态评估任务"}'
                            }
                        }
                    ]
                },
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
        self.assertIn("质量审校", retry_body["messages"][0]["content"])
        self.assertIn("screenshot-20260714-024720.png任务", retry_body["messages"][1]["content"])
        self.assertIn(
            first_body["messages"][1]["content"],
            retry_body["messages"][1]["content"],
        )

    def test_unacceptable_overall_review_returns_no_recommendation_without_recent_calls(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "截图分析任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": false, "title": "远程鉴权故障诊断任务"}'
                            }
                        }
                    ]
                },
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

    def test_malformed_overall_review_returns_no_recommendation_without_recent_calls(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "Node.js升级任务"}}]},
                {"choices": [{"message": {"content": "not valid json"}}]},
            ]
        )
        generator = QwenTitleGenerator(api_key="test-key", opener=opener)

        title = generator.suggest(
            [
                SessionMessage(role="user", text="系统记录", timestamp=None),
                SessionMessage(role="user", text="升级 Node.js", timestamp=None),
            ],
            fallback="Node.js",
        )

        self.assertEqual(title, "暂无推荐")
        self.assertEqual(len(opener.requests), 2)

    def test_structural_validation_does_not_decide_carrier_or_product_semantics(self):
        invalid_titles = (
            "",
            "任务",
            "Node.js升级",
            "/tmp/schema.sql迁移任务",
            "/workspace/repo迁移任务",
            "检查 /srv/app/config.yaml 配置任务",
            "/Users/alice/report.pdf分析任务",
            "检查:/etc配置任务",
            "检查（/etc）配置任务",
            "迁移到:/workspace任务",
            "检查，/etc/passwd迁移任务",
            r"检查；C:\logs\x迁移任务",
            "检查、../secret迁移任务",
            r"检查，\\server\share\x迁移任务",
            r"检查-\\server\share\x迁移任务",
            "检查。/etc/passwd迁移任务",
            "检查！/etc/passwd迁移任务",
            "检查？../secret迁移任务",
            r"检查…C:\logs\x迁移任务",
            r"检查）\\server\share\x迁移任务",
            r"C:\logs\schema.sql迁移任务",
            r"\\server\share\report.pdf分析任务",
            "./schema.sql迁移任务",
            "../schema.sql迁移任务",
        )

        for title in invalid_titles:
            with self.subTest(title=title):
                self.assertTrue(qwen_title._overall_title_failure(title))
                review = json.dumps({"acceptable": True, "title": title})
                self.assertEqual(qwen_title._parse_overall_review(review), "")

        valid_titles = (
            "应急评测泛化优化任务",
            "Python代码质量检查任务",
            "Node.js升级任务",
            "Vue.js迁移任务",
            "截图分析任务",
            "日志诊断任务",
            "schema.sql迁移任务",
            "CI/CD流水线优化任务",
            "TCP/IP协议调试任务",
            "客户端/服务器架构设计任务",
            "CI/CD/DevOps工具链优化任务",
            "TCP/IP/UDP协议对比任务",
            "客户端/服务器/数据库架构设计任务",
            "迁移/workspace/repo任务",
            "C++/CLI互操作任务",
            "C#/.NET互操作任务",
        )
        for title in valid_titles:
            with self.subTest(title=title):
                self.assertEqual(qwen_title._overall_title_failure(title), "")
                review = json.dumps({"acceptable": True, "title": title})
                self.assertEqual(qwen_title._parse_overall_review(review), title)

    def test_model_rewrites_path_bearing_recent_draft(self):
        opener = FakeOpener(
            [
                {"choices": [{"message": {"content": "WorkspaceHub文件共享与权限配置任务"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"acceptable": true, "title": "WorkspaceHub文件共享与权限配置任务"}'
                            }
                        }
                    ]
                },
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
        self.assertEqual(len(opener.requests), 4)
        rewrite_body = json.loads(opener.requests[3][0].data.decode("utf-8"))
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
