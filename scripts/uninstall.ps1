[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Claude', 'Codex', 'Both')]
    [string]$Target = 'Both',
    # 同时删除 ~/.ai-coop（运行记录、偏好、面板状态）
    [switch]$Purge
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Windows PowerShell 5.1 的 -Encoding utf8 会写入 BOM，Claude Code/Codex 解析 JSON 时可能因此失败。
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}


function Resolve-AgentCli([string]$Name) {
    $Command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if (-not $Command) { $Command = Get-Command $Name -ErrorAction SilentlyContinue }
    if ($Command) { return $Command.Source }
    return $null
}

function Remove-JsonProperty([string]$Path, [string]$Container, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $Config = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    $Parent = $Config.PSObject.Properties[$Container].Value
    if ($null -eq $Parent -or $null -eq $Parent.PSObject.Properties[$Name]) { return }
    if ($PSCmdlet.ShouldProcess($Path, "Remove $Container.$Name")) {
        Copy-Item -LiteralPath $Path -Destination "$Path.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        $Parent.PSObject.Properties.Remove($Name)
        Write-Utf8NoBom $Path ($Config | ConvertTo-Json -Depth 20)
    }
}

if ($Target -in @('Claude', 'Both')) {
    Remove-JsonProperty (Join-Path $env:USERPROFILE '.claude\settings.json') 'enabledPlugins' 'ai-coop@skills-dir'
    Remove-JsonProperty (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json') 'mcpServers' 'ai-coop'
    $ClaudePluginRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.claude\skills\ai-coop'))
    $ClaudeSkillsRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.claude\skills')).TrimEnd('\') + '\'
    if ($ClaudePluginRoot.StartsWith($ClaudeSkillsRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $ClaudePluginRoot) -and
        $PSCmdlet.ShouldProcess($ClaudePluginRoot, 'Remove Claude AI Coop plugin')) {
        Remove-Item -LiteralPath $ClaudePluginRoot -Recurse -Force
    }
}

if ($Target -in @('Codex', 'Both')) {
    $CodexPath = Resolve-AgentCli 'codex'
    if ($CodexPath -and $PSCmdlet.ShouldProcess('ai-coop@personal', 'Uninstall Codex AI Coop plugin')) {
        & $CodexPath mcp remove ai-coop *> $null
        & $CodexPath plugin remove 'ai-coop@personal'
    }
    $CodexPluginRoot = Join-Path $env:USERPROFILE 'pluginsi-coop'
    if ((Test-Path -LiteralPath $CodexPluginRoot) -and $PSCmdlet.ShouldProcess($CodexPluginRoot, 'Remove Codex AI Coop copy')) {
        Remove-Item -LiteralPath $CodexPluginRoot -Recurse -Force
    }
}

if ($Purge) {
    $DataRoot = Join-Path $env:USERPROFILE '.ai-coop'
    if ((Test-Path -LiteralPath $DataRoot) -and $PSCmdlet.ShouldProcess($DataRoot, 'Remove AI Coop run logs and preferences')) {
        Remove-Item -LiteralPath $DataRoot -Recurse -Force
    }
}

Write-Host ($(if ($Purge) { 'AI Coop removed, including ~/.ai-coop run logs.' } else { 'AI Coop removed. Run logs in ~/.ai-coop were kept (use -Purge to delete them).' }))
