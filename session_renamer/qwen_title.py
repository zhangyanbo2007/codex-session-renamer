from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .store import SessionMessage
from .title_suggester import format_combined_title, suggest_title, summary_title_context


DASHSCOPE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen-turbo"


class TitleGenerator(Protocol):
    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        ...


class LocalTitleGenerator:
    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        return suggest_title(messages, fallback=fallback)


class QwenTitleGenerator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DASHSCOPE_CHAT_URL,
        timeout: float = 8.0,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.opener = opener or _default_opener()
        self.local = LocalTitleGenerator()

    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        context = summary_title_context(messages)
        if not context:
            return fallback

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 96,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 Codex 会话标题生成器。只输出一行组合标题，格式必须是："
                        "<总摘要标题>｜<最近2轮摘要标题>。"
                        "只能包含一个分隔符“｜”。两个标题都要短，不要输出路径、日期、编号、引号、解释、标点结尾。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "根据以下清洗后的会话线索生成“总摘要标题+最近2轮摘要标题”。"
                        "若内容只是路径、环境上下文或无明确任务，输出“暂无推荐”。\n\n"
                        f"{context}"
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            raw_title = data["choices"][0]["message"]["content"]
        except (KeyError, json.JSONDecodeError, OSError, urllib.error.URLError):
            return self.local.suggest(messages, fallback=fallback)

        title = normalize_model_title(str(raw_title))
        if title:
            return title
        return self.local.suggest(messages, fallback=fallback)


def create_title_generator() -> TitleGenerator:
    provider = os.environ.get("SESSION_RENAMER_TITLE_PROVIDER", "qwen").strip().lower()
    if provider == "local":
        return LocalTitleGenerator()

    api_key = _env_value(
        "SESSION_RENAMER_DASHSCOPE_API_KEY",
        "DASHSCOPE_API_KEY",
        "DASH_SCOPE_API_KEY",
    )
    if not api_key:
        return LocalTitleGenerator()
    return QwenTitleGenerator(
        api_key=api_key,
        model=os.environ.get("SESSION_RENAMER_QWEN_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("SESSION_RENAMER_QWEN_BASE_URL", DASHSCOPE_CHAT_URL),
        timeout=float(os.environ.get("SESSION_RENAMER_QWEN_TIMEOUT", "8")),
    )


def normalize_model_title(raw_title: str) -> str:
    title = raw_title.strip().strip("\"'“”‘’` ")
    title = re.sub(r"^(标题|推荐标题|会话名|名称)\s*[:：]\s*", "", title)
    title = title.replace("总摘要标题", "总")
    title = title.replace("总标题", "总")
    title = title.replace("最近两轮摘要标题", "近2轮")
    title = title.replace("最近2轮摘要标题", "近2轮")
    title = title.replace("近两轮摘要标题", "近2轮")
    title = title.replace("近两轮", "近2轮")
    title = re.sub(r"[\r\n]+", "｜", title)
    title = re.sub(r"\s+", " ", title)
    title = title.strip(" ，。,.：:；;\"'“”‘’`")
    if not title:
        return ""
    if title in {"未命名", "未命名会话", "暂无推荐"}:
        return ""
    if _looks_like_path(title):
        return ""
    title = _strip_summary_labels(title)
    if "｜" not in title:
        title = format_combined_title(title, title)
    else:
        overall, recent = title.split("｜", 1)
        title = format_combined_title(overall, recent)
    if len(title) > 120:
        title = title[:120].rstrip(" ，。,.：:；;|｜")
    return title


def _strip_summary_labels(title: str) -> str:
    title = re.sub(r"^总[:：]\s*", "", title)
    title = re.sub(r"\s*[|｜]\s*近2轮[:：]\s*", "｜", title)
    title = re.sub(r"\s+近2轮[:：]\s*", "｜", title)
    title = re.sub(r"^近2轮[:：]\s*", "", title)
    title = re.sub(r"\s*[|｜]\s*", "｜", title)
    return title.strip(" ，。,.：:；;|｜")


def _looks_like_path(value: str) -> bool:
    return bool(
        re.search(r"(^|\s)/home/[^ ]+", value)
        or re.search(r"(^|\s)/(tmp|var|usr|etc|opt|root|data|mnt)/[^ ]+", value)
        or re.search(r"[A-Za-z]:\\", value)
    )


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip("\"'")

    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() in names:
            return value.strip().strip("\"'")
    return ""


def _default_opener() -> urllib.request.OpenerDirector:
    proxy = os.environ.get("SESSION_RENAMER_QWEN_PROXY", "").strip()
    if not proxy and _local_proxy_open():
        proxy = "http://127.0.0.1:7897"
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def _local_proxy_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 7897), timeout=0.2):
            return True
    except OSError:
        return False
