[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 5273
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRoot = [System.IO.Path]::GetFullPath('C:\Users\anadh\Development\Webnovel')
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$CurrentDirectory = [System.IO.Path]::GetFullPath((Get-Location).Path)
$RuleName = "Webnovel LAN TCP $Port (Private)"

if (-not $ProjectRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $CurrentDirectory.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Firewall configuration aborted: run this script from '$ExpectedRoot'."
}

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator privileges are required. Open PowerShell as Administrator and run this script again.'
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Windows Firewall rule already exists: $RuleName" -ForegroundColor Green
    return
}

New-NetFirewallRule -DisplayName $RuleName -Description 'Allow Webnovel frontend access from devices on the private LAN only.' -Direction Inbound -Action Allow -Enabled True -Profile Private -Protocol TCP -LocalPort $Port | Out-Null
Write-Host "Created Windows Firewall rule: $RuleName" -ForegroundColor Green
Write-Host 'PostgreSQL, Redis, backend, and optional storage ports were not opened.'
