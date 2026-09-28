#!/usr/bin/env python3
"""macOS / Linux installer for AI Coop (the Windows counterpart is install.ps1 / uninstall.ps1).

    install.sh   [--target claude|codex|both] [--read-only]
    uninstall.sh [--target claude|codex|both] [--purge]
    claude-login.sh [--status]

Only the Python standard library is used. Every JSON file that is changed outside the
plugin folder is backed up next to itself first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
DATA_ROOT = HOME / ".ai-coop"
RUNS_DIR = DATA_ROOT / "runs"
CLAUDE_ROOT = HOME / ".claude" / "skills" / "ai-coop"
CODEX_ROOT = HOME / "plugins" / "ai-coop"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
CODEX_MARKETPLACE = HOME / ".agents" / "plugins" / "marketplace.json"
LEGACY_DESKTOP_CONFIGS = [
    HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    HOME / ".config" / "Claude" / "claude_desktop_config.json",
]
STAMP = time.strftime("%Y%m%d-%H%M%S")


def load_server():
    sys.path.insert(0, str(SOURCE_ROOT / "server"))
    import mcp_server  # noqa: E402 - 与服务端共用 CLI 查找与 PATH 补全逻辑
    return mcp_server


def find_cli(name: str) -> str | None:
    server = load_server()
    bridge = server.Bridge(None, RUNS_DIR, False, None, None, 60, "claude" if name == "codex" else "codex")
    return bridge.executable(name, required=False)


def require_cli(name: str) -> str:
    path = find_cli(name)
    if not path:
        raise SystemExit(f"{name} CLI was not found. Install the {name.title()} app or CLI and sign in first.")
    return path


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-{STAMP}"))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_plugin(destination: Path, host: str) -> Path:
    if destination.resolve() == SOURCE_ROOT:
        return destination
    if destination.exists() or destination.is_symlink():
        backup_root = DATA_ROOT / "backups" / host
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(backup_root / f"ai-coop-{STAMP}"))
    shutil.copytree(SOURCE_ROOT, destination, ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"))
    return destination


def write_host_config(root: Path, host: str, python: str, read_only: bool) -> None:
    args = [str(root / "server" / "mcp_server.py"), "--runs-dir", str(RUNS_DIR), "--host-agent", host]
    if not read_only:
        args.append("--allow-write")
    server = {"command": python, "args": args, "env": {"AI_COOP_HOST_AGENT": host}}
    write_json(root / ".mcp.json", {"mcpServers": {"ai-coop": server}})
    # Codex 实际读取插件根目录的 mcp.json（agent-plugins 格式）。实测 Codex 0.158：缺 $schema 或 command
    # 写成绝对路径时整份文件被忽略，但 args 可以是绝对路径。所以命令用 sh，由它 exec 安装时选定的解释器，
    # 不依赖 App 的 PATH 里恰好是哪个 python3（macOS 系统自带的常是 3.9）。
    plugin_args = ["-c", 'exec "$0" "$@"', python, "./server/mcp_server.py", "--host-agent", host]
    plugin_args += [] if read_only else ["--allow-write"]
    write_json(root / "mcp.json", {"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                                   "mcpServers": {"ai-coop": {"type": "stdio", "command": "sh", "args": plugin_args}}})
    if host == "claude":
        manifest_path = root / ".claude-plugin" / "plugin.json"
        manifest = read_json(manifest_path, {})
        claude_args = ["${CLAUDE_PLUGIN_ROOT}/server/mcp_server.py", "--runs-dir", str(RUNS_DIR), "--host-agent", "claude"]
        if not read_only:
            claude_args.append("--allow-write")
        manifest["mcpServers"] = {"ai-coop": {"command": python, "args": claude_args,
                                              "env": {"AI_COOP_HOST_AGENT": "claude"}}}
        write_json(manifest_path, manifest)
    hook = f'"{python}" "${{CLAUDE_PLUGIN_ROOT}}/scripts/auto-collab-hook.py"'
    write_json(root / "hooks" / "hooks.json", {
        "description": "Keep AI Coop automatic after the user opens it once.",
        "hooks": {"UserPromptSubmit": [{"hooks": [{
            "type": "command", "command": hook, "timeout": 5, "statusMessage": "AI Coop"}]}]},
    })


def remove_key(path: Path, container: str, name: str) -> None:
    config = read_json(path, None)
    if not isinstance(config, dict) or name not in (config.get(container) or {}):
        return
    del config[container][name]
    write_json(path, config, backup=True)


def install_claude(python: str, read_only: bool, claude: str) -> None:
    root = copy_plugin(CLAUDE_ROOT, "claude")
    write_host_config(root, "claude", python, read_only)
    settings = read_json(CLAUDE_SETTINGS, {})
    settings.setdefault("enabledPlugins", {})["ai-coop@skills-dir"] = True
    write_json(CLAUDE_SETTINGS, settings, backup=True)
    for legacy in LEGACY_DESKTOP_CONFIGS:
        remove_key(legacy, "mcpServers", "ai-coop")
    if subprocess.call([claude, "plugin", "validate", str(root)]) != 0:
        raise SystemExit("Claude plugin validation failed.")


def install_codex(python: str, read_only: bool, codex: str) -> None:
    root = copy_plugin(CODEX_ROOT, "codex")
    write_host_config(root, "codex", python, read_only)
    marketplace = read_json(CODEX_MARKETPLACE, {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []})
    if marketplace.get("name") != "personal":
        raise SystemExit(f"Unexpected personal marketplace name: {marketplace.get('name')}")
    if not any(p.get("name") == "ai-coop" for p in marketplace.get("plugins") or []):
        marketplace.setdefault("plugins", []).append({
            "name": "ai-coop", "source": {"source": "local", "path": "./plugins/ai-coop"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"})
    write_json(CODEX_MARKETPLACE, marketplace, backup=True)
    # 旧版把服务直接写进 config.toml；现在由插件自带，去掉旧条目以免工具重复。
    subprocess.call([codex, "mcp", "remove", "ai-coop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if subprocess.call([codex, "plugin", "add", "ai-coop@personal"]) != 0:
        raise SystemExit("Codex plugin installation failed.")


def uninstall(target: str, purge: bool) -> None:
    if target in ("claude", "both"):
        remove_key(CLAUDE_SETTINGS, "enabledPlugins", "ai-coop@skills-dir")
        for legacy in LEGACY_DESKTOP_CONFIGS:
            remove_key(legacy, "mcpServers", "ai-coop")
        if CLAUDE_ROOT.is_dir() and CLAUDE_ROOT.parent == HOME / ".claude" / "skills":
            shutil.rmtree(CLAUDE_ROOT)
    if target in ("codex", "both"):
        codex = find_cli("codex")
        if codex:
            subprocess.call([codex, "mcp", "remove", "ai-coop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.call([codex, "plugin", "remove", "ai-coop@personal"])
        if CODEX_ROOT.is_dir() and CODEX_ROOT.parent == HOME / "plugins":
            shutil.rmtree(CODEX_ROOT)
    if purge and DATA_ROOT.is_dir():
        shutil.rmtree(DATA_ROOT)
    print("AI Coop removed" + (", including ~/.ai-coop run logs." if purge
                               else ". Run logs in ~/.ai-coop were kept (use --purge to delete them)."))


def main() -> int:
    if sys.version_info < (3, 10):
        raise SystemExit("AI Coop needs Python 3.10 or newer.")
    parser = argparse.ArgumentParser(prog="ai-coop")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--target", choices=("claude", "codex", "both"), default="both")
    install.add_argument("--read-only", action="store_true",
                         help="never let the partner edit workspace files")
    remove = sub.add_parser("uninstall")
    remove.add_argument("--target", choices=("claude", "codex", "both"), default="both")
    remove.add_argument("--purge", action="store_true",
                        help="also delete ~/.ai-coop (run logs, preferences, plugin backups)")
    login = sub.add_parser("login")
    login.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.command == "uninstall":
        uninstall(args.target, args.purge)
        return 0
    if args.command == "login":
        flag = "--claude-status" if args.status else "--claude-login"
        return subprocess.call([sys.executable, str(SOURCE_ROOT / "server" / "mcp_server.py"), flag])

    python = str(Path(sys.executable).resolve())
    # 先找齐所需的 CLI 再动文件，避免找不到时留下装了一半的状态。
    hosts = ("codex", "claude") if args.target == "both" else (args.target,)
    clis = {host: require_cli(host) for host in hosts}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if "codex" in clis:
        install_codex(python, args.read_only, clis["codex"])
    if "claude" in clis:
        install_claude(python, args.read_only, clis["claude"])
    print(f"AI Coop installed for: {args.target}")
    print("Write mode: " + ("read-only" if args.read_only
                            else "enabled (each implementation run still needs an approved decision)"))
    print("Fully quit and reopen each configured app, then say \"open AI Coop\" once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
