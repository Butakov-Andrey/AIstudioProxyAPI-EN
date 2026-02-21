$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

function Test-Command {
    param([string]$Command)
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-Command "uv")) {
    Write-Host "[ERROR] uv is not installed. Install it first: https://docs.astral.sh/uv/" -ForegroundColor Red
    exit 1
}

$pythonCmd = $null
if (Test-Command "python") {
    $pythonCmd = "python"
}
elseif (Test-Command "py") {
    $pythonCmd = "py"
}
else {
    Write-Host "[ERROR] Python 3.9+ is required." -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Creating .venv with uv..." -ForegroundColor Blue
uv venv --python $pythonCmd

Write-Host "[INFO] Installing dependencies with uv..." -ForegroundColor Blue
uv pip install -r requirements-uv.txt

Write-Host "[INFO] Installing Playwright Firefox..." -ForegroundColor Blue
uv run playwright install firefox

Write-Host "[INFO] Fetching Camoufox..." -ForegroundColor Blue
uv run camoufox fetch

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[INFO] Created .env from .env.example" -ForegroundColor Blue
}

Write-Host "[SUCCESS] UV setup complete." -ForegroundColor Green
Write-Host "Next step:"
Write-Host "  uv run python launch_camoufox.py --headless"
