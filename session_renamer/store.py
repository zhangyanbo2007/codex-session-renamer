from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CODEX_HOME = Path("/home/zhangyanbo/.codex")
DEFAULT_INDEX_PATH = DEFAULT_CODEX_HOME / "session_index.jsonl"


@dataclass(frozen=True)
class SessionMessage:
    role: str
    text: str
    timestamp: str | None


@dataclass(frozen=True)
class SessionSummary:
    id: str
    thread_name: str
    updated_at: str
    log_path: Path | None
    cwd: str = ""
    preview: str = ""
    message_count: int = 0


@dataclass(frozen=True)
class SessionDetail:
    id: str
    thread_name: str
    updated_at: str
    log_path: Path | None
    messages: list[SessionMessage]
    preview: str
    cwd: str = ""


@dataclass(frozen=True)
class DeleteResult:
    backup_path: Path
    moved_logs: list[Path]
    state_backup_path: Path | None = None


class SessionStore:
    def __init__(
        self,
        index_path: Path | str = DEFAULT_INDEX_PATH,
        codex_home: Path | str = DEFAULT_CODEX_HOME,
    ) -> None:
        self.index_path = Path(index_path)
        self.codex_home = Path(codex_home)

    def list_sessions(self) -> list[SessionSummary]:
        records = self._read_session_records()
        log_paths = self._find_log_paths(records)
        summaries: list[SessionSummary] = []
        for record in records:
            session_id = str(record["id"])
            log_path = record.get("log_path") or log_paths.get(session_id)
            messages = self._read_messages(log_path) if log_path else []
            preview = self._make_preview(messages, limit=180) or str(record.get("preview", ""))
            summaries.append(
                SessionSummary(
                    id=session_id,
                    thread_name=str(record.get("thread_name", "")),
                    updated_at=str(record.get("updated_at", "")),
                    log_path=log_path,
                    cwd=str(record.get("cwd", "")),
                    preview=preview,
                    message_count=len(messages),
                )
            )
        return summaries

    def get_session(self, session_id: str) -> SessionDetail:
        record = self._record_for(session_id)
        log_path = record.get("log_path") or self._find_log_paths([record]).get(session_id)
        messages = self._read_messages(log_path) if log_path else []
        preview = self._make_preview(messages, limit=500) or str(record.get("preview", ""))
        return SessionDetail(
            id=str(record["id"]),
            thread_name=str(record.get("thread_name", "")),
            updated_at=str(record.get("updated_at", "")),
            log_path=log_path,
            messages=messages,
            preview=preview,
            cwd=str(record.get("cwd", "")),
        )

    def rename_session(self, session_id: str, new_title: str) -> Path:
        clean_title = self._clean_title(new_title)

        records = self._read_index_records()
        matched_index = False
        changed_index = False
        for record in records:
            if str(record.get("id")) == session_id:
                if record.get("thread_name") != clean_title:
                    record["thread_name"] = clean_title
                    changed_index = True
                matched_index = True
                break

        matched_state = self._state_thread_exists(session_id)
        if not matched_index and not matched_state:
            raise KeyError(f"session id not found: {session_id}")

        backup_path = self._backup_index() if changed_index else None
        if changed_index:
            self._write_index_records(records)

        state_backup_path = None
        if matched_state:
            state_backup_path = self._backup_state()
            self._update_state_title(session_id, clean_title)

        return backup_path or state_backup_path or self._backup_index()

    def rename_sessions(self, titles_by_id: dict[str, str]) -> Path | None:
        clean_titles = {
            str(session_id): self._clean_title(title)
            for session_id, title in titles_by_id.items()
        }
        if not clean_titles:
            return None

        session_ids = {str(record["id"]) for record in self._read_session_records()}
        missing_ids = set(clean_titles) - session_ids
        if missing_ids:
            raise KeyError(f"session id not found: {sorted(missing_ids)[0]}")

        records = self._read_index_records()
        changed_index = False
        matched_ids: set[str] = set()
        for record in records:
            session_id = str(record.get("id"))
            if session_id not in clean_titles:
                continue
            matched_ids.add(session_id)
            if record.get("thread_name") != clean_titles[session_id]:
                record["thread_name"] = clean_titles[session_id]
                changed_index = True

        state_titles = {
            session_id: title
            for session_id, title in clean_titles.items()
            if self._state_thread_exists(session_id)
        }
        if not changed_index and not state_titles:
            return None

        backup_path = self._backup_index() if changed_index else None
        if changed_index:
            self._write_index_records(records)
        state_backup_path = None
        if state_titles:
            state_backup_path = self._backup_state()
            self._update_state_titles(state_titles)
        return backup_path or state_backup_path

    def delete_session(self, session_id: str) -> DeleteResult:
        if not self._record_exists(session_id):
            raise KeyError(f"session id not found: {session_id}")

        records = self._read_index_records()
        remaining = [record for record in records if str(record.get("id")) != session_id]

        record = self._record_for(session_id)
        log_paths = self._matching_log_paths(session_id)
        if record.get("log_path") and record["log_path"] not in log_paths:
            log_paths.append(record["log_path"])
        backup_path = self._backup_index()
        if len(remaining) != len(records):
            self._write_index_records(remaining)

        state_backup_path = None
        if self._state_thread_exists(session_id):
            state_backup_path = self._backup_state()
            self._delete_state_thread(session_id)

        moved_logs: list[Path] = []
        if log_paths:
            trash_dir = self.codex_home / "session-renamer-trash" / datetime.now().strftime(
                "%Y%m%d-%H%M%S"
            )
            trash_dir.mkdir(parents=True, exist_ok=True)
            for log_path in log_paths:
                target = trash_dir / log_path.name
                counter = 1
                while target.exists():
                    target = trash_dir / f"{log_path.stem}-{counter}{log_path.suffix}"
                    counter += 1
                shutil.move(str(log_path), str(target))
                moved_logs.append(target)
        return DeleteResult(
            backup_path=backup_path,
            moved_logs=moved_logs,
            state_backup_path=state_backup_path,
        )

    def _read_index_records(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.index_path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if "id" not in record:
                    raise ValueError(f"missing id at line {line_number}")
                records.append(self._normalize_index_record(record))
        return records

    def _record_for(self, session_id: str) -> dict[str, Any]:
        for record in self._read_session_records():
            if str(record.get("id")) == session_id:
                return record
        raise KeyError(f"session id not found: {session_id}")

    def _read_session_records(self) -> list[dict[str, Any]]:
        index_records = {str(record["id"]): record for record in self._read_index_records()}
        records_by_id = dict(index_records)
        sqlite_ids, sqlite_records = self._read_state_thread_records()
        if sqlite_ids:
            records_by_id = {
                session_id: record
                for session_id, record in records_by_id.items()
                if session_id not in sqlite_ids
            }
            for record in sqlite_records:
                session_id = str(record["id"])
                index_record = index_records.get(session_id)
                if index_record:
                    merged = dict(record)
                    index_title = str(index_record.get("thread_name", "")).strip()
                    if index_title:
                        merged["thread_name"] = index_title
                    index_cwd = str(index_record.get("cwd", "")).strip()
                    if index_cwd and not str(merged.get("cwd", "")).strip():
                        merged["cwd"] = index_cwd
                    records_by_id[session_id] = merged
                else:
                    records_by_id[session_id] = record
        return sorted(
            records_by_id.values(),
            key=lambda record: int(record.get("sort_key", 0)),
            reverse=True,
        )

    def _normalize_index_record(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(record)
        normalized["thread_name"] = str(
            normalized.get("thread_name") or normalized.get("title") or ""
        )
        normalized["updated_at"] = str(normalized.get("updated_at", ""))
        normalized["cwd"] = str(normalized.get("cwd", ""))
        normalized["sort_key"] = self._sort_key_for_updated_at(normalized["updated_at"])
        return normalized

    def _sort_key_for_updated_at(self, value: str) -> int:
        if not value:
            return 0
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return int(parsed.timestamp() * 1000)

    def _find_log_paths(self, records: list[dict[str, Any]]) -> dict[str, Path]:
        ids = [str(record["id"]) for record in records]
        candidates = list((self.codex_home / "sessions").glob("**/*.jsonl"))
        candidates.extend((self.codex_home / "archived_sessions").glob("*.jsonl"))
        mapping: dict[str, Path] = {}
        for session_id in ids:
            matches = [path for path in candidates if session_id in path.name]
            if matches:
                mapping[session_id] = max(matches, key=lambda path: path.stat().st_mtime)
        return mapping

    def _matching_log_paths(self, session_id: str) -> list[Path]:
        candidates = list((self.codex_home / "sessions").glob("**/*.jsonl"))
        candidates.extend((self.codex_home / "archived_sessions").glob("*.jsonl"))
        return sorted(path for path in candidates if session_id in path.name)

    def _state_path(self) -> Path:
        return self.codex_home / "state_5.sqlite"

    def _read_state_thread_records(self) -> tuple[set[str], list[dict[str, Any]]]:
        state_path = self._state_path()
        if not state_path.exists():
            return set(), []
        with sqlite3.connect(f"file:{state_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            all_ids = {
                str(row["id"])
                for row in conn.execute("select id from threads").fetchall()
            }
            cwd_expr = "cwd" if self._column_exists(conn, "threads", "cwd") else "'' as cwd"
            rows = conn.execute(
                f"""
                select id, title, rollout_path, updated_at, updated_at_ms, preview, {cwd_expr}
                from threads
                where coalesce(archived, 0) = 0
                  and coalesce(thread_source, 'user') = 'user'
                """
            ).fetchall()
        records = [self._thread_row_to_record(row) for row in rows]
        return all_ids, records

    def _thread_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        updated_at_ms = row["updated_at_ms"]
        updated_at = row["updated_at"]
        sort_key = int(updated_at_ms or ((updated_at or 0) * 1000))
        rollout_path = Path(row["rollout_path"]) if row["rollout_path"] else None
        return {
            "id": str(row["id"]),
            "thread_name": str(row["title"] or ""),
            "updated_at": self._format_timestamp(updated_at, updated_at_ms),
            "sort_key": sort_key,
            "log_path": rollout_path if rollout_path and rollout_path.exists() else None,
            "preview": str(row["preview"] or ""),
            "cwd": str(row["cwd"] or ""),
        }

    def _format_timestamp(self, seconds: int | None, millis: int | None) -> str:
        if millis:
            stamp = millis / 1000
        elif seconds:
            stamp = seconds
        else:
            return ""
        return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    def _record_exists(self, session_id: str) -> bool:
        return any(str(record.get("id")) == session_id for record in self._read_session_records())

    def _state_thread_exists(self, session_id: str) -> bool:
        state_path = self._state_path()
        if not state_path.exists():
            return False
        with sqlite3.connect(state_path) as conn:
            return (
                conn.execute(
                    "select 1 from threads where id = ? limit 1",
                    (session_id,),
                ).fetchone()
                is not None
            )

    def _update_state_title(self, session_id: str, title: str) -> None:
        self._update_state_titles({session_id: title})

    def _update_state_titles(self, titles_by_id: dict[str, str]) -> None:
        if not titles_by_id:
            return
        with sqlite3.connect(self._state_path()) as conn:
            conn.executemany(
                "update threads set title = ? where id = ?",
                [(title, session_id) for session_id, title in titles_by_id.items()],
            )

    def _delete_state_thread(self, session_id: str) -> None:
        with sqlite3.connect(self._state_path()) as conn:
            if self._table_exists(conn, "thread_dynamic_tools"):
                conn.execute("delete from thread_dynamic_tools where thread_id = ?", (session_id,))
            if self._table_exists(conn, "thread_spawn_edges"):
                conn.execute(
                    "delete from thread_spawn_edges where parent_thread_id = ? or child_thread_id = ?",
                    (session_id, session_id),
                )
            conn.execute("delete from threads where id = ?", (session_id,))

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        return (
            conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    def _column_exists(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(row[1] == column for row in conn.execute(f"pragma table_info({table})"))

    def _read_messages(self, log_path: Path) -> list[SessionMessage]:
        messages: list[SessionMessage] = []
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue
                role = str(payload.get("role", ""))
                if role not in {"user", "assistant"}:
                    continue
                text = self._content_to_text(payload.get("content"))
                if not text:
                    continue
                messages.append(
                    SessionMessage(role=role, text=text, timestamp=obj.get("timestamp"))
                )
        return messages

    def _content_to_text(self, content: Any) -> str:
        pieces: list[str] = []
        if isinstance(content, str):
            pieces.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    pieces.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        pieces.append(text)
        elif isinstance(content, dict):
            text = content.get("text") or content.get("content")
            if isinstance(text, str):
                pieces.append(text)
        return "\n".join(piece.strip() for piece in pieces if piece.strip())

    def _make_preview(self, messages: list[SessionMessage], limit: int) -> str:
        joined = " ".join(message.text.replace("\n", " ") for message in messages[:4])
        joined = " ".join(joined.split())
        if len(joined) <= limit:
            return joined
        return joined[: limit - 1].rstrip() + "..."

    def _clean_title(self, title: str) -> str:
        clean_title = " ".join(title.strip().split())
        if not clean_title:
            raise ValueError("title cannot be blank")
        if len(clean_title) > 120:
            raise ValueError("title must be 120 characters or fewer")
        return clean_title

    def _write_index_records(self, records: list[dict[str, Any]]) -> None:
        tmp_path = self.index_path.with_name(f".{self.index_path.name}.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            for record in records:
                output = {
                    key: value
                    for key, value in record.items()
                    if key not in {"sort_key", "log_path", "preview"}
                }
                fh.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(tmp_path, self.index_path)

    def _backup_index(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.index_path.with_name(f"{self.index_path.name}.bak-{stamp}")
        counter = 1
        while backup_path.exists():
            backup_path = self.index_path.with_name(
                f"{self.index_path.name}.bak-{stamp}-{counter}"
            )
            counter += 1
        shutil.copy2(self.index_path, backup_path)
        return backup_path

    def _backup_state(self) -> Path:
        state_path = self._state_path()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = state_path.with_name(f"{state_path.name}.bak-{stamp}")
        counter = 1
        while backup_path.exists():
            backup_path = state_path.with_name(f"{state_path.name}.bak-{stamp}-{counter}")
            counter += 1
        shutil.copy2(state_path, backup_path)
        return backup_path
