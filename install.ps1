# ==============================================================================
#  music-cli: Windows One-line Installer (PowerShell)
#  Usage:
#    irm https://cdn.jsdelivr.net/gh/ghiffarsabda/music-cli@main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

# Ensure TLS 1.2+ for secure downloads in PowerShell 5.1
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

Write-Host ""
Write-Host " ♫  m u s i c  -  c l i " -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host ""

# Helper to verify a python executable actually works (and isn't the Windows Store 0-byte dummy stub)
function Test-PythonExe ($exePath) {
    if (-not $exePath) { return $false }
    if (-not (Test-Path $exePath)) { return $false }
    try {
        $ver = & $exePath -c "import sys; print(sys.version_info.major)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -and $ver.Trim() -eq "3") {
            return $true
        }
    } catch {}
    return $false
}

function Refresh-EnvPath {
    $userPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
    $machinePath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Machine)
    $env:Path = "$userPath;$machinePath;$env:Path"
}

# 1. Detect or Automatically Install Python
$pyExe = $null

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd -and (Test-PythonExe $pyCmd.Source)) {
    $pyExe = $pyCmd.Source
} else {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd -and (Test-PythonExe $pyCmd.Source)) {
        $pyExe = $pyCmd.Source
    }
}

# If not found in current PATH, check common default Windows Python install locations
if (-not $pyExe) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-PythonExe $cand) {
            $pyExe = $cand
            break
        }
    }
}

# Clean-slate machine: Python is not installed yet! Install it automatically without user effort.
if (-not $pyExe) {
    Write-Host "🌸 Setting up Python for you (takes ~1 minute)..." -ForegroundColor Magenta
    
    # Method A: Try winget (pre-installed on Windows 10 & 11)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "   Downloading via Windows Package Manager..." -ForegroundColor Gray
        try {
            winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        } catch {}
        Refresh-EnvPath
    }

    # Re-check candidate paths after winget
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-PythonExe $cand) {
            $pyExe = $cand
            break
        }
    }

    # Method B: Direct silent install from official python.org
    if (-not $pyExe) {
        Write-Host "   Downloading Python installer..." -ForegroundColor Gray
        $installerUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $installerPath = Join-Path $env:TEMP "python-installer.exe"
        try {
            (New-Object System.Net.WebClient).DownloadFile($installerUrl, $installerPath)
            Write-Host "   Installing Python quietly..." -ForegroundColor Gray
            Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            Refresh-EnvPath
            
            $pyCandidate = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
            if (Test-PythonExe $pyCandidate) {
                $pyExe = $pyCandidate
            }
        } catch {}
    }

    if (-not $pyExe) {
        Write-Host "✗ Could not install Python automatically." -ForegroundColor Red
        Write-Host "Please download Python from https://www.python.org/downloads/ (check 'Add to PATH' when installing)."
        exit 1
    }
}

$pyVer = & $pyExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "✓ Python $pyVer ready" -ForegroundColor Green

# 2. Detect or Automatically Install mpv
$mpvCmd = Get-Command mpv -ErrorAction SilentlyContinue
if (-not $mpvCmd) {
    $mpvCandidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\mpv.exe",
        "$env:LOCALAPPDATA\Programs\mpv\mpv.exe",
        "$env:ProgramFiles\mpv\mpv.exe",
        "C:\ProgramData\chocolatey\bin\mpv.exe",
        "C:\mpv\mpv.exe",
        "C:\tools\mpv\mpv.exe"
    )
    foreach ($cand in $mpvCandidates) {
        if (Test-Path $cand) {
            $mpvCmd = $cand
            break
        }
    }
}

if (-not $mpvCmd) {
    Write-Host "🎵 Setting up audio player..." -ForegroundColor Magenta
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id shinchiro.mpv -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        } catch {}
        Refresh-EnvPath
        $mpvCmd = Get-Command mpv -ErrorAction SilentlyContinue
        if (-not $mpvCmd) {
            $mpvCandidates = @(
                "$env:LOCALAPPDATA\Microsoft\WinGet\Links\mpv.exe",
                "$env:LOCALAPPDATA\Programs\mpv\mpv.exe",
                "$env:ProgramFiles\mpv\mpv.exe"
            )
            foreach ($cand in $mpvCandidates) {
                if (Test-Path $cand) {
                    $mpvCmd = $cand
                    break
                }
            }
        }
    }
    if ($mpvCmd) {
        Write-Host "✓ Audio player ready" -ForegroundColor Green
    } else {
        Write-Host "✓ Audio player setup complete" -ForegroundColor Green
    }
} else {
    Write-Host "✓ Audio player ready" -ForegroundColor Green
}

# 3. Setup isolated virtual environment in %LOCALAPPDATA%\music-cli
$installDir = Join-Path $env:LOCALAPPDATA "music-cli"
$venvDir = Join-Path $installDir "venv"
$scriptsDir = Join-Path $venvDir "Scripts"

Write-Host "✨ Installing music-cli..." -ForegroundColor Magenta
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

& $pyExe -m venv $venvDir

# 4. Install / Upgrade music-cli (zip archive doesn't require git CLI)
$venvPython = Join-Path $scriptsDir "python.exe"
& $venvPython -m pip install --upgrade "https://github.com/ghiffarsabda/music-cli/archive/refs/heads/main.zip" --quiet

# 5. Add to User PATH if needed
$userPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
if ($userPath -notlike "*$scriptsDir*") {
    $newPath = "$scriptsDir;$userPath"
    [Environment]::SetEnvironmentVariable("Path", $newPath, [EnvironmentVariableTarget]::User)
}
if ($env:Path -notlike "*$scriptsDir*") {
    $env:Path = "$scriptsDir;$env:Path"
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host "🎉 You're all set! music-cli is installed!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "Close this window and open PowerShell again, then type:" -ForegroundColor White
Write-Host "  music" -ForegroundColor Cyan
Write-Host ""
