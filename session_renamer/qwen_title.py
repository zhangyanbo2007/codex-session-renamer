from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Protocol

from .store import SessionMessage
from .title_suggester import (
    format_combined_title,
    overall_title_context,
    recent_title_context,
)


DASHSCOPE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3.5-flash"


class TitleGenerator(Protocol):
    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        ...


class ExistingTitleGenerator:
    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        return fallback


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

    def suggest(self, messages: list[SessionMessage], fallback: str) -> str:
        overall_context = overall_title_context(messages)
        if not overall_context:
            return "暂无推荐"
        raw_overall = self._complete(
            (
                "你是 Codex 会话整体任务标题生成器。只输出一个自然的任务名称。"
                "标题必须直接标识核心任务，采用“具体对象+工作动作或目标+任务”，并以“任务”结尾。"
                "“任务”前必须有明确的项目、产品、人物、工具或成果名称，严禁只输出“任务”。"
                "先识别任务对象、目标成果和主要动作，禁止复制用户原句、疑问句、路径或临时进度。"
                "把故障现象改写为排查、修复或分析任务，把需求讨论改写为设计或实现任务。"
                "例如：黄子晨动画HTML制作任务、跨境视频需求分析任务、Codex插件故障排查任务。"
                "对于只有产品名或工具名的稀疏会话，也要结合助手回复推断宽泛但具体的咨询或使用任务，"
                "例如用户只说“codex”时生成“Codex使用咨询任务”，不能输出“暂无推荐”。"
                "只有纯问候、纯测试或完全无对象内容时输出“暂无推荐”。"
            ),
            (
                f"当前标题（仅作为任务线索，不要照抄）：{fallback}\n\n"
                f"根据完整会话线索生成整体任务标题：\n\n{overall_context}"
            ),
        )
        overall_title = _parse_component(raw_overall)
        if _is_generic_title(overall_title):
            overall_title = _parse_component(fallback)
        if _is_generic_title(overall_title):
            return "暂无推荐"

        recent_context = recent_title_context(messages)
        if not recent_context:
            return format_combined_title(overall_title, overall_title)
        raw_recent = self._complete(
            (
                "你是 Codex 会话最近状态标题生成器。只输出一个简短状态标题，不要输出整体标题。"
                "必须围绕给定的整体任务，概括最近2轮正在处理的具体工作、结果或阻塞。"
                "不能照抄“进度如何、现在呢、好了吗”等追问，也不要输出路径、解释或标点结尾。"
            ),
            f"整体任务：{overall_title}\n\n{recent_context}",
        )
        recent_title = _parse_component(raw_recent)
        if _is_generic_title(recent_title):
            recent_title = overall_title
        rewritten_recent = self._complete(
            (
                "你是 Codex 会话状态标题审校器。只输出一个简短状态标题。"
                "根据整体任务审校模型草稿，只保留抽象工作状态、结果或阻塞；"
                "删除文件路径、命令、解释、寒暄和句末标点，不要输出整体标题。"
                "不得增加对话中不存在的事实。"
            ),
            f"整体任务：{overall_title}\n最近状态草稿：{recent_title}",
        )
        recent_title = _parse_component(rewritten_recent) or recent_title
        if _is_generic_title(recent_title):
            recent_title = overall_title
        return format_combined_title(overall_title, recent_title)

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "enable_thinking": False,
            "temperature": 0.2,
            "max_tokens": 96,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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
            return ""
        return str(raw_title)


def create_title_generator() -> TitleGenerator:
    provider = os.environ.get("SESSION_RENAMER_TITLE_PROVIDER", "qwen").strip().lower()
    if provider == "local":
        return ExistingTitleGenerator()

    api_key = _env_value(
        "SESSION_RENAMER_DASHSCOPE_API_KEY",
        "DASHSCOPE_API_KEY",
        "DASH_SCOPE_API_KEY",
    )
    if not api_key:
        return ExistingTitleGenerator()
    return QwenTitleGenerator(
        api_key=api_key,
        model=os.environ.get("SESSION_RENAMER_QWEN_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("SESSION_RENAMER_QWEN_BASE_URL", DASHSCOPE_CHAT_URL),
        timeout=float(os.environ.get("SESSION_RENAMER_QWEN_TIMEOUT", "8")),
    )


def _parse_component(raw_title: str) -> str:
    title = str(raw_title or "").strip().strip("\"'“”‘’` ")
    title = re.sub(r"^(标题|推荐标题|会话名|名称)\s*[:：]\s*", "", title)
    title = re.sub(r"[\r\n]+", " ", title)
    title = re.sub(r"\s+", " ", title)
    title = title.split("｜", 1)[0]
    title = title.strip(" ，。,.：:；;\"'“”‘’`|｜")
    if title in {"未命名", "未命名会话", "暂无推荐"}:
        return ""
    return title


def _is_generic_title(title: str) -> bool:
    normalized = re.sub(r"\s+", "", str(title or "")).lower()
    if not normalized:
        return True
    if normalized in {"hello", "hi", "hey", "test", "demo", "ok", "okay", "你好", "您好", "测试"}:
        return True
    if normalized.isascii() and normalized.isalpha() and len(normalized) <= 2:
        return True
    return False


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
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
