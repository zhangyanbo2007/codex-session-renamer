import json
import html
import sys
import tempfile
import unittest
import warnings
import asyncio
import inspect
from pathlib import Path
from urllib.parse import urlencode

warnings.filterwarnings("ignore", message="Using `httpx`.*", category=Warning)

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.app import create_app
from session_renamer.qwen_title import LocalTitleGenerator
from session_renamer.store import SessionStore


class FixedTitleGenerator:
    def __init__(self, title):
        self.title = title

    def suggest(self, messages, fallback):
        return self.title


class CountingTitleGenerator:
    def __init__(self, title):
        self.title = title
        self.calls = 0

    def suggest(self, messages, fallback):
        self.calls += 1
        return self.title


class FailingTitleGenerator:
    def suggest(self, messages, fallback):
        raise AssertionError("title generator should not be called")


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.codex_home = self.root / ".codex"
        self.codex_home.mkdir()
        self.index_path = self.codex_home / "session_index.jsonl"
        self.index_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": "abc123",
                            "thread_name": "旧标题",
                            "updated_at": "2026-07-08T01:02:03Z",
                            "cwd": "/work/alpha",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "id": "def456",
                            "thread_name": "第二个旧标题",
                            "updated_at": "2026-07-08T02:03:04Z",
                            "cwd": "/work/beta",
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        log_dir = self.codex_home / "sessions" / "2026" / "07" / "08"
        log_dir.mkdir(parents=True)
        (log_dir / "rollout-2026-07-08T00-00-00-abc123.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-07-08T00:59:00Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "系统记录：加载环境上下文，不是真实用户任务",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-07-08T01:00:00Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "帮忙写个程序用于会话改名，支持查看和手动改名",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (log_dir / "rollout-2026-07-08T00-01-00-def456.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-07-08T01:59:00Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "系统记录：加载环境上下文，不是真实用户任务",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-07-08T02:00:00Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "Task Name:\n这是一个测试",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=LocalTitleGenerator(),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def call_endpoint(
        self,
        path,
        *,
        method="POST",
        token="secret",
        query_string=None,
        body=b"",
        headers=None,
        **path_params,
    ):
        route = next(route for route in self.app.routes if getattr(route, "path", None) == path)
        if isinstance(body, str):
            body = body.encode("utf-8")
        if query_string is None:
            query_string = b"" if token is None else f"token={token}".encode("utf-8")
        elif isinstance(query_string, str):
            query_string = query_string.encode("utf-8")
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": query_string,
                "headers": headers or [],
            },
            receive,
        )
        response = route.endpoint(request, **path_params)
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        return response

    def response_text(self, response, *, path="/", method="GET", query_string=b"token=secret"):
        chunks = []

        async def send(message):
            chunks.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": [],
        }
        asyncio.run(response(scope, receive, send))
        body = b"".join(
            message.get("body", b"")
            for message in chunks
            if message.get("type") == "http.response.body"
        )
        return body.decode("utf-8")

    def test_requires_token_for_list_page(self):
        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint("/", method="GET", token=None)

        self.assertEqual(raised.exception.status_code, 401)

    def test_list_page_renders_with_token(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn("旧标题", text)
        self.assertIn("abc123", text)
        self.assertIn("推荐标题", text)
        self.assertIn("Codex会话管理工具", text)
        self.assertIn("单会话改名", text)
        self.assertIn("一键全部改名", text)
        self.assertIn("一键标题推荐", text)
        self.assertIn("删除会话", text)

    def test_list_page_marks_sessions_not_using_model_title(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("只看未改名", text)
        self.assertNotIn("条未改名", text)
        self.assertEqual(text.count('class="status-badge needs-rename"'), 2)
        self.assertIn(">未改名</span>", text)

    def test_list_page_does_not_mark_model_shaped_title_as_unrenamed(self):
        text = self.index_path.read_text(encoding="utf-8")
        self.index_path.write_text(
            text.replace('"thread_name": "旧标题"', '"thread_name": "alpha｜已命名总览｜已命名近况"'),
            encoding="utf-8",
        )

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("alpha｜已命名总览｜已命名近况", text)
        self.assertEqual(text.count('class="status-badge needs-rename"'), 1)

    def test_list_page_hides_model_rename_marker_after_auto_rename(self):
        self.call_endpoint("/auto-rename-all")

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertNotIn('class="status-badge needs-rename"', text)

    def test_list_page_can_filter_to_sessions_not_using_model_title(self):
        self.call_endpoint(
            "/sessions/{session_id}/auto-rename",
            session_id="def456",
        )
        query_string = urlencode({"token": "secret", "needs_rename": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("旧标题", text)
        self.assertNotIn("第二个旧标题", text)
        self.assertIn('class="filter-toggle active"', text)
        self.assertIn("释放未改名", text)
        self.assertNotIn('type="checkbox"', text)

    def test_list_page_preserves_unrenamed_filter_in_actions(self):
        query_string = urlencode({"token": "secret", "needs_rename": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))
        decoded = html.unescape(text)

        self.assertIn("/recommend-all?token=secret&needs_rename=1", decoded)
        self.assertIn("/auto-rename-all?token=secret&needs_rename=1", decoded)
        self.assertIn("/sessions/abc123/rename?token=secret&needs_rename=1&next=list", decoded)

    def test_unrenamed_filter_toggle_preserves_directory_and_search(self):
        query_string = urlencode({"token": "secret", "directory": "/work/alpha", "q": "会话改名"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn('name="directory" value="/work/alpha"', text)
        self.assertIn('name="q" value="会话改名"', text)
        self.assertIn('name="needs_rename" value="1"', text)

    def test_changed_filter_shows_sessions_with_new_conversation_content(self):
        self.call_endpoint("/", method="GET")
        self.call_endpoint("/auto-rename-all")
        log_path = self.codex_home / "sessions" / "2026" / "07" / "08" / "rollout-2026-07-08T00-00-00-abc123.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-08T01:05:00Z",
                        "type": "response_item",
                        "payload": {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "新增：会话内容变化"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        query_string = urlencode({"token": "secret", "changed": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("释放会话变化", text)
        self.assertIn("alpha｜Codex会话管理工具｜Codex会话管理工具", text)
        self.assertNotIn("beta｜这是一个测试｜这是一个测试</a>", text)

    def test_passive_list_view_does_not_clear_changed_filter(self):
        self.call_endpoint("/auto-rename-all")
        log_path = self.codex_home / "sessions" / "2026" / "07" / "08" / "rollout-2026-07-08T00-00-00-abc123.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-08T01:05:00Z",
                        "type": "response_item",
                        "payload": {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "新增：普通查看不应清除变化"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        passive_response = self.call_endpoint("/", method="GET")
        self.response_text(passive_response)
        query_string = urlencode({"token": "secret", "changed": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("alpha｜Codex会话管理工具｜Codex会话管理工具", text)
        self.assertNotIn("没有可展示的会话记录", text)

    def test_changed_filter_view_does_not_clear_changed_filter(self):
        self.call_endpoint("/auto-rename-all")
        log_path = self.codex_home / "sessions" / "2026" / "07" / "08" / "rollout-2026-07-08T00-00-00-abc123.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-08T01:05:00Z",
                        "type": "response_item",
                        "payload": {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "新增：变化筛选不应清除变化"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        query_string = urlencode({"token": "secret", "changed": "1"})
        first_response = self.call_endpoint("/", method="GET", query_string=query_string)
        first_text = self.response_text(first_response, query_string=query_string.encode("utf-8"))

        second_response = self.call_endpoint("/", method="GET", query_string=query_string)
        second_text = self.response_text(second_response, query_string=query_string.encode("utf-8"))

        self.assertIn("alpha｜Codex会话管理工具｜Codex会话管理工具", first_text)
        self.assertIn("alpha｜Codex会话管理工具｜Codex会话管理工具", second_text)
        self.assertNotIn("没有可展示的会话记录", second_text)

    def test_changed_filter_excludes_unchanged_sessions_that_only_need_rename(self):
        self.call_endpoint("/recommend-all")
        query_string = urlencode({"token": "secret", "changed": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("没有可展示的会话记录", text)
        self.assertNotIn("旧标题</a>", text)
        self.assertNotIn("第二个旧标题</a>", text)

    def test_changed_filter_reloads_title_cache_written_by_another_process(self):
        self.call_endpoint("/auto-rename-all")
        log_path = self.codex_home / "sessions" / "2026" / "07" / "08" / "rollout-2026-07-08T00-00-00-abc123.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-08T01:05:00Z",
                        "type": "response_item",
                        "payload": {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "外部进程新增内容"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        original_app = self.app
        try:
            self.app = create_app(
                store=SessionStore(self.index_path, self.codex_home),
                access_token="secret",
                title_generator=FixedTitleGenerator("外部刷新｜最近状态"),
            )
            self.call_endpoint("/recommend-all")
        finally:
            self.app = original_app

        query_string = urlencode({"token": "secret", "changed": "1"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("没有可展示的会话记录", text)
        self.assertNotIn("abc123", text)

    def test_list_page_disables_browser_cache_for_realtime_filters(self):
        response = self.call_endpoint("/", method="GET")

        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_title_cache_is_not_invalidated_by_title_change_only(self):
        generator = CountingTitleGenerator("缓存标题｜最近状态")
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=generator,
        )
        self.call_endpoint("/recommend-all")
        self.assertEqual(generator.calls, 2)

        text = self.index_path.read_text(encoding="utf-8")
        self.index_path.write_text(
            text.replace('"thread_name": "旧标题"', '"thread_name": "alpha｜已命名总览｜已命名近况"'),
            encoding="utf-8",
        )
        second_response = self.call_endpoint("/", method="GET")
        self.response_text(second_response)

        self.assertEqual(generator.calls, 2)

    def test_list_page_places_delete_action_right_of_inline_rename(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn('class="row-actions"', text)
        self.assertIn('class="delete-form inline-delete"', text)
        self.assertLess(text.index('class="inline-rename"'), text.index('class="delete-form inline-delete"'))

    def test_list_page_places_actions_below_page_title(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn('class="topbar-title"', text)
        self.assertIn('class="topbar-actions"', text)
        self.assertLess(text.index('class="topbar-title"'), text.index('class="topbar-actions"'))

    def test_list_page_places_bulk_actions_on_right_side_of_toolbar(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn('class="bulk-actions"', text)
        self.assertLess(text.index('class="directory-filter"'), text.index('class="bulk-actions"'))
        self.assertLess(text.index("只看未改名"), text.index("一键标题推荐"))
        self.assertLess(text.index("只看会话变化"), text.index("一键标题推荐"))
        self.assertLess(text.index("一键标题推荐"), text.index("一键全部改名"))

    def test_list_page_groups_sessions_by_directory_in_recent_order(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("/work/alpha", text)
        self.assertIn("/work/beta", text)
        self.assertLess(text.index("/work/beta"), text.index("/work/alpha"))

    def test_list_page_can_filter_sessions_with_directory_select(self):
        query_string = urlencode({"token": "secret", "directory": "/work/alpha"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn('name="directory"', text)
        self.assertIn('name="q"', text)
        self.assertIn('value="/work/alpha" selected', text)
        self.assertIn('value="/work/beta"', text)
        self.assertNotIn(">筛选</button>", text)
        self.assertIn("旧标题", text)
        self.assertNotIn("第二个旧标题", text)

    def test_list_page_can_search_by_current_title(self):
        query_string = urlencode({"token": "secret", "q": "第二个旧标题"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn('value="第二个旧标题"', text)
        self.assertIn("第二个旧标题", text)
        self.assertNotIn("abc123", text)

    def test_list_page_can_search_by_message_content(self):
        query_string = urlencode({"token": "secret", "q": "会话改名"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("旧标题", text)
        self.assertNotIn("第二个旧标题", text)

    def test_list_page_combines_directory_filter_and_search(self):
        query_string = urlencode({"token": "secret", "directory": "/work/beta", "q": "会话改名"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("0 / 2 条记录", text)
        self.assertIn("没有可展示的会话记录", text)
        self.assertNotIn("旧标题</a>", text)
        self.assertNotIn("第二个旧标题</a>", text)

    def test_suggest_api_returns_local_title(self):
        response = self.call_endpoint(
            "/api/sessions/{session_id}/suggest",
            method="GET",
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["suggested_title"],
            "alpha｜Codex会话管理工具｜Codex会话管理工具",
        )

    def test_suggested_title_uses_current_directory_basename_as_first_level(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("alpha｜Codex会话管理工具｜Codex会话管理工具", text)
        self.assertIn("beta｜这是一个测试｜这是一个测试", text)

    def test_rename_post_updates_index(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/rename",
            method="POST",
            query_string="token=secret&next=list",
            body=urlencode({"thread_name": "新标题"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?token=secret&status=renamed")
        self.assertIn('"thread_name":"新标题"', self.index_path.read_text(encoding="utf-8"))

    def test_rename_post_preserves_directory_filter_in_redirect(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/rename",
            method="POST",
            query_string=urlencode(
                {
                    "token": "secret",
                    "next": "list",
                    "directory": "/work/alpha",
                    "q": "会话改名",
                }
            ),
            body=urlencode({"thread_name": "新标题"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/?token=secret&directory=%2Fwork%2Falpha&q=%E4%BC%9A%E8%AF%9D%E6%94%B9%E5%90%8D&status=renamed",
        )

    def test_detail_rename_post_redirects_with_feedback_status(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/rename",
            method="POST",
            body=urlencode({"thread_name": "新标题"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/sessions/abc123?token=secret&status=renamed",
        )

    def test_auto_rename_post_uses_suggested_title(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/auto-rename",
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/sessions/abc123?token=secret&status=renamed",
        )
        self.assertIn(
            '"thread_name":"alpha｜Codex会话管理工具｜Codex会话管理工具"',
            self.index_path.read_text(encoding="utf-8"),
        )

    def test_auto_rename_all_updates_every_session_from_content(self):
        response = self.call_endpoint("/auto-rename-all")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?token=secret&status=renamed_all")
        index_text = self.index_path.read_text(encoding="utf-8")
        self.assertIn('"thread_name":"alpha｜Codex会话管理工具｜Codex会话管理工具"', index_text)
        self.assertIn('"thread_name":"beta｜这是一个测试｜这是一个测试"', index_text)

    def test_auto_rename_all_preserves_directory_filter_in_redirect(self):
        response = self.call_endpoint(
            "/auto-rename-all",
            query_string=urlencode(
                {"token": "secret", "directory": "/work/alpha", "q": "会话改名"}
            ),
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/?token=secret&directory=%2Fwork%2Falpha&q=%E4%BC%9A%E8%AF%9D%E6%94%B9%E5%90%8D&status=renamed_all",
        )

    def test_recommend_all_refreshes_displayed_titles_and_preserves_directory_filter(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FixedTitleGenerator("刷新标题｜最近状态"),
        )

        response = self.call_endpoint(
            "/recommend-all",
            query_string=urlencode(
                {"token": "secret", "directory": "/work/alpha", "q": "会话改名"}
            ),
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/?token=secret&directory=%2Fwork%2Falpha&q=%E4%BC%9A%E8%AF%9D%E6%94%B9%E5%90%8D&status=recommended",
        )

        page = self.call_endpoint(
            "/",
            method="GET",
            query_string=urlencode({"token": "secret", "directory": "/work/alpha"}),
        )
        text = self.response_text(
            page,
            query_string=urlencode({"token": "secret", "directory": "/work/alpha"}).encode("utf-8"),
        )
        self.assertIn("alpha｜刷新标题｜最近状态", text)
        self.assertNotIn("beta｜刷新标题｜最近状态", text)

    def test_list_page_shows_recommend_all_feedback(self):
        query_string = urlencode({"token": "secret", "status": "recommended"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("已完成一键标题推荐", text)

    def test_placeholder_recommendation_is_displayed_but_not_written(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FixedTitleGenerator("未命名会话"),
        )

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("暂无推荐", text)
        self.assertNotIn('value="未命名会话"', text)

        response = self.call_endpoint("/auto-rename-all")

        self.assertEqual(response.status_code, 303)
        index_text = self.index_path.read_text(encoding="utf-8")
        self.assertIn('"thread_name": "旧标题"', index_text)
        self.assertIn('"thread_name": "第二个旧标题"', index_text)
        self.assertNotIn("未命名会话", index_text)

    def test_list_page_shows_rename_feedback(self):
        query_string = urlencode({"token": "secret", "status": "renamed"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("已改名会话", text)
        self.assertIn('data-auto-dismiss="true"', text)
        self.assertIn("searchParams.delete('status')", text)

    def test_list_page_shows_rename_all_feedback(self):
        query_string = urlencode({"token": "secret", "status": "renamed_all"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("已完成一键全部改名", text)

    def test_detail_page_shows_rename_feedback(self):
        query_string = urlencode({"token": "secret", "status": "renamed"})
        response = self.call_endpoint(
            "/sessions/{session_id}",
            method="GET",
            query_string=query_string,
            session_id="abc123",
        )
        text = self.response_text(
            response,
            path="/sessions/abc123",
            query_string=query_string.encode("utf-8"),
        )

        self.assertIn("已改名会话", text)
        self.assertIn('data-auto-dismiss="true"', text)
        self.assertIn("searchParams.delete('status')", text)

    def test_detail_page_omits_redundant_auto_rename_button(self):
        response = self.call_endpoint(
            "/sessions/{session_id}",
            method="GET",
            session_id="abc123",
        )
        text = self.response_text(response, path="/sessions/abc123")

        self.assertIn(">保存</button>", text)
        self.assertIn("推荐标题：", text)
        self.assertNotIn("使用建议并保存", text)
        self.assertNotIn("/sessions/abc123/auto-rename", text)

    def test_list_page_reuses_persistent_title_cache_after_restart(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FixedTitleGenerator("缓存标题｜最近状态"),
        )
        self.call_endpoint("/recommend-all")

        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FailingTitleGenerator(),
        )
        second_response = self.call_endpoint("/", method="GET")
        text = self.response_text(second_response)

        self.assertIn("alpha｜缓存标题｜最近状态", text)

    def test_delete_post_removes_session_from_index(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/delete",
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?token=secret&status=deleted")
        index_text = self.index_path.read_text(encoding="utf-8")
        self.assertNotIn("abc123", index_text)
        self.assertIn("def456", index_text)

    def test_delete_post_preserves_directory_filter_in_redirect(self):
        response = self.call_endpoint(
            "/sessions/{session_id}/delete",
            query_string=urlencode(
                {"token": "secret", "directory": "/work/alpha", "q": "会话改名"}
            ),
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/?token=secret&directory=%2Fwork%2Falpha&q=%E4%BC%9A%E8%AF%9D%E6%94%B9%E5%90%8D&status=deleted",
        )

    def test_list_page_shows_delete_feedback(self):
        query_string = urlencode({"token": "secret", "status": "deleted"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("已删除会话", text)
        self.assertIn('data-auto-dismiss="true"', text)
        self.assertIn("searchParams.delete('status')", text)


if __name__ == "__main__":
    unittest.main()
