"""AI Coop's loopback-only control panel, hosted in Codex's right browser pane."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

ASSETS = Path(__file__).resolve().parents[1] / "assets"


RUN_ID = re.compile(r"^[0-9a-f-]{8,64}$")
MAX_ENTRY_CHARS = 20_000


def _short(text, limit=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


SHELL_WRAPPER = re.compile(
    r'^\s*"?[^"]*?(?:pwsh|powershell|bash|sh|cmd)(?:\.exe)?"?\s+(?:-NoProfile\s+)?(?:-Command|-l?c|/c)\s+', re.I)


def _unwrap_shell(command):
    """去掉 pwsh.exe -Command '...' / bash -lc "..." 这层外壳，只留实际执行的命令。"""
    text = SHELL_WRAPPER.sub("", str(command or ""), count=1).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    return text


def _codex_entries(event):
    """把 codex exec --json 的一条事件转成对话条目；文件改动等不属于“对话”的输出跳过。"""
    kind = event.get("type")
    item = event.get("item") or {}
    itype = item.get("type")
    if kind == "item.completed" and itype == "agent_message" and item.get("text"):
        return [("message", item["text"])]
    if kind == "item.completed" and itype == "reasoning" and item.get("text"):
        return [("reasoning", item["text"])]
    if kind == "item.started" and itype == "command_execution":
        return [("step", "运行 " + _short(_unwrap_shell(item.get("command")), 120))]
    if kind == "item.started" and itype in ("web_search", "web_search_call"):
        return [("step", "搜索 " + _short(item.get("query") or item.get("action") or "", 120))]
    if kind == "item.completed" and itype == "mcp_tool_call":
        return [("step", "调用工具 " + _short(item.get("tool") or item.get("name"), 80))]
    if kind == "item.completed" and itype == "error":
        message = str(item.get("message") or "")
        if "ignoring" in message and "configuration" in message:
            return []  # 启动时对 -c 覆盖项的例行提示，不是对话内容
        if message.startswith("Reconnecting"):
            return []  # Codex 自动重连的过程提示；重连失败会另有 turn.failed/error 事件
        return [("error", message)]
    if kind in ("turn.failed", "error"):
        return [("error", _short((event.get("error") or {}).get("message") or event.get("message"), 400))]
    return []


def _claude_entries(event):
    """把 claude -p --output-format stream-json 的一条事件转成对话条目。"""
    if event.get("type") != "assistant":
        return []
    entries = []
    for block in (event.get("message") or {}).get("content") or []:
        btype = block.get("type")
        if btype == "text" and block.get("text"):
            entries.append(("message", block["text"]))
        elif btype == "thinking" and block.get("thinking"):
            entries.append(("reasoning", block["thinking"]))
        elif btype == "tool_use":
            args = block.get("input") or {}
            hint = args.get("command") or args.get("pattern") or args.get("file_path") or args.get("query") or args.get("url") or ""
            entries.append(("step", _short(f"{block.get('name', '工具')} {hint}", 140)))
    return entries


def read_transcript(run_dir):
    entries = []
    stream = run_dir / "stream.jsonl"
    if stream.exists():
        for raw in stream.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(raw)
                event = json.loads(record.get("line") or "")
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            agent = record.get("agent") or ""
            parse = _claude_entries if agent == "claude" else _codex_entries
            for kind, text in parse(event):
                entries.append({"agent": agent, "at": record.get("at"), "kind": kind,
                                "text": str(text)[:MAX_ENTRY_CHARS]})
    if not any(e["kind"] == "message" for e in entries):
        # 旧版运行没有事件流：退回到保存下来的协作回复全文。
        for name in ("partner-result.md", "result.md"):
            path = run_dir / name
            if path.exists():
                entries.append({"agent": "", "at": None, "kind": "message",
                                "text": path.read_text(encoding="utf-8", errors="replace")[-MAX_ENTRY_CHARS * 3:]})
                break
    return entries


def codex_rate_limits():
    """从 Codex 最近的会话日志里取最后一次 rate_limits（账户 5 小时 / 每周额度占用）。

    codex exec --json 不输出额度信息；Codex App 与交互式 CLI 会把 token_count 事件写进
    ~/.codex/sessions/**/rollout-*.jsonl。只读取最近几个文件的末尾，避免扫描整个历史。
    """
    root = Path.home() / ".codex" / "sessions"
    try:
        files = sorted(root.glob("*/*/*/rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
    except OSError:
        return None
    for path in files:
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - 400_000))
                tail = handle.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(tail):
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            limits = (event.get("payload") or {}).get("rate_limits") or event.get("rate_limits")
            if not isinstance(limits, dict):
                continue
            def window(key):
                value = limits.get(key) or {}
                if value.get("used_percent") is None:
                    return None
                return {"used_percent": value.get("used_percent"),
                        "window_minutes": value.get("window_minutes"),
                        "resets_at": value.get("resets_at")}
            return {"primary": window("primary"), "secondary": window("secondary"), "source": "codex",
                    "observed_at": event.get("timestamp") or int(path.stat().st_mtime)}
    return None


def process_alive(pid):
    """只查询不打扰：Windows 上 os.kill(pid, 0) 会直接结束进程，所以用 OpenProcess 查询退出码。"""
    if not isinstance(pid, int) or pid <= 0:
        return True  # 旧记录没有 owner_pid，无法判断时按仍在运行处理
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def settle_orphan(run):
    """宿主进程已不在而状态仍是 queued/running：显示为已中断（只改返回给面板的副本，不改磁盘记录）。"""
    if run.get("state") in ("queued", "running") and not process_alive(run.get("owner_pid")):
        run = dict(run, state="failed", error="宿主进程已退出，这一轮已中断")
    return run


def run_partner(run):
    """这一轮被调用的是哪一端：route.partner_agent，缺省时从 agent_settings 推断。"""
    route = run.get("route") or {}
    if route.get("partner_agent") in ("codex", "claude"):
        return route["partner_agent"]
    settings = run.get("agent_settings") or {}
    if settings.get("agent") in ("codex", "claude"):
        return settings["agent"]
    keys = [k for k in settings if k in ("codex", "claude")]
    if len(keys) == 1:
        return keys[0]
    if keys:
        return "both"  # 辩论：两端都参与，两边面板都显示
    return "codex" if settings.get("model") else None  # 实施任务只有 Codex


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, bridge, workspace: Path, primary: str):
        super().__init__(("127.0.0.1", 0), PanelHandler)
        self.bridge = bridge
        self.workspace = workspace.resolve()
        self.primary = primary
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.last_activity = time.monotonic()
        self.lock = threading.Lock()
        self.catalog = None
        self.catalog_at = 0.0
        self.limits = (0.0, None)

    def partner_limits(self, partner):
        """对端账号额度，两边都实时读取（缓存 60 秒）。

        Codex 的实时接口不可用时，退回读 Codex App 会话日志里最近一次记录——注意插件自己的调用
        不写会话日志，所以那份数据可能是旧的，面板会注明读取时间。
        """
        if partner not in ("codex", "claude"):
            return None
        at, value = self.limits
        if time.monotonic() - at > 60:
            from mcp_server import claude_rate_limits, codex_live_limits
            value = (codex_live_limits() or codex_rate_limits()) if partner == "codex" else claude_rate_limits()
            self.limits = (time.monotonic(), value)
        return value

    def state(self):
        with self.lock:
            # 模型目录（含登录状态）10 分钟刷新一次：登录、升级 CLI 或账号可用模型变化后无需重开面板。
            age = time.monotonic() - self.catalog_at
            waiting_login = (self.catalog or {}).get("claude_login") and not self.catalog["claude_login"].get("logged_in")
            if self.catalog is None or age > 600 or (waiting_login and age > 15):
                self.catalog = self.bridge.get_model_catalog({
                    "workspace": str(self.workspace), "primary_agent": self.primary,
                })
                self.catalog_at = time.monotonic()
            data = dict(self.catalog)
            prefs = self.bridge._read_preferences()
            data["preferences"] = prefs.get("partners", {}).get(data["partner_agent"], {})
            data["collaboration_enabled"] = bool(prefs.get("enabled", False))
        data["workspace"] = str(self.workspace)
        data["write_enabled"] = self.bridge.allow_write
        data["partner_limits"] = self.partner_limits(data.get("partner_agent"))
        data["runs"] = [
            {key: run.get(key) for key in ("run_id", "state", "kind", "mode", "stage", "route",
                                           "agent_settings", "usage_summary", "actual_model",
                                           "created_at", "updated_at", "error")}
            for run in map(settle_orphan, self.bridge.list_runs({"limit": 50}))
            if str(Path(run.get("workspace") or ".").resolve()) == str(self.workspace)
            # 两个宿主共用运行目录：只显示“本端调用对端”的记录（Claude 面板看调 Codex 的，Codex 面板看调 Claude 的）
            and run_partner(run) in (data["partner_agent"], "both")
        ][:8]
        return data


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log the local session token.

    def reply(self, status, value, mime="application/json; charset=utf-8"):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def valid_request(self, auth=False):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.reply(403, {"error": "Invalid host"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self.reply(403, {"error": "Invalid origin"})
            return False
        if auth and not secrets.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + self.server.token
        ):
            self.reply(401, {"error": "面板会话已失效，请重新打开 AI Coop"})
            return False
        self.server.last_activity = time.monotonic()
        return True

    def do_GET(self):
        route = urlsplit(self.path).path
        if not self.valid_request(auth=route.startswith("/api/")):
            return
        if route == "/api/ping":
            self.reply(200, {"ok": True, "workspace": str(self.server.workspace)})
        elif route == "/api/run":
            run_id = (parse_qs(urlsplit(self.path).query).get("id") or [""])[0]
            if not RUN_ID.match(run_id):
                self.reply(400, {"error": "Invalid run id"})
                return
            run_dir = self.server.bridge.runs_dir / run_id
            try:
                status = settle_orphan(json.loads((run_dir / "status.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                self.reply(404, {"error": "找不到这次调用的记录"})
                return
            keys = ("run_id", "state", "kind", "mode", "stage", "route", "agent_settings",
                    "actual_model", "created_at", "updated_at", "error")
            self.reply(200, {"run": {k: status.get(k) for k in keys},
                             "task": (run_dir / "request.md").read_text(encoding="utf-8", errors="replace")[:4000]
                             if (run_dir / "request.md").exists() else "",
                             "entries": read_transcript(run_dir)})
        elif route == "/api/state":
            try:
                self.reply(200, self.server.state())
            except Exception as exc:
                self.reply(500, {"error": str(exc)})
        elif route in ("/", "/sidebar.js", "/sidebar.css", "/background.js"):
            name = "sidebar.html" if route == "/" else route[1:]
            mime = {"sidebar.html": "text/html", "sidebar.js": "text/javascript",
                    "background.js": "text/javascript", "sidebar.css": "text/css"}[name]
            self.reply(200, (ASSETS / name).read_bytes(), mime + "; charset=utf-8")
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self.valid_request(auth=True):
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("JSON required")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 8192:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            with self.server.lock:
                if self.path == "/api/preferences":
                    if set(data) - {"partner_selection", "partner_model", "partner_effort"}:
                        raise ValueError("Unknown preference")
                    result = self.server.bridge.set_partner_preferences({**data, "primary_agent": self.server.primary})
                elif self.path == "/api/claude-login":
                    # 在新的可见终端里运行登录（需要用户在浏览器授权，必要时在终端里粘贴授权码）。
                    server_py = Path(__file__).with_name("mcp_server.py")
                    options = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if os.name == "nt" else {}
                    python = Path(sys.executable)
                    if python.name.lower() == "pythonw.exe" and python.with_name("python.exe").exists():
                        python = python.with_name("python.exe")  # pythonw 没有控制台，登录提示会看不到
                    subprocess.Popen([str(python), str(server_py), "--claude-login"], **options)
                    self.server.catalog = None  # 登录完成后下一次刷新重新读取登录状态
                    result = {"started": True}
                elif self.path == "/api/shutdown":
                    self.reply(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif self.path == "/api/mode":
                    if set(data) != {"enabled"}:
                        raise ValueError("enabled required")
                    result = self.server.bridge.set_collaboration_mode(data)
                else:
                    self.reply(404, {"error": "Not found"})
                    return
            self.reply(200, result)
        except (ValueError, TypeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)})


def healthy_session(record, workspace):
    try:
        parsed = urlsplit(record["url"])
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            return False
        request = Request(record["url"].split("#")[0] + "api/ping", headers={"Authorization": "Bearer " + record["token"]})
        with build_opener(ProxyHandler({})).open(request, timeout=1) as response:
            return json.load(response).get("workspace") == str(workspace)
    except (OSError, ValueError, KeyError):
        return False


def retire_old_panels(folder, keep, workspace, primary):
    """面板常驻不闲置退出；为免进程累积，启动新版面板前请同一工作区、同一端的旧面板自行退出。

    通过旧面板自己的 /api/shutdown（需其令牌）通知，而不是按 pid 结束进程，避免误伤复用了 pid 的其他程序。
    """
    for other in folder.glob("*.json"):
        if other == keep:
            continue
        try:
            record = json.loads(other.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("workspace") != str(workspace) or record.get("primary") != primary:
            continue
        try:
            request = Request(record["url"].split("#")[0] + "api/shutdown", data=b"{}", method="POST",
                              headers={"Authorization": "Bearer " + record["token"],
                                       "Content-Type": "application/json"})
            build_opener(ProxyHandler({})).open(request, timeout=2).close()
        except (OSError, ValueError, KeyError):
            pass
        try:
            other.unlink()
        except OSError:
            pass


def ensure_panel(bridge, workspace, primary):
    workspace = Path(workspace).resolve()
    # New code gets a new process; each panel remains bound to its own workspace.
    digest = hashlib.sha256()
    digest.update(f"{workspace}|{primary}|{bridge.allow_write}".encode())
    for path in (Path(__file__), Path(__file__).with_name("mcp_server.py"), ASSETS / "sidebar.html", ASSETS / "sidebar.js",
                 ASSETS / "sidebar.css", ASSETS / "background.js"):
        digest.update(path.read_bytes())
    folder = bridge.runs_dir.parent / "panels"
    folder.mkdir(parents=True, exist_ok=True)
    state_file = folder / (digest.hexdigest()[:20] + ".json")
    try:
        record = json.loads(state_file.read_text(encoding="utf-8"))
        if healthy_session(record, workspace):
            return {"url": record["url"], "workspace": str(workspace), "placement": "right"}
    except (OSError, ValueError):
        pass
    retire_old_panels(folder, state_file, workspace, primary)
    args = [sys.executable, str(Path(__file__).resolve()), "--serve", "--workspace", str(workspace),
            "--runs-dir", str(bridge.runs_dir), "--host-agent", primary, "--state-file", str(state_file)]
    if bridge.allow_write:
        args.append("--allow-write")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, cwd=workspace, **options)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"AI Coop 面板启动失败（exit {child.returncode}）")
        try:
            record = json.loads(state_file.read_text(encoding="utf-8"))
            if healthy_session(record, workspace):
                return {"url": record["url"], "workspace": str(workspace), "placement": "right"}
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    child.terminate()
    raise RuntimeError("AI Coop 面板启动超时")


def main():
    from mcp_server import Bridge, default_runs_dir
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, default=default_runs_dir())
    parser.add_argument("--host-agent", choices=("codex", "claude"), default="codex")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    bridge = Bridge(None, args.runs_dir, args.allow_write, None, None, 3600, args.host_agent)
    workspace = bridge.resolve_workspace(str(args.workspace))
    if not args.serve:
        print(json.dumps(ensure_panel(bridge, workspace, args.host_agent), ensure_ascii=False))
        return
    server = PanelServer(bridge, workspace, args.host_agent)
    record = {"url": server.origin + "/#" + server.token, "token": server.token, "pid": os.getpid(),
              "workspace": str(workspace), "primary": args.host_agent}
    args.state_file.write_text(json.dumps(record), encoding="utf-8")
    try:
        server.serve_forever(poll_interval=0.5)  # 常驻：面板关掉也保留，下次打开立即可用
    finally:
        server.server_close()
        try:
            if json.loads(args.state_file.read_text()).get("pid") == os.getpid():
                args.state_file.unlink()
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    main()
