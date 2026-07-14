import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.store import SessionMessage
from session_renamer.title_suggester import (
    overall_title_context,
    summary_title_context,
)


SYSTEM_USER_RECORD = "系统记录：加载 AGENTS.md、环境变量、权限上下文，不是真实用户任务"


class TitleSuggesterTest(unittest.TestCase):
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

    def test_summary_context_does_not_truncate_cleaned_conversation(self):
        long_request = "完整需求" + "甲" * 4000
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="user", text=long_request, timestamp=None),
            SessionMessage(role="assistant", text="完整回复" + "乙" * 1000, timestamp=None),
        ]

        context = summary_title_context(messages)

        self.assertIn(long_request, context)
        self.assertIn("乙" * 1000, context)

    def test_overall_context_caps_large_input(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="user", text="甲" * 120_000, timestamp=None),
            SessionMessage(role="user", text="最近任务状态", timestamp=None),
            SessionMessage(role="assistant", text="最近处理结果", timestamp=None),
        ]

        context = overall_title_context(messages, max_tokens=100_000)

        self.assertLessEqual(len(context), 99_000)

    def test_keeps_project_name_from_path_when_request_follows_it(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(
                role="user",
                text="/home/example/projects/kuajing_video 帮忙看看需求，怎么实现，给个方案",
                timestamp=None,
            ),
        ]

        context = summary_title_context(messages)

        self.assertIn("kuajing_video", context)
        self.assertNotIn("/home/example", context)
        self.assertNotIn("帮忙看看需求", context)

    def test_ignores_internal_context_in_model_context(self):
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

        context = summary_title_context(messages)

        self.assertNotIn("Continue working", context)
        self.assertIn("这是一个测试", context)

    def test_summary_context_ignores_pure_greeting_messages(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="user", text="hello", timestamp=None),
            SessionMessage(role="assistant", text="hi", timestamp=None),
        ]

        context = summary_title_context(messages)

        self.assertEqual(context, "")


if __name__ == "__main__":
    unittest.main()
