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

INPUT_TOKEN_RESERVE = 1_000
MAX_RECENT_CONTEXT_CHARS = 20_000


def meaningful_user_candidates(messages: Iterable[SessionMessage]) -> list[str]:
    candidates: list[str] = []
    for message in _messages_without_first_user(messages):
        if message.role != "user":
            continue
        candidate = _clean_candidate(message.text)
        if candidate:
            candidates.append(candidate)
    return candidates


def summary_title_context(
    messages: Iterable[SessionMessage], max_tokens: int = 100_000
) -> str:
    message_list = list(messages)
    budget = max(0, max_tokens - INPUT_TOKEN_RESERVE)
    recent_section = recent_title_context(
        message_list, max_chars=min(MAX_RECENT_CONTEXT_CHARS, budget)
    )
    separator = 2 if recent_section else 0
    overall_section = _overall_title_context_with_budget(
        message_list, max(0, budget - len(recent_section) - separator)
    )
    return "\n\n".join(section for section in (overall_section, recent_section) if section)


def overall_title_context(
    messages: Iterable[SessionMessage], max_tokens: int = 100_000
) -> str:
    return _overall_title_context_with_budget(
        messages, max(0, max_tokens - INPUT_TOKEN_RESERVE)
    )


def _overall_title_context_with_budget(
    messages: Iterable[SessionMessage], budget: int
) -> str:
    overall_chunks = meaningful_user_candidates(messages)
    overall_prefix = "总任务线索：\n"
    all_lines = [f"- {chunk}" for chunk in overall_chunks]
    if len(overall_prefix) + len("\n".join(all_lines)) <= budget:
        overall_lines = all_lines
    else:
        overall_lines = _first_and_newest_lines(all_lines, budget - len(overall_prefix))
    return overall_prefix + "\n".join(overall_lines) if overall_lines else ""


def _first_and_newest_lines(lines: list[str], budget: int) -> list[str]:
    if not lines or budget <= 2:
        return []
    if len(lines) == 1:
        return [lines[0][:budget]]
    newest_reserve = min(len(lines[-1]), max(4, budget // 3))
    first_budget = max(3, budget - newest_reserve - 1)
    first = lines[0][:first_budget]
    selected = [first]
    remaining = budget - len(first)
    newest_lines = []
    for line in reversed(lines[1:]):
        required = len(line) + 1
        if required <= remaining:
            newest_lines.append(line)
            remaining -= required
        elif not newest_lines and remaining > 3:
            newest_lines.append(line[: remaining - 1])
            break
        else:
            break
    selected.extend(reversed(newest_lines))
    return selected


def recent_title_context(
    messages: Iterable[SessionMessage], max_chars: int = MAX_RECENT_CONTEXT_CHARS
) -> str:
    recent_chunks = []
    for index, round_messages in enumerate(_recent_rounds(list(messages)), start=1):
        user_text = round_messages.get("user")
        assistant_text = round_messages.get("assistant")
        if user_text:
            recent_chunks.append(f"第{index}轮用户：{user_text}")
        if assistant_text:
            recent_chunks.append(f"第{index}轮助手：{assistant_text}")
    if not recent_chunks or max_chars <= len("最近2轮：\n"):
        return ""
    prefix = "最近2轮：\n"
    full_context = prefix + "\n".join(recent_chunks)
    if len(full_context) <= max_chars:
        return full_context
    available = max_chars - len(prefix) - max(0, len(recent_chunks) - 1)
    chunk_limit = max(1, available // len(recent_chunks))
    bounded_chunks = [chunk[:chunk_limit] for chunk in recent_chunks]
    return (prefix + "\n".join(bounded_chunks))[:max_chars]


def format_combined_title(overall: str, recent: str) -> str:
    overall_title = _truncate_component(overall, 32)
    recent_title = _truncate_component(recent or overall_title, 72)
    return f"{overall_title}｜{recent_title}"


def _clean_candidate(text: str) -> str:
    if any(marker in text for marker in NOISE_MARKERS):
        return ""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
    cleaned = re.sub(
        r"(?<!\S)/(?:home|tmp|var|usr|etc|opt|root|data|mnt)/[^\s，。,]+",
        _project_name_from_path,
        cleaned,
    )
    cleaned = re.sub(r"<codex_internal_context.*?</codex_internal_context>", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<environment_context>.*?</environment_context>", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<[^>]{1,80}>", " ", cleaned)
    cleaned = cleaned.replace("Task Name:", " ")
    cleaned = cleaned.replace("任务名：", " ")
    cleaned = cleaned.replace("任务名:", " ")
    cleaned = re.sub(r"^Rename this task to:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(
        r"(?:帮忙|请)?看看需求[，。,、\s]*(?:怎么实现)?[，。,、\s]*(?:给个方案)?",
        " ",
        cleaned,
    )
    lines = [line.strip(" \t\r\n，。,.：:；;()（）[]【】") for line in cleaned.splitlines()]
    lines = [line for line in lines if line and not _is_noise_line(line)]
    if not lines:
        return ""
    cleaned = " ".join(lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if _is_noise_line(cleaned):
        return ""
    return cleaned


def _project_name_from_path(match: re.Match[str]) -> str:
    path = match.group(0).rstrip("/")
    basename = path.rsplit("/", 1)[-1]
    return basename if "." not in basename else " "


def _truncate_component(candidate: str, limit: int) -> str:
    candidate = candidate.strip(" ，。,.：:；;|｜")
    candidate = re.sub(r"\s*[|｜]\s*", "；", candidate)
    if len(candidate) <= limit:
        return candidate
    return candidate[:limit].rstrip(" ，。,.：:；;|｜")


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
