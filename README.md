# Claude-Codex-coop

[English](README.en.md) · 中文

**你是否也遇到过这些情况？**

- 一个 AI 说得头头是道，你却拿不准它是不是在"一本正经地胡说"；
- 想让 Claude 和 Codex 互相把关，只能在两个窗口之间来回复制粘贴，两边说法不同时也不知道该信谁。

**Claude-Codex-coop 让两个 AI 在同一个对话里替你互相把关。**

在 Claude 桌面版或 Codex 桌面版里照常聊天，当前的 AI 就是**主协调**：它先形成自己的判断，需要时自动调用另一边的 AI 做审查、找反例或实现，逐项核对对方的依据，再给你一个综合回答，并说清哪些已证实、哪些存疑。

| 在哪边聊天 | 主协调 | 被调用执行任务的协作 AI |
|---|---|---|
| Claude 桌面版 | Claude | Codex |
| Codex 桌面版 | Codex | Claude |

<table>
  <tr>
    <td width="50%"><img src="docs/panel-running.png" alt="侧边面板：正在调用 Codex，显示模型、推理强度与账号额度"></td>
    <td width="50%"><img src="docs/detail-review.png" alt="点开一次调用，查看 Codex 的完整回复"></td>
  </tr>
  <tr>
    <td>侧边面板：正在调用的模型、推理强度、实时额度与调用记录</td>
    <td>点开任意一次调用，查看对方的完整回复</td>
  </tr>
</table>

> 预览版，目前仅支持 Windows 10/11，macOS 版计划中。

## 和官方 codex-plugin-cc 有什么不同

[OpenAI 的 codex-plugin-cc](https://github.com/openai/codex-plugin-cc) 让你在 Claude Code 里调用 Codex，提供命令、自然语言委派和可选的审查门禁。本项目的侧重点不同：

- **双向**：同时装进 Claude 与 Codex 桌面版，在哪边聊天，哪边就能调用另一边。
- **自动协作，并按协议复核**：开启后按任务需要自动调用；主协调先给初判，结构化交接，逐项核对依据，分歧转成可执行的检验，最后标出已证实与存疑之处。适用于代码，也适用于写作、分析等需要"防胡说"的场景。
- **可视化面板**：随时看到对方的模型、额度、完整回复和实时进度。

## 功能

- **自动协作**：打开一次，之后值得协作的任务会自动调用另一边；问候、状态查询等不会触发。
- **协作协议**：主协调独立判断后，把目标、已知、初判、具体问题、验收标准交给对方；对方按分析、决策、审查、实施四种模式交付；每个任务最多两轮。
- **侧边面板**：对方的模型、推理强度、实时状态、账号额度与本轮 token；完整回复（思考过程与命令步骤默认折叠）；手动指定下一次调用的模型与推理强度；背景可跟随 App 浅色/深色，或选择极光、星河、地平线动态背景。
- **按任务授权**：分析、决策、审查只读；实施任务按你给出的授权修改文件，两边规则相同。

## 安装

**前提**：Windows 10/11；Python 3.10+，并且在 PowerShell 里能运行 `python --version`；已登录的 Claude 桌面版与 Codex 桌面版。

### 方式一：插件市场（推荐）

在 Claude 桌面版的 Code 对话框（或 Claude Code）中输入：

```text
/plugin marketplace add youagainchen/claude-codex-coop
/plugin install ai-coop@claude-codex-coop
```

在 PowerShell 中为 Codex 安装：

```powershell
codex plugin marketplace add youagainchen/claude-codex-coop
codex plugin add ai-coop@claude-codex-coop
```

### 方式二：安装脚本

```powershell
git clone https://github.com/youagainchen/claude-codex-coop.git
cd claude-codex-coop
.\scripts\install.ps1 -Target Both
```

没有 Git 时，可在 GitHub 页面下载 ZIP，解压后在解压出的仓库文件夹里打开 PowerShell，运行 `.\scripts\install.ps1 -Target Both`。若 PowerShell 提示禁止运行脚本，改用 `powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Target Both`。

- 只装一边：`-Target Claude` 或 `-Target Codex`；禁止协作方修改工作区文件：加 `-ReadOnly`。
- 升级：`git pull` 后再次运行 `.\scripts\install.ps1 -Target Both`。

安装后**完全退出并重新打开**两个 App。

## 使用

1. 在任意一边的对话里说 **"打开 AI Coop"**，面板出现在右侧，自动协作开启。
2. 第一次使用时，如果面板提示 Claude CLI 未登录，点 **"登录 Claude CLI"**，在浏览器里用与 Claude 桌面版相同的账号授权即可（只需一次）。
3. 正常描述任务。可以先试一句：*"帮我审查这个项目的 README，请另一边找出遗漏，并核对你们的分歧"*。面板里出现调用记录，就说明协作已经生效。
4. 指定对方的模型或推理强度：在面板"下一次调用"里选"手动指定"，或直接在对话里说，例如"让 Codex 用 gpt-6-sol、high 审查这个方案"。
5. 关闭：点面板右上角的开关，或说"关闭 AI Coop"。

## 数据与隐私

- **发给协作 AI 的内容**：任务包，以及当前工作区的只读快照：文件清单（最多 400 项）和常见说明文件（`AGENTS.md`、`CLAUDE.md`、`README.md` 等）。
  - 快照会跳过疑似密钥或凭据的文件（`.env*`、`*.pem`、`*.key`、`id_rsa*`、`*credentials*`、`*secret*` 等），以及 `.git`、`.ssh`、`node_modules` 等目录。
  - 在项目根目录放一个 `.ai-coop-context`（每行一个相对路径），可以指定随文件清单一起附带哪些说明文件；密钥类文件即使写进去也会被跳过。
- **本地记录**：每次调用的请求、回复与事件流保存在 `~/.ai-coop/runs/`。
- **账号额度与模型列表**（额度为预览功能，仅用于面板显示）：使用两边 CLI 已有的登录查询额度（`api.anthropic.com`、`chatgpt.com`）；Claude 的可用模型来自 Anthropic 的模型接口，Codex 的模型来自本机 Codex CLI。额度接口并非公开文档接口，两边升级后可能失效；失效时面板只是不显示额度，不影响协作。

## 卸载

- 插件市场安装：在 Claude 中 `/plugin uninstall ai-coop@claude-codex-coop`；在 PowerShell 中 `codex plugin remove ai-coop@claude-codex-coop`。
- 脚本安装：`.\scripts\uninstall.ps1 -Target Both`，加 `-Purge` 会同时删除 `~/.ai-coop` 里的运行记录。

## 常见问题

- **协作一直失败**：运行 `.\scripts\doctor.ps1`，确认输出中的 `codex_exe` 和 `claude_exe` 都有路径；任一为 `null` 表示没找到对应的 CLI，可用环境变量 `AI_COOP_CODEX_EXE` / `AI_COOP_CLAUDE_EXE` 指定。
- **找不到 Python**：安装 Python 3.10+ 并勾选加入 PATH（插件市场安装要求 PATH 上有 `python`）；脚本安装也可以用环境变量 `AI_COOP_PYTHON_EXE` 指定解释器。

## 工作原理

插件是一个本地 MCP 服务（`server/mcp_server.py`，只依赖 Python 标准库）：主协调调用 `start_workflow` 后，服务在后台启动另一边的 CLI（`codex exec --json` 或 `claude -p --output-format stream-json`），事件实时写入面板，结束后结果交回主协调。调用 Claude 时固定使用 Claude CLI 登录的账号。面板（`server/sidebar.py`）只监听 `127.0.0.1`，端口随机，每次启动生成一个访问令牌。

开发测试：`python -m unittest discover -s tests`

## 许可

代码采用 MIT 许可，见 [LICENSE](LICENSE)。面板的"极光"背景改编自 nimitz 的 Shadertoy 作品，出处与许可见 [NOTICE.md](NOTICE.md)。
