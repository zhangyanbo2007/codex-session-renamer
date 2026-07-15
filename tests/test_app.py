import json
import html
import sys
import tempfile
import unittest
import warnings
import asyncio
import inspect
import multiprocessing
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

warnings.filterwarnings("ignore", message="Using `httpx`.*", category=Warning)

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.app import create_app, _list_url, _merge_existing_summary
from session_renamer.store import SessionStore


class FixedTitleGenerator:
    def __init__(self, title):
        self.title = title

    def suggest(self, messages, fallback):
        return self.title


class FixtureTitleGenerator:
    def suggest(self, messages, fallback):
        if fallback == "第二个旧标题":
            return "这是一个测试｜这是一个测试"
        return "Codex会话管理工具｜Codex会话管理工具"


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


def write_distinct_cache_keys(cache_path, prefix, start_event):
    from session_renamer.app import _update_title_cache

    start_event.wait()
    for index in range(30):
        _update_title_cache(
            Path(cache_path),
            {f"{prefix}:{index}": f"value-{index}"},
        )


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
            title_generator=FixtureTitleGenerator(),
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

    def read_title_cache(self):
        return json.loads(
            (self.codex_home / "session-renamer-title-cache.json").read_text(
                encoding="utf-8"
            )
        )

    def title_cache_or_empty(self):
        cache_path = self.codex_home / "session-renamer-title-cache.json"
        if not cache_path.exists():
            return {}
        return json.loads(cache_path.read_text(encoding="utf-8"))

    def assert_no_applied_provenance(self, *session_ids):
        cache = self.title_cache_or_empty()
        for session_id in session_ids:
            for prefix in ("applied-content", "applied-title", "overall-owner"):
                self.assertNotIn(f"{prefix}:{session_id}", cache)

    def replace_thread_name(self, session_id, thread_name):
        records = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["id"] == session_id:
                record["thread_name"] = thread_name
            records.append(json.dumps(record, ensure_ascii=False))
        self.index_path.write_text("\n".join(records) + "\n", encoding="utf-8")

    def append_user_message(self, session_id, text):
        log_path = next((self.codex_home / "sessions").rglob(f"*{session_id}.jsonl"))
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-08T03:00:00Z",
                        "type": "response_item",
                        "payload": {
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def test_requires_token_for_list_page(self):
        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint("/", method="GET", token=None)

        self.assertEqual(raised.exception.status_code, 401)

    def test_empty_list_url_has_no_trailing_query(self):
        self.assertEqual(_list_url(""), "/")

    def test_no_token_mode_serves_list_page_without_token(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="",
            title_generator=FixtureTitleGenerator(),
        )
        response = self.call_endpoint("/", method="GET", token=None)
        text = self.response_text(response, query_string=b"")

        self.assertEqual(response.status_code, 200)
        self.assertIn("abc123", text)
        self.assertNotIn("token=", text)

    def test_no_token_mode_renders_clean_action_urls(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="",
            title_generator=FixtureTitleGenerator(),
        )
        response = self.call_endpoint("/", method="GET", token=None)
        text = html.unescape(self.response_text(response, query_string=b""))

        self.assertIn('action="/recommend-all"', text)
        self.assertIn('action="/auto-rename-all"', text)
        self.assertIn('action="/sessions/abc123/recommend?next=list"', text)
        self.assertIn('action="/sessions/abc123/rename?next=list"', text)
        self.assertIn('action="/sessions/abc123/delete"', text)
        self.assertNotIn('?&', text)

    def test_no_token_mode_allows_actions_and_redirects_without_token(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="",
            title_generator=FixtureTitleGenerator(),
        )
        response = self.call_endpoint(
            "/sessions/{session_id}/rename",
            method="POST",
            token=None,
            query_string="next=list",
            body=urlencode({"thread_name": "无 Token 新标题"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?status=renamed")
        self.assertNotIn("token=", response.headers["location"])
        self.assertIn("无 Token 新标题", self.index_path.read_text(encoding="utf-8"))

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
        self.assertIn("v0.7.1", text)

    def test_list_page_marks_sessions_not_using_model_title(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("只看未改名", text)
        self.assertNotIn("条未改名", text)
        self.assertEqual(text.count('class="status-badge needs-rename"'), 2)
        self.assertIn(">未改名</span>", text)

    def test_list_page_keeps_manual_index_title_when_sqlite_title_has_reverted(self):
        text = self.index_path.read_text(encoding="utf-8")
        self.index_path.write_text(
            text.replace('"thread_name": "旧标题"', '"thread_name": "alpha｜已命名总览｜已命名近况"'),
            encoding="utf-8",
        )
        state_path = self.codex_home / "state_5.sqlite"
        with sqlite3.connect(state_path) as conn:
            conn.execute(
                """
                create table threads (
                    id text primary key,
                    rollout_path text,
                    created_at integer,
                    updated_at integer,
                    title text,
                    archived integer,
                    thread_source text,
                    preview text,
                    updated_at_ms integer,
                    cwd text
                )
                """
            )
            conn.execute("create table thread_dynamic_tools (thread_id text)")
            conn.execute(
                "create table thread_spawn_edges (parent_thread_id text, child_thread_id text)"
            )
            conn.execute(
                """
                insert into threads (
                    id, rollout_path, created_at, updated_at, title, archived,
                    thread_source, preview, updated_at_ms, cwd
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "abc123",
                    str(self.codex_home / "sessions" / "2026" / "07" / "08" / "rollout-2026-07-08T00-00-00-abc123.jsonl"),
                    1783500000,
                    1783500000,
                    "live reverted title",
                    0,
                    "user",
                    "live preview",
                    1783500000000,
                    "/work/alpha",
                ),
            )

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn("alpha｜已命名总览｜已命名近况", text)
        self.assertNotIn("live reverted title", text)

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

    def test_list_page_does_not_mark_renamed_sessions_as_changed(self):
        self.call_endpoint("/auto-rename-all")

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertNotIn('class="status-badge changed"', text)

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
        self.assertIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", text)
        self.assertNotIn("beta｜这是一个测试任务｜这是一个测试</a>", text)

    def test_changed_filter_excludes_sessions_without_an_applied_rename_baseline(self):
        query_string = urlencode({"token": "secret", "changed": "1"})

        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("没有可展示的会话记录", text)
        self.assertNotIn("旧标题</a>", text)
        self.assertNotIn("第二个旧标题</a>", text)

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

        self.assertIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", text)
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

        self.assertIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", first_text)
        self.assertIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", second_text)
        self.assertNotIn("没有可展示的会话记录", second_text)

    def test_recommend_all_keeps_changed_sessions_visible_until_rename(self):
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
                            "content": [{"type": "input_text", "text": "新增：推荐后仍待改名"}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        query_string = urlencode({"token": "secret", "changed": "1"})

        self.call_endpoint("/recommend-all", query_string=query_string)
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", text)
        self.assertNotIn("没有可展示的会话记录", text)

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

        self.assertNotIn("没有可展示的会话记录", text)
        self.assertIn("abc123", text)

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

    def test_changed_session_preserves_existing_summary_segment_after_model_rename(self):
        self.assertEqual(
            _merge_existing_summary(
                "alpha｜稳态总览｜稳态近况",
                "alpha｜新总览｜新近况",
                "/work/alpha",
            ),
            "alpha｜稳态总览｜新近况",
        )

    def test_changed_session_does_not_merge_first_rename(self):
        self.assertEqual(
            _merge_existing_summary(
                "旧标题",
                "alpha｜新总览｜新近况",
                "/work/alpha",
            ),
            "alpha｜新总览｜新近况",
        )

    def test_changed_model_owned_title_can_evolve_overall_and_recent_segments(self):
        generator = CountingTitleGenerator("第一版总览｜第一版近况")
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=generator,
        )
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.append_user_message("abc123", "新增：任务方向已经改变")
        generator.title = "第二版总览｜第二版近况"

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        detail = self.app.state.store.get_session("abc123")
        cache = self.read_title_cache()
        self.assertEqual(
            cache[f"session:{detail.id}"],
            "第二版总览任务｜第二版近况",
        )
        self.assertEqual(
            cache[f"recommendation-owner:{detail.content_cache_key}"],
            "model",
        )

    def test_changed_manual_owned_title_preserves_overall_segment(self):
        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode({"thread_name": "alpha｜人工总览任务｜人工近况"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )
        self.append_user_message("abc123", "新增：只更新最近状态")
        self.app.state.title_generator = FixedTitleGenerator("模型新总览｜模型新近况")

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        detail = self.app.state.store.get_session("abc123")
        cache = self.read_title_cache()
        self.assertEqual(
            cache[f"session:{detail.id}"],
            "人工总览任务｜模型新近况",
        )
        self.assertEqual(
            cache[f"recommendation-owner:{detail.content_cache_key}"],
            "manual",
        )

    def test_unchanged_manual_owned_title_preserves_overall_segment(self):
        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode({"thread_name": "alpha｜人工总览任务｜人工近况"}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )
        self.app.state.title_generator = FixedTitleGenerator("模型新总览｜模型新近况")

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        cache = self.read_title_cache()
        self.assertEqual(
            cache["session:abc123"],
            "人工总览任务｜模型新近况",
        )

    def test_external_title_drift_changes_model_owned_title_to_manual(self):
        self.app.state.title_generator = FixedTitleGenerator("模型总览｜模型近况")
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.replace_thread_name("abc123", "alpha｜外部人工总览任务｜外部近况")
        self.append_user_message("abc123", "外部 /rename 后继续对话")
        self.app.state.title_generator = FixedTitleGenerator("模型新总览｜模型新近况")

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        detail = self.app.state.store.get_session("abc123")
        cache = self.read_title_cache()
        self.assertEqual(
            cache[f"session:{detail.id}"],
            "外部人工总览任务｜模型新近况",
        )
        self.assertEqual(
            cache[f"recommendation-owner:{detail.content_cache_key}"],
            "manual",
        )

    def test_passive_list_and_detail_preserve_manual_drift_before_form_apply(self):
        generator = CountingTitleGenerator("模型总览｜模型近况")
        self.app.state.title_generator = generator
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.assertEqual(generator.calls, 1)
        self.replace_thread_name("abc123", "alpha｜外部人工总览任务｜外部近况")

        list_response = self.call_endpoint("/", method="GET")
        list_text = self.response_text(list_response)
        detail_response = self.call_endpoint(
            "/sessions/{session_id}", method="GET", session_id="abc123"
        )
        detail_text = self.response_text(detail_response, path="/sessions/abc123")
        preserved = "alpha｜外部人工总览任务｜模型近况"

        self.assertIn(f'name="thread_name" value="{preserved}"', list_text)
        self.assertIn(f'name="thread_name" value="{preserved}"', detail_text)
        self.assertEqual(generator.calls, 1)

        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode({"thread_name": preserved}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "manual")
        self.assertEqual(cache["applied-title:abc123"], preserved)
        self.assertIn(
            f'"thread_name":"{preserved}"',
            self.index_path.read_text(encoding="utf-8"),
        )

    def test_external_short_title_drift_is_still_manual_owned(self):
        self.app.state.title_generator = FixedTitleGenerator("模型总览｜模型近况")
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.replace_thread_name("abc123", "外部短标题")

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        detail = self.app.state.store.get_session("abc123")
        cache = self.read_title_cache()
        self.assertEqual(
            cache[f"recommendation-owner:{detail.content_cache_key}"],
            "manual",
        )

    def test_auto_rename_remerges_cached_recommendation_after_external_drift(self):
        self.app.state.title_generator = FixedTitleGenerator("模型总览｜模型近况")
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.replace_thread_name("abc123", "alpha｜外部人工总览任务｜外部近况")
        self.app.state.title_generator = FailingTitleGenerator()

        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")

        self.assertIn(
            '"thread_name":"alpha｜外部人工总览任务｜模型近况"',
            self.index_path.read_text(encoding="utf-8"),
        )
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "manual")
        self.assertEqual(
            cache["applied-title:abc123"],
            "alpha｜外部人工总览任务｜模型近况",
        )

    def test_unknown_stored_owner_fails_conservatively_to_manual(self):
        self.app.state.title_generator = FixedTitleGenerator("模型总览｜模型近况")
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        cache_path = self.codex_home / "session-renamer-title-cache.json"
        cache = self.read_title_cache()
        cache["overall-owner:abc123"] = "unknown"
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        self.app.state.title_generator = FixedTitleGenerator("新模型总览｜新模型近况")

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        detail = self.app.state.store.get_session("abc123")
        cache = self.read_title_cache()
        self.assertEqual(cache["session:abc123"], "模型总览任务｜新模型近况")
        self.assertEqual(
            cache[f"recommendation-owner:{detail.content_cache_key}"],
            "manual",
        )

    def test_legacy_exact_cached_recommendation_is_inferred_model_owned(self):
        legacy_title = "alpha｜旧模型总览任务｜旧模型近况"
        self.replace_thread_name("abc123", legacy_title)
        (self.codex_home / "session-renamer-title-cache.json").write_text(
            json.dumps(
                {"session:abc123": "旧模型总览任务｜旧模型近况"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=FixedTitleGenerator("新模型总览｜新模型近况"),
        )

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        self.assertEqual(
            self.read_title_cache()["session:abc123"],
            "新模型总览任务｜新模型近况",
        )

    def test_legacy_unknown_three_level_title_is_inferred_manual_owned(self):
        self.replace_thread_name("abc123", "alpha｜未知来源总览任务｜旧近况")
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=FixedTitleGenerator("新模型总览｜新模型近况"),
        )

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        self.assertEqual(
            self.read_title_cache()["session:abc123"],
            "未知来源总览任务｜新模型近况",
        )

    def test_exact_form_recommendation_inherits_owner_but_edited_value_is_manual(self):
        self.app.state.title_generator = FixedTitleGenerator("推荐总览｜推荐近况")
        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")
        recommendation = f"alpha｜{self.read_title_cache()['session:abc123']}"

        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode({"thread_name": recommendation}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "model")
        self.assertEqual(cache["applied-title:abc123"], recommendation)

        edited = "alpha｜编辑后的总览任务｜推荐近况"
        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode({"thread_name": edited}),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "manual")
        self.assertEqual(cache["applied-title:abc123"], edited)

    def test_canonically_equal_form_recommendation_inherits_owner(self):
        self.app.state.title_generator = FixedTitleGenerator("推荐总览｜推荐近况")
        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")

        self.call_endpoint(
            "/sessions/{session_id}/rename",
            body=urlencode(
                {"thread_name": "  alpha ｜ 推荐总览任务 ｜ 推荐近况  "}
            ),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
            session_id="abc123",
        )

        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "model")
        self.assertEqual(
            cache["applied-title:abc123"],
            "alpha｜推荐总览任务｜推荐近况",
        )

    def test_manual_recommendation_owner_survives_single_and_bulk_auto_apply(self):
        for session_id, title in (
            ("abc123", "alpha｜人工甲总览任务｜旧近况"),
            ("def456", "beta｜人工乙总览任务｜旧近况"),
        ):
            self.call_endpoint(
                "/sessions/{session_id}/rename",
                body=urlencode({"thread_name": title}),
                headers=[(b"content-type", b"application/x-www-form-urlencoded")],
                session_id=session_id,
            )
        self.app.state.title_generator = FixedTitleGenerator("模型总览｜模型近况")

        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        self.call_endpoint("/auto-rename-all")

        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "manual")
        self.assertEqual(cache["overall-owner:def456"], "manual")
        for session_id in ("abc123", "def456"):
            detail = self.app.state.store.get_session(session_id)
            self.assertEqual(
                cache[f"recommendation-owner:{detail.content_cache_key}"],
                "manual",
            )
        self.assertEqual(
            cache["applied-title:abc123"],
            "alpha｜人工甲总览任务｜模型近况",
        )
        self.assertEqual(
            cache["applied-title:def456"],
            "beta｜人工乙总览任务｜模型近况",
        )

    def test_invalid_form_apply_does_not_write_applied_provenance(self):
        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint(
                "/sessions/{session_id}/rename",
                body=urlencode({"thread_name": "   "}),
                headers=[(b"content-type", b"application/x-www-form-urlencoded")],
                session_id="abc123",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assert_no_applied_provenance("abc123")

    def test_form_store_failure_does_not_write_applied_provenance(self):
        def fail_rename(_session_id, _title):
            raise ValueError("rename failed")

        self.app.state.store.rename_session = fail_rename

        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint(
                "/sessions/{session_id}/rename",
                body=urlencode({"thread_name": "有效新标题"}),
                headers=[(b"content-type", b"application/x-www-form-urlencoded")],
                session_id="abc123",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assert_no_applied_provenance("abc123")

    def test_single_auto_no_actionable_suggestion_writes_no_applied_provenance(self):
        self.app.state.title_generator = FixedTitleGenerator("未命名会话")

        response = self.call_endpoint(
            "/sessions/{session_id}/auto-rename",
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assert_no_applied_provenance("abc123")

    def test_single_auto_store_failure_writes_no_applied_provenance(self):
        def fail_rename(_session_id, _title):
            raise ValueError("rename failed")

        self.app.state.store.rename_session = fail_rename

        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint(
                "/sessions/{session_id}/auto-rename",
                session_id="abc123",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assert_no_applied_provenance("abc123")

    def test_bulk_auto_no_actionable_suggestions_write_no_applied_provenance(self):
        self.app.state.title_generator = FixedTitleGenerator("未命名会话")

        response = self.call_endpoint("/auto-rename-all")

        self.assertEqual(response.status_code, 303)
        self.assert_no_applied_provenance("abc123", "def456")

    def test_bulk_auto_store_failure_writes_no_applied_provenance(self):
        def fail_rename_all(_titles_by_id):
            raise ValueError("bulk rename failed")

        self.app.state.store.rename_sessions = fail_rename_all

        with self.assertRaises(HTTPException) as raised:
            self.call_endpoint("/auto-rename-all")

        self.assertEqual(raised.exception.status_code, 400)
        self.assert_no_applied_provenance("abc123", "def456")

    def test_generator_exception_fails_closed_for_suggest_api(self):
        self.app.state.title_generator = FailingTitleGenerator()

        response = self.call_endpoint(
            "/api/sessions/{session_id}/suggest",
            method="GET",
            session_id="abc123",
        )

        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["suggested_title"],
            "暂无推荐",
        )
        self.assertEqual(self.title_cache_or_empty(), {})

    def test_generator_exception_fails_closed_for_single_recommend(self):
        self.app.state.title_generator = FailingTitleGenerator()

        response = self.call_endpoint(
            "/sessions/{session_id}/recommend",
            session_id="abc123",
        )

        self.assertIn("status=no_recommendation", response.headers["location"])
        self.assertEqual(self.title_cache_or_empty(), {})

    def test_generator_exception_fails_closed_for_bulk_recommend(self):
        self.app.state.title_generator = FailingTitleGenerator()

        response = self.call_endpoint("/recommend-all")

        self.assertIn("status=no_recommendation", response.headers["location"])
        self.assertEqual(self.title_cache_or_empty(), {})

    def test_generator_exception_fails_closed_for_single_auto(self):
        self.app.state.title_generator = FailingTitleGenerator()

        response = self.call_endpoint(
            "/sessions/{session_id}/auto-rename",
            session_id="abc123",
        )

        self.assertIn("status=no_recommendation", response.headers["location"])
        self.assertIn('"thread_name": "旧标题"', self.index_path.read_text())
        self.assertEqual(self.title_cache_or_empty(), {})

    def test_generator_exception_fails_closed_for_bulk_auto(self):
        self.app.state.title_generator = FailingTitleGenerator()

        response = self.call_endpoint("/auto-rename-all")

        self.assertIn("status=no_recommendation", response.headers["location"])
        index_text = self.index_path.read_text()
        self.assertIn('"thread_name": "旧标题"', index_text)
        self.assertIn('"thread_name": "第二个旧标题"', index_text)
        self.assertEqual(self.title_cache_or_empty(), {})

    def test_multiprocess_cache_updates_retain_all_distinct_keys(self):
        cache_path = self.codex_home / "concurrent-title-cache.json"
        context = multiprocessing.get_context("fork")
        start_event = context.Event()
        processes = [
            context.Process(
                target=write_distinct_cache_keys,
                args=(str(cache_path), f"worker-{index}", start_event),
            )
            for index in range(4)
        ]
        for process in processes:
            process.start()
        start_event.set()
        for process in processes:
            process.join(10)

        self.assertEqual([process.exitcode for process in processes], [0, 0, 0, 0])
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(len(cache), 120)
        for worker in range(4):
            for index in range(30):
                self.assertEqual(
                    cache[f"worker-{worker}:{index}"],
                    f"value-{index}",
                )

    def test_single_and_bulk_auto_rename_store_model_ownership(self):
        self.call_endpoint("/sessions/{session_id}/auto-rename", session_id="abc123")
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:abc123"], "model")
        self.assertEqual(
            cache["applied-title:abc123"],
            "alpha｜Codex会话管理工具任务｜Codex会话管理工具",
        )

        self.call_endpoint("/auto-rename-all")
        cache = self.read_title_cache()
        self.assertEqual(cache["overall-owner:def456"], "model")
        self.assertEqual(
            cache["applied-title:def456"],
            "beta｜这是一个测试任务｜这是一个测试",
        )

    def test_recommend_all_and_single_recommend_preserve_manual_overall_consistently(self):
        self.replace_thread_name("abc123", "alpha｜人工总览任务｜旧近况")
        self.replace_thread_name("def456", "beta｜人工总览任务｜旧近况")
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=FixedTitleGenerator("模型总览｜模型近况"),
        )

        self.call_endpoint("/sessions/{session_id}/recommend", session_id="abc123")
        self.call_endpoint("/recommend-all")

        cache = self.read_title_cache()
        self.assertEqual(
            cache["session:abc123"],
            "人工总览任务｜模型近况",
        )
        self.assertEqual(
            cache["session:def456"],
            "人工总览任务｜模型近况",
        )

    def test_list_page_can_search_by_current_title(self):
        query_string = urlencode({"token": "secret", "q": "第二个旧标题"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn('value="第二个旧标题"', text)
        self.assertIn("第二个旧标题", text)
        self.assertNotIn("abc123", text)

    def test_search_input_has_no_implicit_default_or_browser_autocomplete(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn('id="session-search" name="session_search_display" value=""', text)
        self.assertIn('autocomplete="new-password"', text)
        self.assertIn('readonly data-session-search-input', text)
        self.assertIn('id="search-query-param" name="q" value=""', text)
        self.assertIn("url.searchParams.has('q')", text)
        self.assertIn("searchInput.value = initialQuery", text)
        self.assertNotIn('value="studio"', text)

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

    def test_suggest_api_returns_generated_title(self):
        response = self.call_endpoint(
            "/api/sessions/{session_id}/suggest",
            method="GET",
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["suggested_title"],
            "alpha｜Codex会话管理工具任务｜Codex会话管理工具",
        )

    def test_index_page_does_not_generate_title_recommendations(self):
        store = SessionStore(self.index_path, self.codex_home)
        generator = CountingTitleGenerator("不应调用｜不应生成")
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=generator,
        )

        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertNotIn("alpha｜Codex会话管理工具任务｜Codex会话管理工具", text)
        self.assertNotIn("beta｜这是一个测试任务｜这是一个测试", text)
        self.assertEqual(generator.calls, 0)

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
            '"thread_name":"alpha｜Codex会话管理工具任务｜Codex会话管理工具"',
            self.index_path.read_text(encoding="utf-8"),
        )

    def test_auto_rename_all_updates_every_session_from_content(self):
        response = self.call_endpoint("/auto-rename-all")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?token=secret&status=renamed_all")
        index_text = self.index_path.read_text(encoding="utf-8")
        self.assertIn('"thread_name":"alpha｜Codex会话管理工具任务｜Codex会话管理工具"', index_text)
        self.assertIn('"thread_name":"beta｜这是一个测试任务｜这是一个测试"', index_text)

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
        self.assertIn("alpha｜刷新标题任务｜最近状态", text)
        self.assertNotIn("beta｜刷新标题任务｜最近状态", text)

    def test_recommend_all_prefills_rename_input_without_changing_current_title(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FixedTitleGenerator("刷新标题｜最近状态"),
        )

        self.call_endpoint("/recommend-all")
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        self.assertIn(">旧标题</a>", text)
        self.assertIn(
            'name="thread_name" value="alpha｜刷新标题任务｜最近状态"',
            text,
        )

    def test_list_page_places_single_recommend_before_single_rename(self):
        response = self.call_endpoint("/", method="GET")
        text = self.response_text(response)

        recommend = text.index("单会话标题推荐")
        rename = text.index("单会话改名")
        self.assertLess(recommend, rename)
        self.assertIn("/sessions/abc123/recommend?", text)

    def test_single_recommend_updates_only_recommendation(self):
        store = SessionStore(self.index_path, self.codex_home)
        generator = CountingTitleGenerator("会话管理优化｜增加单条推荐按钮")
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=generator,
        )

        response = self.call_endpoint(
            "/sessions/{session_id}/recommend",
            query_string=urlencode({"token": "secret", "next": "list"}),
            session_id="abc123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(generator.calls, 1)
        self.assertIn("status=recommended", response.headers["location"])
        self.assertIn('"thread_name": "旧标题"', self.index_path.read_text())
        list_response = self.call_endpoint("/", method="GET")
        text = self.response_text(list_response)
        self.assertIn(
            'name="thread_name" value="alpha｜会话管理优化任务｜增加单条推荐按钮"',
            text,
        )

    def test_detail_page_shows_single_recommend_action(self):
        response = self.call_endpoint(
            "/sessions/{session_id}", method="GET", session_id="abc123"
        )
        text = self.response_text(response, path="/sessions/abc123")

        self.assertIn("重新推荐", text)
        self.assertIn("/sessions/abc123/recommend?token=secret", text)
        self.assertIn('class="detail-actions"', text)
        self.assertNotIn("任务线索", text)
        self.assertNotIn('class="preview-block"', text)

    def test_passive_detail_uses_cached_recommendation_without_generator_call(self):
        self.replace_thread_name("abc123", "alpha｜人工总览任务｜人工近况")
        (self.codex_home / "session-renamer-title-cache.json").write_text(
            json.dumps(
                {"session:abc123": "旧模型总览任务｜缓存近况"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        generator = CountingTitleGenerator("不应调用｜不应生成")
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=generator,
        )

        response = self.call_endpoint(
            "/sessions/{session_id}", method="GET", session_id="abc123"
        )
        text = self.response_text(response, path="/sessions/abc123")

        self.assertEqual(generator.calls, 0)
        self.assertIn("alpha｜人工总览任务｜缓存近况", text)

    def test_passive_detail_without_cache_uses_current_title_without_generator_call(self):
        generator = CountingTitleGenerator("不应调用｜不应生成")
        self.app = create_app(
            store=SessionStore(self.index_path, self.codex_home),
            access_token="secret",
            title_generator=generator,
        )

        response = self.call_endpoint(
            "/sessions/{session_id}", method="GET", session_id="abc123"
        )
        text = self.response_text(response, path="/sessions/abc123")

        self.assertEqual(generator.calls, 0)
        self.assertIn('name="thread_name" value="旧标题"', text)

    def test_detail_single_recommend_prefills_rename_input(self):
        store = SessionStore(self.index_path, self.codex_home)
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=FixedTitleGenerator("会话管理优化｜增加详情推荐按钮"),
        )
        response = self.call_endpoint(
            "/sessions/{session_id}/recommend", session_id="abc123"
        )
        self.assertEqual(response.status_code, 303)

        detail_response = self.call_endpoint(
            "/sessions/{session_id}", method="GET", session_id="abc123"
        )
        text = self.response_text(detail_response, path="/sessions/abc123")
        self.assertIn(
            'name="thread_name" value="alpha｜会话管理优化任务｜增加详情推荐按钮"',
            text,
        )

    def test_list_page_shows_recommend_all_feedback(self):
        query_string = urlencode({"token": "secret", "status": "recommended"})
        response = self.call_endpoint("/", method="GET", query_string=query_string)
        text = self.response_text(response, query_string=query_string.encode("utf-8"))

        self.assertIn("已完成一键标题推荐", text)

    def test_recommend_all_generates_title_only_on_request(self):
        store = SessionStore(self.index_path, self.codex_home)
        generator = CountingTitleGenerator("未命名会话")
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=generator,
        )

        response = self.call_endpoint("/", method="GET")
        self.assertEqual(generator.calls, 0)

        response = self.call_endpoint("/recommend-all")
        self.assertEqual(response.status_code, 303)
        self.assertGreater(generator.calls, 0)

    def test_recommend_all_refreshes_unchanged_cached_sessions(self):
        store = SessionStore(self.index_path, self.codex_home)
        generator = CountingTitleGenerator("第一版标题｜第一版状态")
        self.app = create_app(
            store=store,
            access_token="secret",
            title_generator=generator,
        )

        self.call_endpoint("/recommend-all")
        self.assertEqual(generator.calls, 2)
        generator.title = "第二版标题｜第二版状态"

        self.call_endpoint("/recommend-all")

        self.assertEqual(generator.calls, 4)
        page = self.call_endpoint("/", method="GET")
        self.assertIn("alpha｜第二版标题任务｜第二版状态", self.response_text(page))

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
        self.assertIn("推荐标题", text)
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

        self.assertIn("alpha｜缓存标题任务｜最近状态", text)

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

    def test_delete_post_removes_only_session_scoped_title_cache_keys(self):
        cache_path = self.codex_home / "session-renamer-title-cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "session:abc123": "旧推荐任务｜旧近况",
                    "pending-recommendation:abc123": "hash-abc",
                    "prefill-recommendation:abc123": "hash-abc",
                    "applied-content:abc123": "hash-abc",
                    "applied-title:abc123": "alpha｜旧推荐任务｜旧近况",
                    "overall-owner:abc123": "model",
                    "recommendation-owner:hash-abc": "model",
                    "unrelated:key": "keep",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.call_endpoint("/sessions/{session_id}/delete", session_id="abc123")

        cache = self.read_title_cache()
        for prefix in (
            "session",
            "pending-recommendation",
            "prefill-recommendation",
            "applied-content",
            "applied-title",
            "overall-owner",
        ):
            self.assertNotIn(f"{prefix}:abc123", cache)
        self.assertEqual(cache["recommendation-owner:hash-abc"], "model")
        self.assertEqual(cache["unrelated:key"], "keep")

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
