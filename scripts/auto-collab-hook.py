#!/usr/bin/env python3
"""Inject automatic AI Coop routing after the user has enabled it once."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def preferences_path() -> Path:
    # 与 mcp_server.default_runs_dir 保持一致（避开 MSIX 对 AppData 的重定向）。
    if os.name == "nt":
        return Path.home() / ".ai-coop" / "preferences.json"
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "ai-coop" / "preferences.json"
    return Path.home() / ".local" / "state" / "ai-coop" / "preferences.json"


def is_enabled() -> bool:
    path = preferences_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("enabled") is True


def main() -> int:
    # Partner CLI calls are deliberately isolated. Never let an inner agent
    # start another collaboration round recursively.
    if os.environ.get("AI_COOP_NESTED") == "1" or not is_enabled():
        return 0

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        event = {}
    if event.get("hook_event_name") not in {None, "UserPromptSubmit"}:
        return 0

    context = (
        "AI Coop 已启用，当前聊天的 AI 是主协调。先判断本任务是否值得协作：问候、状态或设置操作、"
        "简单且证据充分的回答、用户要求停止协作时不发起调用。需要协作时先独立形成初判，"
        "再调用一次 start_workflow（显式选择 analyze/decide/review/implement，workspace 用当前聊天工作区的绝对路径），"
        "task 写成任务包：目标、已知及来源、你的初判、最多三个具体问题、验收标准、禁止事项。"
        "轮询同一 run_id 至完成，逐项核对对方依据后整合回答，区分已证实/待验证/建议。"
        "只有影响结论的分歧才追加一轮针对性检验，每个任务最多两轮。"
        "implement 需要用户对具体改动的授权并附已批准决定；不要让协作 AI 再次调用 AI Coop；不要让用户输入 workflow。"
        "在 Claude 桌面版中，若本对话还没在内置浏览器面板打开 AI Coop 面板，"
        "先调用 open_sidebar 并用浏览器面板的 preview_start 打开其 URL，再发起第一次 start_workflow。"
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            # 输出纯 ASCII（中文转义）：Windows 管道默认按系统代码页写出，宿主按 UTF-8 读取会乱码。
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
