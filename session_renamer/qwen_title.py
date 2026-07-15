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
            return fallback
        recent_context = recent_title_context(messages)
        overall_evidence = "\n\n".join(
            section for section in (overall_context, recent_context) if section
        )
        overall_system_prompt = (
            "你是 Codex 会话整体任务标题生成器。只输出一个自然的任务名称。"
            "标题必须直接标识核心任务，采用“具体对象+工作动作或目标+任务”，并以“任务”结尾。"
            "“任务”前必须有明确的项目、产品、人物、工具或成果名称，严禁只输出“任务”。"
            "路径、附件名、文件名及扩展名，以及截图、图片、文件、代码和日志，"
            "都只是承载任务线索的输入载体，不能单独作为任务对象。"
            "先识别任务对象、目标成果和主要动作，禁止复制用户原句、疑问句、路径或临时进度。"
            "把故障现象改写为排查、修复或分析任务，把需求讨论改写为设计或实现任务。"
            "例如：产品演示动画HTML制作任务、跨境视频需求分析任务、Codex插件故障排查任务。"
            "对于只有产品名或工具名的稀疏会话，也要结合助手回复推断宽泛但具体的咨询或使用任务，"
            "例如用户只说“codex”时生成“Codex使用咨询任务”，不能输出“暂无推荐”。"
            "只有纯问候、纯测试或完全无对象内容时输出“暂无推荐”。"
        )
        overall_user_prompt = (
            f"当前标题（仅作为任务线索，不要照抄）：{fallback}\n\n"
            f"根据完整会话线索生成整体任务标题：\n\n{overall_evidence}"
        )
        raw_overall = self._complete(
            overall_system_prompt,
            overall_user_prompt,
        )
        raw_review = self._complete(
            (
                "你是 Codex 会话整体任务标题质量审校器。审查候选，并在必要时直接纠正。"
                "必须只输出严格 JSON 对象，不要 Markdown 或解释，格式为："
                '{"acceptable": true, "title": "具体任务标题任务"}。'
                "acceptable 必须是布尔值，title 必须是字符串并以“任务”结尾。"
                "路径、附件名、文件名、扩展名、截图、图片、文件、代码和日志可能只是输入载体；"
                "要结合会话证据区分纯载体与真正具体的产品、系统、仓库、服务器或编辑器对象。"
                "应拒绝或改写：screenshot.png任务、截图分析任务、日志诊断任务。"
                "可接受：Node.js升级任务、Vue.js迁移任务、代码仓库迁移任务、"
                "文件服务器修复任务、图片编辑器开发任务。"
                "如果能依据同一证据纠正为具体标题，返回 acceptable=true 和纠正后的 title；"
                "如果证据不足以得到合格标题，返回 acceptable=false 和空 title。"
            ),
            f"初始候选：{raw_overall}\n\n{overall_user_prompt}",
        )
        overall_title = _parse_overall_review(raw_review)
        if not overall_title:
            return "暂无推荐"

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
        if not recent_title:
            return "暂无推荐"
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


def _overall_title_failure(title: str) -> str:
    if not title:
        return "候选标题为空"
    if not title.endswith("任务"):
        return "候选标题没有以任务结尾"
    task_object = re.sub(r"\s+", "", title[: -len("任务")])
    if not task_object:
        return "候选标题缺少具体任务对象"
    if _contains_unmistakable_path(task_object):
        return "候选标题包含明确文件路径"
    return ""


_UNIX_ABSOLUTE_PATH = re.compile(
    r"/(?:home|tmp|var|usr|etc|opt|root|data|mnt)(?:/|$)"
)
_WINDOWS_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/]")
_DOT_TRAVERSAL_PATH = re.compile(r"(?<!\.)\.\.?[\\/]")


def _contains_unmistakable_path(title: str) -> bool:
    return bool(
        _UNIX_ABSOLUTE_PATH.search(title)
        or _WINDOWS_DRIVE_PATH.search(title)
        or _DOT_TRAVERSAL_PATH.search(title)
    )


def _parse_overall_review(raw_review: str) -> str:
    try:
        review = json.loads(raw_review)
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(review, dict) or set(review) != {"acceptable", "title"}:
        return ""
    if type(review["acceptable"]) is not bool or not isinstance(review["title"], str):
        return ""
    if not review["acceptable"]:
        return ""
    title = re.sub(r"\s+", " ", review["title"]).strip()
    return "" if _overall_title_failure(title) else title


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
