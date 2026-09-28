# Changelog

## v0.13.0 — 2026-09-28

- 面板支持英文界面：默认随系统语言（中文系统显示中文，其余英文），可在外观菜单切换并记住选择，也可用地址参数 `&lang=en` / `&lang=zh` 指定；插件自带的路由说明、步骤前缀与报错一并译出；切换语言不会丢失未保存的模型选择。
- 外观菜单选完背景或语言后自动收起，点菜单外或按 Esc 也会收起。
- macOS 实验性支持：`scripts/install.sh` / `uninstall.sh` / `claude-login.sh`（逻辑在 `posix_setup.py`）；服务端读取 macOS 系统代理与钥匙串里的 Claude 登录凭据，为图形界面程序补全 PATH，查找 App 自带的 CLI，面板登录按钮打开“终端”；Codex 经 `sh` 启动安装时选定的 Python 3.10+，不受 App 的 PATH 影响；找不到 CLI 时安装脚本在改动任何文件前退出。数据目录各平台统一为 `~/.ai-coop`。尚未在真机验证。
- 修复：Codex 实际读取插件根目录的 `mcp.json`，其中缺少 `--allow-write`，导致以 Codex 为主协调时协作方无法实施改动；安装脚本现在同时写入该文件（Codex 要求它带 `$schema`、命令不能是绝对路径）。
- README：Claude 改为在 PowerShell 用 `claude plugin …` 安装（桌面版没有 `/plugin` 命令，走 **+ → Plugins** 界面）；只有 Codex 桌面版时给出定位 App 自带 `codex` 的命令。

## v0.12.0 — 2026-09-28

- 支持通过插件市场安装：Claude（`/plugin marketplace add youagainchen/claude-codex-coop`）与 Codex（`codex plugin marketplace add youagainchen/claude-codex-coop`）。
- 面板在 Claude CLI 未登录时显示"登录 Claude CLI"按钮，点击即打开登录窗口，无需手动找脚本。
- Codex 额度改为实时读取；插件自身的调用也会及时反映在额度上。
- 面板地址支持参数：`&bg=aurora` 指定背景、`&run=<id>` 直接打开某次调用。
- 修复：卸载脚本中 Codex 副本路径含控制字符导致无法删除；`.ai-coop-context` 自定义列出的密钥类文件现在也会被跳过；详情页不再把 Codex 自动重连提示显示成错误；有序列表保留原编号。
- 新增英文 README 与演示截图。

## v0.11.0 — 2026-09-27

- 协作协议：主协调先给初判，按"目标 / 已知 / 初判 / 具体问题 / 验收标准 / 禁止事项"交接；协作方按分析、决策、审查、实施四种模式结构化交付；分歧转成可执行检验，每个任务最多两轮。
- Claude 与 Codex 作为协作方规则对等：实施任务时两边都可修改文件。
- 新增 `scripts/claude-login.ps1`；面板改为常驻，升级后自动替换旧面板。
- 修复：钩子输出中文在 Windows 上乱码。

## v0.10.0 — 2026-09-27

- 首个公开版本（Windows 预览版）：Claude 桌面版与 Codex 桌面版双向调用、自动协作、侧边面板（模型、推理强度、实时状态、完整回复、账号额度）。
