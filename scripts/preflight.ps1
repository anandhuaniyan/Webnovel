[CmdletBinding()]
param(
    [switch]$SkipPortCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$EnvPath = Join-Path $ProjectRoot '.env'
$ComposePath = Join-Path $ProjectRoot 'docker-compose.yml'
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
    param([Parameter(Mandatory)][string]$Message)
    $failures.Add($Message)
}

function Read-DotEnv {
    param([Parameter(Mandatory)][string]$Path)

    $values = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.*)\s*$') {
            $values[$Matches.key] = $Matches.value.Trim().Trim('"').Trim("'")
        }
    }
    return $values
}

function Test-PathInsideRoot {
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string]$Root
    )

    $fullCandidate = if ([System.IO.Path]::IsPathRooted($Candidate)) {
        [System.IO.Path]::GetFullPath($Candidate)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $Root $Candidate))
    }
    $rootPrefix = $Root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    return $fullCandidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Add-Failure "Script root '$ProjectRoot' is not the expected project root '$ExpectedRoot'."
}

$expectedRootPrefix = $ExpectedRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$currentIsInsideRoot = $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $CurrentDirectory.StartsWith($expectedRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
if (-not $currentIsInsideRoot) {
    Add-Failure "Current directory '$CurrentDirectory' is outside '$ExpectedRoot'."
}

$requiredDirectories = @(
    'frontend', 'backend', 'workers', 'scripts', 'data', 'data\source-books',
    'data\processed-books', 'data\rights-evidence', 'data\imports', 'data\exports',
    'storage', 'storage\covers', 'storage\chapter-images', 'storage\temporary',
    'storage\minio', 'database', 'database\postgres', 'database\redis', 'docker',
    'logs', 'backups', 'docs', 'tests'
)
foreach ($relativePath in $requiredDirectories) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $relativePath) -PathType Container)) {
        Add-Failure "Required directory is missing: $relativePath"
    }
}

$requiredFiles = @('.env', '.env.example', 'docker-compose.yml', 'README.md', '.cursor\rules\project-isolation.mdc')
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $relativePath) -PathType Leaf)) {
        Add-Failure "Required file is missing: $relativePath"
    }
}

if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    Add-Failure "Environment file is missing: $EnvPath"
    $environment = @{}
}
else {
    $environment = Read-DotEnv -Path $EnvPath
}

$expectedValues = @{
    COMPOSE_PROJECT_NAME = 'webnovel_platform'
    WEBNOVEL_PROJECT_ROOT = 'C:/Users/anadh/Development/Webnovel'
    WEBNOVEL_POSTGRES_DB = 'webnovel'
    WEBNOVEL_POSTGRES_USER = 'webnovel_app'
    WEBNOVEL_DOCKER_NETWORK = 'webnovel_network'
    WEBNOVEL_FRONTEND_CONTAINER = 'webnovel_frontend'
    WEBNOVEL_POSTGRES_CONTAINER = 'webnovel_postgres'
    WEBNOVEL_REDIS_CONTAINER = 'webnovel_redis'
    WEBNOVEL_STORAGE_CONTAINER = 'webnovel_storage'
}
foreach ($key in $expectedValues.Keys) {
    if (-not $environment.ContainsKey($key) -or $environment[$key] -ne $expectedValues[$key]) {
        Add-Failure "$key must be exactly '$($expectedValues[$key])'."
    }
}

$pathKeys = @(
    'WEBNOVEL_DATA_PATH', 'WEBNOVEL_STORAGE_PATH', 'WEBNOVEL_DATABASE_PATH',
    'WEBNOVEL_LOGS_PATH', 'WEBNOVEL_BACKUPS_PATH'
)
foreach ($key in $pathKeys) {
    if (-not $environment.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($environment[$key])) {
        Add-Failure "$key is missing."
        continue
    }
    if (-not (Test-PathInsideRoot -Candidate $environment[$key] -Root $ExpectedRoot)) {
        Add-Failure "$key points outside the Webnovel root: '$($environment[$key])'."
    }
}

$portKeys = @(
    'WEBNOVEL_FRONTEND_PORT', 'WEBNOVEL_BACKEND_PORT', 'WEBNOVEL_POSTGRES_PORT',
    'WEBNOVEL_REDIS_PORT', 'WEBNOVEL_STORAGE_PORT', 'WEBNOVEL_STORAGE_CONSOLE_PORT'
)
$webnovelOwnedPorts = [System.Collections.Generic.HashSet[int]]::new()
if ($null -ne (Get-Command docker -ErrorAction SilentlyContinue)) {
    $containerIds = @(& docker ps -q --filter 'label=com.docker.compose.project=webnovel_platform' 2>$null)
    if ($LASTEXITCODE -eq 0) {
        foreach ($containerId in $containerIds) {
            foreach ($mapping in @(& docker port $containerId 2>$null)) {
                if ($mapping -match ':(?<port>\d+)$') {
                    [void]$webnovelOwnedPorts.Add([int]$Matches.port)
                }
            }
        }
    }
}
$seenPorts = [System.Collections.Generic.HashSet[int]]::new()
foreach ($key in $portKeys) {
    $port = 0
    if (-not $environment.ContainsKey($key) -or -not [int]::TryParse($environment[$key], [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        Add-Failure "$key must contain a valid TCP port."
        continue
    }
    if (-not $seenPorts.Add($port)) {
        Add-Failure "Port $port is assigned more than once."
    }
    if (-not $SkipPortCheck) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($null -ne $listener -and -not $webnovelOwnedPorts.Contains($port)) {
            $owners = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
            Add-Failure "$key requests occupied port $port (process ID: $owners). Run scripts\select-ports.ps1."
        }
    }
}

$databaseHost = if ($environment.ContainsKey('WEBNOVEL_POSTGRES_HOST')) { $environment['WEBNOVEL_POSTGRES_HOST'] } else { '<missing>' }
$databasePort = if ($environment.ContainsKey('WEBNOVEL_POSTGRES_PORT')) { $environment['WEBNOVEL_POSTGRES_PORT'] } else { '<missing>' }
$databaseName = if ($environment.ContainsKey('WEBNOVEL_POSTGRES_DB')) { $environment['WEBNOVEL_POSTGRES_DB'] } else { '<missing>' }
Write-Host 'Configured database identity:'
Write-Host "  host: $databaseHost"
Write-Host "  port: $databasePort"
Write-Host "  name: $databaseName"

if ($environment.ContainsKey('WEBNOVEL_DATABASE_URL')) {
    try {
        $databaseUri = [System.Uri]$environment['WEBNOVEL_DATABASE_URL']
        if ($databaseUri.Host -ne $databaseHost -or
            $databaseUri.Port.ToString() -ne $databasePort -or
            $databaseUri.AbsolutePath.Trim('/') -ne 'webnovel') {
            Add-Failure 'WEBNOVEL_DATABASE_URL does not match the configured Webnovel database identity.'
        }
    }
    catch {
        Add-Failure 'WEBNOVEL_DATABASE_URL is not a valid database URL.'
    }
}
else {
    Add-Failure 'WEBNOVEL_DATABASE_URL is missing.'
}

$filesToInspect = @($EnvPath, $ComposePath) +
    @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File | Select-Object -ExpandProperty FullName)
$otherProjectPattern = '(?i)C:[\\/]+Users[\\/]+anadh[\\/]+Development[\\/]+(?<project>[A-Za-z0-9._-]+)'
$globalCleanupPattern = '(?i)\bdocker(?:\.exe)?\s+(?:(?:system|volume|network|container|image|builder)\s+prune|volume\s+rm)\b'
$composeVolumeRemovalPattern = '(?i)\bdocker(?:\.exe)?\s+compose\b[^\r\n]*(?:\s-v\b|--volumes\b)'
foreach ($path in $filesToInspect) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        continue
    }
    $content = [System.IO.File]::ReadAllText($path)
    foreach ($match in [regex]::Matches($content, $otherProjectPattern)) {
        if ($match.Groups['project'].Value -ne 'Webnovel') {
            Add-Failure "File '$path' references another development project: '$($match.Value)'."
        }
    }
    if ([regex]::IsMatch($content, $globalCleanupPattern) -or [regex]::IsMatch($content, $composeVolumeRemovalPattern)) {
        Add-Failure "File '$path' contains a prohibited Docker cleanup command."
    }
}

if (Test-Path -LiteralPath $ComposePath -PathType Leaf) {
    $composeText = [System.IO.File]::ReadAllText($ComposePath)
    foreach ($requiredResource in @(
        'webnovel_network', 'webnovel_postgres_data', 'webnovel_redis_data',
        'webnovel_storage_data', 'webnovel_frontend', 'webnovel_postgres', 'webnovel_redis', 'webnovel_storage'
    )) {
        if (-not $composeText.Contains($requiredResource)) {
            Add-Failure "Compose configuration is missing dedicated resource '$requiredResource'."
        }
    }
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCommand) {
    Add-Failure 'Docker is not installed or is not available on PATH.'
}
elseif ((Test-Path -LiteralPath $ComposePath -PathType Leaf) -and (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    & docker compose --project-name webnovel_platform --env-file $EnvPath -f $ComposePath config --quiet
    if ($LASTEXITCODE -ne 0) {
        Add-Failure 'Docker Compose configuration validation failed.'
    }
}

if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host 'Webnovel preflight FAILED:' -ForegroundColor Red
    foreach ($failure in $failures) {
        Write-Host "  - $failure" -ForegroundColor Red
    }
    throw "Preflight aborted with $($failures.Count) failure(s). No service was started."
}

Write-Host ''
Write-Host 'Webnovel preflight passed. Project boundaries and configuration are isolated.' -ForegroundColor Green
