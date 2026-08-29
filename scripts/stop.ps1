[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$EnvPath = Join-Path $ProjectRoot '.env'
$ComposePath = Join-Path $ProjectRoot 'docker-compose.yml'

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Shutdown aborted: run this script from '$ExpectedRoot'."
}

& (Join-Path $PSScriptRoot 'preflight.ps1') -SkipPortCheck

& docker compose --project-name webnovel_platform --env-file $EnvPath -f $ComposePath --profile storage down --remove-orphans
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel shutdown failed.'
}

Write-Host 'Stopped only the webnovel_platform containers. Persistent volumes were preserved.' -ForegroundColor Green
