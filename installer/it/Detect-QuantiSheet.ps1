<#
.SYNOPSIS
    Detection script for QuantiSheet (Intune Win32 app, ConfigMgr script
    detection, PDQ conditions).

.DESCRIPTION
    Looks for the server setup (all users) and the standalone setup (per
    user or all users) in the Uninstall keys and compares DisplayVersion
    with -MinimumVersion. Intune rule: detected = exit code 0 AND
    something written to standard output. Not detected = exit 0 with no
    output (or exit 1).

    Edit $MinimumVersion below when you upload a newer setup, or run it by
    hand:  powershell -ExecutionPolicy Bypass -File Detect-QuantiSheet.ps1 -MinimumVersion 0.12.31

.NOTES
    Read-only: it changes nothing on the machine. Intune and ConfigMgr run
    detection as SYSTEM for a system-context app, where CurrentUser is
    SYSTEM's own hive, so the script also looks in every signed-in user's
    hive (HKEY_USERS). Users who aren't signed in aren't seen - for
    per-user installs deploy as a user-context app, or use the server
    setup or the MSI (all users).
#>
param(
    [string]$MinimumVersion = "0.12.31",
    [ValidateSet("Any", "Server", "Standalone")]
    [string]$Edition = "Any"
)

$ErrorActionPreference = "SilentlyContinue"
$WarningPreference = "SilentlyContinue"

# Both setups install 64-bit: read the 64-bit registry view even when this
# script runs in 32-bit PowerShell (ConfigMgr, or Intune "run as 32-bit").
$server = "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1"
$standalone = "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{375F90B3-3B41-4FE9-B790-B29C6D30C75E}_is1"
$checks = @()
if ($Edition -in "Any", "Server") { $checks += ,@("LocalMachine", $server) }
if ($Edition -in "Any", "Standalone") {
    $checks += ,@("LocalMachine", $standalone)
    $checks += ,@("CurrentUser", $standalone)
    # run as SYSTEM (Intune / ConfigMgr), CurrentUser is SYSTEM's own hive:
    # look in every loaded user hive too (Venice review M5)
    $users = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::Users,
        [Microsoft.Win32.RegistryView]::Registry64)
    foreach ($sid in $users.GetSubKeyNames()) {
        if ($sid -notlike "*_Classes" -and $sid -like "S-1-5-21-*") {
            $checks += ,@("Users", "$sid\$standalone")
        }
    }
}

function ConvertTo-Version([string]$text) {
    # "0.12.24 Beta" -> 0.12.24
    $m = [regex]::Match($text, '\d+(\.\d+){1,3}')
    if ($m.Success) { return [version]$m.Value }
    return $null
}

$want = ConvertTo-Version $MinimumVersion
if (-not $want) {
    # a bad -MinimumVersion must not match every install
    Write-Error "MinimumVersion '$MinimumVersion' is not a version number"
    exit 1
}
foreach ($c in $checks) {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]($c[0]),
        [Microsoft.Win32.RegistryView]::Registry64)
    $key = $base.OpenSubKey($c[1])
    if (-not $key) { continue }
    $shown = [string]$key.GetValue("DisplayVersion")
    $key.Close()
    $have = ConvertTo-Version $shown
    if ($have -and $have -ge $want) {
        Write-Output "QuantiSheet $shown found ($($c[0])\$($c[1]))"
        exit 0
    }
}
exit 0
