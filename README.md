# AI Coop（claude-codex-coop）

让 **Claude 桌面版** 和 **Codex 桌面版** 在各自原本的聊天框里互相协作的插件。

你在哪一边聊天，哪一边就是"主协调"：它先形成自己的判断，需要时自动把任务交给另一边的 AI（审查、找反例、做实现），读回结果后给你一个综合回答。你不需要切换窗口，也不需要输入任何特殊命令。

- 在 **Claude** 里聊天：Claude 主协调，**Codex** 是协作伙伴，经你批准后可以修改工作区。
- 在 **Codex** 里聊天：Codex 主协调，**Claude** 是协作伙伴，只做分析和审查。

> 状态：预览版，目前**只支持 Windows 10/11**。

## 能做什么

- **自动协作**：打开一次后，之后的实质性任务会自动咨询另一边；问候、状态查询等不会触发。
- **右侧面板**：在 Claude 的内置浏览器面板或 Codex 的右侧面板里显示：
  - 协作伙伴当前用的**模型、推理强度**和**实时运行状态**；
  - 对方账号的**额度占用**（5 小时 / 每周窗口及具体重置时间）和本轮 token 用量；
  - 点开任意一次调用，查看对方的**完整回复**（Markdown 排版；思考过程和命令步骤默认折叠）；
  - 手动指定下一次调用的模型与推理强度（列表来自对方账号当前可调用的模型）；
  - 可选动态背景（极光 / 星河 / 地平线）或跟随 App 的浅色/深色。
- **写入需要批准**：分析、决策、审查类调用始终只读；只有带着"已批准的具体决定"发起的实施任务，Codex 才会改文件。

## 前提条件

| 需要 | 说明 |
|---|---|
| Windows 10/11 | 安装脚本为 PowerShell（5.1 或 7 均可） |
| Python 3.10+ | 插件后台服务使用；也可用环境变量 `AI_COOP_PYTHON_EXE` 指定解释器 |
| Codex 桌面版 | 已登录。插件会调用它自带的 `codex` 命令行，共用同一个登录 |
| Claude 桌面版 + Claude Code 命令行 | 命令行需**单独登录一次**：`claude auth login`（用与 Claude App 相同的账号） |

为什么 Claude 需要单独登录：Codex App 与命令行共用 `~/.codex/auth.json`，但 Claude App 的登录只保存在 App 内部，命令行读不到，所以要用 `claude auth login` 生成命令行自己的登录文件。只需一次，之后自动续期。

如果你的网络无法直连 Anthropic / OpenAI，请先设置代理（例如 PowerShell 里 `$env:HTTPS_PROXY="http://127.0.0.1:端口"`）再登录。插件调用命令行时，若环境里没有代理变量，会自动沿用 Windows 系统代理。

## 安装

```powershell
git clone https://github.com/youagainchen/claude-codex-coop.git
cd claude-codex-coop
.\scripts\doctor.ps1                 # 检查 Python 与两个命令行
.\scripts\install.ps1 -Target Both   # 同时装到 Claude 与 Codex
```

- 安装后**完全退出并重新打开** Claude 与 Codex 两个 App。
- 默认允许写入：每一轮是否真的修改文件，仍由"实施模式 + 已批准的决定"逐次放行。想全局禁止写入，安装时加 `-ReadOnly`。
- 只装一边：`-Target Claude` 或 `-Target Codex`。
- 升级：`git pull` 后重新运行安装脚本。

安装位置：Claude 端 `~/.claude/skills/ai-coop`，Codex 端 `~/plugins/ai-coop`（并登记到 Codex 的个人插件市场）。

## 使用

1. 在任意一边的对话里说一句 **"打开 AI Coop"**。面板会出现在右侧，自动协作开启。
2. 之后正常描述任务即可。需要另一边帮忙时，主协调会自动发起调用，面板实时显示进度。
3. 想指定对方的模型或推理强度：在面板"下一次调用"里选"手动指定"，或直接在对话里说（例如"让 Codex 用 gpt-5.6-sol、high 审查这个方案"）。
4. 关闭：点面板右上角开关，或说"关闭 AI Coop"。

面板关掉了不影响协作；需要时再说一次"打开 AI Coop"即可。

## 数据与隐私

请在使用前了解插件会读写哪些数据：

- **发给另一边 AI 的内容**：你的任务描述、主协调补充的上下文，以及当前工作区的只读快照，包括：
  - 文件清单（最多 400 项）；
  - 常见的说明文件（`AGENTS.md`、`CLAUDE.md`、`README.md`、`PROJECT_BRIEF.md`、`DECISIONS.md`、`HANDOFF.md` 等）。

  快照不会列出或读取疑似密钥/凭据的文件（`.env*`、`*.pem`、`*.key`、`id_rsa*`、`*credentials*`、`*secret*` 等），也会跳过 `.git`、`.ssh`、`node_modules` 等目录。这些内容只发送给你自己已登录的另一个 AI 账号。
- **自定义附带文件**：在项目根目录放一个 `.ai-coop-context`，每行一个相对路径，就会改为附带这些文件。
- **本地记录**：每次调用的请求、对方回复、事件流保存在 `~/.ai-coop/runs/`，偏好设置在 `~/.ai-coop/preferences.json`。可随时删除，或用 `uninstall.ps1 -Purge` 一并清除。
- **账号信息**（仅用于面板显示）：
  - Claude：读取 `claude auth login` 生成的 `~/.claude/.credentials.json` 中的访问令牌，只向 `api.anthropic.com` 请求可用模型列表（`/v1/models`）和额度占用（`/api/oauth/usage`）。令牌不写日志、不转交其他程序。
  - Codex：从 Codex App 自己的会话日志（`~/.codex/sessions`）读取最近一次记录的额度，不联网。

## 卸载

```powershell
.\scripts\uninstall.ps1 -Target Both          # 移除插件，保留 ~/.ai-coop 运行记录
.\scripts\uninstall.ps1 -Target Both -Purge   # 连运行记录一起删除
```

## 常见问题

- **面板显示"命令行还没登录 Claude"**：运行 `claude auth login`，网络受限时先设置 `HTTPS_PROXY`。
- **登录时报 `Login failed: ... 403`**：浏览器授权成功，但命令行换取令牌时被网络拦截。设置代理后重新登录。
- **协作一直失败**：运行 `.\scripts\doctor.ps1`，检查 Python 版本和两个命令行能否找到。
- **找不到 Claude 命令行**：插件会在 PATH、`System32` 和 Claude App 自带的 Claude Code 中选版本最高的一份；也可以用环境变量 `AI_COOP_CLAUDE_EXE` 指定。Codex 同理，用 `AI_COOP_CODEX_EXE`。

## 工作原理

插件是一个本地 MCP 服务（`server/mcp_server.py`，只用 Python 标准库），同时装进两个宿主：

- 主协调调用 `start_workflow` 时，服务在后台启动另一边的命令行：`codex exec --json` 或 `claude -p --output-format stream-json`。事件逐行写入 `stream.jsonl` 供面板实时读取，结束后把结果交回主协调。
- 调用 Claude 时只读项目级与本机级 Claude 配置（`--setting-sources project,local`），不受用户级配置里第三方供应商设置的影响，固定使用命令行登录的 Claude 账号。
- 面板（`server/sidebar.py`）只监听 `127.0.0.1`、端口随机、带一次性访问令牌，闲置一小时自动退出。

## 开发

```powershell
python -m unittest discover -s tests
```

## 许可

- 代码：MIT，见 [LICENSE](LICENSE)。
- 面板的"极光"背景着色器改编自 nimitz 的 Shadertoy 作品，使用 CC BY-NC-SA 3.0，见 [NOTICE.md](NOTICE.md)。
