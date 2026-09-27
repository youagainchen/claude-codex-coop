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
        "AI Coop automatic collaboration is enabled. For each substantive user task, the AI in "
        "this native chat is the primary coordinator: form an initial view, call AI Coop's "
        "start_workflow exactly once with the absolute path of the workspace currently open in "
        "this chat to ask the other AI, poll the same run_id with get_run_status "
        "until completion, then give one integrated answer. Continue another round only when a "
        "material disagreement remains. Do not ask the user to type or invoke 'workflow'. Do not "
        "start a partner run for greetings, connection/status checks, model-setting changes, or a "
        "request to disable AI Coop. Preserve normal approval and write-safety requirements. "
        "In the Claude desktop app, if the AI Coop panel is not already open in the built-in "
        "browser pane in this conversation, call open_sidebar and open its URL with the browser "
        "pane's preview_start before the first start_workflow, so the user sees the partner model, "
        "reasoning effort and run state."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
