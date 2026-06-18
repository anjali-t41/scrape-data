# push.ps1 — collect local Claude Code data and push to the central store
# Usage:
#   .\push.ps1                              # uses POSTGRES_URL env var
#   .\push.ps1 --since 7d                  # override period
#   .\push.ps1 --central <url> --since 7d
#   .\push.ps1 --dry-run                    # preview without writing
#
# If execution policy blocks the script, run once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# ── Python check ──────────────────────────────────────────────────────────────
$Python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info >= (3,11))" 2>$null
        if ($ver -eq "True") { $Python = $cmd; break }
    } catch {}
}

if (-not $Python) {
    Write-Error "Python 3.11+ not found. Install from https://python.org"
    exit 1
}

$platform = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
$pyver    = & $Python --version
Write-Host "[push] Platform : $platform"
Write-Host "[push] Python   : $pyver"

# ── Virtual environment ───────────────────────────────────────────────────────
if (-not (Test-Path ".venv")) {
    Write-Host "[push] Creating virtual environment..."
    & $Python -m venv .venv
}

$VenvPython = ".venv\Scripts\python.exe"
$VenvPip    = ".venv\Scripts\pip.exe"

Write-Host "[push] Installing dependencies..."
& $VenvPip install -q -r requirements.txt

# ── Run push ──────────────────────────────────────────────────────────────────
Write-Host "[push] Starting push..."
Write-Host ""
& $VenvPython push.py @args
