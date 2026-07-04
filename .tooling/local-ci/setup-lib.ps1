# =============================================================================
# personal-template / shared PowerShell primitives
# =============================================================================
# Dot-source this file (= `. .\setup-lib.ps1`) before using its helpers.
#
# Exposed primitives:
#   Get-PtVersionsFile [-Path <path>]   Resolves versions.yaml path.
#   Get-PtToolchain    [-Path <path>]   Returns hashtable of key -> constraint.
#   Test-PtCommand     <name>           True if command exists on PATH.
#   Get-PtVersion      <name>           Returns binary's semver string ("" on miss).
#   Test-PtVersion     <actual> <constraint>   True if actual meets constraint.
#   Write-PtInfo / Write-PtOk / Write-PtWarn / Write-PtFail
#                                       Coloured Host writers (= stderr-like).
# =============================================================================

function Get-PtVersionsFile {
    [CmdletBinding()]
    param([string]$Path)
    if ($Path) {
        if (Test-Path $Path) { return (Resolve-Path $Path).Path }
        return $null
    }
    if (Test-Path ".tooling\versions.yaml") { return (Resolve-Path ".tooling\versions.yaml").Path }
    if (Test-Path "_core\.tooling\versions.yaml") { return (Resolve-Path "_core\.tooling\versions.yaml").Path }
    return $null
}

function Get-PtToolchain {
    [CmdletBinding()]
    param([string]$Path)
    $file = Get-PtVersionsFile -Path $Path
    if (-not $file) { Write-PtFail "versions.yaml not found"; return $null }

    $result = @{}
    foreach ($raw in (Get-Content -LiteralPath $file)) {
        $line = ($raw -split '#', 2)[0].TrimEnd()
        if (-not $line -or $line -match '^\s') { continue }
        if ($line -match '^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*"?([^"]+?)"?\s*$') {
            $result[$matches[1]] = $matches[2]
        }
    }
    return $result
}

function Test-PtCommand {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PtVersion {
    param([Parameter(Mandatory)][string]$Name)
    try {
        switch ($Name) {
            'bash'   { $raw = & bash --version 2>$null | Select-Object -First 1 }
            'git'    { $raw = & git --version 2>$null }
            'python' { $raw = & python --version 2>&1 }
            'node'   { $raw = & node --version 2>$null }
            'jq'     { $raw = & jq --version 2>$null }
            default  { return "" }
        }
    } catch { return "" }
    if (-not $raw) { return "" }
    if ($raw -match '([0-9]+\.[0-9]+(\.[0-9]+)?)') { return $matches[1] }
    return ""
}

function Test-PtVersion {
    param(
        [Parameter(Mandatory)][string]$Actual,
        [Parameter(Mandatory)][string]$Constraint
    )
    if (-not $Actual) { return $false }

    function ToInt([string]$v) {
        $parts = ($v -split '\.') + @('0', '0', '0')
        return [int64]$parts[0] * 1000000 + [int64]$parts[1] * 1000 + [int64]$parts[2]
    }

    if ($Constraint.StartsWith('>=')) {
        $floor = $Constraint.Substring(2)
        return (ToInt $Actual) -ge (ToInt $floor)
    }
    return $Actual -eq $Constraint
}

function Write-PtInfo { param($Message); Write-Host "info: $Message" -ForegroundColor Cyan }
function Write-PtOk   { param($Message); Write-Host "ok:   $Message" -ForegroundColor Green }
function Write-PtWarn { param($Message); Write-Host "warn: $Message" -ForegroundColor Yellow }
function Write-PtFail { param($Message); Write-Host "fail: $Message" -ForegroundColor Red }
