# ==============================================================================
#  music-cli: Windows One-line Installer (PowerShell)
#  Usage:
#    irm https://raw.githubusercontent.com/ghiffarsabda/music-cli/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

# Ensure TLS 1.2+ for secure downloads in PowerShell 5.1
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

Write-Host ""
Write-Host "♫  m u s i c  -  c l i Installer (Windows)" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host ""

# 1. Check Python
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
}

if (-not $pyCmd) {
    Write-Host "✗ Error: Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.9+ from https://www.python.org or run: winget install Python.Python.3.12"
    exit 1
}

$pyVersion = & $pyCmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "✓ Found Python $pyVersion" -ForegroundColor Green

# 2. Check for mpv
$mpvCmd = Get-Command mpv -ErrorAction SilentlyContinue
if (-not $mpvCmd) {
    Write-Host "⚠ mpv player is not detected." -ForegroundColor Yellow
    Write-Host "music-cli requires mpv for audio streaming."
    $mpvInstalled = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "→ Installing mpv via winget..." -ForegroundColor Cyan
        try {
            winget install --id shinchiro.mpv --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -eq 0) { $mpvInstalled = $true }
        } catch {}
    }
    if (-not $mpvInstalled -and (Get-Command scoop -ErrorAction SilentlyContinue)) {
        Write-Host "→ Installing mpv via scoop..." -ForegroundColor Cyan
        try {
            scoop install mpv
            if ($LASTEXITCODE -eq 0) { $mpvInstalled = $true }
        } catch {}
    }
    if (-not $mpvInstalled -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Host "→ Installing mpv via choco..." -ForegroundColor Cyan
        try {
            choco install mpv -y
            if ($LASTEXITCODE -eq 0) { $mpvInstalled = $true }
        } catch {}
    }
    if (-not $mpvInstalled) {
        Write-Host "Please install mpv from https://mpv.io or run: winget install shinchiro.mpv" -ForegroundColor Yellow
    }
} else {
    Write-Host "✓ Found mpv audio backend" -ForegroundColor Green
}

# 3. Setup isolated virtual environment in %LOCALAPPDATA%\music-cli
$installDir = Join-Path $env:LOCALAPPDATA "music-cli"
$venvDir = Join-Path $installDir "venv"
$scriptsDir = Join-Path $venvDir "Scripts"

Write-Host ""
Write-Host "→ Setting up environment in $installDir..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

& $pyCmd.Source -m venv $venvDir

# 4. Install / Upgrade music-cli (zip archive doesn't require git CLI)
Write-Host "→ Installing music-cli and dependencies..." -ForegroundColor Cyan
$pipExe = Join-Path $scriptsDir "pip.exe"
& $pipExe install --upgrade pip --quiet
& $pipExe install --upgrade "https://github.com/ghiffarsabda/music-cli/archive/refs/heads/main.zip" --quiet

# 5. Add to User PATH if needed
$userPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
if ($userPath -notlike "*$scriptsDir*") {
    Write-Host "→ Adding $scriptsDir to User PATH..." -ForegroundColor Cyan
    $newPath = "$scriptsDir;$userPath"
    [Environment]::SetEnvironmentVariable("Path", $newPath, [EnvironmentVariableTarget]::User)
    $env:Path = "$scriptsDir;$env:Path"
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host "🎉 music-cli installed successfully!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "Restart your PowerShell / Windows Terminal, then launch music-cli by typing:"
Write-Host "  music" -ForegroundColor Cyan
Write-Host ""
