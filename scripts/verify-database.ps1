[CmdletBinding()]
param(
    [switch]$RequireConnection
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$EnvPath = Join-Path $ProjectRoot '.env'

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Database verification must run from '$ExpectedRoot'."
}

& (Join-Path $PSScriptRoot 'preflight.ps1') -SkipPortCheck
if ($LASTEXITCODE -ne 0) {
    throw 'Database verification aborted because preflight failed.'
}

$environment = @{}
foreach ($line in [System.IO.File]::ReadAllLines($EnvPath)) {
    if ($line -match '^\s*(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.*)\s*$') {
        $environment[$Matches.key] = $Matches.value.Trim().Trim('"').Trim("'")
    }
}

$hostName = $environment['WEBNOVEL_POSTGRES_HOST']
$port = $environment['WEBNOVEL_POSTGRES_PORT']
$database = $environment['WEBNOVEL_POSTGRES_DB']
$user = $environment['WEBNOVEL_POSTGRES_USER']
$container = $environment['WEBNOVEL_POSTGRES_CONTAINER']

Write-Host 'Database migration guard:'
Write-Host "  host: $hostName"
Write-Host "  port: $port"
Write-Host "  name: $database"
Write-Host "  user: $user"

if ($database -ne 'webnovel' -or $user -ne 'webnovel_app' -or $container -ne 'webnovel_postgres') {
    throw 'Database verification failed: configured identity is not the Webnovel database.'
}

if (-not $RequireConnection) {
    Write-Host 'Configured database identity is valid. Use -RequireConnection before a migration.' -ForegroundColor Green
    exit 0
}

$running = (& docker inspect --format '{{.State.Running}}' $container 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or $running -ne 'true') {
    throw "Database verification failed: container '$container' is not running."
}

$composeProject = (& docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' $container).Trim()
if ($LASTEXITCODE -ne 0 -or $composeProject -ne 'webnovel_platform') {
    throw "Database verification failed: container '$container' belongs to Compose project '$composeProject'."
}

$actualDatabase = (& docker exec $container psql -v ON_ERROR_STOP=1 -U $user -d $database -tA -c 'SELECT current_database();').Trim()
if ($LASTEXITCODE -ne 0 -or $actualDatabase -ne 'webnovel') {
    throw "Database verification failed: connected database is '$actualDatabase', not 'webnovel'."
}

$actualUser = (& docker exec $container psql -v ON_ERROR_STOP=1 -U $user -d $database -tA -c 'SELECT current_user;').Trim()
if ($LASTEXITCODE -ne 0 -or $actualUser -ne 'webnovel_app') {
    throw "Database verification failed: connected user is '$actualUser', not 'webnovel_app'."
}

Write-Host 'Database connection identity verified. Migrations may target this database.' -ForegroundColor Green
