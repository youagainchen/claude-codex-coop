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

If the partner is Claude and its CLI is not logged in (the panel or an error says so), tell the user to run `scripts/claude-login.ps1` from the plugin folder once; do not start runs until then.

## 协作协议（自动协作开启后的每个任务）

当前聊天里的 AI 始终是**主协调**：理解用户意图与授权、划定任务、复核证据、给出最终回答。协作 AI 只交付本轮指定的成果，不接管对话。按任务需要分工，而不是按模型名字假定谁更可靠：需要检查仓库、运行代码、复现或实现时，交给具备相应工具和权限的一方；需要论证结构、反例、审稿或表达时，可交给另一方。两方意见一致不等于正确。

**何时调用**：只有当独立核查可能改变关键结论、任务需要另一方的工具或专长，或用户明确要求协作时才调用。问候、状态查询、设置操作、简单且证据充分的回答，以及用户要求停止协作时，不发起调用。

**调用前**：先独立形成自己的初判，再调用一次 `start_workflow`，明确选择 `mode`（analyze / decide / review / implement，不依赖默认值），`workspace` 用当前聊天工作区的绝对路径。`task` 写成任务包：

- **目标**：本轮要交付什么，在用户任务中用来做什么。
- **已知**：已核实的事实及来源或文件位置；未经核实的标为"待核"。
- **我的初判**：当前结论、依据、信心，以及最担心的反例。要求对方先独立判断，再与之比较。
- **具体问题**：最多三个，指出需要补的盲点；说明已完成的工作，避免重复。
- **验收标准**：成果形式、需要的可复核依据与检验、停止条件。
- **禁止事项**：权限边界、不得触碰的范围、需另行批准的操作。

**调用后**：用 `get_run_status` 轮询同一个 `run_id` 直到完成（除非用户只要 `run_id`）。逐项核对关键依据、实际文件或运行结果，检查对方是否回答了任务包里的问题，并重新审视自己的初判。回答用户时区分"已证实 / 待验证 / 仅为建议"，说明协作方贡献了什么、有哪些分歧；不要把对方的文字直接当最终结论。

**分歧**：只有影响结论的分歧才处理。先写成"冲突主张—各自依据—可执行的区分性检验—通过标准"，只针对它追加一轮；**每个任务最多两轮**（初轮 + 一次追问）。检验做不了或两轮后仍有分歧，就停止，把不确定性、可行的下一步和需要用户决定的地方告诉用户。

**权限**：analyze、decide、review 始终只读。implement 仅在用户对具体改动已授权、任务包附上已批准决定（`approved_decision`）且协作方可写时使用；协作方是 Claude 时只读，改为让它给方案、由主协调自己实施。收到实施结果后，主协调要复核实际改动和验证结果再向用户汇总。保留用户明确指定的模型、推理强度和权限要求；协作 AI 不得再次调用 AI Coop。

如用户要求关闭自动协作，调用 `set_collaboration_mode`，`enabled: false`。
