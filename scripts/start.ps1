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

& docker @composeArguments build frontend backend
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel image build failed.'
}

& docker @composeArguments up -d postgres redis
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel database or Redis startup failed.'
}

foreach ($attempt in 1..60) {
    $postgresHealth = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' webnovel_postgres).Trim()
    $redisHealth = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' webnovel_redis).Trim()
    if ($postgresHealth -eq 'healthy' -and $redisHealth -eq 'healthy') { break }
    if ($attempt -eq 60) { throw 'Webnovel dependencies did not become healthy.' }
    Start-Sleep -Seconds 1
}

& (Join-Path $PSScriptRoot 'migrate.ps1')

& docker @composeArguments up -d
if ($LASTEXITCODE -ne 0) {
    throw 'Webnovel startup failed. No unrelated Docker resources were modified.'
}

Write-Host 'Webnovel infrastructure started under Compose project webnovel_platform.' -ForegroundColor Green
