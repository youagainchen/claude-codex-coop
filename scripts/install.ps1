[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Claude', 'Codex', 'Both')]
    [string]$Target = 'Both',
    # 默认允许写入：每一轮是否真的改文件，由 implement 模式里写明的已批准决定逐次放行。
    [switch]$ReadOnly
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Windows PowerShell 5.1 的 -Encoding utf8 会写入 BOM，Claude Code/Codex 解析 JSON 时可能因此失败。
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

$SourcePluginRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
# 不用 LOCALAPPDATA：MSIX 打包的宿主（Claude 桌面版）会把 AppData 下的新文件重定向到包内目录
$RunsDir = Join-Path $env:USERPROFILE '.ai-coop\runs'
$BackupRoot = Join-Path $env:USERPROFILE '.ai-coop\backups'

function Resolve-AgentCli([string]$Name) {
    $Command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    if ($Name -eq 'codex' -and $env:LOCALAPPDATA) {
        $BinRoot = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
        if (Test-Path -LiteralPath $BinRoot) {
            $Candidate = Get-ChildItem -LiteralPath $BinRoot -Filter codex.exe -File -Recurse -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($Candidate) { return $Candidate.FullName }
        }
    }
    throw "$Name CLI was not found. Install it and sign in first."
}

function Resolve-Python {
    if ($env:AI_COOP_PYTHON_EXE -and (Test-Path -LiteralPath $env:AI_COOP_PYTHON_EXE -PathType Leaf)) {
        return $env:AI_COOP_PYTHON_EXE
    }
    if ($env:USERPROFILE) {
        $Bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $Bundled -PathType Leaf) { return $Bundled }
    }
    $Command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    throw 'Python 3 was not found. Install Python or set AI_COOP_PYTHON_EXE.'
}

function Copy-PluginTree([string]$Destination, [string]$HostName) {
    $SourceFull = [IO.Path]::GetFullPath($SourcePluginRoot).TrimEnd('\')
    $DestinationFull = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($SourceFull -ieq $DestinationFull) { return $DestinationFull }
    $Parent = Split-Path -Parent $DestinationFull
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    if (Test-Path -LiteralPath $DestinationFull) {
        $HostBackupRoot = Join-Path $BackupRoot $HostName
        New-Item -ItemType Directory -Force -Path $HostBackupRoot | Out-Null
        $Backup = Join-Path $HostBackupRoot ("ai-coop-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Move-Item -LiteralPath $DestinationFull -Destination $Backup
    }
    New-Item -ItemType Directory -Force -Path $DestinationFull | Out-Null
    Get-ChildItem -Force -LiteralPath $SourceFull | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $DestinationFull -Recurse -Force
    }
    return $DestinationFull
}

function Write-HostPluginConfig(
    [string]$PluginRoot,
    [string]$HostAgent,
    [string]$PythonExe
) {
    $ServerPath = Join-Path $PluginRoot 'server\mcp_server.py'
    $Args = @(
        $ServerPath,
        '--runs-dir', $RunsDir,
        '--host-agent', $HostAgent
    )
    if (-not $ReadOnly) { $Args += '--allow-write' }
    $McpPython = $PythonExe
    if ([IO.Path]::GetFileName($PythonExe) -ieq 'python.exe') {
        $Pythonw = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
        if (Test-Path -LiteralPath $Pythonw -PathType Leaf) { $McpPython = $Pythonw }
    }
    $Mcp = [ordered]@{
        mcpServers = [ordered]@{
            'ai-coop' = [ordered]@{
                command = $McpPython
                args = $Args
                env = [ordered]@{ AI_COOP_HOST_AGENT = $HostAgent }
            }
        }
    }
    Write-Utf8NoBom (Join-Path $PluginRoot '.mcp.json') ($Mcp | ConvertTo-Json -Depth 20)

    if ($HostAgent -eq 'claude') {
        # Claude 插件清单内嵌 MCP 配置（${CLAUDE_PLUGIN_ROOT} 由 Claude Code 展开），同步为本机解析出的 Python。
        $ManifestPath = Join-Path $PluginRoot '.claude-plugin\plugin.json'
        $Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
        $ClaudeArgs = @('${CLAUDE_PLUGIN_ROOT}/server/mcp_server.py', '--runs-dir', $RunsDir, '--host-agent', 'claude')
        if (-not $ReadOnly) { $ClaudeArgs += '--allow-write' }
        $Manifest.mcpServers = [ordered]@{
            'ai-coop' = [ordered]@{ command = $McpPython; args = $ClaudeArgs; env = [ordered]@{ AI_COOP_HOST_AGENT = 'claude' } }
        }
        Write-Utf8NoBom $ManifestPath ($Manifest | ConvertTo-Json -Depth 20)
    }

    $HookCommand = '"' + $McpPython + '" "${CLAUDE_PLUGIN_ROOT}/scripts/auto-collab-hook.py"'
    $HookCommandWindows = '"' + $McpPython + '" "${CLAUDE_PLUGIN_ROOT}\scripts\auto-collab-hook.py"'
    $Hooks = [ordered]@{
        description = 'Keep AI Coop automatic after the user opens it once.'
        hooks = [ordered]@{
            UserPromptSubmit = @(
                [ordered]@{
                    hooks = @(
                        [ordered]@{
                            type = 'command'
                            command = $HookCommand
                            commandWindows = $HookCommandWindows
                            timeout = 5
                            statusMessage = 'AI Coop'
                        }
                    )
                }
            )
        }
    }
    Write-Utf8NoBom (Join-Path $PluginRoot 'hooks\hooks.json') ($Hooks | ConvertTo-Json -Depth 20)
}

function Remove-LegacyMcpEntry([string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { return }
    $Config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    if ($null -eq $Config.mcpServers) { return }
    $Entry = $Config.mcpServers.PSObject.Properties['ai-coop']
    if ($null -eq $Entry) { return }
    Copy-Item -LiteralPath $ConfigPath -Destination "$ConfigPath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $Config.mcpServers.PSObject.Properties.Remove('ai-coop')
    Write-Utf8NoBom $ConfigPath ($Config | ConvertTo-Json -Depth 20)
}

function Enable-ClaudePlugin([string]$PluginRoot) {
    $SettingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SettingsPath) | Out-Null
    if (Test-Path -LiteralPath $SettingsPath) {
        Copy-Item -LiteralPath $SettingsPath -Destination "$SettingsPath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        $Settings = Get-Content -Raw -LiteralPath $SettingsPath | ConvertFrom-Json
    } else {
        $Settings = [pscustomobject]@{}
    }
    if ($null -eq $Settings.enabledPlugins) {
        $Settings | Add-Member -NotePropertyName enabledPlugins -NotePropertyValue ([pscustomobject]@{})
    }
    $Settings.enabledPlugins | Add-Member -Force -NotePropertyName 'ai-coop@skills-dir' -NotePropertyValue $true
    Write-Utf8NoBom $SettingsPath ($Settings | ConvertTo-Json -Depth 20)

    Remove-LegacyMcpEntry (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json')

    $ClaudePath = Resolve-AgentCli 'claude'
    & $ClaudePath plugin validate $PluginRoot
    if ($LASTEXITCODE -ne 0) { throw 'Claude plugin validation failed.' }
}

function Ensure-PersonalCodexMarketplace([string]$PluginRoot) {
    $MarketplacePath = Join-Path $env:USERPROFILE '.agents\plugins\marketplace.json'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $MarketplacePath) | Out-Null
    if (Test-Path -LiteralPath $MarketplacePath) {
        Copy-Item -LiteralPath $MarketplacePath -Destination "$MarketplacePath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        $Marketplace = Get-Content -Raw -LiteralPath $MarketplacePath | ConvertFrom-Json
    } else {
        $Marketplace = [pscustomobject]@{
            name = 'personal'
            interface = [pscustomobject]@{ displayName = 'Personal' }
            plugins = @()
        }
    }
    if ($Marketplace.name -ne 'personal') { throw "Unexpected personal marketplace name: $($Marketplace.name)" }
    $Existing = @($Marketplace.plugins | Where-Object { $_.name -eq 'ai-coop' })
    if ($Existing.Count -eq 0) {
        $Entry = [pscustomobject]@{
            name = 'ai-coop'
            source = [pscustomobject]@{ source = 'local'; path = './plugins/ai-coop' }
            policy = [pscustomobject]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
            category = 'Productivity'
        }
        $Marketplace.plugins = @($Marketplace.plugins) + @($Entry)
    }
    Write-Utf8NoBom $MarketplacePath ($Marketplace | ConvertTo-Json -Depth 20)

    $CodexPath = Resolve-AgentCli 'codex'
    # Older builds registered the bridge directly in config.toml. The plugin now
    # owns the MCP server, so keep only the plugin copy to avoid duplicate tools
    # and stale write permissions.
    & $CodexPath mcp remove ai-coop *> $null
    & $CodexPath plugin add 'ai-coop@personal'
    if ($LASTEXITCODE -ne 0) { throw 'Codex plugin installation failed.' }
}

$PythonExe = Resolve-Python
New-Item -ItemType Directory -Force -Path $RunsDir | Out-Null

if ($Target -in @('Codex', 'Both')) {
    $CodexPluginRoot = Join-Path $env:USERPROFILE 'plugins\ai-coop'
    if ($PSCmdlet.ShouldProcess($CodexPluginRoot, 'Install AI Coop for Codex')) {
        $CodexPluginRoot = Copy-PluginTree $CodexPluginRoot 'codex'
        Write-HostPluginConfig $CodexPluginRoot 'codex' $PythonExe
        Ensure-PersonalCodexMarketplace $CodexPluginRoot
    }
}

if ($Target -in @('Claude', 'Both')) {
    $ClaudePluginRoot = Join-Path $env:USERPROFILE '.claude\skills\ai-coop'
    if ($PSCmdlet.ShouldProcess($ClaudePluginRoot, 'Install AI Coop for Claude')) {
        $ClaudePluginRoot = Copy-PluginTree $ClaudePluginRoot 'claude'
        Write-HostPluginConfig $ClaudePluginRoot 'claude' $PythonExe
        Enable-ClaudePlugin $ClaudePluginRoot
    }
}

Write-Host "AI Coop installed for: $Target"
Write-Host ($(if ($ReadOnly) { 'Write mode: read-only' } else { 'Write mode: enabled (each implementation run still needs an approved decision)' }))
Write-Host 'Fully exit and reopen each configured app. Then open AI Coop once; no workflow command is needed.'
