from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .qwen_title import TitleGenerator, create_title_generator
from .store import SessionStore


PROJECT_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=str(PROJECT_DIR / "templates"))
NO_RECOMMENDATION_TITLE = "暂无推荐"
PLACEHOLDER_TITLES = {"", "未命名", "未命名会话", NO_RECOMMENDATION_TITLE}


def create_app(
    store: SessionStore | None = None,
    access_token: str | None = None,
    title_generator: TitleGenerator | None = None,
) -> FastAPI:
    token = access_token if access_token is not None else os.environ.get("SESSION_RENAMER_TOKEN")
    if not token:
        raise RuntimeError("SESSION_RENAMER_TOKEN is required")

    app = FastAPI(title="Codex会话管理工具")
    app.state.store = store or SessionStore()
    app.state.access_token = token
    app.state.title_generator = title_generator or create_title_generator()
    app.state.title_cache_path = app.state.store.codex_home / "session-renamer-title-cache.json"
    app.state.title_cache = _load_title_cache(app.state.title_cache_path)
    app.state.title_cache_lock = threading.Lock()

    static_dir = PROJECT_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def require_token(request: Request) -> str:
        provided = (
            request.query_params.get("token")
            or request.headers.get("x-session-renamer-token")
            or request.cookies.get("session_renamer_token")
        )
        if provided != app.state.access_token:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        return provided

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        current_token = require_token(request)
        (
            all_sessions,
            directory_options,
            selected_directory,
            search_query,
            selected_needs_rename,
            selected_changed,
            sessions,
            details,
        ) = list_state_for_request(request)
        rows = []
        list_query = _list_query(
            current_token,
            selected_directory,
            search_query,
            needs_rename=selected_needs_rename,
            changed=selected_changed,
        )
        for session in sessions:
            detail = details[session.id]
            needs_model_rename = _needs_model_rename(session.thread_name, session.cwd)
            conversation_changed = _conversation_changed(detail, app.state.title_cache)
            needs_summary = needs_model_rename or conversation_changed
            if selected_needs_rename and not needs_model_rename:
                continue
            if selected_changed and not needs_summary:
                continue
            suggested_title = (
                suggested_title_for(detail)
                if needs_summary
                else _sanitize_title(session.thread_name)
            )
            can_use_suggestion = _is_actionable_title(suggested_title)
            rows.append(
                {
                    "session": session,
                    "display_thread_name": _display_thread_name(session.thread_name),
                    "suggested_title": suggested_title,
                    "rename_value": _rename_value(suggested_title, session.thread_name),
                    "can_use_suggestion": can_use_suggestion,
                    "needs_model_rename": needs_model_rename,
                    "conversation_changed": conversation_changed,
                    "needs_summary": needs_summary,
                }
            )
        sessions = [row["session"] for row in rows]
        groups = _build_directory_groups(rows)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "rows": rows,
                "groups": groups,
                "sessions": sessions,
                "total_count": len(all_sessions),
                "directory_options": directory_options,
                "selected_directory": selected_directory,
                "search_query": search_query,
                "status_message": _status_message(request.query_params.get("status", "")),
                "list_query": list_query,
                "selected_needs_rename": selected_needs_rename,
                "selected_changed": selected_changed,
                "token": current_token,
            },
        )

    @app.post("/auto-rename-all")
    async def auto_rename_all(request: Request) -> RedirectResponse:
        current_token = require_token(request)
        (
            _all_sessions,
            _directory_options,
            selected_directory,
            search_query,
            selected_needs_rename,
            selected_changed,
            sessions,
            details,
        ) = list_state_for_request(request)
        titles_by_id: dict[str, str] = {}
        for session in sessions:
            detail = details[session.id]
            needs_model_rename = _needs_model_rename(session.thread_name, session.cwd)
            needs_summary = needs_model_rename or _conversation_changed(
                detail,
                app.state.title_cache,
            )
            if selected_needs_rename and not needs_model_rename:
                continue
            if selected_changed and not needs_summary:
                continue
            suggested_title = suggested_title_for(detail)
            if _is_actionable_title(suggested_title):
                titles_by_id[session.id] = suggested_title
        try:
            app.state.store.rename_sessions(titles_by_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            url=_list_url(
                current_token,
                selected_directory,
                search_query,
                needs_rename=selected_needs_rename,
                changed=selected_changed,
                status="renamed_all",
            ),
            status_code=303,
        )

    @app.post("/recommend-all")
    async def recommend_all(request: Request) -> RedirectResponse:
        current_token = require_token(request)
        (
            _all_sessions,
            _directory_options,
            selected_directory,
            search_query,
            selected_needs_rename,
            selected_changed,
            sessions,
            details,
        ) = list_state_for_request(request)
        for session in sessions:
            detail = details[session.id]
            needs_model_rename = _needs_model_rename(session.thread_name, session.cwd)
            needs_summary = needs_model_rename or _conversation_changed(
                detail,
                app.state.title_cache,
            )
            if selected_needs_rename and not needs_model_rename:
                continue
            if selected_changed and not needs_summary:
                continue
            suggested_title_for(detail, refresh=_conversation_changed(detail, app.state.title_cache))
        return RedirectResponse(
            url=_list_url(
                current_token,
                selected_directory,
                search_query,
                needs_rename=selected_needs_rename,
                changed=selected_changed,
                status="recommended",
            ),
            status_code=303,
        )

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    def session_detail(request: Request, session_id: str) -> HTMLResponse:
        current_token = require_token(request)
        try:
            detail = app.state.store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        suggested_title = suggested_title_for(detail)
        can_use_suggestion = _is_actionable_title(suggested_title)
        return TEMPLATES.TemplateResponse(
            request,
            "session.html",
            {
                "session": detail,
                "display_thread_name": _display_thread_name(detail.thread_name),
                "suggested_title": suggested_title,
                "rename_value": _rename_value(suggested_title, detail.thread_name),
                "can_use_suggestion": can_use_suggestion,
                "status_message": _status_message(request.query_params.get("status", "")),
                "token": current_token,
            },
        )

    @app.get("/api/sessions/{session_id}/suggest")
    def suggest(request: Request, session_id: str) -> JSONResponse:
        require_token(request)
        try:
            detail = app.state.store.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return JSONResponse({"suggested_title": suggested_title_for(detail)})

    @app.post("/sessions/{session_id}/rename")
    async def rename(request: Request, session_id: str) -> RedirectResponse:
        current_token = require_token(request)
        body = (await request.body()).decode("utf-8")
        values = parse_qs(body, keep_blank_values=True)
        new_title = values.get("thread_name", [""])[0]
        try:
            app.state.store.rename_session(session_id, new_title)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        next_page = request.query_params.get("next")
        if next_page == "list":
            return RedirectResponse(
                url=_list_url(
                    current_token,
                    request.query_params.get("directory", ""),
                    request.query_params.get("q", ""),
                    needs_rename=_selected_needs_rename(
                        request.query_params.get("needs_rename", "")
                    ),
                    changed=_selected_changed(request.query_params.get("changed", "")),
                    status="renamed",
                ),
                status_code=303,
            )
        return RedirectResponse(
            url=_session_url(session_id, current_token, status="renamed"),
            status_code=303,
        )

    @app.post("/sessions/{session_id}/auto-rename")
    async def auto_rename(request: Request, session_id: str) -> RedirectResponse:
        current_token = require_token(request)
        try:
            detail = app.state.store.get_session(session_id)
            suggested_title = suggested_title_for(detail)
            if _is_actionable_title(suggested_title):
                app.state.store.rename_session(session_id, suggested_title)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            url=_session_url(session_id, current_token, status="renamed"),
            status_code=303,
        )

    @app.post("/sessions/{session_id}/delete")
    async def delete_session(request: Request, session_id: str) -> RedirectResponse:
        current_token = require_token(request)
        try:
            app.state.store.delete_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return RedirectResponse(
            url=_list_url(
                current_token,
                request.query_params.get("directory", ""),
                request.query_params.get("q", ""),
                needs_rename=_selected_needs_rename(
                    request.query_params.get("needs_rename", "")
                ),
                changed=_selected_changed(request.query_params.get("changed", "")),
                status="deleted",
            ),
            status_code=303,
        )

    def list_state_for_request(request: Request):
        all_sessions = app.state.store.list_sessions()
        directory_options = _build_directory_options(all_sessions)
        selected_directory = _selected_directory(
            request.query_params.get("directory", ""),
            directory_options,
        )
        search_query = _search_query(request.query_params.get("q", ""))
        selected_needs_rename = _selected_needs_rename(
            request.query_params.get("needs_rename", "")
        )
        selected_changed = _selected_changed(request.query_params.get("changed", ""))
        directory_sessions = _filter_sessions_by_directory(all_sessions, selected_directory)
        details = {}
        for session in directory_sessions:
            try:
                details[session.id] = app.state.store.get_session(session.id)
            except KeyError:
                continue
        sessions = _filter_sessions_by_search(directory_sessions, details, search_query)
        details = {session.id: details[session.id] for session in sessions if session.id in details}
        return (
            all_sessions,
            directory_options,
            selected_directory,
            search_query,
            selected_needs_rename,
            selected_changed,
            sessions,
            details,
        )

    def suggested_title_for(detail, refresh: bool = False) -> str:
        cache_key = _title_cache_key(detail)
        cached = None
        if not refresh:
            with app.state.title_cache_lock:
                cached = app.state.title_cache.get(cache_key)
        if cached:
            return _title_with_directory_prefix(detail.cwd, cached)
        try:
            raw_title = app.state.title_generator.suggest(detail.messages, detail.thread_name)
        except Exception:
            raw_title = detail.thread_name
        title = _content_title_for_directory(raw_title, detail.cwd)
        with app.state.title_cache_lock:
            app.state.title_cache[cache_key] = title
            _save_title_cache(app.state.title_cache_path, app.state.title_cache)
        return _title_with_directory_prefix(detail.cwd, title)

    def suggested_titles_for(details) -> dict[str, str]:
        if not details:
            return {}
        max_workers = max(
            1,
            min(
                int(os.environ.get("SESSION_RENAMER_TITLE_WORKERS", "6")),
                len(details),
            ),
        )
        if max_workers == 1:
            return {detail.id: suggested_title_for(detail) for detail in details}
        titles: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(suggested_title_for, detail): detail.id
                for detail in details
            }
            for future in as_completed(futures):
                titles[futures[future]] = future.result()
        return titles

    return app


def _load_title_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _save_title_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _title_cache_key(detail) -> str:
    messages = [
        [message.role, message.timestamp or "", message.text]
        for message in getattr(detail, "messages", [])
    ]
    payload = [
        "v5-conversation-content",
        detail.id,
        messages,
        getattr(detail, "preview", ""),
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sanitize_title(title: str) -> str:
    clean = _clean_whitespace(title)
    if _is_placeholder_title(clean):
        return NO_RECOMMENDATION_TITLE
    parts = _title_parts(clean)
    if not parts:
        return NO_RECOMMENDATION_TITLE
    if len(parts) > 3:
        parts = [parts[0], parts[1], "；".join(parts[2:])]
    clean = "｜".join(parts)
    if len(clean) > 120:
        clean = clean[:120].rstrip(" ，。,.：:；;|｜")
    return clean or NO_RECOMMENDATION_TITLE


def _content_title_for_directory(raw_title: str, cwd: str) -> str:
    clean = _sanitize_title(raw_title)
    if not _is_actionable_title(clean):
        return NO_RECOMMENDATION_TITLE
    parts = _title_parts(clean)
    directory = _directory_title_component(cwd)
    if len(parts) >= 3 and parts[0] == directory:
        parts = parts[1:]
    if len(parts) > 2:
        parts = [parts[0], "；".join(parts[1:])]
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if not parts:
        return NO_RECOMMENDATION_TITLE
    return "｜".join(
        [
            _truncate_title_component(parts[0], 32),
            _truncate_title_component(parts[1], 56),
        ]
    )


def _title_with_directory_prefix(cwd: str, content_title: str) -> str:
    content = _content_title_for_directory(content_title, cwd)
    if not _is_actionable_title(content):
        return NO_RECOMMENDATION_TITLE
    parts = _title_parts(content)
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    return "｜".join(
        [
            _directory_title_component(cwd),
            _truncate_title_component(parts[0], 32),
            _truncate_title_component(parts[1], 56),
        ]
    )


def _title_parts(title: str) -> list[str]:
    clean = _clean_whitespace(title)
    parts = [
        _truncate_title_component(part, 120)
        for part in re.split(r"[|｜]", clean)
        if part.strip(" ，。,.：:；;|｜")
    ]
    return [part for part in parts if part]


def _clean_whitespace(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate_title_component(value: str, limit: int) -> str:
    component = _clean_whitespace(value).strip(" ，。,.：:；;|｜")
    component = re.sub(r"\s*[|｜]\s*", "；", component)
    if len(component) <= limit:
        return component
    return component[:limit].rstrip(" ，。,.：:；;|｜")


def _directory_title_component(cwd: str) -> str:
    raw_directory = str(cwd or "").strip()
    directory = Path(raw_directory).name if raw_directory else ""
    return _truncate_title_component(directory or raw_directory or "未记录目录", 28)


def _is_placeholder_title(title: str) -> bool:
    return " ".join(title.strip().split()) in PLACEHOLDER_TITLES


def _is_actionable_title(title: str) -> bool:
    return not _is_placeholder_title(title)


def _display_thread_name(title: str) -> str:
    if _is_placeholder_title(title):
        return "未设置标题"
    return title


def _rename_value(suggested_title: str, current_title: str) -> str:
    if _is_actionable_title(suggested_title):
        return suggested_title
    if _is_placeholder_title(current_title):
        return ""
    return current_title


def _needs_model_rename(current_title: str, cwd: str = "") -> bool:
    return not _is_model_renamed_title(current_title, cwd)


def _is_model_renamed_title(title: str, cwd: str = "") -> bool:
    parts = _title_parts(title)
    if len(parts) < 3:
        return False
    directory = _directory_title_component(cwd)
    if parts[0] != directory:
        return False
    return all(_is_actionable_title(part) for part in parts[:3])


def _conversation_changed(detail, title_cache: dict[str, str]) -> bool:
    return _title_cache_key(detail) not in title_cache


def _build_directory_groups(rows):
    groups_by_directory = {}
    for row in rows:
        directory = _directory_label(getattr(row["session"], "cwd", ""))
        group = groups_by_directory.setdefault(
            directory,
            {"directory": directory, "rows": []},
        )
        group["rows"].append(row)
    return [
        {**group, "count": len(group["rows"])}
        for group in groups_by_directory.values()
    ]


def _directory_label(cwd: str) -> str:
    directory = str(cwd or "").strip()
    return directory or "未记录目录"


def _build_directory_options(sessions):
    options_by_directory = {}
    for session in sessions:
        directory = _directory_label(getattr(session, "cwd", ""))
        option = options_by_directory.setdefault(
            directory,
            {"directory": directory, "count": 0},
        )
        option["count"] += 1
    return list(options_by_directory.values())


def _selected_directory(raw_directory: str, directory_options) -> str:
    directory = str(raw_directory or "").strip()
    valid_directories = {option["directory"] for option in directory_options}
    if directory in valid_directories:
        return directory
    return ""


def _filter_sessions_by_directory(sessions, selected_directory: str):
    if not selected_directory:
        return sessions
    return [
        session
        for session in sessions
        if _directory_label(getattr(session, "cwd", "")) == selected_directory
    ]


def _search_query(raw_query: str) -> str:
    return " ".join(str(raw_query or "").strip().split())


def _selected_needs_rename(raw_value: str) -> bool:
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def _selected_changed(raw_value: str) -> bool:
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def _filter_sessions_by_search(sessions, details_by_id, search_query: str):
    if not search_query:
        return sessions
    needle = search_query.casefold()
    matched = []
    for session in sessions:
        detail = details_by_id.get(session.id)
        if not detail:
            continue
        if needle in _session_search_text(session, detail).casefold():
            matched.append(session)
    return matched


def _session_search_text(session, detail) -> str:
    pieces = [
        getattr(session, "thread_name", ""),
        getattr(detail, "thread_name", ""),
        getattr(session, "preview", ""),
        getattr(detail, "preview", ""),
    ]
    pieces.extend(message.text for message in getattr(detail, "messages", []))
    return "\n".join(piece for piece in pieces if piece)


def _status_message(status: str) -> str:
    if status == "recommended":
        return "已完成一键标题推荐"
    if status == "renamed":
        return "已改名会话"
    if status == "renamed_all":
        return "已完成一键全部改名"
    if status == "deleted":
        return "已删除会话"
    return ""


def _list_query(
    token: str,
    directory: str = "",
    search_query: str = "",
    needs_rename: bool = False,
    changed: bool = False,
    status: str = "",
) -> str:
    values = [("token", token)]
    if directory:
        values.append(("directory", directory))
    if search_query:
        values.append(("q", _search_query(search_query)))
    if needs_rename:
        values.append(("needs_rename", "1"))
    if changed:
        values.append(("changed", "1"))
    if status:
        values.append(("status", status))
    return urlencode(values)


def _list_url(
    token: str,
    directory: str = "",
    search_query: str = "",
    needs_rename: bool = False,
    changed: bool = False,
    status: str = "",
) -> str:
    return f"/?{_list_query(token, directory, search_query, needs_rename, changed, status)}"


def _session_url(session_id: str, token: str, status: str = "") -> str:
    values = [("token", token)]
    if status:
        values.append(("status", status))
    return f"/sessions/{session_id}?{urlencode(values)}"
