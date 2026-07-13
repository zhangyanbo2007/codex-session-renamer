import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_renamer.store import SessionStore


class RecordingThreadRenamer:
    def __init__(self, state_path):
        self.state_path = state_path
        self.calls = []

    def set_names(self, titles_by_id):
        self.calls.append(dict(titles_by_id))
        with sqlite3.connect(self.state_path) as conn:
            conn.executemany(
                "update threads set title = ? where id = ?",
                [(title, session_id) for session_id, title in titles_by_id.items()],
            )


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.codex_home = self.root / ".codex"
        self.codex_home.mkdir()
        self.index_path = self.codex_home / "session_index.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write_index(self, records):
        with self.index_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_log(self, session_id, records):
        log_dir = self.codex_home / "sessions" / "2026" / "07" / "08"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"rollout-2026-07-08T00-00-00-{session_id}.jsonl"
        with log_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return log_path

    def write_state_threads(self, rows):
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
            conn.executemany(
                """
                insert into threads (
                    id, rollout_path, created_at, updated_at, title, archived,
                    thread_source, preview, updated_at_ms, cwd
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [row if len(row) == 10 else (*row, "") for row in rows],
            )
        return state_path

    def test_default_paths_follow_codex_home_environment(self):
        configured_home = self.root / "custom-codex-home"
        configured_home.mkdir()

        with patch.dict("os.environ", {"CODEX_HOME": str(configured_home)}):
            store = SessionStore(
                thread_renamer=RecordingThreadRenamer(
                    configured_home / "state_5.sqlite"
                )
            )

        self.assertEqual(store.codex_home, configured_home)
        self.assertEqual(store.index_path, configured_home / "session_index.jsonl")

    def test_list_sessions_loads_index_and_attaches_log_path(self):
        self.write_index(
            [
                {
                    "id": "abc123",
                    "thread_name": "旧标题",
                    "updated_at": "2026-07-08T01:02:03Z",
                    "cwd": "/work/alpha",
                }
            ]
        )
        log_path = self.write_log("abc123", [])

        store = SessionStore(self.index_path, self.codex_home)
        sessions = store.list_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "abc123")
        self.assertEqual(sessions[0].thread_name, "旧标题")
        self.assertEqual(sessions[0].log_path, log_path)
        self.assertEqual(sessions[0].cwd, "/work/alpha")

    def test_list_sessions_sorts_by_updated_at_descending(self):
        self.write_index(
            [
                {
                    "id": "older",
                    "thread_name": "旧会话",
                    "updated_at": "2026-07-08T01:02:03Z",
                },
                {
                    "id": "newer",
                    "thread_name": "新会话",
                    "updated_at": "2026-07-08T03:02:03Z",
                },
            ]
        )
        self.write_log("older", [])
        self.write_log("newer", [])

        sessions = SessionStore(self.index_path, self.codex_home).list_sessions()

        self.assertEqual([session.id for session in sessions], ["newer", "older"])

    def test_list_sessions_loads_current_codex_threads_from_sqlite(self):
        self.write_index(
            [
                {
                    "id": "index-only",
                    "thread_name": "旧索引会话",
                    "updated_at": "2026-07-08T01:02:03Z",
                }
            ]
        )
        sqlite_new_log = self.write_log("sqlite-new", [])
        sqlite_old_log = self.write_log("sqlite-old", [])
        self.write_log("sqlite-subagent", [])
        self.write_log("sqlite-archived", [])
        self.write_state_threads(
            [
                (
                    "sqlite-old",
                    str(sqlite_old_log),
                    1783500000,
                    1783500000,
                    "较早 SQLite 会话",
                    0,
                    "user",
                    "较早预览",
                    1783500000000,
                    "/work/old",
                ),
                (
                    "sqlite-new",
                    str(sqlite_new_log),
                    1783600000,
                    1783600000,
                    "较新 SQLite 会话",
                    0,
                    "user",
                    "较新预览",
                    1783600000000,
                    "/work/new",
                ),
                (
                    "sqlite-subagent",
                    "",
                    1783700000,
                    1783700000,
                    "后台子任务",
                    0,
                    "subagent",
                    "不应展示",
                    1783700000000,
                    "/work/subagent",
                ),
                (
                    "sqlite-archived",
                    "",
                    1783800000,
                    1783800000,
                    "归档会话",
                    1,
                    "user",
                    "不应展示",
                    1783800000000,
                    "/work/archived",
                ),
            ]
        )

        sessions = SessionStore(self.index_path, self.codex_home).list_sessions()

        self.assertEqual(
            [session.id for session in sessions],
            ["sqlite-new", "sqlite-old", "index-only"],
        )
        self.assertEqual(sessions[0].thread_name, "较新 SQLite 会话")
        self.assertEqual(sessions[0].log_path, sqlite_new_log)
        self.assertEqual(sessions[0].preview, "较新预览")
        self.assertEqual(sessions[0].cwd, "/work/new")

    def test_list_sessions_prefers_index_title_when_sqlite_title_has_reverted(self):
        self.write_index(
            [
                {
                    "id": "renamed",
                    "thread_name": "alpha｜已命名总览｜已命名近况",
                    "updated_at": "2026-07-08T01:02:03Z",
                    "cwd": "/work/alpha",
                }
            ]
        )
        log_path = self.write_log("renamed", [])
        self.write_state_threads(
            [
                (
                    "renamed",
                    str(log_path),
                    1783600000,
                    1783600000,
                    "live state reverted to original title",
                    0,
                    "user",
                    "live preview",
                    1783600000000,
                    "/work/alpha",
                )
            ]
        )

        sessions = SessionStore(self.index_path, self.codex_home).list_sessions()

        self.assertEqual(sessions[0].id, "renamed")
        self.assertEqual(
            sessions[0].thread_name,
            "alpha｜已命名总览｜已命名近况",
        )

    def test_rename_session_updates_sqlite_only_thread(self):
        self.write_index([])
        log_path = self.write_log("sqlite-only", [])
        self.write_state_threads(
            [
                (
                    "sqlite-only",
                    str(log_path),
                    1783500000,
                    1783500000,
                    "旧 SQLite 标题",
                    0,
                    "user",
                    "",
                    1783500000000,
                )
            ]
        )

        renamer = RecordingThreadRenamer(self.codex_home / "state_5.sqlite")
        backup_path = SessionStore(
            self.index_path,
            self.codex_home,
            thread_renamer=renamer,
        ).rename_session("sqlite-only", "新 SQLite 标题")

        self.assertTrue(backup_path.exists())
        self.assertEqual(
            renamer.calls,
            [{"sqlite-only": "新 SQLite 标题"}],
        )
        with sqlite3.connect(self.codex_home / "state_5.sqlite") as conn:
            self.assertEqual(
                conn.execute(
                    "select title from threads where id = 'sqlite-only'"
                ).fetchone()[0],
                "新 SQLite 标题",
            )

    def test_sqlite_rename_invalidates_in_process_session_list(self):
        self.write_index([])
        log_path = self.write_log("sqlite-cached", [])
        self.write_state_threads(
            [
                (
                    "sqlite-cached",
                    str(log_path),
                    100,
                    200,
                    "旧 SQLite 标题",
                    0,
                    "user",
                    "",
                    200000,
                    "/work/demo",
                )
            ]
        )
        renamer = RecordingThreadRenamer(self.codex_home / "state_5.sqlite")
        store = SessionStore(
            self.index_path,
            self.codex_home,
            thread_renamer=renamer,
        )
        self.assertEqual(store.list_sessions()[0].thread_name, "旧 SQLite 标题")

        store.rename_session("sqlite-cached", "新 SQLite 标题")

        self.assertEqual(store.list_sessions()[0].thread_name, "新 SQLite 标题")

    def test_delete_session_removes_sqlite_only_thread_and_moves_log_to_trash(self):
        self.write_index([])
        log_path = self.write_log("sqlite-only", [])
        self.write_state_threads(
            [
                (
                    "sqlite-only",
                    str(log_path),
                    1783500000,
                    1783500000,
                    "旧 SQLite 标题",
                    0,
                    "user",
                    "",
                    1783500000000,
                )
            ]
        )

        result = SessionStore(self.index_path, self.codex_home).delete_session("sqlite-only")

        with sqlite3.connect(self.codex_home / "state_5.sqlite") as conn:
            self.assertEqual(
                conn.execute("select count(*) from threads where id = 'sqlite-only'").fetchone()[0],
                0,
            )
        self.assertTrue(result.backup_path.exists())
        self.assertTrue(result.state_backup_path.exists())
        self.assertFalse(log_path.exists())
        self.assertEqual(len(result.moved_logs), 1)
        self.assertTrue(result.moved_logs[0].exists())

    def test_get_session_extracts_messages_and_preview(self):
        self.write_index(
            [
                {
                    "id": "abc123",
                    "thread_name": "旧标题",
                    "updated_at": "2026-07-08T01:02:03Z",
                }
            ]
        )
        self.write_log(
            "abc123",
            [
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
                {
                    "timestamp": "2026-07-08T01:00:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "我会先设计数据层。"}
                        ],
                    },
                },
            ],
        )

        detail = SessionStore(self.index_path, self.codex_home).get_session("abc123")

        self.assertEqual(len(detail.messages), 2)
        self.assertEqual(detail.messages[0].role, "user")
        self.assertIn("会话改名", detail.preview)
        self.assertIn("设计数据层", detail.preview)

    def test_rename_session_updates_only_matching_record_and_creates_backup(self):
        self.write_index(
            [
                {
                    "id": "abc123",
                    "thread_name": "旧标题",
                    "updated_at": "2026-07-08T01:02:03Z",
                },
                {
                    "id": "def456",
                    "thread_name": "另一个标题",
                    "updated_at": "2026-07-08T02:03:04Z",
                },
            ]
        )

        store = SessionStore(self.index_path, self.codex_home)
        backup_path = store.rename_session("abc123", "新标题")

        records = [
            json.loads(line)
            for line in self.index_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["thread_name"], "新标题")
        self.assertEqual(records[1]["thread_name"], "另一个标题")
        self.assertTrue(backup_path.exists())
        self.assertIn('"thread_name": "旧标题"', backup_path.read_text(encoding="utf-8"))

    def test_rename_rejects_blank_title(self):
        self.write_index(
            [
                {
                    "id": "abc123",
                    "thread_name": "旧标题",
                    "updated_at": "2026-07-08T01:02:03Z",
                }
            ]
        )

        with self.assertRaises(ValueError):
            SessionStore(self.index_path, self.codex_home).rename_session("abc123", " ")

    def test_delete_session_removes_index_record_and_moves_log_to_trash(self):
        self.write_index(
            [
                {
                    "id": "abc123",
                    "thread_name": "旧标题",
                    "updated_at": "2026-07-08T01:02:03Z",
                },
                {
                    "id": "def456",
                    "thread_name": "保留标题",
                    "updated_at": "2026-07-08T02:03:04Z",
                },
            ]
        )
        log_path = self.write_log("abc123", [])

        result = SessionStore(self.index_path, self.codex_home).delete_session("abc123")

        index_text = self.index_path.read_text(encoding="utf-8")
        self.assertNotIn("abc123", index_text)
        self.assertIn("def456", index_text)
        self.assertTrue(result.backup_path.exists())
        self.assertFalse(log_path.exists())
        self.assertEqual(len(result.moved_logs), 1)
        self.assertTrue(result.moved_logs[0].exists())
        self.assertIn("session-renamer-trash", str(result.moved_logs[0]))


if __name__ == "__main__":
    unittest.main()
