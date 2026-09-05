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
    # Ignore the 0-byte Windows Store redirect stub
    if ($exePath -like "*\Microsoft\WindowsApps\*") { return $false }
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

$pyCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "$env:ProgramFiles\Python311\python.exe",
    "${env:ProgramFiles(x86)}\Python312\python.exe"
)

# If not found in current PATH, check common default Windows Python install locations
if (-not $pyExe) {
    foreach ($cand in $pyCandidates) {
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
        foreach ($cand in $pyCandidates) {
            if (Test-PythonExe $cand) {
                $pyExe = $cand
                break
            }
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
            
            foreach ($cand in $pyCandidates) {
                if (Test-PythonExe $cand) {
                    $pyExe = $cand
                    break
                }
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
function Find-MpvExe {
    $cmd = Get-Command mpv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    # 1. Check App Paths in Windows Registry
    $regLocations = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe"
    )
    foreach ($reg in $regLocations) {
        if (Test-Path $reg) {
            $val = (Get-ItemProperty -Path $reg -ErrorAction SilentlyContinue).'(default)'
            if ($val -and (Test-Path $val)) { return $val }
        }
    }

    # 2. Check Uninstall keys in Windows Registry (Inno Setup, WinGet, standard installers)
    $uninstallPaths = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($unPath in $uninstallPaths) {
        $entries = Get-ItemProperty -Path $unPath -ErrorAction SilentlyContinue
        foreach ($e in $entries) {
            if ($e.DisplayName -like "*mpv*" -or $e.PSChildName -like "*mpv*") {
                if ($e.InstallLocation -and (Test-Path (Join-Path $e.InstallLocation "mpv.exe"))) {
                    return (Join-Path $e.InstallLocation "mpv.exe")
                }
                if ($e.'Inno Setup: App Path' -and (Test-Path (Join-Path $e.'Inno Setup: App Path' "mpv.exe"))) {
                    return (Join-Path $e.'Inno Setup: App Path' "mpv.exe")
                }
                if ($e.DisplayIcon -and ($e.DisplayIcon -like "*mpv.exe*")) {
                    $cleanIcon = $e.DisplayIcon.Split(',')[0].Trim('"')
                    if (Test-Path $cleanIcon) { return $cleanIcon }
                }
            }
        }
    }

    # 3. Known common install locations
    $candidates = @(
        "$env:ProgramFiles\mpv\mpv.exe",
        "${env:ProgramFiles(x86)}\mpv\mpv.exe",
        "$env:LOCALAPPDATA\Programs\mpv\mpv.exe",
        "$env:LOCALAPPDATA\mpv\mpv.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\mpv.exe",
        "$env:ProgramFiles\WinGet\Links\mpv.exe",
        "$env:APPDATA\mpv\mpv.exe",
        "C:\mpv\mpv.exe",
        "C:\tools\mpv\mpv.exe",
        "C:\ProgramData\chocolatey\bin\mpv.exe",
        "C:\ProgramData\chocolatey\lib\mpvio.install\tools\mpv.exe",
        "C:\ProgramData\chocolatey\lib\mpv\tools\mpv.exe",
        "$env:USERPROFILE\scoop\apps\mpv\current\mpv.exe",
        "C:\scoop\apps\mpv\current\mpv.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) { return $cand }
    }

    # 4. Search WinGet package directories
    $wgDirs = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:ProgramFiles\WinGet\Packages",
        "$env:ProgramData\Microsoft\WinGet\Packages"
    )
    foreach ($wg in $wgDirs) {
        if (Test-Path $wg) {
            $found = Get-ChildItem -Path $wg -Filter "mpv.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }

    return $null
}

$mpvExe = Find-MpvExe

if (-not $mpvExe) {
    Write-Host "🎵 Setting up audio player..." -ForegroundColor Magenta
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id shinchiro.mpv -e --silent --force --accept-package-agreements --accept-source-agreements | Out-Null
        } catch {}
        Refresh-EnvPath
        $mpvExe = Find-MpvExe
    }
}

if ($mpvExe) {
    $mpvDir = Split-Path -Parent $mpvExe
    if ($env:Path -notlike "*$mpvDir*") {
        $env:Path = "$mpvDir;$env:Path"
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
    if ($userPath -notlike "*$mpvDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$mpvDir;$userPath", [EnvironmentVariableTarget]::User)
    }
    Write-Host "✓ Audio player ready ($mpvExe)" -ForegroundColor Green
} else {
    Write-Host "⚠  mpv audio player was not found automatically." -ForegroundColor Yellow
    Write-Host "   To enable music playback, install mpv using:" -ForegroundColor Yellow
    Write-Host "   winget install shinchiro.mpv" -ForegroundColor Cyan
    Write-Host "   or download from https://mpv.io" -ForegroundColor Cyan
}

# 3. Setup isolated virtual environment in %LOCALAPPDATA%\music-cli
$installDir = Join-Path $env:LOCALAPPDATA "music-cli"
$venvDir = Join-Path $installDir "venv"
$scriptsDir = Join-Path $venvDir "Scripts"
$venvPython = Join-Path $scriptsDir "python.exe"

Write-Host "✨ Installing music-cli..." -ForegroundColor Magenta
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

# Clean up corrupted or incomplete venv from previous failed attempts
if ((Test-Path $venvDir) -and (-not (Test-Path $venvPython))) {
    Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
}

if (-not (Test-Path $venvPython)) {
    & $pyExe -m venv $venvDir
}

# 4. Install / Upgrade music-cli
if ((Test-Path ".\pyproject.toml") -and (Test-Path ".\music")) {
    Write-Host "   Installing from local repository..." -ForegroundColor Gray
    & $venvPython -m pip install --upgrade . --quiet
} else {
    & $venvPython -m pip install --upgrade "https://github.com/ghiffarsabda/music-cli/archive/refs/heads/main.zip" --quiet
}

# Create command wrappers music.cmd and music.ps1 so running 'music' works reliably across CMD and PowerShell
$cmdWrapper = Join-Path $scriptsDir "music.cmd"
Set-Content -Path $cmdWrapper -Value "@echo off`r`n`"%~dp0python.exe`" -m music %*"

$ps1Wrapper = Join-Path $scriptsDir "music.ps1"
Set-Content -Path $ps1Wrapper -Value "& `"`$PSScriptRoot\python.exe`" -m music `$args"

# Save detected mpv path to user config so music-cli finds it directly
if ($mpvExe) {
    $cfgDir = Join-Path $env:USERPROFILE ".config\music-cli"
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    $cfgFile = Join-Path $cfgDir "config.json"
    $escapedMpv = $mpvExe -replace '\\', '\\'
    if (Test-Path $cfgFile) {
        try {
            $existingJson = Get-Content $cfgFile -Raw | ConvertFrom-Json
            $existingJson | Add-Member -NotePropertyName "mpv_path" -NotePropertyValue $mpvExe -Force
            $existingJson | ConvertTo-Json | Set-Content $cfgFile
        } catch {}
    } else {
        Set-Content -Path $cfgFile -Value "{`r`n  `"mpv_path`": `"$escapedMpv`"`r`n}"
    }
}

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
Write-Host "To start listening, simply type:" -ForegroundColor White
Write-Host "  music" -ForegroundColor Cyan
Write-Host ""
