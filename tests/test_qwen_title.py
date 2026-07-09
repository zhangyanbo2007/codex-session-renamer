import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.qwen_title import QwenTitleGenerator, normalize_model_title
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
        self.payload = payload
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payload)


class QwenTitleTest(unittest.TestCase):
    def test_qwen_generator_returns_model_title(self):
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": "整理浏览器书签｜按项目分组书签；确认分类方案"
                        }
                    }
                ]
            }
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

        self.assertEqual(title, "整理浏览器书签｜按项目分组书签；确认分类方案")
        body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        self.assertEqual(body["model"], "qwen-turbo")
        self.assertIn("最近2轮", body["messages"][1]["content"])
        self.assertIn("<总摘要标题>｜<最近2轮摘要标题>", body["messages"][0]["content"])
        self.assertIn("只能包含一个", body["messages"][0]["content"])
        self.assertNotIn("总：<", body["messages"][0]["content"])
        self.assertNotIn("近2轮：<", body["messages"][0]["content"])
        self.assertNotIn("/home/zhangyanbo", body["messages"][1]["content"])
        self.assertNotIn("系统记录", body["messages"][1]["content"])

    def test_model_path_output_is_rejected(self):
        self.assertEqual(normalize_model_title("/home/zhangyanbo/owner/xiaow"), "")

    def test_placeholder_output_is_rejected(self):
        self.assertEqual(normalize_model_title("未命名会话"), "")

    def test_extra_model_separators_are_folded_into_recent_title(self):
        self.assertEqual(
            normalize_model_title("红鸟挑战营邮件撰写｜范老师理念融入｜邮件润色建议"),
            "红鸟挑战营邮件撰写｜范老师理念融入；邮件润色建议",
        )


if __name__ == "__main__":
    unittest.main()
