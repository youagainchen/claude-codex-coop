[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Launcher = Join-Path $PSScriptRoot 'launch.ps1'
Write-Host 'AI Coop connection diagnostics'
$TempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$DiagnosticDir = Join-Path $TempBase ("ai-coop-doctor-" + [guid]::NewGuid().ToString('N'))
try {
    & $Launcher -RunsDir $DiagnosticDir -SelfTest
    if ($LASTEXITCODE -ne 0) { throw "Self-test failed with exit code: $LASTEXITCODE" }
} finally {
    $Resolved = [IO.Path]::GetFullPath($DiagnosticDir)
    if ($Resolved.StartsWith($TempBase, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $Resolved)) {
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}
