from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class CodexAppServerError(RuntimeError):
    pass


class CodexAppServerThreadRenamer:
    def __init__(
        self,
        codex_home: Path | str,
        binary_path: Path | str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.codex_home = Path(codex_home)
        self._auto_discover_binary = binary_path is None
        self.binary_path = Path(binary_path) if binary_path else _find_codex_binary()
        self.timeout = timeout

    def set_names(self, titles_by_id: dict[str, str]) -> None:
        if not titles_by_id:
            return

        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.codex_home)
        binary_path = self._binary_for_launch()
        process = subprocess.Popen(
            [str(binary_path), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        response_buffer = bytearray()
        try:
            self._send(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-session-renamer",
                            "version": "1",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            self._wait_for_response(process, 1, response_buffer)
            self._send(process, {"method": "initialized"})

            for request_id, (thread_id, title) in enumerate(
                titles_by_id.items(), start=2
            ):
                self._send(
                    process,
                    {
                        "id": request_id,
                        "method": "thread/name/set",
                        "params": {"threadId": thread_id, "name": title},
                    },
                )
                self._wait_for_response(process, request_id, response_buffer)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def _binary_for_launch(self) -> Path:
        if self.binary_path.is_file():
            return self.binary_path
        if self._auto_discover_binary:
            self.binary_path = _find_codex_binary()
            return self.binary_path
        raise CodexAppServerError(
            f"Configured Codex binary does not exist: {self.binary_path}"
        )

    def _send(self, process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise CodexAppServerError("Codex app-server stdin is unavailable")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        try:
            process.stdin.write(payload.encode("utf-8") + b"\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise self._process_error(process, "Codex app-server closed its input") from exc

    def _wait_for_response(
        self,
        process: subprocess.Popen[bytes],
        request_id: int,
        response_buffer: bytearray,
    ) -> dict[str, Any]:
        if process.stdout is None:
            raise CodexAppServerError("Codex app-server stdout is unavailable")

        deadline = time.monotonic() + self.timeout
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                while b"\n" in response_buffer:
                    raw_line, _, remainder = response_buffer.partition(b"\n")
                    response_buffer[:] = remainder
                    if not raw_line.strip():
                        continue
                    message = json.loads(raw_line)
                    if message.get("id") != request_id:
                        continue
                    if "error" in message:
                        raise CodexAppServerError(
                            f"Codex app-server request failed: {message['error']}"
                        )
                    return message

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexAppServerError(
                        f"Codex app-server request {request_id} timed out"
                    )
                if not selector.select(remaining):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if chunk:
                    response_buffer.extend(chunk)
                    continue
                raise self._process_error(process, "Codex app-server exited unexpectedly")
        finally:
            selector.close()

    def _process_error(
        self, process: subprocess.Popen[bytes], message: str
    ) -> CodexAppServerError:
        stderr = b""
        if process.stderr is not None and process.poll() is not None:
            stderr = process.stderr.read()
        detail = stderr.decode("utf-8", errors="replace").strip()
        return CodexAppServerError(f"{message}: {detail}" if detail else message)


def _find_codex_binary() -> Path:
    configured = os.environ.get("SESSION_RENAMER_CODEX_BIN")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        raise CodexAppServerError(f"Configured Codex binary does not exist: {path}")

    extension_root = Path.home() / ".vscode-server" / "extensions"
    extension_binaries = list(
        extension_root.glob("openai.chatgpt-*/bin/*/codex")
    )
    if extension_binaries:
        return max(extension_binaries, key=lambda path: path.stat().st_mtime)

    executable = shutil.which("codex")
    if executable:
        return Path(executable)
    raise CodexAppServerError("Could not find a Codex binary with app-server support")
