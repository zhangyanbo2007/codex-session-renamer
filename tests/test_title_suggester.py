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

    def test_overall_context_over_budget_keeps_first_and_newest_user_intent(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="user", text="首个真实任务：排查远程输入法", timestamp=None),
            SessionMessage(role="user", text="中间过程" + "甲" * 80, timestamp=None),
            SessionMessage(role="user", text="最新意图：验证修复结果", timestamp=None),
        ]

        context = overall_title_context(messages, max_tokens=1_060)

        self.assertIn("首个真实任务：排查远程输入法", context)
        self.assertIn("最新意图：验证修复结果", context)
        self.assertNotIn("中间过程", context)
        self.assertLessEqual(len(context), 60)

    def test_overall_context_prioritizes_partial_newest_turn_over_older_turn(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(role="user", text="首个任务：定位问题", timestamp=None),
            SessionMessage(role="user", text="较短旧进度", timestamp=None),
            SessionMessage(
                role="user",
                text="最新任务：验证输入法修复" + "乙" * 50,
                timestamp=None,
            ),
        ]

        context = overall_title_context(messages, max_tokens=1_050)

        self.assertIn("首个任务：定位问题", context)
        self.assertIn("最新任务：验证", context)
        self.assertNotIn("较短旧进度", context)
        self.assertLessEqual(len(context), 50)

    def test_keeps_project_name_from_path_when_request_follows_it(self):
        messages = [
            SessionMessage(role="user", text=SYSTEM_USER_RECORD, timestamp=None),
            SessionMessage(
                role="user",
                text="/home/example/projects/video_project 帮忙看看需求，怎么实现，给个方案",
                timestamp=None,
            ),
        ]

        context = summary_title_context(messages)

        self.assertIn("video_project", context)
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


if __name__ == "__main__":
    unittest.main()
