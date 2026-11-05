# QuantiSheet: install the programs QuantiSheet uses, if they're missing.
#
#   Python 3.12      runs QuantiSheet                         (required)
#   Tesseract OCR    makes scanned sheets searchable (OCR)   (recommended)
#   Ollama + model   local AI review, RFI finder, translate  (optional, ~2 GB)
#   LibreOffice      Office files to PDF, when Microsoft Office isn't here
#                                                             (optional, ~350 MB)
#
# Uses winget (built into Windows 10/11). Without winget it downloads the
# official installer where there is a stable link, or opens the download page.
# Nothing is asked except Windows' own permission (UAC) prompts.
#
#   -NoAIModel      skip Ollama and the AI model
#   -NoLibreOffice  skip LibreOffice
#   -NoPython       skip Python (the installed program has its own)
#   -DetectOnly     only report what is installed; change nothing
param(
    [switch]$NoAIModel,
    [switch]$NoLibreOffice,
    [switch]$NoPython,
    [switch]$DetectOnly,
    [string]$Model = "llama3.2"
)

$ErrorActionPreference = "Continue"
$results = New-Object System.Collections.Generic.List[object]

function Note($name, $status, $detail) {
    $results.Add([pscustomobject]@{ Program = $name; Status = $status; Detail = $detail })
}

function Has-Winget {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}

function Winget-Install($id) {
    $wargs = @("install", "--id", $id, "-e", "--silent",
              "--accept-package-agreements", "--accept-source-agreements")
    $p = Start-Process winget -ArgumentList $wargs -Wait -PassThru -NoNewWindow
    # 0 = installed; -1978335189 (0x8A15002B) = already installed / no upgrade
    return ($p.ExitCode -eq 0 -or $p.ExitCode -eq -1978335189)
}

# A downloaded installer runs ONLY when Windows says its digital signature
# is valid and it was signed by the expected publisher (threat model T-006:
# a download changed on the way, or a file swapped in the temp folder, is
# never run). It is saved in a new private folder, not straight in %TEMP%.
function Download-Run($url, $silentArgs, $publisher) {
    if (-not $publisher) { return $false }
    $dir = Join-Path $env:TEMP ("qs-deps-" + [guid]::NewGuid().ToString("N"))
    $file = Join-Path $dir ([IO.Path]::GetFileName($url))
    try {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
        $sig = Get-AuthenticodeSignature -FilePath $file
        $who = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
        if ($sig.Status -ne "Valid" -or $who -notlike "*$publisher*") {
            Write-Host "Not run: $url is not validly signed by $publisher ($($sig.Status))."
            return $false
        }
        $p = Start-Process $file -ArgumentList $silentArgs -Wait -PassThru
        return ($p.ExitCode -eq 0)
    } catch {
        return $false
    } finally {
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure($name, $test, $wingetId, $url, $silentArgs, $page, $publisher) {
    if (& $test) { Note $name "already installed" ""; return $true }
    if ($DetectOnly) { Note $name "missing" "would install"; return $false }
    Write-Host "Installing $name..."
    $ok = $false
    if (Has-Winget) { $ok = Winget-Install $wingetId }
    if (-not $ok -and $url) { $ok = Download-Run $url $silentArgs $publisher }
    Refresh-Path
    if ($ok -and (& $test)) { Note $name "installed" ""; return $true }
    if ($page) { Start-Process $page }
    Note $name "NOT installed" "download it from $page"
    return $false
}

# ---- detection ------------------------------------------------------------------

function Find-Python {
    foreach ($c in @("py -3.12", "py -3.13", "py -3.11")) {
        $exe, $ver = $c.Split(" ")
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            & $exe $ver -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return $true }
        }
    }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:ProgramFiles\Python312\python.exe")) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function Find-Tesseract {
    if (Get-Command tesseract -ErrorAction SilentlyContinue) { return $true }
    foreach ($b in @($env:ProgramFiles, ${env:ProgramFiles(x86)},
                     "$env:LOCALAPPDATA\Programs")) {
        if ($b -and (Test-Path (Join-Path $b "Tesseract-OCR\tesseract.exe"))) { return $true }
    }
    return $false
}

function Ollama-Exe {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $p) { return $p }
    return $null
}

function Find-Ollama { return [bool](Ollama-Exe) }

function Find-Office {
    return (Test-Path "Registry::HKEY_CLASSES_ROOT\Word.Application") -or
           (Test-Path "$env:ProgramFiles\LibreOffice\program\soffice.exe") -or
           (Test-Path "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe")
}

# ---- install ---------------------------------------------------------------------

Write-Host ""
Write-Host "=== Programs QuantiSheet uses ==="

if (-not $NoPython) {
    Ensure "Python 3.12" { Find-Python } "Python.Python.3.12" `
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" `
        "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1" `
        "https://www.python.org/downloads/" "Python Software Foundation" | Out-Null
}

Ensure "Tesseract OCR" { Find-Tesseract } "UB-Mannheim.TesseractOCR" `
    $null $null "https://github.com/UB-Mannheim/tesseract/wiki" | Out-Null

if ($NoAIModel) {
    Note "Ollama (local AI)" "skipped" "-NoAIModel"
} else {
    $have = Ensure "Ollama (local AI)" { Find-Ollama } "Ollama.Ollama" `
        "https://ollama.com/download/OllamaSetup.exe" "/VERYSILENT /NORESTART" `
        "https://ollama.com/download" "Ollama"
    $exe = Ollama-Exe
    if ($exe) {
        $list = (& $exe list 2>$null) -join "`n"
        if ($LASTEXITCODE -ne 0) {
            if (-not $DetectOnly) {
                Start-Process $exe -ArgumentList "serve" -WindowStyle Hidden
                Start-Sleep -Seconds 4
                $list = (& $exe list 2>$null) -join "`n"
            }
        }
        if ($list -match [regex]::Escape($Model)) {
            Note "AI model $Model" "already installed" ""
        } elseif ($DetectOnly) {
            Note "AI model $Model" "missing" "would download (~2 GB)"
        } else {
            Write-Host "Downloading the AI model $Model (about 2 GB)..."
            & $exe pull $Model
            if ($LASTEXITCODE -eq 0) { Note "AI model $Model" "installed" "" }
            else { Note "AI model $Model" "NOT installed" "run: ollama pull $Model" }
        }
    }
}

if ($NoLibreOffice) {
    Note "LibreOffice" "skipped" "-NoLibreOffice"
} elseif (Test-Path "Registry::HKEY_CLASSES_ROOT\Word.Application") {
    Note "LibreOffice" "not needed" "Microsoft Office is installed"
} else {
    Ensure "LibreOffice" { Find-Office } "TheDocumentFoundation.LibreOffice" `
        $null $null "https://www.libreoffice.org/download/download-libreoffice/" | Out-Null
}

Write-Host ""
$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
$log = Join-Path (Split-Path $PSScriptRoot -Parent) "install-deps-log.txt"
try {
    $results | Format-Table -AutoSize | Out-String -Width 200 | Set-Content $log -ErrorAction Stop
} catch {
    $log = Join-Path $env:TEMP "quantisheet-install-deps-log.txt"
    $results | Format-Table -AutoSize | Out-String -Width 200 | Set-Content $log
}
$missingRequired = $results | Where-Object { $_.Program -eq "Python 3.12" -and $_.Status -like "NOT*" }
if ($missingRequired) { exit 2 }
exit 0
