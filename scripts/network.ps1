Set-StrictMode -Version Latest

function Get-WebnovelLanIPv4Address {
    $virtualPattern = '(?i)(WSL|vEthernet|Docker|Hyper-V|Virtual|VPN|Tailscale|WireGuard|Loopback)'
    $candidates = [System.Collections.Generic.List[object]]::new()

    foreach ($configuration in @(Get-NetIPConfiguration -ErrorAction SilentlyContinue)) {
        if ($null -eq $configuration.NetAdapter -or $configuration.NetAdapter.Status -ne 'Up') {
            continue
        }
        if ($configuration.InterfaceAlias -match $virtualPattern -or
            $configuration.InterfaceDescription -match $virtualPattern -or
            $null -eq $configuration.IPv4DefaultGateway) {
            continue
        }

        foreach ($ipv4 in @($configuration.IPv4Address)) {
            $address = [string]$ipv4.IPv4Address
            if ([string]::IsNullOrWhiteSpace($address) -or
                $address -eq '0.0.0.0' -or
                $address.StartsWith('127.') -or
                $address.StartsWith('169.254.')) {
                continue
            }
            $score = 0
            if ($configuration.InterfaceAlias -match '(?i)^(Ethernet|Wi-?Fi)') { $score += 10 }
            if ($address.StartsWith('192.168.')) { $score += 3 }
            elseif ($address.StartsWith('10.')) { $score += 2 }
            elseif ($address -match '^172\.(1[6-9]|2\d|3[01])\.') { $score += 1 }
            $candidates.Add([pscustomobject]@{ Address = $address; Score = $score })
        }
    }

    return $candidates | Sort-Object Score -Descending | Select-Object -First 1 -ExpandProperty Address
}

function Test-WebnovelHttpUrl {
    param([Parameter(Mandatory)][string]$Url)

    $arguments = @{
        Uri = $Url
        Method = 'Get'
        UseBasicParsing = $true
        TimeoutSec = 5
        ErrorAction = 'Stop'
    }
    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey('NoProxy')) {
        $arguments['NoProxy'] = $true
    }
    try {
        $response = Invoke-WebRequest @arguments
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}
