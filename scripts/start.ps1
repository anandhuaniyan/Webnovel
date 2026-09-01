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

. (Join-Path $PSScriptRoot 'network.ps1')

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

$frontendPortLine = [System.IO.File]::ReadAllLines($EnvPath) |
    Where-Object { $_ -match '^WEBNOVEL_FRONTEND_PORT=' } |
    Select-Object -First 1
if (-not $frontendPortLine) {
    throw 'Webnovel startup validation failed: WEBNOVEL_FRONTEND_PORT is missing.'
}
$frontendPort = [int](($frontendPortLine -split '=', 2)[1].Trim())
$lanAddress = Get-WebnovelLanIPv4Address
$localUrl = "http://localhost:$frontendPort"
$networkUrl = if ([string]::IsNullOrWhiteSpace($lanAddress)) { $null } else { "http://${lanAddress}:$frontendPort" }

$localReady = $false
foreach ($attempt in 1..60) {
    if ((Test-WebnovelHttpUrl -Url "$localUrl/health") -and
        (Test-WebnovelHttpUrl -Url "$localUrl/api/health")) {
        $localReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $localReady) {
    throw "Webnovel started but failed its same-origin health checks at '$localUrl'."
}

if ($networkUrl -and
    (-not (Test-WebnovelHttpUrl -Url "$networkUrl/health") -or
     -not (Test-WebnovelHttpUrl -Url "$networkUrl/api/health"))) {
    throw "Webnovel is healthy on localhost but not through '$networkUrl'. Check the Private-profile Windows Firewall rule and router client isolation."
}

$activeProfiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
    Where-Object { $_.IPv4Connectivity -ne 'None' } |
    Select-Object -ExpandProperty NetworkCategory -Unique)
$profileText = if ($activeProfiles.Count -gt 0) { ($activeProfiles | ForEach-Object { $_.ToString() }) -join ', ' } else { 'Unknown' }

Write-Host ''
Write-Host '============================================================'
Write-Host 'Webnovel is running' -ForegroundColor Green
Write-Host '============================================================'
Write-Host ''
Write-Host 'Host PC:'
Write-Host $localUrl -ForegroundColor Cyan
Write-Host ''
if ($networkUrl) {
    Write-Host 'Phones/Tablets on the same Wi-Fi or LAN:'
    Write-Host $networkUrl -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Admin:'
    Write-Host "$networkUrl/admin" -ForegroundColor Cyan
}
else {
    Write-Warning 'No physical LAN IPv4 address with a default gateway was detected.'
}
Write-Host ''
Write-Host 'Backend: internal through /api (direct backend access remains loopback-only)'
Write-Host 'PostgreSQL and Redis: loopback-only'
Write-Host "Active Windows network profile: $profileText"
if ($profileText -notmatch 'Private|DomainAuthenticated') {
    Write-Warning 'LAN access is intended for a trusted Private network profile. Review the active Windows network profile before connecting other devices.'
}
Write-Host '============================================================'
