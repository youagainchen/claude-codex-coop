[CmdletBinding()]
param([string]$TargetDir = (Get-Location).Path)

$ErrorActionPreference = 'Stop'
$PluginRoot = Split-Path -Parent $PSScriptRoot
$TemplateDir = Join-Path $PluginRoot 'templates'
$WorkflowDir = Join-Path $TargetDir '.ai-coop-workflow'
New-Item -ItemType Directory -Force -Path $WorkflowDir | Out-Null

Get-ChildItem -LiteralPath $TemplateDir -File | ForEach-Object {
    $Destination = Join-Path $WorkflowDir $_.Name
    if (Test-Path -LiteralPath $Destination) {
        Write-Host "Preserved existing file: $Destination"
    } else {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination
        Write-Host "Created: $Destination"
    }
}

Write-Host "Collaboration workspace initialized: $WorkflowDir"
