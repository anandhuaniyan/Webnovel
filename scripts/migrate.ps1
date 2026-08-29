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
    throw "Migration aborted: run this script from '$ExpectedRoot'."
}

& (Join-Path $PSScriptRoot 'verify-database.ps1') -RequireConnection

& docker compose --project-name webnovel_platform --env-file $EnvPath -f $ComposePath run --rm --no-deps backend alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel migration failed. No other database was touched.'
}

Write-Host 'Webnovel database migration completed successfully.' -ForegroundColor Green
