import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.store import SessionMessage
from session_renamer.title_suggester import suggest_title, summary_title_context


SYSTEM_USER_RECORD = "系统记录：加载 AGENTS.md、环境变量、权限上下文，不是真实用户任务"


class TitleSuggesterTest(unittest.TestCase):
    def test_suggests_session_renamer_title_from_chinese_task(self):
        messages = [
            SessionMessage(
                role="user",
                text=SYSTEM_USER_RECORD,
                timestamp="2026-07-08T00:59:00Z",
            ),
            SessionMessage(
                role="user",
                text="帮忙写个程序用于会话改名（支持会话记录查看，手动改，根据内容自动改等）",
                timestamp="2026-07-08T01:00:00Z",
            )
        ]

        self.assertEqual(suggest_title(messages), "Codex会话管理工具｜Codex会话管理工具")

    def test_skips_first_user_record_when_choosing_title(self):
        messages = [
            SessionMessage(
                role="user",
                text="系统记录：会话管理工具启动上下文，不是真实任务",
                timestamp=None,
            ),
            SessionMessage(
                role="assistant",
                text="读取上下文。",
                timestamp=None,
            ),
            SessionMessage(
                role="user",
                text="帮我整理 Chrome 书签，按项目和用途分组",
                timestamp=None,
            ),
        ]

        self.assertEqual(suggest_title(messages), "帮我整理 Chrome 书签，按项目和用途分组｜帮我整理 Chrome 书签，按项目和用途分组")

    def test_summary_context_skips_first_user_record(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="assistant", text="已加载上下文。", timestamp=None),
            SessionMessage(role="user", text="写一个发票整理脚本", timestamp=None),
            SessionMessage(role="assistant", text="我会先解析文件名。", timestamp=None),
        ]

        context = summary_title_context(messages)

        self.assertNotIn("系统记录", context)
        self.assertNotIn("已加载上下文", context)
        self.assertIn("写一个发票整理脚本", context)

    def test_ignores_absolute_paths_when_choosing_title(self):
        messages = [
            SessionMessage(
                role="user",
                text="/home/zhangyanbo/owner/xiaowangzi/projects/privacy-engineering",
                timestamp="2026-07-08T01:00:00Z",
            )
        ]

        self.assertEqual(suggest_title(messages, fallback="旧标题"), "旧标题")

    def test_ignores_internal_context_and_uses_real_user_request(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(
                role="user",
                text="<codex_internal_context source=\"goal\">Continue working</codex_internal_context>",
                timestamp="2026-07-08T01:00:00Z",
            ),
            SessionMessage(
                role="user",
                text="Task Name:\n这是一个测试",
                timestamp="2026-07-08T01:00:10Z",
            ),
        ]

        self.assertEqual(suggest_title(messages), "这是一个测试｜这是一个测试")

    def test_falls_back_to_existing_title_when_no_meaningful_content(self):
        messages = [
            SessionMessage(role="assistant", text="我会继续。", timestamp=None),
        ]

        self.assertEqual(suggest_title(messages, fallback="旧标题"), "旧标题")

    def test_combines_overall_title_with_recent_two_turn_titles(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(
                role="user",
                text="帮忙写个程序用于会话改名，支持查看和手动改名",
                timestamp=None,
            ),
            SessionMessage(role="assistant", text="我会先搭建列表页。", timestamp=None),
            SessionMessage(role="user", text="改用 Qwen 便宜模型生成推荐名字", timestamp=None),
            SessionMessage(role="assistant", text="已改为 Qwen 优先，本地兜底。", timestamp=None),
            SessionMessage(role="user", text="支持会话内删除无价值会话", timestamp=None),
        ]

        self.assertEqual(
            suggest_title(messages),
            "Codex会话管理工具｜改用 Qwen 便宜模型生成推荐名字；Codex会话管理工具",
        )


if __name__ == "__main__":
    unittest.main()
