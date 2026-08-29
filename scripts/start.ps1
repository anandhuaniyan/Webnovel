[CmdletBinding()]
param(
    [switch]$WithStorage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$EnvPath = Join-Path $ProjectRoot '.env'
$ComposePath = Join-Path $ProjectRoot 'docker-compose.yml'

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Startup aborted: run this script from '$ExpectedRoot'."
}

& (Join-Path $PSScriptRoot 'select-ports.ps1')
& (Join-Path $PSScriptRoot 'preflight.ps1')

$composeArguments = @(
    'compose', '--project-name', 'webnovel_platform', '--env-file', $EnvPath,
    '-f', $ComposePath
)
if ($WithStorage) {
    $composeArguments += @('--profile', 'storage')
}
$composeArguments += @('up', '-d')

& docker @composeArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel startup failed. No unrelated Docker resources were modified.'
}

Write-Host 'Webnovel infrastructure started under Compose project webnovel_platform.' -ForegroundColor Green
