---
name: ai-coop-open
description: Open AI Coop once, then automatically coordinate the other AI for later substantive tasks in the same native chat. Use when the user asks to open, start, enable, or use AI collaboration, and on later tasks after AI Coop is enabled.
---

# Open AI Coop

When the user opens or enables AI Coop, identify the absolute path of the workspace currently open in this native chat. Pass that path as `workspace` to `health_check` once. If the bridge is healthy, call `set_collaboration_mode` with `enabled: true`. Never reuse an install-time folder or a workspace from another chat.

In Codex, call `open_sidebar` with that workspace, then use the Codex app's `open_in_codex` tool with `target: {type: "browser", url: <returned URL>}` and `placement: "right"`. This opens an independent right-side control panel beside the conversation. The plugin hosts this page on loopback in a hidden background process; reuse its returned session rather than opening multiple servers. Do not call `show_partner_selector` for this route: it produces an inline chat card, not a sidebar. A successful `open_sidebar` response only proves the page is ready; report the pane opened only after the app tool succeeds.

If this conversation still has older MCP tools without `open_sidebar`, use the plugin's `server/sidebar.py --workspace <absolute current workspace> --host-agent codex` with an available Python interpreter and pass its returned URL to `open_in_codex`. Resolve the script relative to this installed skill (`../../server/sidebar.py`); do not invent an installation directory. Use the same runs directory reported by `health_check` via `--runs-dir`.

In the Claude desktop app, call `open_sidebar` with that workspace and `primary_agent: "claude"`, then open the returned URL (including its `#` token) in the built-in browser pane with `mcp__Claude_Browser__preview_start` (`url` parameter). The panel shows the partner's model, reasoning effort and live run state and polls every two seconds, so it does not need to be reopened for each run. If the pane was closed later, call `open_sidebar` again before the next `start_workflow`; it reuses the running panel process.

In hosts without either pane tool, keep using `show_partner_selector` once as the inline fallback and accurately describe it as an inline selector. Do not install an external launcher or change another application's installation. Tell the user collaboration is active and they can describe tasks normally. Do not ask them to invoke a second skill or workflow command.

If the health check fails, report the failing CLI or path instead of creating a workflow run. Do not call `start_workflow` until the user provides an actual collaboration task.

For each later substantive task while collaboration is enabled:

1. The AI in the current native chat remains the primary coordinator. Form an initial view.
2. Call `start_workflow` once with the absolute path of the workspace currently open in this native chat. The bridge automatically selects the other AI and its saved or automatic model settings.
3. Unless the user explicitly requests only the `run_id`, poll that same run with `get_run_status` until it completes.
4. Read the partner result and give one integrated answer. Start another round only when a material disagreement remains.

Do not start a partner run for greetings, connection/status checks, model-setting changes, or a request to close or disable AI Coop. If the user asks to disable automatic collaboration, call `set_collaboration_mode` with `enabled: false`.

Preserve explicit model and effort requests. Implementation still requires the user's concrete authorization and write mode; do not broaden permissions merely because collaboration is enabled. Nested agents must not invoke AI Coop again.
