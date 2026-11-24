<#
.SYNOPSIS
  Timeline Studio Kit v4.2 — Portable Automatic Windows Installer (`install.ps1`)
.DESCRIPTION
  Sets up everything needed on any fresh Windows PC with zero manual configuration:
    1. System binaries via winget if missing (Python 3, Node.js LTS, FFmpeg, Git)
    2. Isolated Python runtime (.runtime/.venv) with faster-whisper, Pillow, requests, yt-dlp, edge-tts
    3. Timeline Studio CLI & CC0 SFX (MartinDelophy/ai-video-editor) in .runtime/timeline-studio
    4. Motion Graphics & Natural Earth Cartography runtime (.runtime/node_modules: Playwright, GSAP,
       Three.js, p5, p5.brush, world-atlas, d3-geo, topojson-client, maplibre-gl, @turf/turf, fflate)
    5. Headless browser check (reuses Chrome/Edge or installs Playwright Chromium) + Whisper small warm-up
#>
param(
    [switch]$SkipWhisperPreload = $false
)

$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Resolve agent workspace root (walks up from .runtime/kit/scripts, .agents/skills/..., or .claude/skills/...)
$Workspace = $ScriptDir
for ($i = 0; $i -lt 8; $i++) {
    $leaf = Split-Path -Leaf $Workspace
    if ($leaf -eq ".agents" -or $leaf -eq ".claude" -or $leaf -eq ".runtime") {
        $Workspace = Split-Path -Parent $Workspace
        break
    }
    $parent = Split-Path -Parent $Workspace
    if (-not $parent -or $parent -eq $Workspace) {
        $Workspace = (Get-Location).Path
        break
    }
    $Workspace = $parent
}

$RuntimeDir = Join-Path $Workspace ".runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " Timeline Studio Kit v4.2 — Windows Automatic Setup" -ForegroundColor Cyan
Write-Host " Workspace: $Workspace" -ForegroundColor Gray
Write-Host "======================================================================" -ForegroundColor Cyan

function Refresh-Path {
    $extra = New-Object System.Collections.Generic.List[string]
    $wgLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    if (Test-Path $wgLinks) { $extra.Add($wgLinks) }

    # Scan WinGet extracted packages (FFmpeg, Node, Git) so they work immediately without reboot
    $wgPkgs = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $wgPkgs) {
        foreach ($pattern in @("Gyan.FFmpeg*", "FFmpeg*", "BtbN.FFmpeg*", "OpenJS.NodeJS*", "Git.Git*")) {
            Get-ChildItem -Path $wgPkgs -Directory -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
                $extra.Add($_.FullName)
                Get-ChildItem -Path $_.FullName -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                    $binD = Join-Path $_.FullName "bin"
                    $cmdD = Join-Path $_.FullName "cmd"
                    if (Test-Path $binD) { $extra.Add($binD) }
                    if (Test-Path $cmdD) { $extra.Add($cmdD) }
                }
            }
        }
    }

    # Scan standard Python 3 installations (prioritized ahead of WindowsApps store stub!)
    foreach ($pyRoot in @((Join-Path $env:LOCALAPPDATA "Programs\Python"), $env:ProgramFiles)) {
        if ($pyRoot -and (Test-Path $pyRoot)) {
            Get-ChildItem -Path $pyRoot -Directory -Filter "Python3*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object {
                if (Test-Path (Join-Path $_.FullName "python.exe")) {
                    $extra.Add($_.FullName)
                    $sc = Join-Path $_.FullName "Scripts"
                    if (Test-Path $sc) { $extra.Add($sc) }
                }
            }
        }
    }

    foreach ($d in @("C:\ffmpeg\bin", "$env:ProgramFiles\nodejs", "$env:ProgramFiles\Git\cmd")) {
        if (Test-Path $d) { $extra.Add($d) }
    }

    $mach = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $usr = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (($extra -join ";") + ";$usr;$mach").Trim(";")
}

function Find-RealCommand {
    param([string]$Cmd)
    $hits = Get-Command $Cmd -All -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandType -eq "Application" -and $_.Source -and ($_.Source -notmatch "WindowsApps")
    }
    if ($hits) { return ($hits | Select-Object -First 1).Source }
    return $null
}

function Ensure-WingetTool {
    param([string]$Cmd, [string]$WingetId, [string]$Label, [bool]$Optional = $false)
    $found = Find-RealCommand $Cmd
    if ($found) {
        Write-Host "  [OK] $Label found: $found" -ForegroundColor Green
        return $found
    }
    Write-Host "  [INSTALL] $Label missing -> installing via winget ($WingetId)..." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        if ($Optional) {
            Write-Host "  [WARN] winget unavailable; continuing without optional $Label." -ForegroundColor Yellow
            return $null
        }
        throw "$Label is missing and winget is unavailable. Install $Label manually and re-run."
    }
    try {
        & winget install --id $WingetId -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    } catch {
        Write-Host "  [WARN] winget returned notice for ${Label}: $_" -ForegroundColor Yellow
    }
    Refresh-Path
    $found = Find-RealCommand $Cmd
    if (-not $found) {
        if ($Optional) {
            Write-Host "  [WARN] $Label still not on PATH; using ZIP fallback." -ForegroundColor Yellow
            return $null
        }
        throw "$Label installation finished but '$Cmd' was not found on PATH. Re-open terminal or install $Label."
    }
    Write-Host "  [OK] $Label ready: $found" -ForegroundColor Green
    return $found
}

Write-Host "`n[1/5] Checking System Binaries (Python 3, Node.js, FFmpeg, Git)..." -ForegroundColor Cyan
Refresh-Path
$RealPy = Ensure-WingetTool -Cmd "python" -WingetId "Python.Python.3.12" -Label "Python 3"
$RealNode = Ensure-WingetTool -Cmd "node" -WingetId "OpenJS.NodeJS.LTS" -Label "Node.js LTS"
$RealFfmpeg = Ensure-WingetTool -Cmd "ffmpeg" -WingetId "Gyan.FFmpeg" -Label "FFmpeg"
$RealGit = Ensure-WingetTool -Cmd "git" -WingetId "Git.Git" -Label "Git" -Optional $true

Write-Host "`n[2/5] Setting up Python Dependencies (faster-whisper, Pillow, requests, yt-dlp)..." -ForegroundColor Cyan
$SysPyOk = $false
try {
    & $RealPy -B -c "import PIL, requests, faster_whisper, shutil, sys; sys.exit(0 if shutil.which('yt-dlp') else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $SysPyOk = $true }
} catch {}

$VenvPy = Join-Path $RuntimeDir ".venv\Scripts\python.exe"
if ($SysPyOk) {
    Write-Host "  [OK] Existing Python already has all required packages + yt-dlp." -ForegroundColor Green
    $PyExe = $RealPy
} else {
    if (-not (Test-Path $VenvPy)) {
        Write-Host "  [SETUP] Creating isolated venv at $RuntimeDir\.venv ..." -ForegroundColor Yellow
        & $RealPy -m venv (Join-Path $RuntimeDir ".venv")
    }
    & $VenvPy -B -m pip install --upgrade pip --quiet
    & $VenvPy -B -m pip install -r (Join-Path $ScriptDir "requirements.txt")
    $PyExe = $VenvPy
}

Write-Host "`n[3/5] Setting up Timeline Studio CLI & CC0 SFX (MartinDelophy/ai-video-editor)..." -ForegroundColor Cyan
$SharedTs = Join-Path $env:USERPROFILE "OpenBot\Shared\timeline-studio"
$LocalTs = Join-Path $RuntimeDir "timeline-studio"
if (Test-Path (Join-Path $SharedTs "scripts\timeline-command.mjs")) {
    Write-Host "  [OK] Reusing existing Timeline Studio at $SharedTs" -ForegroundColor Green
} elseif (Test-Path (Join-Path $LocalTs "scripts\timeline-command.mjs")) {
    Write-Host "  [OK] Timeline Studio already present at $LocalTs" -ForegroundColor Green
} else {
    $cloned = $false
    if ($RealGit) {
        try {
            Write-Host "  [CLONE] Cloning MartinDelophy/ai-video-editor (--depth 1)..." -ForegroundColor Yellow
            & $RealGit clone --depth 1 "https://github.com/MartinDelophy/ai-video-editor.git" $LocalTs
            if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $LocalTs "scripts\timeline-command.mjs"))) { $cloned = $true }
        } catch {}
    }
    if (-not $cloned) {
        Write-Host "  [ZIP] Downloading MartinDelophy/ai-video-editor ZIP fallback..." -ForegroundColor Yellow
        $zipFile = Join-Path $RuntimeDir "_ts_tmp.zip"
        $tmpDir = Join-Path $RuntimeDir "_ts_extract"
        if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
        if (Test-Path $LocalTs) { Remove-Item -Recurse -Force $LocalTs }
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -fsSL "https://github.com/MartinDelophy/ai-video-editor/archive/refs/heads/main.zip" -o $zipFile
        } else {
            Invoke-WebRequest -UseBasicParsing "https://github.com/MartinDelophy/ai-video-editor/archive/refs/heads/main.zip" -OutFile $zipFile
        }
        Expand-Archive -Force $zipFile $tmpDir
        $inner = (Get-ChildItem $tmpDir -Directory | Select-Object -First 1).FullName
        Move-Item $inner $LocalTs
        Remove-Item -Recurse -Force $tmpDir, $zipFile -ErrorAction SilentlyContinue
        Write-Host "  [OK] Timeline Studio extracted to $LocalTs" -ForegroundColor Green
    }
}

Write-Host "`n[4/5] Setting up Motion Graphics, Natural Earth Maps & CLI Node Runtime..." -ForegroundColor Cyan
$SharedMotion = Join-Path $env:USERPROFILE "OpenBot\Shared\motion-video-lab\runtime"
$ReqNodePkgs = @("playwright", "gsap", "three", "p5", "p5.brush", "world-atlas", "d3-geo", "topojson-client", "maplibre-gl")
$SharedReady = $true
foreach ($pkg in $ReqNodePkgs) {
    if (-not (Test-Path (Join-Path $SharedMotion "node_modules\$pkg"))) { $SharedReady = $false; break }
}
$LocalReady = $true
foreach ($pkg in ($ReqNodePkgs + @("fflate"))) {
    if (-not (Test-Path (Join-Path $RuntimeDir "node_modules\$pkg"))) { $LocalReady = $false; break }
}

if ($SharedReady -and (Test-Path (Join-Path $SharedTs "node_modules\fflate"))) {
    Write-Host "  [OK] Reusing existing Motion + Timeline Studio Node runtimes." -ForegroundColor Green
} elseif ($LocalReady) {
    Write-Host "  [OK] Local Motion & CLI runtime already installed at $RuntimeDir" -ForegroundColor Green
} else {
    Copy-Item -Force (Join-Path $ScriptDir "runtime-package.json") (Join-Path $RuntimeDir "package.json")
    Push-Location $RuntimeDir
    try {
        Write-Host "  [NPM] Installing Playwright, GSAP, Three.js, p5.brush, Natural Earth maps, fflate..." -ForegroundColor Yellow
        & npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

# Ensure a headless browser exists (reuse system Chrome/Edge or install Playwright Chromium)
$HasBrowser = (Test-Path "$env:ProgramFiles\Google\Chrome\Application\chrome.exe") -or
              (Test-Path "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") -or
              (Test-Path "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") -or
              (Test-Path "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") -or
              (Test-Path "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
if (-not $HasBrowser) {
    Write-Host "  [BROWSER] No Chrome/Edge detected -> installing Playwright Chromium..." -ForegroundColor Yellow
    Push-Location $RuntimeDir
    try { & npx playwright install chromium } finally { Pop-Location }
} else {
    Write-Host "  [OK] System Chrome/Edge detected for headless rendering." -ForegroundColor Green
}

Write-Host "`n[5/5] Warming up local offline Whisper model & running final Doctor check..." -ForegroundColor Cyan
if (-not $SkipWhisperPreload) {
    try {
        & $PyExe -B -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); print('  [OK] faster-whisper small model cached.')"
    } catch {
        Write-Host "  [WARN] Could not pre-cache Whisper model right now (will download automatically on first audio)." -ForegroundColor Yellow
    }
}

& $PyExe -B (Join-Path $ScriptDir "doctor.py")
if ($LASTEXITCODE -ne 0) {
    throw "Environment doctor reported missing dependencies. See JSON output above."
}
Write-Host "`n[DONE] Timeline Studio Kit v4.2 is READY!" -ForegroundColor Green
