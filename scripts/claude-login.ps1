# 登录协作用的 Claude CLI（只需一次）。自动找到本机最新的 Claude CLI（含 Claude 桌面版自带的一份），
# 沿用 Windows 系统代理，并跳过第三方供应商的用户级配置。
#   .\scripts\claude-login.ps1           登录
#   .\scripts\claude-login.ps1 -Status   查看登录状态
[CmdletBinding()]
param([switch]$Status)

$ErrorActionPreference = 'Stop'
$Server = Join-Path (Split-Path -Parent $PSScriptRoot) 'server\mcp_server.py'
$Python = if ($env:AI_COOP_PYTHON_EXE) { $env:AI_COOP_PYTHON_EXE } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw 'Python 3.10+ was not found. Install Python or set AI_COOP_PYTHON_EXE.' }
if ($Status) { & $Python $Server --claude-status } else { & $Python $Server --claude-login }
exit $LASTEXITCODE
