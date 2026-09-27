[CmdletBinding()]
param(
    [string]$RunsDir,
    [ValidateSet('Auto', 'Codex', 'Claude')]
    [string]$HostAgent = 'Auto',
    [switch]$AllowWrite,
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
$PluginRoot = Split-Path -Parent $PSScriptRoot
$ServerPath = Join-Path $PluginRoot 'server\mcp_server.py'

if (-not $RunsDir) {
    $DataRoot = if ($env:PLUGIN_DATA) {
        $env:PLUGIN_DATA
    } elseif ($env:CLAUDE_PLUGIN_DATA) {
        $env:CLAUDE_PLUGIN_DATA
    } elseif ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE '.ai-coop'
    } else {
        Join-Path $PluginRoot 'data'
    }
    $RunsDir = Join-Path $DataRoot 'runs'
}

$PythonExe = $null
$PythonPrefix = @()
if ($env:AI_COOP_PYTHON_EXE -and (Test-Path -LiteralPath $env:AI_COOP_PYTHON_EXE -PathType Leaf)) {
    $PythonExe = $env:AI_COOP_PYTHON_EXE
} else {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $PythonExe = $PythonCommand.Source
    } else {
        $PyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($PyCommand) {
            $PythonExe = $PyCommand.Source
            $PythonPrefix = @('-3')
        }
    }
}

if (-not $PythonExe -and $env:USERPROFILE) {
    $RuntimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes'
    if (Test-Path -LiteralPath $RuntimeRoot) {
        $Candidate = Get-ChildItem -LiteralPath $RuntimeRoot -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($Candidate) { $PythonExe = $Candidate.FullName }
    }
}

if (-not $PythonExe) {
    throw 'Python 3 was not found. Install Python or set AI_COOP_PYTHON_EXE.'
}
if (-not (Test-Path -LiteralPath $ServerPath -PathType Leaf)) {
    throw "MCP server was not found: $ServerPath"
}
New-Item -ItemType Directory -Force -Path $RunsDir | Out-Null
$ServerArgs = @($ServerPath, '--runs-dir', $RunsDir)
$ServerArgs += @('--host-agent', $HostAgent.ToLowerInvariant())
if ($AllowWrite -or $env:AI_COOP_ALLOW_WRITE -eq '1') { $ServerArgs += '--allow-write' }
if ($SelfTest) { $ServerArgs += '--self-test' }

& $PythonExe @PythonPrefix @ServerArgs
exit $LASTEXITCODE
