# Claude-Codex-coop

**你是否也遇到过这些情况？**

- 一个 AI 说得头头是道，你却拿不准它是不是在"一本正经地胡说"，只能自己再去查一遍；
- 想让 Claude 和 Codex 互相把关，就得在两个窗口之间复制粘贴，来回切换；
- 两边给出不同答案时，不知道该信谁，也不知道分歧到底在哪。

**Claude-Codex-coop 让两个 AI 在同一个对话里替你互相把关。**

在 Claude 桌面版或 Codex 桌面版里照常聊天，当前的 AI 就是**主协调**：它先形成自己的判断，需要时自动调用另一边的 AI 做审查、找反例或实现，逐项核对对方的依据，再给你一个综合回答，并说清哪些已证实、哪些存疑。你不用切换窗口，也不用复制粘贴。

| 在哪边聊天 | 主协调 | 被调用执行任务的协作 AI |
|---|---|---|
| Claude 桌面版 | Claude | Codex |
| Codex 桌面版 | Codex | Claude |

> 预览版，目前仅支持 Windows 10/11。

## 功能

- **自动协作**：打开一次，之后值得协作的任务会自动调用另一边；问候、状态查询等不会触发。
- **协作协议**：主协调先给出自己的初判，再按"目标 / 已知 / 初判 / 具体问题 / 验收标准 / 禁止事项"把任务交给对方；对方按分析、决策、审查、实施四种模式交付结构化结果；主协调逐项复核，分歧转成可执行的检验，每个任务最多两轮。
- **侧边面板**：
  - 对方正在用的模型、推理强度和实时运行状态；
  - 对方账号的额度占用（5 小时 / 每周，含重置时间）与本轮 token；
  - 点开任意一次调用，查看对方的完整回复（思考过程与命令步骤默认折叠）；
  - 手动指定下一次调用的模型与推理强度，列表来自对方账号当前可调用的模型；
  - 背景可选跟随 App 的浅色/深色，或极光、星河、地平线动态背景。
- **按任务授权**：分析、决策、审查只读；实施任务按你给出的授权修改文件，两边规则相同。

## 前提

- Windows 10/11，PowerShell 5.1 或 7
- Python 3.10+（或用环境变量 `AI_COOP_PYTHON_EXE` 指定解释器）
- Codex 桌面版，已登录
- Claude 桌面版，并完成一次 Claude CLI 登录（见下方安装第 3 步；桌面版自带 Claude CLI，无需另装）

## 安装

```powershell
git clone https://github.com/youagainchen/claude-codex-coop.git
cd claude-codex-coop
.\scripts\install.ps1 -Target Both   # 1. 安装到 Claude 与 Codex
.\scripts\doctor.ps1                 # 2. 检查 Python 与两边的 CLI
.\scripts\claude-login.ps1           # 3. 登录 Claude CLI（用与 Claude 桌面版相同的账号，只需一次）
```

然后**完全退出并重新打开**两个 App。

- 只装一边：`-Target Claude` 或 `-Target Codex`。
- 全局禁止写入：安装时加 `-ReadOnly`。
- 升级：`git pull` 后重新运行 `install.ps1`。
- 查看 Claude CLI 登录状态：`.\scripts\claude-login.ps1 -Status`。

## 使用

1. 在任意一边的对话里说 **"打开 AI Coop"**，面板出现在右侧，自动协作开启。
2. 正常描述任务。需要另一边时，主协调会自动发起调用，面板实时显示进度。
3. 指定对方的模型或推理强度：在面板"下一次调用"里选"手动指定"，或直接在对话里说，例如"让 Codex 用 gpt-5.6-sol、high 审查这个方案"。
4. 关闭：点面板右上角的开关，或说"关闭 AI Coop"。

## 数据与隐私

- **发给协作 AI 的内容**：任务包，以及当前工作区的只读快照：文件清单（最多 400 项）和常见说明文件（`AGENTS.md`、`CLAUDE.md`、`README.md`、`PROJECT_BRIEF.md`、`DECISIONS.md`、`HANDOFF.md` 等）。
  - 快照会跳过疑似密钥或凭据的文件（`.env*`、`*.pem`、`*.key`、`id_rsa*`、`*credentials*`、`*secret*` 等），以及 `.git`、`.ssh`、`node_modules` 等目录。
  - 在项目根目录放一个 `.ai-coop-context`（每行一个相对路径），可以自定义附带哪些文件。
- **本地记录**：每次调用的请求、回复与事件流保存在 `~/.ai-coop/runs/`，偏好保存在 `~/.ai-coop/preferences.json`。
- **账号信息**（仅用于面板显示）：
  - Claude：使用 Claude CLI 的登录凭证，只向 `api.anthropic.com` 查询可用模型和额度；
  - Codex：从 Codex 自己的会话日志读取最近一次记录的额度，不联网。

## 卸载

```powershell
.\scripts\uninstall.ps1 -Target Both          # 移除插件，保留 ~/.ai-coop
.\scripts\uninstall.ps1 -Target Both -Purge   # 连运行记录一起删除
```

## 常见问题

- **面板提示 Claude CLI 未登录**：运行 `.\scripts\claude-login.ps1`。
- **协作一直失败**：运行 `.\scripts\doctor.ps1`，检查 Python 版本和两边的 CLI 能否找到。
- **指定 CLI 位置**：环境变量 `AI_COOP_CLAUDE_EXE`、`AI_COOP_CODEX_EXE`。默认会在 PATH 和两个桌面版自带的 CLI 中选版本最高的一份。

## 工作原理

插件是一个本地 MCP 服务（`server/mcp_server.py`，只依赖 Python 标准库），同时安装进两个桌面版：

- 主协调调用 `start_workflow` 后，服务在后台启动另一边的 CLI（`codex exec --json` 或 `claude -p --output-format stream-json`）。事件逐行写入 `stream.jsonl` 供面板实时显示，结束后结果交回主协调。
- 调用 Claude 时只读取项目级与本机级配置，固定使用 Claude CLI 登录的账号。
- 面板（`server/sidebar.py`）只监听 `127.0.0.1`，端口随机并带一次性令牌；启动后常驻，插件升级后会自动替换旧面板。

开发测试：`python -m unittest discover -s tests`

## 许可

代码采用 MIT 许可，见 [LICENSE](LICENSE)。面板的"极光"背景改编自 nimitz 的 Shadertoy 作品，出处与许可见 [NOTICE.md](NOTICE.md)。
