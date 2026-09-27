#!/usr/bin/env python3
"""A dependency-free MCP bridge between a host AI and its partner AI.

The server intentionally uses only the Python standard library.  It exposes a
small, workspace-confined tool surface and launches Codex/Claude in isolated
non-interactive processes so the two agents cannot recursively call the bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "0.10.0"
MAX_TASK_CHARS = 20_000
MAX_CONTEXT_CHARS = 40_000
MAX_AGENT_OUTPUT_CHARS = 40_000
MAX_SNAPSHOT_CHARS = 30_000
GIT_STATUS_TIMEOUT_SECONDS = 8
MAX_GIT_STATUS_CHARS = 20_000
GIT_STATUS_EXCLUDES = (".python-runtime", ".pytest_cache")
DEFAULT_TIMEOUT_SECONDS = 3600
CODEX_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
CLAUDE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
DEFAULT_CODEX_CONSULT_MODEL = "gpt-5.6-terra"
DEFAULT_CODEX_DEBATE_MODEL = "gpt-5.6-terra"
DEFAULT_CODEX_IMPLEMENT_MODEL = "gpt-5.6-sol"
DEFAULT_CLAUDE_MODEL = "sonnet"
# 协作伙伴 Claude 固定使用命令行登录的 Claude 账号（claude auth login）：
# 只读项目级/本机级配置（--setting-sources project,local），跳过用户级 ~/.claude/settings.json，
# 其中第三方供应商切换工具（如 CC Switch）写入的地址与令牌不会影响协作调用。
CLAUDE_OFFICIAL_ARGS = ["--setting-sources", "project,local"]


def claude_official_args(workspace: Path | None) -> list[str]:
    """工作区恰好是用户主目录时，其“项目级”配置 ~/.claude/settings.json 就是用户级配置本身，
    其中的第三方供应商设置会被重新读入；这种情况只读本机级（local）配置。"""
    try:
        at_home = workspace is not None and Path(workspace).resolve() == Path.home().resolve()
    except OSError:
        at_home = False
    return ["--setting-sources", "local"] if at_home else list(CLAUDE_OFFICIAL_ARGS)
# 宿主注入的变量不能漏给协作 Claude：ANTHROPIC_* 会盖过上面的账号选择，
# CLAUDE_CODE_* 会话变量会让子进程误以为自己嵌在宿主会话里。保留 Windows 必需的 GIT_BASH_PATH。
HOST_ENV_KEEP = {"CLAUDE_CODE_GIT_BASH_PATH"}


def _system_proxy() -> str | None:
    """读取 Windows 系统代理（Internet Settings 里的 ProxyServer）。

    图形界面程序（Claude/Codex App）会自动走系统代理，命令行程序不会：直连时 Anthropic/OpenAI
    接口可能不可达或被拒绝。为协作 CLI 补上 HTTP(S)_PROXY，行为才与 App 一致。
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return None
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except OSError:
        return None
    if not server:
        return None
    if "=" in server:  # 形如 http=host:port;https=host:port
        parts = dict(item.split("=", 1) for item in server.split(";") if "=" in item)
        server = parts.get("https") or parts.get("http") or ""
    if not server:
        return None
    return server if "://" in server else "http://" + server


def _with_proxy(env: dict[str, str]) -> dict[str, str]:
    if any(env.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")):
        return env
    proxy = _system_proxy()
    if proxy:
        env = dict(env, HTTPS_PROXY=proxy, HTTP_PROXY=proxy)
        env.setdefault("NO_PROXY", "localhost,127.0.0.1,::1")
    return env


def _claude_oauth_get(path: str, timeout: float = 15.0) -> Any:
    """用命令行 claude auth login 留下的凭证 GET 官方接口（模型列表、账号用量）。

    令牌只在本进程内读取并直接发往 api.anthropic.com，不写日志、不转交其他进程；
    失败（未登录、令牌过期、网络不通）返回 None。
    """
    try:
        cred = json.loads((Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        token = (cred.get("claudeAiOauth") or {}).get("accessToken")
    except (OSError, ValueError, AttributeError):
        return None
    if not token:
        return None
    import urllib.request
    request = urllib.request.Request(
        "https://api.anthropic.com" + path,
        headers={"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01",
                 "anthropic-beta": "oauth-2025-04-20"},
    )
    proxy = next((os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY") if os.environ.get(k)), None)
    proxy = proxy or _system_proxy()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy} if proxy else {}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def _claude_account_models() -> list[dict[str, Any]]:
    """该 Claude 账号当前可用的模型（/v1/models），按发布时间新到旧。"""
    payload = _claude_oauth_get("/v1/models?limit=100") or {}
    models = [{"id": item["id"], "label": item.get("display_name") or item["id"],
               "created_at": item.get("created_at")}
              for item in payload.get("data") or [] if item.get("id")]
    models.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return models


def claude_rate_limits() -> dict[str, Any] | None:
    """Claude 账号的 5 小时 / 每周额度占用（与 Claude App 设置页“用量”同一来源），实时读取。"""
    payload = _claude_oauth_get("/api/oauth/usage")
    if not isinstance(payload, dict):
        return None

    def window(key: str) -> dict[str, Any] | None:
        value = payload.get(key) or {}
        if value.get("utilization") is None:
            return None
        resets = value.get("resets_at")
        try:
            epoch = int(datetime.fromisoformat(str(resets).replace("Z", "+00:00")).timestamp()) if resets else None
        except ValueError:
            epoch = None
        return {"used_percent": value["utilization"], "resets_at": epoch}

    return {"primary": window("five_hour"), "secondary": window("seven_day"),
            "source": "claude", "observed_at": utc_now()}


def _cli_version(path: str) -> tuple[int, ...]:
    try:
        completed = _hidden_run([path, "--version"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=15, stdin=subprocess.DEVNULL)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", completed.stdout or "")
        return tuple(int(x) for x in match.groups()) if match else (0,)
    except (OSError, subprocess.SubprocessError):
        return (0,)


def _detect_host() -> str:
    """未显式配置宿主时，按宿主注入的环境变量判断：Claude Code 设置 CLAUDE_PLUGIN_ROOT/CLAUDECODE。"""
    if os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("CLAUDECODE"):
        return "claude"
    if any(key.startswith("CODEX_") for key in os.environ):
        return "codex"
    return "auto"


SECRET_NAME_PATTERNS = (".env", "*.env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
                        "*credentials*", "*secret*", "*.token", ".netrc", ".npmrc", ".pypirc")


def _looks_secret(name: str) -> bool:
    """快照不列出、也不读取像密钥/凭据的文件（它们的内容会被发给另一端 AI）。"""
    import fnmatch
    lower = name.lower()
    return any(fnmatch.fnmatch(lower, pattern) for pattern in SECRET_NAME_PATTERNS)


def _host_env_var(name: str) -> bool:
    upper = name.upper()
    if upper in HOST_ENV_KEEP:
        return False
    return upper.startswith("ANTHROPIC_") or upper == "CLAUDECODE" or upper.startswith("CLAUDE_CODE_")
# The host caches MCP UI templates by resource URI. Bump this URI whenever the
# embedded HTML/JS changes incompatibly so an older blank iframe is not reused.
PARTNER_SELECTOR_URI = "ui://ai-coop/partner-selector-v2.html"
PARTNER_SELECTOR_PATH = Path(__file__).resolve().parents[1] / "assets" / "partner-selector.html"
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

MODEL_CATALOG = {
    "codex": [
        {"id": "gpt-6-astra", "label": "GPT-6 Astra", "tier": "deep"},
        {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "tier": "quality"},
        {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "tier": "balanced"},
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "tier": "fast"},
    ],
    "claude": [
        {"id": "opus", "label": "Claude Opus", "tier": "deep"},
        {"id": "sonnet", "label": "Claude Sonnet", "tier": "balanced"},
        {"id": "haiku", "label": "Claude Haiku", "tier": "fast"},
    ],
}


def ordered_efforts(values: Any) -> list[str]:
    unique = {str(value).strip().lower() for value in values if str(value).strip()}
    return sorted(
        unique,
        key=lambda value: (
            EFFORT_ORDER.index(value) if value in EFFORT_ORDER else len(EFFORT_ORDER),
            value,
        ),
    )


def ui_resources() -> list[dict[str, Any]]:
    return [
        {
            "uri": PARTNER_SELECTOR_URI,
            "name": "ai-coop-partner-selector",
            "title": "AI Coop 协作模型选择",
            "description": "紧凑显示另一端 AI 的模型与推理强度选择。",
            "mimeType": "text/html;profile=mcp-app",
        }
    ]


def read_ui_resource(uri: str) -> dict[str, Any]:
    if uri != PARTNER_SELECTOR_URI:
        raise ValueError(f"未知 UI 资源：{uri}")
    html = PARTNER_SELECTOR_PATH.read_text(encoding="utf-8")
    return {
        "contents": [
            {
                "uri": PARTNER_SELECTOR_URI,
                "mimeType": "text/html;profile=mcp-app",
                "text": html,
                "_meta": {"ui": {"prefersBorder": False}},
            }
        ]
    }


def prompt_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "open_ai_coop",
            "title": "打开 AI 协作",
            "description": "检查 AI Coop 连接，并在当前对话显示协作模型与推理强度选择。",
            "arguments": [],
        }
    ]


def read_prompt(name: str) -> dict[str, Any]:
    if name != "open_ai_coop":
        raise ValueError(f"未知提示入口：{name}")
    return {
        "description": "打开 AI Coop 协作控制",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "请调用 ai-coop 的 health_check 检查协作桥。若连接正常，"
                        "调用 set_collaboration_mode 启用自动协作，再调用 "
                        "show_partner_selector 恰好一次。此后用户只需正常描述任务，"
                        "主对话 AI 自动调用另一端协作；不要要求用户再输入 workflow。"
                        "若连接失败，只报告失败项。"
                    ),
                },
            }
        ],
    }


# MCP 服务由 pythonw（无控制台）启动；Windows 上它再启动 codex.exe / claude.exe 这类控制台程序时
# 会为子进程新开一个终端窗口。统一加 CREATE_NO_WINDOW，协作调用全程不弹窗。
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _hidden_run(*args: Any, **kwargs: Any) -> "subprocess.CompletedProcess[Any]":
    return subprocess.run(*args, **{**_NO_WINDOW, **kwargs})


def _hidden_popen(*args: Any, **kwargs: Any) -> "subprocess.Popen[Any]":
    return subprocess.Popen(*args, **{**_NO_WINDOW, **kwargs})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_runs_dir() -> Path:
    # 不放在 %LOCALAPPDATA%：MSIX 打包的宿主（Claude 桌面版）会把 AppData 下新建的文件
    # 重定向到包内虚拟目录，临时文件与目标文件落在不同盘，replace 报 WinError 17；
    # 两个宿主也会各看到一份不同的记录。用户主目录不受重定向影响。
    if os.name == "nt":
        return Path.home() / ".ai-coop" / "runs"
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "ai-coop" / "runs"
    return Path.home() / ".local" / "state" / "ai-coop" / "runs"


def replace_file(temp: Path, target: Path) -> None:
    """原子替换；若宿主文件系统虚拟化导致跨盘（WinError 17），退回直接写入。"""
    try:
        temp.replace(target)
    except OSError:
        target.write_bytes(temp.read_bytes())
        temp.unlink(missing_ok=True)


def safe_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"输入过长：最多允许 {limit} 个字符")
    return text


def safe_model(value: Any, default: str) -> str:
    model = safe_text(value or default, 100)
    if not model or any(ch.isspace() for ch in model):
        raise ValueError("模型名称不能为空或包含空白字符")
    return model


def safe_effort(value: Any, default: str, allowed: set[str]) -> str:
    effort = safe_text(value or default, 20).lower()
    if effort not in allowed:
        raise ValueError(f"不支持的推理强度：{effort}")
    return effort


class Bridge:
    def __init__(
        self,
        root: Path | None,
        runs_dir: Path,
        allow_write: bool,
        codex_exe: str | None,
        claude_exe: str | None,
        timeout_seconds: int,
        host_agent: str = "auto",
    ) -> None:
        # A fixed root is optional. Installed plugins run in per-call workspace
        # mode so the native chat can pass whichever folder is currently open.
        # Tests and standalone deployments may still opt into a fixed root.
        self.root = root.resolve() if root else None
        self.runs_dir = runs_dir.resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.allow_write = allow_write
        # Resolve lazily. One unavailable CLI must not prevent the bridge from
        # starting or the other AI from being used.
        self.codex_configured = (
            codex_exe
            or os.environ.get("AI_COOP_CODEX_EXE")
            or os.environ.get("CODEX_CLI_PATH")
        )
        self.claude_configured = claude_exe or os.environ.get("AI_COOP_CLAUDE_EXE")
        self.timeout_seconds = timeout_seconds
        configured_host = safe_text(
            os.environ.get("AI_COOP_HOST_AGENT") or host_agent or _detect_host(), 20
        ).lower()
        if configured_host not in {"auto", "codex", "claude"}:
            raise ValueError("host_agent 必须是 auto、codex 或 claude")
        self.host_agent = configured_host
        self._write_lock = threading.Lock()
        # 每个协作任务在独立线程里运行；记下当前线程对应的 run_dir，
        # 让 _run_process 把协作 AI 的事件流逐行写进 stream.jsonl，面板可实时查看。
        self._job_local = threading.local()

    def resolve_host_agent(self, value: Any = None) -> str:
        requested = safe_text(value or "auto", 20).lower()
        if requested not in {"auto", "codex", "claude"}:
            raise ValueError("primary_agent 必须是 auto、codex 或 claude")
        resolved = self.host_agent if requested == "auto" else requested
        if resolved == "auto":
            raise ValueError(
                "无法识别主对话 AI。请通过 --host-agent 配置宿主，或传入 primary_agent。"
            )
        return resolved

    @staticmethod
    def partner_for(primary_agent: str) -> str:
        return "claude" if primary_agent == "codex" else "codex"

    @staticmethod
    def _resolve_executable(configured: str | None, fallback: str) -> str | None:
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                return str(path.resolve())
            found = shutil.which(configured)
            if found:
                return found
            # Codex App 每次自更新都会换掉 bin/<hash>/ 这一层目录名，写死的绝对路径
            # 会在更新后失效并导致 MCP 服务启动即退出。若配置路径形如
            # .../bin/<hash>/<exe>，就在其祖父目录下按修改时间挑最新的同名可执行文件。
            parent = path.parent
            if parent.name and parent.parent.is_dir():
                candidates = sorted(
                    (c for c in parent.parent.glob(f"*/{path.name}") if c.is_file()),
                    key=lambda c: c.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    return str(candidates[0].resolve())
            return shutil.which(fallback)
        found = shutil.which(fallback)
        if found:
            return found

        # GUI hosts often start with a reduced PATH. Discover the CLIs from
        # their standard Windows install locations without opening a terminal.
        candidates: list[Path] = []
        if fallback == "codex":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                bin_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
                if bin_root.is_dir():
                    candidates.extend(bin_root.glob("*/codex.exe"))
        elif fallback == "claude":
            windows_dir = os.environ.get("WINDIR")
            if windows_dir:
                candidates.append(Path(windows_dir) / "System32" / "claude.exe")
        existing = [path for path in candidates if path.is_file()]
        if not existing:
            return None
        return str(max(existing, key=lambda path: path.stat().st_mtime).resolve())

    def _newest_claude(self) -> str | None:
        """在 PATH、System32 与 Claude App 自带的 Claude Code 里选版本最高的一个。

        旧版 CLI 会把 opus/sonnet 别名解析到旧型号；Claude App 会自动更新它自带的那份，
        通常最新。App 自带版本的版本号直接取目录名，其余调用一次 --version（结果缓存 10 分钟）。
        """
        cached = getattr(self, "_claude_exe_cache", None)
        if cached and time.monotonic() - cached[0] < 600:
            return cached[1]
        found: dict[str, tuple[int, ...]] = {}
        on_path = shutil.which("claude")
        if on_path:
            found[str(Path(on_path).resolve())] = ()
        windows_dir = os.environ.get("WINDIR")
        if windows_dir and (Path(windows_dir) / "System32" / "claude.exe").is_file():
            found.setdefault(str((Path(windows_dir) / "System32" / "claude.exe").resolve()), ())
        roots = []
        if os.environ.get("APPDATA"):
            roots.append(Path(os.environ["APPDATA"]) / "Claude" / "claude-code")
        if os.environ.get("LOCALAPPDATA"):
            roots.extend(Path(os.environ["LOCALAPPDATA"], "Packages").glob("Claude_*/LocalCache/Roaming/Claude/claude-code"))
        for root in roots:
            for exe in root.glob("*/claude.exe"):
                match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", exe.parent.name)
                if match and exe.is_file():
                    found[str(exe.resolve())] = tuple(int(x) for x in match.groups())
        for path, version in list(found.items()):
            if not version:
                found[path] = _cli_version(path)
        best = max(found.items(), key=lambda kv: kv[1])[0] if found else None
        self._claude_exe_cache = (time.monotonic(), best)
        return best

    def executable(self, agent: str, required: bool = True) -> str | None:
        configured = self.codex_configured if agent == "codex" else self.claude_configured
        if agent == "claude" and not configured:
            newest = self._newest_claude()
            if newest:
                return newest
        found = self._resolve_executable(configured, agent)
        if found or not required:
            return found
        env_name = f"AI_COOP_{agent.upper()}_EXE"
        raise FileNotFoundError(
            f"找不到 {agent} CLI。请安装并登录，或设置环境变量 {env_name} 后重启宿主。"
        )

    def resolve_workspace(self, value: Any) -> Path:
        raw = safe_text(value, 2_000)
        if not raw and self.root is None:
            raise ValueError("请传入当前聊天正在使用的项目目录")
        raw = raw or "."
        candidate = Path(raw)
        if not candidate.is_absolute():
            if self.root is None:
                raise ValueError("请传入当前聊天正在使用的项目目录")
            candidate = self.root / candidate
        candidate = candidate.resolve()
        if self.root is not None:
            try:
                candidate.relative_to(self.root)
            except ValueError as exc:
                raise ValueError(f"工作区必须位于允许的根目录内：{self.root}") from exc
        if not candidate.is_dir():
            raise ValueError(f"工作区不存在或不是目录：{candidate}")
        return candidate

    def resolve_file(self, workspace: Path, value: Any) -> Path:
        raw = safe_text(value, 2_000)
        if not raw:
            raise ValueError("path 不能为空")
        candidate = (workspace / raw).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError("文件必须位于所选工作区内") from exc
        if not candidate.is_file():
            raise ValueError(f"文件不存在：{candidate}")
        return candidate

    def _run_path(self, run_id: str) -> Path:
        if not run_id or any(ch not in "0123456789abcdef-" for ch in run_id.lower()):
            raise ValueError("无效的 run_id")
        return self.runs_dir / run_id

    def workspace_snapshot(self, workspace: Path) -> str:
        """Build a bounded, read-only evidence packet for nested agents.

        A nested Codex process can be denied shell access by the parent desktop
        app's policy even when its own sandbox is read-only.  Supplying this
        snapshot keeps consultations evidence-based without granting more
        permissions to the child process.
        """
        ignored_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules",
                        ".ssh", ".aws", ".gnupg", ".idea", ".vscode"}
        file_lines: list[str] = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace)
            parts = set(relative.parts)
            if parts & ignored_dirs or _looks_secret(relative.name):
                continue
            if len(relative.parts) >= 2 and relative.parts[0] == ".ai-coop" and relative.parts[1] == "runs":
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            file_lines.append(f"- {relative.as_posix()} ({size} bytes)")
            if len(file_lines) >= 400:
                file_lines.append("- …文件清单已截断…")
                break

        sections = [
            f"工作区：{workspace}",
            "\n文件清单：\n" + ("\n".join(file_lines) or "- （空）"),
            "\n工作区状态：\n" + self.project_status({"workspace": str(workspace)}),
        ]
        remaining = MAX_SNAPSHOT_CHARS - len("\n".join(sections))
        for name in self._context_files(workspace):
            path = workspace / name
            if not path.is_file() or remaining <= 500:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            excerpt = text[: min(6_000, remaining - 200)]
            section = f"\n{name}：\n{excerpt}"
            sections.append(section)
            remaining -= len(section)
        return "\n".join(sections)[:MAX_SNAPSHOT_CHARS]

    DEFAULT_CONTEXT_FILES = (
        "AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", "README.md",
        "PROJECT_BRIEF.md", "docs/PROJECT_BRIEF.md", "DECISIONS.md", "HANDOFF.md", "WORKFLOW.md",
    )

    @classmethod
    def _context_files(cls, workspace: Path) -> list[str]:
        """快照里附带给协作 AI 的项目说明文件。

        项目根目录若有 .ai-coop-context（每行一个相对路径，# 开头为注释），按它列出的顺序读取；
        否则读取常见的说明文件。只接受工作区内的相对路径。
        """
        listing = workspace / ".ai-coop-context"
        names: list[str] = []
        if listing.is_file():
            try:
                for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not Path(line).is_absolute() and ".." not in Path(line).parts:
                        names.append(line.replace("\\", "/"))
            except OSError:
                names = []
        return names or list(cls.DEFAULT_CONTEXT_FILES)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        with self._write_lock:
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            replace_file(temp, path)

    def _update_status(self, run_dir: Path, **changes: Any) -> dict[str, Any]:
        status_path = run_dir / "status.json"
        with self._write_lock:
            if status_path.exists():
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            else:
                payload = {}
            payload.update(changes)
            payload["updated_at"] = utc_now()
            temp = status_path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            replace_file(temp, status_path)
        return payload

    def _start_job(
        self,
        kind: str,
        task: str,
        workspace: Path,
        target: Callable[[Path, str, Path], None],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        run_dir = self._run_path(run_id)
        run_dir.mkdir(parents=True)
        (run_dir / "request.md").write_text(task + "\n", encoding="utf-8")
        self._update_status(
            run_dir,
            run_id=run_id,
            kind=kind,
            state="queued",
            workspace=str(workspace),
            created_at=utc_now(),
            owner_pid=os.getpid(),  # 面板据此判断：宿主进程已退出而状态仍是 running，即已中断
            **(metadata or {}),
        )

        def wrapped() -> None:
            self._job_local.run_dir = run_dir
            self._update_status(run_dir, state="running")
            try:
                target(run_dir, task, workspace)
                self._update_status(run_dir, state="completed")
            except Exception as exc:  # Keep details in the local audit log.
                (run_dir / "error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                self._update_status(run_dir, state="failed", error=str(exc))

        threading.Thread(target=wrapped, daemon=True, name=f"ai-coop-{run_id}").start()
        return {
            "run_id": run_id,
            "state": "queued",
            "message": "任务已在后台启动。稍后调用 get_run_status 获取结果。",
        }

    def _record_usage(
        self, run_dir: Path, label: str, metadata: dict[str, Any]
    ) -> None:
        """Persist raw per-call usage and a small numeric aggregate."""
        usage_path = run_dir / "usage.json"
        with self._write_lock:
            if usage_path.exists():
                payload = json.loads(usage_path.read_text(encoding="utf-8"))
            else:
                payload = {"calls": []}
            record = {"label": label, "recorded_at": utc_now(), **metadata}
            payload["calls"].append(record)

            summary: dict[str, dict[str, Any]] = {}
            for call in payload["calls"]:
                provider = str(call.get("provider") or "unknown")
                bucket = summary.setdefault(provider, {"calls": 0})
                bucket["calls"] += 1
                for key, value in (call.get("usage") or {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        bucket[key] = bucket.get(key, 0) + value
                cost = call.get("total_cost_usd")
                if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                    bucket["total_cost_usd"] = bucket.get("total_cost_usd", 0) + cost
            payload["summary"] = summary
            temp = usage_path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            replace_file(temp, usage_path)
        self._update_status(run_dir, usage_summary=summary)

    @staticmethod
    def _kill_process_tree(proc: "subprocess.Popen[str]") -> None:
        """Terminate the child and every descendant that may hold our pipes."""
        if proc.poll() is not None:
            return
        if os.name == "nt":
            _hidden_run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            proc.kill()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass

    def _run_process(
        self, argv: list[str], prompt: str, workspace: Path, agent: str = "",
        drop_env: Callable[[str], bool] | None = None,
    ) -> tuple[str, str]:
        env = _with_proxy({k: v for k, v in os.environ.items() if not (drop_env and drop_env(k))})
        env["AI_COOP_NESTED"] = "1"
        run_dir = getattr(self._job_local, "run_dir", None)
        stream_path = run_dir / "stream.jsonl" if run_dir else None
        # 用 Popen 逐行读取：一边收集输出，一边把每行事件追加到 stream.jsonl 供面板实时显示。
        # 超时后必须杀掉整棵进程树：Codex 会派生孙进程，孙进程继承 stdout/stderr 管道句柄，
        # 只杀直接子进程时管道不会关闭，读取会无限阻塞。
        proc = _hidden_popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workspace,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        out_lines: list[str] = []
        err_parts: list[str] = []

        def feed() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(prompt)
                proc.stdin.close()
            except (OSError, ValueError):
                pass

        def pump_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                out_lines.append(line)
                if stream_path and line.strip():
                    record = json.dumps(
                        {"agent": agent, "at": utc_now(), "line": line.rstrip("\n")},
                        ensure_ascii=False,
                    )
                    try:
                        with stream_path.open("a", encoding="utf-8") as handle:
                            handle.write(record + "\n")
                    except OSError:
                        pass

        def pump_stderr() -> None:
            assert proc.stderr is not None
            err_parts.append(proc.stderr.read())

        threads = [threading.Thread(target=fn, daemon=True) for fn in (feed, pump_stdout, pump_stderr)]
        for thread in threads:
            thread.start()
        try:
            proc.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            self._kill_process_tree(proc)
            for thread in threads:
                thread.join(timeout=30)
            partial = "".join(out_lines).strip()
            raise RuntimeError(
                f"命令超时（{self.timeout_seconds}s），已终止进程树。已产生的输出："
                f"{partial[-8_000:] or '无'}"
            )
        for thread in threads:
            thread.join(timeout=30)
        stdout = "".join(out_lines).strip()
        stderr = "".join(err_parts).strip()
        if proc.returncode != 0:
            detail = stderr or stdout or "无输出"
            raise RuntimeError(
                f"命令执行失败（退出码 {proc.returncode}）：{detail[-4_000:]}"
            )
        return stdout, stderr

    def run_codex(
        self,
        prompt: str,
        workspace: Path,
        writable: bool = False,
        model: str = DEFAULT_CODEX_CONSULT_MODEL,
        effort: str = "medium",
    ) -> tuple[str, dict[str, Any]]:
        output_file = self.runs_dir / f".codex-{uuid.uuid4()}.txt"
        sandbox = "workspace-write" if writable else "read-only"
        argv = [
            self.executable("codex"),
            "exec",
            "-c",
            "mcp_servers={}",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-C",
            str(workspace),
            "-s",
            sandbox,
            "-o",
            str(output_file),
            "-",
        ]
        guard = (
            "\n\n若工作区存在 AGENTS.md 或项目协作说明，先阅读并遵守。"
            "\n安全边界：不要调用 ai-coop/MCP 协作工具，不要自行启动另一个 AI。"
            "不要提交、推送、合并或删除文件，除非任务文字明确要求且当前模式允许。"
        )
        try:
            stdout, _ = self._run_process(argv, prompt + guard, workspace, agent="codex")
            if output_file.exists():
                result = output_file.read_text(encoding="utf-8", errors="replace").strip()
            else:
                result = stdout
            usage: dict[str, Any] = {}
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn.completed" and isinstance(
                    event.get("usage"), dict
                ):
                    usage = event["usage"]
            metadata = {
                "provider": "codex",
                "model": model,
                "effort": effort,
                "usage": usage,
            }
            return result[-MAX_AGENT_OUTPUT_CHARS:], metadata
        finally:
            if output_file.exists():
                output_file.unlink()

    def run_claude(
        self,
        prompt: str,
        workspace: Path,
        model: str = DEFAULT_CLAUDE_MODEL,
        effort: str = "medium",
    ) -> tuple[str, dict[str, Any]]:
        empty_mcp = json.dumps({"mcpServers": {}}, separators=(",", ":"))
        argv = [
            self.executable("claude"),
            *claude_official_args(workspace),
            "-p",
            "--permission-mode",
            "plan",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            model,
            "--effort",
            effort,
            "--strict-mcp-config",
            "--mcp-config",
            empty_mcp,
        ]
        guarded_prompt = (
            prompt
            + "\n\n安全边界：只分析和审查，不修改文件；不要调用其他 AI 或 MCP 工具。"
        )
        stdout, _ = self._run_process(argv, guarded_prompt, workspace, agent="claude",
                                      drop_env=_host_env_var)
        actual_model = None
        for line in stdout.splitlines():
            if '"subtype":"init"' in line.replace(" ", ""):
                try:
                    actual_model = json.loads(line).get("model")
                except json.JSONDecodeError:
                    pass
                break
        run_dir = getattr(self._job_local, "run_dir", None)
        if run_dir and actual_model:
            self._update_status(run_dir, actual_model=actual_model)
        try:
            # stream-json：逐行事件，最后一条 type=result 与原 --output-format json 的载荷相同。
            payload = next(
                event for event in (
                    json.loads(line) for line in reversed(stdout.splitlines()) if line.strip().startswith("{")
                ) if isinstance(event, dict) and event.get("type") == "result"
            )
            result = payload.get("result") or payload.get("message") or stdout
            if payload.get("is_error"):
                message = str(payload.get("result") or "")
                if "Not logged in" in message or payload.get("api_error_status") == 401:
                    raise RuntimeError(
                        "命令行 Claude 还没有登录：请在终端运行 `claude auth login`，"
                        "用与 Claude App 相同的账号登录一次（若网络无法直连 Anthropic，请先设置 HTTPS_PROXY）。"
                    )
                raise RuntimeError(f"Claude 调用失败：{message[-2_000:]}")
            metadata = {
                "provider": "claude",
                "model": model,
                "actual_model": actual_model,
                "effort": effort,
                "usage": payload.get("usage") or {},
                "model_usage": payload.get("modelUsage") or {},
                "total_cost_usd": payload.get("total_cost_usd"),
            }
        except (json.JSONDecodeError, StopIteration):
            result = stdout
            metadata = {
                "provider": "claude",
                "model": model,
                "effort": effort,
                "usage": {},
            }
        return str(result).strip()[-MAX_AGENT_OUTPUT_CHARS:], metadata

    @staticmethod
    def _save_markdown(run_dir: Path, name: str, title: str, text: str) -> None:
        (run_dir / name).write_text(f"# {title}\n\n{text.strip()}\n", encoding="utf-8")

    def health_check(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace = self.resolve_workspace(arguments.get("workspace"))
        agents: dict[str, Any] = {}
        for agent in ("codex", "claude"):
            path = self.executable(agent, required=False)
            item: dict[str, Any] = {"available": bool(path), "path": path}
            if path:
                try:
                    completed = _hidden_run(
                        [path, "--version"],
                        cwd=workspace,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=10,
                        check=False,
                    )
                    version = (completed.stdout or completed.stderr).strip()
                    item.update(
                        probe_ok=completed.returncode == 0,
                        version=version[:500],
                        returncode=completed.returncode,
                    )
                except Exception as exc:
                    item.update(probe_ok=False, error=str(exc))
            agents[agent] = item
        return {
            "ok": all(item.get("available") and item.get("probe_ok") for item in agents.values()),
            "server_version": SERVER_VERSION,
            "host_agent": self.host_agent,
            "partner_agent": self.partner_for(self.host_agent) if self.host_agent != "auto" else "unknown",
            "workspace": str(workspace),
            "workspace_mode": "fixed-root" if self.root else "current-chat",
            "runs_dir": str(self.runs_dir),
            "write_enabled": self.allow_write,
            "agents": agents,
        }

    def claude_login_status(self) -> dict[str, Any]:
        """用 `claude auth status` 查命令行登录状态（与 run_claude 使用同一账号来源）。"""
        path = self.executable("claude", required=False)
        if not path:
            return {"logged_in": False, "detail": "找不到 claude 命令行"}
        argv = [path, *CLAUDE_OFFICIAL_ARGS, "auth", "status"]
        env = _with_proxy({k: v for k, v in os.environ.items() if not _host_env_var(k)})
        try:
            completed = _hidden_run(argv, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30, env=env, stdin=subprocess.DEVNULL)
            info = json.loads(completed.stdout or "{}")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"logged_in": False, "detail": str(exc)[:200]}
        return {"logged_in": bool(info.get("loggedIn")),
                "auth_method": info.get("authMethod"), "api_provider": info.get("apiProvider")}

    def _read_preferences(self) -> dict[str, Any]:
        path = self.runs_dir.parent / "preferences.json"
        if not path.is_file():
            return {"partners": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"partners": {}}
        return payload if isinstance(payload, dict) else {"partners": {}}

    def set_collaboration_mode(self, arguments: dict[str, Any]) -> dict[str, Any]:
        enabled = arguments.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        payload = self._read_preferences()
        payload["enabled"] = enabled
        payload["updated_at"] = utc_now()
        self._write_json(self.runs_dir.parent / "preferences.json", payload)
        return {
            "enabled": enabled,
            "message": (
                "AI Coop 已开启；后续直接描述任务即可自动协作。"
                if enabled
                else "AI Coop 自动协作已关闭。"
            ),
        }

    def set_partner_preferences(self, arguments: dict[str, Any]) -> dict[str, Any]:
        primary = self.resolve_host_agent(arguments.get("primary_agent"))
        partner = self.partner_for(primary)
        selection = safe_text(arguments.get("partner_selection") or "auto", 20).lower()
        if selection not in {"auto", "manual"}:
            raise ValueError("partner_selection 必须是 auto 或 manual")
        model = safe_model(
            arguments.get("partner_model"),
            DEFAULT_CODEX_CONSULT_MODEL if partner == "codex" else DEFAULT_CLAUDE_MODEL,
        )
        allowed = CODEX_EFFORTS if partner == "codex" else CLAUDE_EFFORTS
        effort = safe_effort(arguments.get("partner_effort"), "medium", allowed)
        payload = self._read_preferences()
        partners = payload.setdefault("partners", {})
        partners[partner] = {
            "selection": selection,
            "model": model,
            "effort": effort,
            "updated_at": utc_now(),
        }
        self._write_json(self.runs_dir.parent / "preferences.json", payload)
        return {
            "saved": True,
            "primary_agent": primary,
            "partner_agent": partner,
            "preferences": partners[partner],
        }

    def _discover_efforts(self, agent: str, workspace: Path) -> dict[str, Any]:
        fallback = CODEX_EFFORTS if agent == "codex" else CLAUDE_EFFORTS
        path = self.executable(agent, required=False)
        if agent == "claude" and path:
            try:
                completed = _hidden_run(
                    [path, "--help"],
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=False,
                )
                effort_line = next(
                    (line for line in completed.stdout.splitlines() if "--effort <level>" in line),
                    "",
                )
                match = re.search(r"\(([^()]*)\)", effort_line)
                if completed.returncode == 0 and match:
                    detected = ordered_efforts(
                        item.strip().strip('"\'') for item in match.group(1).split(",")
                    )
                    detected = [item for item in detected if item in EFFORT_ORDER]
                    if detected:
                        return {
                            "values": detected,
                            "source": "claude --help",
                            "verified": True,
                        }
            except (OSError, subprocess.SubprocessError):
                pass
        return {
            "values": ordered_efforts(fallback),
            "source": "bundled-fallback",
            "verified": False,
        }

    def _verified_models_from_history(
        self, agent: str, efforts: list[str]
    ) -> list[dict[str, Any]]:
        """Return exact model IDs observed in completed local CLI responses."""
        found: dict[str, str] = {}
        usage_paths = sorted(
            self.runs_dir.glob("*/usage.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:100]
        for usage_path in usage_paths:
            try:
                payload = json.loads(usage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for call in payload.get("calls", []):
                if not isinstance(call, dict) or call.get("provider") != agent:
                    continue
                model_usage = call.get("model_usage") or {}
                if isinstance(model_usage, dict):
                    for model_id in model_usage:
                        value = safe_text(model_id, 100)
                        if value:
                            found.setdefault(value.casefold(), value)
                resolved = safe_text(call.get("resolved_model"), 100)
                if resolved:
                    found.setdefault(resolved.casefold(), resolved)
        return [
            {
                "id": value,
                "label": f"{value} · 已运行验证",
                "tier": "verified-run",
                "verified": True,
                "efforts": efforts,
            }
            for value in found.values()
        ]

    def _discover_models(self, agent: str, workspace: Path) -> dict[str, Any]:
        effort_info = self._discover_efforts(agent, workspace)
        verified_history = self._verified_models_from_history(
            agent, effort_info["values"]
        )
        env_name = f"AI_COOP_{agent.upper()}_MODELS"
        configured = [item.strip() for item in os.environ.get(env_name, "").split(",") if item.strip()]
        if configured:
            return {
                "agent": agent,
                "source": env_name,
                "verified": False,
                "models": [
                    {
                        "id": item,
                        "label": item,
                        "tier": "configured",
                        "efforts": effort_info["values"],
                    }
                    for item in configured
                ],
                "efforts": effort_info["values"],
                "effort_source": effort_info["source"],
                "efforts_verified": effort_info["verified"],
                "note": "来自本机环境配置；真正可用性仍由对应登录账户决定。",
            }

        path = self.executable(agent, required=False)
        if agent == "claude":
            now = time.monotonic()
            cached = getattr(self, "_claude_models_cache", None)
            if not cached or now - cached[0] > 600:
                cached = (now, _claude_account_models())
                self._claude_models_cache = cached
            if cached[1]:
                return {
                    "agent": agent,
                    "source": "Anthropic /v1/models",
                    "verified": True,
                    "models": [{**m, "tier": "detected", "efforts": effort_info["values"]} for m in cached[1]],
                    "efforts": effort_info["values"],
                    "effort_source": effort_info["source"],
                    "efforts_verified": effort_info["verified"],
                    "note": "按命令行登录的 Claude 账号实时读取可用模型。",
                }
        if agent == "codex" and path:
            try:
                completed = _hidden_run(
                    [path, "debug", "models"],
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                )
                payload = json.loads(completed.stdout)
                detected = []
                for item in payload.get("models", []):
                    if item.get("visibility") not in {None, "list"}:
                        continue
                    levels = [
                        level.get("effort") for level in item.get("supported_reasoning_levels", [])
                        if level.get("effort")
                    ]
                    detected.append({
                        "id": item.get("slug"),
                        "label": item.get("display_name") or item.get("slug"),
                        "tier": "detected",
                        "default_effort": item.get("default_reasoning_level"),
                        "efforts": levels,
                    })
                detected = [item for item in detected if item["id"]]
                if detected:
                    return {
                        "agent": agent,
                        "source": "codex debug models",
                        "verified": True,
                        "models": detected,
                        "efforts": ordered_efforts(
                            level
                            for item in detected
                            for level in item.get("efforts", [])
                        ),
                        "effort_source": "codex debug models",
                        "efforts_verified": True,
                        "note": "由本机 Codex CLI 的模型目录返回。",
                    }
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                pass

        aliases = [
            {
                **item,
                "label": f"{item['label']} · 别名",
                "verified": False,
                "efforts": effort_info["values"],
            }
            for item in MODEL_CATALOG[agent]
            if item["id"].casefold()
            not in {model["id"].casefold() for model in verified_history}
        ]
        return {
            "agent": agent,
            "source": "run-history+aliases" if verified_history else "aliases",
            "verified": bool(verified_history),
            "models": verified_history + aliases,
            "efforts": effort_info["values"],
            "effort_source": effort_info["source"],
            "efforts_verified": effort_info["verified"],
            "note": (
                "已运行验证的完整型号来自本机历史响应；Claude CLI 不提供账户模型列表，opus/sonnet/haiku 仅为别名，也可手动输入完整模型 ID。"
                if agent == "claude"
                else "未能读取 CLI 模型目录；显示内置候选，可手动输入模型 ID。"
            ),
        }

    def get_model_catalog(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace = self.resolve_workspace(arguments.get("workspace"))
        try:
            primary = self.resolve_host_agent(arguments.get("primary_agent"))
        except ValueError:
            primary = "unknown"
        partner = self.partner_for(primary) if primary != "unknown" else "unknown"
        discovered = (
            self._discover_models(partner, workspace)
            if partner != "unknown"
            else {"agent": "unknown", "source": "unresolved", "verified": False, "models": [],
                  "note": "先识别主对话 AI，才能确定协作 AI。"}
        )
        return {
            "models": MODEL_CATALOG,
            "primary_agent": primary,
            "partner_agent": partner,
            "partner": discovered,
            "partner_efforts": discovered.get("efforts") or ordered_efforts(
                CODEX_EFFORTS if partner == "codex" else CLAUDE_EFFORTS
            ),
            "preferences": self._read_preferences().get("partners", {}).get(partner, {}),
            "collaboration_enabled": bool(self._read_preferences().get("enabled", False)),
            "claude_login": self.claude_login_status() if partner == "claude" else None,
            "note": "主对话 AI 的模型和推理强度由当前聊天界面管理；这里只配置另一栏的协作 AI。",
        }

    def show_partner_selector(self, arguments: dict[str, Any]) -> dict[str, Any]:
        catalog = self.get_model_catalog(arguments)
        partner = catalog.get("partner_agent", "协作 AI")
        return {
            "__mcp_result__": {
                "content": [
                    {
                        "type": "text",
                        "text": f"已显示 {partner} 的协作模型与推理强度选择条。选择会保存并用于后续协作调用。",
                    }
                ],
                "structuredContent": catalog,
            }
        }

    def open_sidebar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        import importlib.util
        workspace = self.resolve_workspace(arguments.get("workspace"))
        primary = self.resolve_host_agent(arguments.get("primary_agent"))
        spec = importlib.util.spec_from_file_location("ai_coop_sidebar", Path(__file__).with_name("sidebar.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.ensure_panel(self, workspace, primary)
        if primary == "claude":
            result["next_action"] = (
                "Open this URL in the Claude desktop app's built-in browser pane "
                "(mcp__Claude_Browser__preview_start with url). The URL is ready; "
                "the pane has not been opened yet."
            )
        else:
            result["next_action"] = (
                "Use Codex open_in_codex with target type browser, this URL, placement right. "
                "The URL is ready; the pane has not been opened yet."
            )
        return result

    @staticmethod
    def _auto_partner_settings(task: str, mode: str, partner: str) -> dict[str, str]:
        lower = task.lower()
        code_markers = (
            "代码", "实现", "修复", "测试", "仓库", "编译", "部署", "脚本",
            "code", "implement", "debug", "test", "repository", "deploy",
        )
        writing_markers = (
            "写作", "润色", "文案", "叙事", "反例", "审稿", "合同", "政策",
            "writing", "rewrite", "narrative", "critique", "policy",
        )
        decision_markers = (
            "决策", "比较", "选择", "权衡", "方案", "评估", "风险",
            "decide", "compare", "choose", "tradeoff", "evaluate", "risk",
        )
        if partner == "codex":
            if mode == "implement" or any(marker in lower for marker in code_markers):
                return {"model": DEFAULT_CODEX_IMPLEMENT_MODEL, "effort": "high",
                        "reason": "协作 AI 负责代码实施或验证，使用偏执行的 Codex 配置。"}
            if mode == "decide" or any(marker in lower for marker in decision_markers):
                return {"model": DEFAULT_CODEX_DEBATE_MODEL, "effort": "high",
                        "reason": "任务包含决策权衡，增加协作 AI 的推理强度。"}
            return {"model": DEFAULT_CODEX_CONSULT_MODEL, "effort": "medium",
                    "reason": "使用 Codex 的均衡咨询配置。"}
        if any(marker in lower for marker in writing_markers) or mode in {"decide", "review"}:
            return {"model": DEFAULT_CLAUDE_MODEL, "effort": "high",
                    "reason": "任务需要审查、写作或权衡，增加协作 AI 的推理强度。"}
        return {"model": DEFAULT_CLAUDE_MODEL, "effort": "medium",
                "reason": "使用 Claude 的均衡咨询配置。"}

    def start_workflow(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = safe_text(arguments.get("task"), MAX_TASK_CHARS)
        if not task:
            raise ValueError("task 不能为空")
        context = safe_text(arguments.get("context"), MAX_CONTEXT_CHARS)
        mode = safe_text(arguments.get("mode") or "decide", 20).lower()
        if mode not in {"analyze", "decide", "implement", "review"}:
            raise ValueError("mode 必须是 analyze、decide、implement 或 review")
        primary = self.resolve_host_agent(arguments.get("primary_agent"))
        partner = self.partner_for(primary)
        saved = self._read_preferences().get("partners", {}).get(partner, {})
        selection = safe_text(
            arguments.get("partner_selection") or arguments.get("selection")
            or saved.get("selection") or "auto", 20
        ).lower()
        if selection not in {"auto", "manual"}:
            raise ValueError("partner_selection 必须是 auto 或 manual")

        automatic = self._auto_partner_settings(task, mode, partner)

        decision = safe_text(arguments.get("approved_decision"), MAX_CONTEXT_CHARS)
        if mode == "implement":
            if not decision:
                raise ValueError("implement 模式必须提供 approved_decision")
            if partner == "codex" and not self.allow_write:
                raise PermissionError("Codex 协作写入未启用；请重新安装并启用 AllowWrite。")
        legacy_model = arguments.get("codex_model") if partner == "codex" else arguments.get("claude_model")
        legacy_effort = arguments.get("codex_effort") if partner == "codex" else arguments.get("claude_effort")
        if selection == "auto":
            partner_model = automatic["model"]
            partner_effort = automatic["effort"]
        else:
            partner_model = safe_model(
                arguments.get("partner_model") or legacy_model or saved.get("model"), automatic["model"]
            )
            allowed_efforts = CODEX_EFFORTS if partner == "codex" else CLAUDE_EFFORTS
            partner_effort = safe_effort(
                arguments.get("partner_effort") or legacy_effort or saved.get("effort"),
                automatic["effort"], allowed_efforts,
            )
        workspace = self.resolve_workspace(arguments.get("workspace"))
        task_id = safe_text(arguments.get("task_id"), 100)

        def job(run_dir: Path, request: str, project: Path) -> None:
            snapshot = self.workspace_snapshot(project)
            self._save_markdown(run_dir, "workspace-snapshot.md", "工作区只读快照", snapshot)
            base = (
                f"主对话 AI 是 {primary}，你是协作 AI {partner}。主对话 AI 正在和用户持续交流，"
                "你只向主对话 AI 提供协作意见。区分已知事实、推断、建议和待批准决定；"
                "关键结论给出可复核依据。不要调用另一个 AI 或直接代替主对话 AI 向用户收尾。\n\n"
                f"任务模式：{mode}\n任务：\n{request}\n\n上下文：\n{context or '无'}\n\n"
                f"已批准决定：\n{decision or '无'}\n\n工作区证据快照：\n{snapshot}"
            )
            self._update_status(run_dir, stage=f"{partner}_partner_turn")
            if partner == "codex":
                final, usage = self.run_codex(
                    base + "\n\n请完成主对话 AI 分配的本轮工作，返回结论、依据、分歧点和建议的下一轮问题。",
                    project,
                    writable=(mode == "implement"),
                    model=partner_model,
                    effort=partner_effort,
                )
            else:
                final, usage = self.run_claude(
                    base + "\n\n请完成主对话 AI 分配的本轮工作，返回结论、依据、分歧点和建议的下一轮问题。",
                    project,
                    model=partner_model,
                    effort=partner_effort,
                )
            self._record_usage(run_dir, f"{partner}_partner_turn", usage)
            self._save_markdown(run_dir, "partner-result.md", f"{partner} 协作回复", final)
            route_text = json.dumps(
                {"primary_agent": primary, "partner_agent": partner,
                 "partner_selection": selection, "partner_model": partner_model,
                 "partner_effort": partner_effort,
                 "reason": automatic["reason"] if selection == "auto" else "用户手动指定协作 AI 模型"},
                ensure_ascii=False, indent=2,
            )
            report = f"# AI Coop 协作 AI 回复\n\n## 本轮设置\n\n```json\n{route_text}\n```\n\n{final}\n"
            (run_dir / "result.md").write_text(report, encoding="utf-8")

        route = {
            "primary_agent": primary,
            "partner_agent": partner,
            "partner_selection": selection,
            "partner_model": partner_model,
            "partner_effort": partner_effort,
            "reason": automatic["reason"] if selection == "auto" else "用户手动指定协作 AI 模型",
        }
        started = self._start_job(
            "routed_workflow", task, workspace, job,
            metadata={
                "task_id": task_id or None,
                "mode": mode,
                "route": route,
                "agent_settings": {partner: {"model": partner_model, "effort": partner_effort}},
            },
        )
        started["route"] = route
        return started

    def start_consultation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        agent = safe_text(arguments.get("agent"), 20).lower()
        if agent not in {"codex", "claude"}:
            raise ValueError("agent 必须是 codex 或 claude")
        task = safe_text(arguments.get("task"), MAX_TASK_CHARS)
        if not task:
            raise ValueError("task 不能为空")
        context = safe_text(arguments.get("context"), MAX_CONTEXT_CHARS)
        role = safe_text(arguments.get("role") or "独立审稿人", 200)
        task_id = safe_text(arguments.get("task_id"), 100)
        human_owner = safe_text(arguments.get("human_owner"), 100)
        if agent == "codex":
            model = safe_model(arguments.get("model"), DEFAULT_CODEX_CONSULT_MODEL)
            effort = safe_effort(arguments.get("effort"), "medium", CODEX_EFFORTS)
        else:
            model = safe_model(arguments.get("model"), DEFAULT_CLAUDE_MODEL)
            effort = safe_effort(arguments.get("effort"), "medium", CLAUDE_EFFORTS)
        workspace = self.resolve_workspace(arguments.get("workspace"))

        def job(run_dir: Path, request: str, project: Path) -> None:
            snapshot = self.workspace_snapshot(project)
            self._save_markdown(run_dir, "workspace-snapshot.md", "工作区只读快照", snapshot)
            prompt = (
                f"你是当前项目的{role}。请独立完成以下任务，区分事实、推断与建议；"
                "对关键结论给出可复核依据；发现信息不足时明确说明。\n\n"
                f"任务：\n{request}\n\n补充上下文：\n{context or '无'}\n\n"
                "以下是协作桥直接从工作区生成的只读证据快照；即使本地命令被策略阻止，"
                "也必须基于这份快照分析：\n\n"
                f"{snapshot}"
            )
            result, usage = (
                self.run_codex(prompt, project, model=model, effort=effort)
                if agent == "codex"
                else self.run_claude(prompt, project, model=model, effort=effort)
            )
            self._record_usage(run_dir, f"{agent}_consultation", usage)
            self._save_markdown(run_dir, "result.md", f"{agent} consultation", result)

        return self._start_job(
            f"{agent}_consultation",
            task,
            workspace,
            job,
            metadata={
                "task_id": task_id or None,
                "human_owner": human_owner or None,
                "agent_settings": {"agent": agent, "model": model, "effort": effort},
            },
        )

    def start_debate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = safe_text(arguments.get("task"), MAX_TASK_CHARS)
        if not task:
            raise ValueError("task 不能为空")
        context = safe_text(arguments.get("context"), MAX_CONTEXT_CHARS)
        rounds = int(arguments.get("rounds", 1))
        if rounds not in {1, 2}:
            raise ValueError("rounds 只能是 1 或 2")
        task_id = safe_text(arguments.get("task_id"), 100)
        human_owner = safe_text(arguments.get("human_owner"), 100)
        codex_model = safe_model(arguments.get("codex_model"), DEFAULT_CODEX_DEBATE_MODEL)
        codex_effort = safe_effort(
            arguments.get("codex_effort"), "medium", CODEX_EFFORTS
        )
        claude_model = safe_model(arguments.get("claude_model"), DEFAULT_CLAUDE_MODEL)
        claude_effort = safe_effort(
            arguments.get("claude_effort"), "medium", CLAUDE_EFFORTS
        )
        workspace = self.resolve_workspace(arguments.get("workspace"))

        def job(run_dir: Path, request: str, project: Path) -> None:
            snapshot = self.workspace_snapshot(project)
            self._save_markdown(run_dir, "workspace-snapshot.md", "工作区只读快照", snapshot)
            base = (
                "这是项目决策。请给出候选方案、信息口径、假设、验证方案、失败条件，"
                "并把事实、推断和建议分开。不要因为另一个模型的意见而放弃独立判断。\n\n"
                f"任务：\n{request}\n\n上下文：\n{context or '无'}\n\n"
                f"工作区只读证据快照：\n{snapshot}"
            )
            self._update_status(run_dir, stage="independent_claude")
            claude_plan, usage = self.run_claude(
                base, project, model=claude_model, effort=claude_effort
            )
            self._record_usage(run_dir, "independent_claude", usage)
            self._save_markdown(run_dir, "01-claude-plan.md", "Claude 独立方案", claude_plan)

            self._update_status(run_dir, stage="independent_codex")
            codex_plan, usage = self.run_codex(
                base, project, model=codex_model, effort=codex_effort
            )
            self._record_usage(run_dir, "independent_codex", usage)
            self._save_markdown(run_dir, "02-codex-plan.md", "Codex 独立方案", codex_plan)

            synthesis = codex_plan
            critique = ""
            for index in range(1, rounds + 1):
                self._update_status(run_dir, stage=f"claude_critique_{index}")
                critique_prompt = (
                    "你是严格的独立审查者。比较两个方案，重点找口径不一致、未经证实的假设、"
                    "利益与风险遗漏、验证失真和复现缺口。给出必须修改项与可证伪测试。\n\n"
                    f"任务：\n{request}\n\nClaude 初案：\n{claude_plan}\n\n"
                    f"Codex 当前方案：\n{synthesis}"
                )
                critique, usage = self.run_claude(
                    critique_prompt,
                    project,
                    model=claude_model,
                    effort=claude_effort,
                )
                self._record_usage(run_dir, f"claude_critique_{index}", usage)
                self._save_markdown(
                    run_dir,
                    f"{index * 2 + 1:02d}-claude-critique.md",
                    f"Claude 第 {index} 轮质询",
                    critique,
                )

                self._update_status(run_dir, stage=f"codex_adjudication_{index}")
                adjudication_prompt = (
                    "你是最终技术裁决人。不得简单投票或平均；逐项核验证据，保留仍未解决的"
                    "分歧。输出：最终建议、选择理由、被否决方案、验证门槛、实施步骤、停止条件。\n\n"
                    f"任务：\n{request}\n\nClaude 初案：\n{claude_plan}\n\n"
                    f"Codex 初案/上一版：\n{synthesis}\n\nClaude 质询：\n{critique}"
                )
                synthesis, usage = self.run_codex(
                    adjudication_prompt,
                    project,
                    model=codex_model,
                    effort=codex_effort,
                )
                self._record_usage(run_dir, f"codex_adjudication_{index}", usage)
                self._save_markdown(
                    run_dir,
                    f"{index * 2 + 2:02d}-codex-decision.md",
                    f"Codex 第 {index} 轮裁决",
                    synthesis,
                )

            report = (
                "# 双模型讨论结果\n\n"
                f"- 任务：{request}\n"
                f"- 工作区：{project}\n"
                f"- 轮数：{rounds}\n"
                f"- 完成时间：{utc_now()}\n\n"
                "## 最终裁决\n\n"
                f"{synthesis}\n\n"
                "## 最后一轮质询\n\n"
                f"{critique}\n"
            )
            (run_dir / "result.md").write_text(report, encoding="utf-8")

        return self._start_job(
            "model_debate",
            task,
            workspace,
            job,
            metadata={
                "task_id": task_id or None,
                "human_owner": human_owner or None,
                "agent_settings": {
                    "codex": {"model": codex_model, "effort": codex_effort},
                    "claude": {"model": claude_model, "effort": claude_effort},
                    "rounds": rounds,
                },
            },
        )

    def start_implementation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_write:
            raise PermissionError(
                "写入功能未启用。确认工作流后，在 MCP 服务参数中加入 --allow-write 并重启应用。"
            )
        task = safe_text(arguments.get("task"), MAX_TASK_CHARS)
        decision = safe_text(arguments.get("approved_decision"), MAX_CONTEXT_CHARS)
        if not task or not decision:
            raise ValueError("task 和 approved_decision 都不能为空")
        task_id = safe_text(arguments.get("task_id"), 100)
        human_owner = safe_text(arguments.get("human_owner"), 100)
        reviewer = safe_text(arguments.get("reviewer"), 100)
        model = safe_model(arguments.get("codex_model"), DEFAULT_CODEX_IMPLEMENT_MODEL)
        effort = safe_effort(arguments.get("codex_effort"), "medium", CODEX_EFFORTS)
        workspace = self.resolve_workspace(arguments.get("workspace"))

        def job(run_dir: Path, request: str, project: Path) -> None:
            prompt = (
                "你是实施者。严格按已批准决策修改当前工作区；先检查现状与现有改动，"
                "不得覆盖无关的用户修改。完成后运行与风险相称的验证。不要提交、推送、"
                "合并或删除材料，并在结论中列出修改文件、验证结果与剩余风险。\n\n"
                f"实施任务：\n{request}\n\n已批准决策：\n{decision}"
            )
            result, usage = self.run_codex(
                prompt,
                project,
                writable=True,
                model=model,
                effort=effort,
            )
            self._record_usage(run_dir, "codex_implementation", usage)
            status = self.project_status({"workspace": str(project)})
            report = f"# Codex 实施结果\n\n{result}\n\n## 工作区状态\n\n```text\n{status}\n```\n"
            (run_dir / "result.md").write_text(report, encoding="utf-8")

        return self._start_job(
            "codex_implementation",
            task,
            workspace,
            job,
            metadata={
                "task_id": task_id or None,
                "human_owner": human_owner or None,
                "reviewer": reviewer or None,
                "agent_settings": {"model": model, "effort": effort},
            },
        )

    def get_run_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        run_id = safe_text(arguments.get("run_id"), 100)
        run_dir = self._run_path(run_id)
        status_path = run_dir / "status.json"
        if not status_path.exists():
            raise ValueError(f"找不到运行记录：{run_id}")
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        result_path = run_dir / "result.md"
        if result_path.exists():
            payload["result"] = result_path.read_text(
                encoding="utf-8", errors="replace"
            )[-MAX_AGENT_OUTPUT_CHARS:]
        payload["run_dir"] = str(run_dir)
        return payload

    def list_runs(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        limit = max(1, min(int(arguments.get("limit", 10)), 50))
        records: list[dict[str, Any]] = []
        for status_path in sorted(
            self.runs_dir.glob("*/status.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                records.append(json.loads(status_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def get_usage_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        run_id = safe_text(arguments.get("run_id"), 100)
        if run_id:
            usage_path = self._run_path(run_id) / "usage.json"
            if not usage_path.exists():
                return {"run_id": run_id, "calls": [], "summary": {}}
            return json.loads(usage_path.read_text(encoding="utf-8"))

        limit = max(1, min(int(arguments.get("limit", 20)), 100))
        usage_paths = sorted(
            self.runs_dir.glob("*/usage.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
        aggregate: dict[str, dict[str, Any]] = {}
        run_summaries: list[dict[str, Any]] = []
        for usage_path in usage_paths:
            try:
                payload = json.loads(usage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            summary = payload.get("summary") or {}
            run_summaries.append(
                {"run_id": usage_path.parent.name, "summary": summary}
            )
            for provider, values in summary.items():
                bucket = aggregate.setdefault(provider, {})
                for key, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        bucket[key] = bucket.get(key, 0) + value
        return {
            "runs_included": len(run_summaries),
            "aggregate": aggregate,
            "runs": run_summaries,
            "note": "这是 ai-coop 本地任务用量，不等于账户剩余额度。",
        }

    def read_project_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace = self.resolve_workspace(arguments.get("workspace"))
        path = self.resolve_file(workspace, arguments.get("path"))
        max_chars = max(1, min(int(arguments.get("max_chars", 30_000)), 100_000))
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        return {
            "path": str(path),
            "content": text[:max_chars],
            "truncated": truncated,
            "total_chars": len(text),
        }

    def project_status(self, arguments: dict[str, Any]) -> str:
        workspace = self.resolve_workspace(arguments.get("workspace"))
        # Keep this health check fast and bounded. Local runtime junctions can
        # contain tens of thousands of files and may be unreadable inside a
        # desktop app sandbox; scanning them used to make the MCP client time
        # out before the server could return a useful response.
        scope = ["--", "."]
        for excluded in GIT_STATUS_EXCLUDES:
            scope.extend(
                [f":(exclude){excluded}", f":(exclude){excluded}/**"]
            )
        commands = [
            [
                "git",
                "-C",
                str(workspace),
                "status",
                "--short",
                "--branch",
                "--untracked-files=normal",
                *scope,
            ],
            ["git", "-C", str(workspace), "diff", "--stat", *scope],
        ]
        sections: list[str] = []
        for argv in commands:
            try:
                completed = _hidden_run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=GIT_STATUS_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                sections.append(
                    f"(git 命令超时 {GIT_STATUS_TIMEOUT_SECONDS}s，已跳过：{' '.join(argv[3:])})"
                )
                continue
            if completed.returncode == 0:
                output = completed.stdout.strip() or "(无变更)"
                if len(output) > MAX_GIT_STATUS_CHARS:
                    total_lines = output.count("\n") + 1
                    output = (
                        output[:MAX_GIT_STATUS_CHARS]
                        + f"\n…Git 输出已截断（共 {total_lines} 行）…"
                    )
                sections.append(output)
            elif not sections:
                entries = sorted(path.name for path in workspace.iterdir())[:200]
                return "非 Git 工作区。顶层文件：\n" + "\n".join(entries)
        return "\n\n".join(sections)

    def tools(self) -> list[dict[str, Any]]:
        workspace_prop = {
            "type": "string",
            "description": "当前原生聊天所打开工作区的绝对路径；每次调用按当前聊天动态选择，不绑定安装目录。",
        }
        return [
            {
                "name": "health_check",
                "title": "检查 AI Coop 连接",
                "description": "检查 Codex/Claude CLI、工作区、运行目录和写入模式，不启动模型任务。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"workspace": workspace_prop},
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "get_model_catalog",
                "title": "读取模型目录",
                "description": "识别主对话 AI，并读取另一端协作 AI 的候选模型、推理强度和已保存设置。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace": workspace_prop,
                        "primary_agent": {"type": "string", "enum": ["auto", "codex", "claude"], "default": "auto"},
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "show_partner_selector",
                "title": "显示协作 AI 选择条",
                "description": "在当前对话中显示一个紧凑的协作 AI 模型与推理强度选择条；选择会保存并用于之后的 start_workflow 调用。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace": workspace_prop,
                        "primary_agent": {"type": "string", "enum": ["auto", "codex", "claude"], "default": "auto"},
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
                "_meta": {
                    "ui": {"resourceUri": PARTNER_SELECTOR_URI},
                    "openai/outputTemplate": PARTNER_SELECTOR_URI,
                    "openai/toolInvocation/invoking": "正在识别协作 AI 选项…",
                    "openai/toolInvocation/invoked": "协作 AI 选项已就绪。",
                },
            },
            {
                "name": "open_sidebar",
                "title": "准备 AI Coop 侧栏",
                "description": "准备当前工作区的本地协作控制页（显示协作伙伴模型、推理强度与运行状态），返回 URL。Codex 用 open_in_codex 在 right 面板打开；Claude 桌面版用内置浏览器面板 preview_start 打开。此工具本身不会打开面板。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace": workspace_prop,
                        "primary_agent": {"type": "string", "enum": ["auto", "codex", "claude"], "default": "auto"},
                    },
                    "required": ["workspace"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            },
            {
                "name": "set_collaboration_mode",
                "title": "打开或关闭 AI Coop",
                "description": "打开后，当前宿主中的后续实质任务会自动交给另一端 AI 协作；用户无需再调用 workflow。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            },
            {
                "name": "set_partner_preferences",
                "title": "保存协作 AI 设置",
                "description": "保存另一端 AI 的自动/手动选模、模型 ID 和推理强度，供之后的原生聊天协作调用使用。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "primary_agent": {"type": "string", "enum": ["auto", "codex", "claude"], "default": "auto"},
                        "partner_selection": {"type": "string", "enum": ["auto", "manual"], "default": "auto"},
                        "partner_model": {"type": "string"},
                        "partner_effort": {"type": "string", "enum": sorted(CODEX_EFFORTS | CLAUDE_EFFORTS), "default": "medium"},
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            },
            {
                "name": "start_workflow",
                "title": "让协作 AI 执行一轮工作",
                "description": "当前聊天 AI 自动担任主协调者，把本轮任务交给另一端 AI；完成后主 AI读取结果、继续追问或向用户汇总。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "context": {"type": "string"},
                        "workspace": workspace_prop,
                        "mode": {"type": "string", "enum": ["analyze", "decide", "implement", "review"], "default": "decide"},
                        "primary_agent": {"type": "string", "enum": ["auto", "codex", "claude"], "default": "auto"},
                        "partner_selection": {"type": "string", "enum": ["auto", "manual"]},
                        "partner_model": {"type": "string"},
                        "partner_effort": {"type": "string", "enum": sorted(CODEX_EFFORTS | CLAUDE_EFFORTS)},
                        "approved_decision": {"type": "string"},
                        "task_id": {"type": "string"},
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            },
            {
                "name": "start_consultation",
                "description": "后台启动一次 Codex 或 Claude 的独立只读咨询。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "enum": ["codex", "claude"]},
                        "task": {"type": "string"},
                        "workspace": workspace_prop,
                        "context": {"type": "string"},
                        "role": {"type": "string", "default": "独立审稿人"},
                        "model": {"type": "string"},
                        "effort": {
                            "type": "string",
                            "enum": sorted(CODEX_EFFORTS | CLAUDE_EFFORTS),
                        },
                        "task_id": {"type": "string"},
                        "human_owner": {"type": "string"},
                    },
                    "required": ["agent", "task"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "start_model_debate",
                "description": "后台启动 Claude 与 Codex 的独立方案、交叉质询和证据裁决；不会修改项目。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "workspace": workspace_prop,
                        "context": {"type": "string"},
                        "rounds": {"type": "integer", "enum": [1, 2], "default": 1},
                        "codex_model": {
                            "type": "string",
                            "default": DEFAULT_CODEX_DEBATE_MODEL,
                        },
                        "codex_effort": {
                            "type": "string",
                            "enum": sorted(CODEX_EFFORTS),
                            "default": "medium",
                        },
                        "claude_model": {
                            "type": "string",
                            "default": DEFAULT_CLAUDE_MODEL,
                        },
                        "claude_effort": {
                            "type": "string",
                            "enum": sorted(CLAUDE_EFFORTS),
                            "default": "medium",
                        },
                        "task_id": {"type": "string"},
                        "human_owner": {"type": "string"},
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "start_codex_implementation",
                "description": "按用户已批准的决策让 Codex 修改项目并验证。服务需显式启用 --allow-write。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "approved_decision": {"type": "string"},
                        "workspace": workspace_prop,
                        "codex_model": {
                            "type": "string",
                            "default": DEFAULT_CODEX_IMPLEMENT_MODEL,
                        },
                        "codex_effort": {
                            "type": "string",
                            "enum": sorted(CODEX_EFFORTS),
                            "default": "medium",
                        },
                        "task_id": {"type": "string"},
                        "human_owner": {"type": "string"},
                        "reviewer": {"type": "string"},
                    },
                    "required": ["task", "approved_decision"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
            },
            {
                "name": "get_run_status",
                "description": "查询后台协作任务状态；完成后返回最终报告。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "list_runs",
                "description": "列出最近的协作运行记录。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50}
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "get_usage_summary",
                "description": "读取 ai-coop 单次或最近多次任务的 Codex/Claude token 与费用统计；不代表账户剩余额度。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        },
                    },
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "project_status",
                "description": "读取项目 Git 状态和差异统计；非 Git 目录则列出顶层文件。",
                "inputSchema": {
                    "type": "object",
                    "properties": {"workspace": workspace_prop},
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "read_project_file",
                "description": "读取所选工作区内的 UTF-8 文本文件，禁止越界访问。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace": workspace_prop,
                        "path": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100000,
                            "default": 30000,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "health_check": self.health_check,
            "get_model_catalog": self.get_model_catalog,
            "show_partner_selector": self.show_partner_selector,
            "open_sidebar": self.open_sidebar,
            "set_collaboration_mode": self.set_collaboration_mode,
            "set_partner_preferences": self.set_partner_preferences,
            "start_workflow": self.start_workflow,
            "start_consultation": self.start_consultation,
            "start_model_debate": self.start_debate,
            "start_codex_implementation": self.start_implementation,
            "get_run_status": self.get_run_status,
            "list_runs": self.list_runs,
            "get_usage_summary": self.get_usage_summary,
            "project_status": self.project_status,
            "read_project_file": self.read_project_file,
        }
        if name not in handlers:
            raise ValueError(f"未知工具：{name}")
        return handlers[name](arguments)


def send(payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(data.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def serve(bridge: Bridge) -> None:
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        try:
            request = json.loads(raw.decode("utf-8"))
            method = request.get("method")
            request_id = request.get("id")
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {"name": "ai-coop", "version": SERVER_VERSION},
                    "instructions": (
                        "AI Coop connects the AI in the current native chat to the other AI. "
                        "When collaboration mode is enabled, automatically use start_workflow "
                        "for substantive user tasks, poll the returned run with get_run_status, "
                        "and give one integrated answer. Never ask the user to invoke a separate "
                        "workflow command. Settings, connection checks, greetings, and requests "
                        "to disable AI Coop do not require a partner run."
                    ),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": bridge.tools()}
            elif method == "resources/list":
                result = {"resources": ui_resources()}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": []}
            elif method == "resources/read":
                params = request.get("params") or {}
                result = read_ui_resource(safe_text(params.get("uri"), 2_000))
            elif method == "prompts/list":
                result = {"prompts": prompt_catalog()}
            elif method == "prompts/get":
                params = request.get("params") or {}
                result = read_prompt(safe_text(params.get("name"), 200))
            elif method == "tools/call":
                params = request.get("params") or {}
                value = bridge.call_tool(params.get("name", ""), params.get("arguments") or {})
                if isinstance(value, dict) and "__mcp_result__" in value:
                    result = value["__mcp_result__"]
                    result["isError"] = False
                else:
                    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
                    result = {
                        "content": [{"type": "text", "text": text}],
                        "structuredContent": value if isinstance(value, (dict, list)) else None,
                        "isError": False,
                    }
            elif method and method.startswith("notifications/"):
                continue
            else:
                raise ValueError(f"不支持的 MCP 方法：{method}")
            if request_id is not None:
                send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            request_id = locals().get("request", {}).get("id")
            if request_id is not None:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex/Claude local MCP bridge")
    # Accepted only so an old launcher cannot re-enable the removed fixed-root
    # behavior. The value is deliberately ignored.
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--codex-exe")
    parser.add_argument("--claude-exe")
    parser.add_argument("--host-agent", choices=("auto", "codex", "claude"), default="auto")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def _require_python() -> None:
    if sys.version_info < (3, 10):
        sys.stderr.write("AI Coop 需要 Python 3.10 或更高版本。\n")
        raise SystemExit(2)


def main() -> int:
    _require_python()
    args = parse_args()
    root = None
    runs_dir = (args.runs_dir or default_runs_dir()).resolve()
    bridge = Bridge(
        root=root,
        runs_dir=runs_dir,
        allow_write=args.allow_write,
        codex_exe=args.codex_exe,
        claude_exe=args.claude_exe,
        timeout_seconds=args.timeout_seconds,
        host_agent=args.host_agent,
    )
    if args.self_test:
        print(
            json.dumps(
                {
                    "ok": True,
                    "root": str(bridge.root) if bridge.root else None,
                    "workspace_mode": "fixed-root" if bridge.root else "current-chat",
                    "runs_dir": str(bridge.runs_dir),
                    "allow_write": bridge.allow_write,
                    "host_agent": bridge.host_agent,
                    "codex_exe": bridge.executable("codex", required=False),
                    "claude_exe": bridge.executable("claude", required=False),
                    "tools": [tool["name"] for tool in bridge.tools()],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    serve(bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
