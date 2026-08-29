[CmdletBinding()]
param(
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$EnvPath = Join-Path $ProjectRoot '.env'

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Port selection aborted: script root '$ProjectRoot' is not '$ExpectedRoot'."
}

if (-not $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Port selection aborted: run this script from '$ExpectedRoot'."
}

if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    throw "Port selection aborted: missing '$EnvPath'."
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

function Get-WebnovelOwnedPorts {
    $ports = [System.Collections.Generic.HashSet[int]]::new()
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $ports
    }

    $containerIds = @(& docker ps -q --filter 'label=com.docker.compose.project=webnovel_platform' 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $ports
    }

    foreach ($containerId in $containerIds) {
        foreach ($mapping in @(& docker port $containerId 2>$null)) {
            if ($mapping -match ':(?<port>\d+)$') {
                [void]$ports.Add([int]$Matches.port)
            }
        }
    }
    return $ports
}

$webnovelOwnedPorts = Get-WebnovelOwnedPorts

function Test-PortAvailable {
    param([Parameter(Mandatory)][ValidateRange(1, 65535)][int]$Port)

    if ($webnovelOwnedPorts.Contains($Port)) {
        return $true
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -eq $listener
}

function Find-AvailablePort {
    param(
        [Parameter(Mandatory)][ValidateRange(1, 65535)][int]$PreferredPort,
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.HashSet[int]]$ReservedPorts
    )

    $upperBound = [Math]::Min(65535, $PreferredPort + 999)
    for ($candidate = $PreferredPort; $candidate -le $upperBound; $candidate++) {
        if (-not $ReservedPorts.Contains($candidate) -and (Test-PortAvailable -Port $candidate)) {
            return $candidate
        }
    }
    throw "No unused port was found in range $PreferredPort-$upperBound."
}

function Update-DotEnv {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Updates
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]][System.IO.File]::ReadAllLines($Path))
    $updatedKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)

    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*=') {
            $key = $Matches.key
            if ($Updates.ContainsKey($key)) {
                $lines[$index] = "$key=$($Updates[$key])"
                [void]$updatedKeys.Add($key)
            }
        }
    }

    foreach ($key in $Updates.Keys) {
        if (-not $updatedKeys.Contains($key)) {
            $lines.Add("$key=$($Updates[$key])")
        }
    }

    [System.IO.File]::WriteAllLines($Path, $lines, [System.Text.UTF8Encoding]::new($false))
}

$environment = Read-DotEnv -Path $EnvPath
$requests = @(
    [pscustomobject]@{ Key = 'WEBNOVEL_FRONTEND_PORT'; Preferred = 5273 },
    [pscustomobject]@{ Key = 'WEBNOVEL_BACKEND_PORT'; Preferred = 8270 },
    [pscustomobject]@{ Key = 'WEBNOVEL_POSTGRES_PORT'; Preferred = 55432 },
    [pscustomobject]@{ Key = 'WEBNOVEL_REDIS_PORT'; Preferred = 56379 },
    [pscustomobject]@{ Key = 'WEBNOVEL_STORAGE_PORT'; Preferred = 59000 },
    [pscustomobject]@{ Key = 'WEBNOVEL_STORAGE_CONSOLE_PORT'; Preferred = 59001 }
)

$reservedPorts = [System.Collections.Generic.HashSet[int]]::new()
$updates = @{}

foreach ($request in $requests) {
    $configuredPort = $request.Preferred
    if ($environment.ContainsKey($request.Key)) {
        $parsedPort = 0
        if ([int]::TryParse($environment[$request.Key], [ref]$parsedPort) -and $parsedPort -ge 1 -and $parsedPort -le 65535) {
            $configuredPort = $parsedPort
        }
    }

    if (-not $reservedPorts.Contains($configuredPort) -and (Test-PortAvailable -Port $configuredPort)) {
        $selectedPort = $configuredPort
        $status = 'available'
    }
    else {
        $selectedPort = Find-AvailablePort -PreferredPort $request.Preferred -ReservedPorts $reservedPorts
        $status = "selected instead of occupied/reserved port $configuredPort"
    }

    [void]$reservedPorts.Add($selectedPort)
    $updates[$request.Key] = $selectedPort
    Write-Host "$($request.Key)=$selectedPort ($status)"
}

$databaseUser = $environment['WEBNOVEL_POSTGRES_USER']
$databasePassword = $environment['WEBNOVEL_POSTGRES_PASSWORD']
$databaseName = $environment['WEBNOVEL_POSTGRES_DB']
$redisPassword = $environment['WEBNOVEL_REDIS_PASSWORD']

if ([string]::IsNullOrWhiteSpace($databaseUser) -or
    [string]::IsNullOrWhiteSpace($databasePassword) -or
    [string]::IsNullOrWhiteSpace($databaseName) -or
    [string]::IsNullOrWhiteSpace($redisPassword)) {
    throw 'Port selection aborted: database or Redis identity values are missing from .env.'
}

$encodedDatabaseUser = [System.Uri]::EscapeDataString($databaseUser)
$encodedDatabasePassword = [System.Uri]::EscapeDataString($databasePassword)
$encodedRedisPassword = [System.Uri]::EscapeDataString($redisPassword)
$updates['WEBNOVEL_FRONTEND_URL'] = "http://localhost:$($updates['WEBNOVEL_FRONTEND_PORT'])"
$updates['WEBNOVEL_BACKEND_URL'] = "http://localhost:$($updates['WEBNOVEL_BACKEND_PORT'])"
$updates['WEBNOVEL_DATABASE_URL'] = "postgresql://${encodedDatabaseUser}:${encodedDatabasePassword}@127.0.0.1:$($updates['WEBNOVEL_POSTGRES_PORT'])/$databaseName"
$updates['WEBNOVEL_REDIS_URL'] = "redis://:${encodedRedisPassword}@127.0.0.1:$($updates['WEBNOVEL_REDIS_PORT'])/0"

if ($WhatIf) {
    Write-Host 'WhatIf: .env was not changed.'
}
else {
    Update-DotEnv -Path $EnvPath -Updates $updates
    Write-Host "Selected ports and dependent URLs were saved to '$EnvPath'."
}
