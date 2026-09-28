# Changelog

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
