from __future__ import annotations

import re
from collections.abc import Iterable

from .store import SessionMessage


NOISE_MARKERS = (
    "<codex_internal_context",
    "AGENTS.md instructions",
    "<environment_context>",
    "Continue working toward the active thread goal",
    "Workspace Rules",
    "permission_profile",
)


def suggest_title(messages: Iterable[SessionMessage], fallback: str = "未命名会话") -> str:
    candidates = meaningful_user_candidates(messages)
    if candidates:
        overall = _title_for_candidate(candidates[0])
        recent = "；".join(_title_for_candidate(candidate) for candidate in candidates[-2:])
        return format_combined_title(overall, recent)
    return fallback


def meaningful_user_candidates(messages: Iterable[SessionMessage]) -> list[str]:
    candidates: list[str] = []
    for message in _messages_without_first_user(messages):
        if message.role != "user":
            continue
        candidate = _clean_candidate(message.text)
        if candidate:
            candidates.append(candidate)
    return candidates


def title_context(messages: Iterable[SessionMessage], max_chars: int = 1600) -> str:
    chunks = meaningful_user_candidates(messages)[:6]
    context = "\n".join(f"- {chunk}" for chunk in chunks)
    if len(context) <= max_chars:
        return context
    return context[:max_chars].rsplit("\n", 1)[0].strip()


def summary_title_context(messages: Iterable[SessionMessage], max_chars: int = 3200) -> str:
    message_list = list(messages)
    overall_chunks = meaningful_user_candidates(message_list)[:8]
    recent_chunks = []
    for index, round_messages in enumerate(_recent_rounds(message_list), start=1):
        user_text = round_messages.get("user")
        assistant_text = round_messages.get("assistant")
        if user_text:
            recent_chunks.append(f"第{index}轮用户：{_truncate_context(user_text)}")
        if assistant_text:
            recent_chunks.append(f"第{index}轮助手：{_truncate_context(assistant_text)}")

    sections = []
    if overall_chunks:
        sections.append("总任务线索：\n" + "\n".join(f"- {_truncate_context(chunk)}" for chunk in overall_chunks))
    if recent_chunks:
        sections.append("最近2轮：\n" + "\n".join(recent_chunks))
    context = "\n\n".join(sections)
    if len(context) <= max_chars:
        return context
    return context[:max_chars].rsplit("\n", 1)[0].strip()


def format_combined_title(overall: str, recent: str) -> str:
    overall_title = _truncate_component(overall, 32)
    recent_title = _truncate_component(recent or overall_title, 72)
    return f"{overall_title}｜{recent_title}"


def _clean_candidate(text: str) -> str:
    if any(marker in text for marker in NOISE_MARKERS):
        return ""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
    cleaned = re.sub(r"<codex_internal_context.*?</codex_internal_context>", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<environment_context>.*?</environment_context>", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<[^>]{1,80}>", " ", cleaned)
    cleaned = cleaned.replace("Task Name:", " ")
    cleaned = cleaned.replace("任务名：", " ")
    cleaned = cleaned.replace("任务名:", " ")
    cleaned = re.sub(r"^Rename this task to:\s*", "", cleaned, flags=re.I)
    lines = [line.strip(" \t\r\n，。,.：:；;()（）[]【】") for line in cleaned.splitlines()]
    lines = [line for line in lines if line and not _is_noise_line(line)]
    if not lines:
        return ""
    cleaned = " ".join(lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if _is_noise_line(cleaned):
        return ""
    return cleaned


def _keyword_title(candidate: str) -> str | None:
    if "会话" in candidate and ("改名" in candidate or "重命名" in candidate):
        return "Codex会话管理工具"
    if "会话" in candidate and ("管理" in candidate or "删除" in candidate):
        return "Codex会话管理工具"
    if "FRP" in candidate.upper() and ("访问" in candidate or "暴露" in candidate):
        return "FRP 访问配置"
    if "测试" in candidate and len(candidate) <= 12:
        return candidate
    return None


def _title_for_candidate(candidate: str) -> str:
    mapped = _keyword_title(candidate)
    return mapped or _truncate_title(candidate)


def _truncate_title(candidate: str) -> str:
    candidate = candidate.strip(" ，。,.：:；;")
    if len(candidate) <= 28:
        return candidate
    return candidate[:28].rstrip(" ，。,.：:；;")


def _truncate_component(candidate: str, limit: int) -> str:
    candidate = candidate.strip(" ，。,.：:；;|｜")
    candidate = re.sub(r"\s*[|｜]\s*", "；", candidate)
    if len(candidate) <= limit:
        return candidate
    return candidate[:limit].rstrip(" ，。,.：:；;|｜")


def _truncate_context(candidate: str, limit: int = 260) -> str:
    candidate = " ".join(candidate.split())
    if len(candidate) <= limit:
        return candidate
    return candidate[:limit].rstrip(" ，。,.：:；;") + "..."


def _recent_rounds(messages: list[SessionMessage], limit: int = 2) -> list[dict[str, str]]:
    rounds: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for message in _messages_without_first_user(messages):
        cleaned = _clean_candidate(message.text)
        if not cleaned:
            continue
        if message.role == "user":
            current = {"user": cleaned}
            rounds.append(current)
        elif message.role == "assistant" and current is not None:
            existing = current.get("assistant", "")
            current["assistant"] = f"{existing} {cleaned}".strip()
    return rounds[-limit:]


def _messages_without_first_user(
    messages: Iterable[SessionMessage],
) -> Iterable[SessionMessage]:
    skipped_first_user = False
    for message in messages:
        if message.role == "user" and not skipped_first_user:
            skipped_first_user = True
            continue
        yield message


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.search(r"(^|\s)/home/[^ ]+", stripped):
        return True
    if re.search(r"(^|\s)/(tmp|var|usr|etc|opt|root|data|mnt)/[^ ]+", stripped):
        return True
    if re.search(r"[A-Za-z]:\\", stripped):
        return True
    if stripped.startswith(("<", "{", "[")) and len(stripped) > 80:
        return True
    if "AGENTS.md" in stripped or "environment_context" in stripped:
        return True
    if len(stripped) < 4 and "/" in stripped:
        return True
    return False
