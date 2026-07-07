# Day Trading Trainer — one-command launcher + onboarding.
#
# Fresh clone -> .\run.ps1 -> working app. Creates the venv, installs backend
# and frontend dependencies, builds the UI, starts the backend, and opens the
# browser once it responds. Every step is idempotent and skipped when already
# satisfied. In-app first-run (Alpaca keys + backfill) takes over from there.
#
#   -Build   rebuild the UI (after frontend changes)
#   -Setup   redo the venv / npm installs
#   -Port    backend port (default 8000)
#
# PowerShell 5.1 compatible. Deliberately no --reload on uvicorn: a reload
# restart would kill in-memory replay sessions and duplicate the poller task.
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Setup,
    [int]$Port = 8000
)

$root = $PSScriptRoot
$url = "http://127.0.0.1:$Port"
$venvPython = Join-Path $root 'backend\.venv\Scripts\python.exe'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- Already running? Just open the browser. --------------------------------
try {
    $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "$url/api/health"
    Write-Host "Already running at $url - opening browser."
    Start-Process $url
    exit 0
} catch { }

# --- Find a Python >= 3.12 (detect only; never auto-install). ---------------
function Find-Python {
    $probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($v in @('-3.13', '-3.12', '-3')) {
            try {
                $exe = & py $v -c "$probe; print()" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    return (& py $v -c 'import sys; print(sys.executable)').Trim()
                }
            } catch { }
        }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            & $cmd.Source -c $probe 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd.Source }
        } catch { }
    }
    return $null
}

# --- Backend onboarding: venv + pip install. ---------------------------------
if ($Setup -or -not (Test-Path $venvPython)) {
    $py = Find-Python
    if (-not $py) {
        Fail "Python 3.12+ not found. Install it from https://www.python.org/downloads/ then rerun .\run.ps1"
    }
    if (-not (Test-Path $venvPython)) {
        Step "Creating Python venv (backend\.venv) with $py ..."
        & $py -m venv (Join-Path $root 'backend\.venv')
        if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
    }
    Step "Installing backend dependencies (pip install -r requirements.txt) ..."
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
}

# --- Frontend onboarding: npm ci + build. ------------------------------------
$distIndex = Join-Path $root 'frontend\dist\index.html'
$needInstall = $Setup -or -not (Test-Path (Join-Path $root 'frontend\node_modules'))
$needBuild = $Build -or -not (Test-Path $distIndex)

if ($needInstall -or $needBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail "npm not found. Install Node.js (LTS) from https://nodejs.org/ then rerun .\run.ps1"
    }
}

if ($needInstall) {
    Step "Installing frontend dependencies (npm ci) ..."
    Push-Location (Join-Path $root 'frontend')
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "npm ci failed - falling back to npm install"
        npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed" }
    }
    Pop-Location
}

if ($needBuild) {
    Step "Building the UI (npm run build) ..."
    Push-Location (Join-Path $root 'frontend')
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "frontend build failed" }
    Pop-Location
} else {
    # Warn-only staleness check. OneDrive rewrites make mtimes unreliable as an
    # auto-trigger, and a surprise 30s build at launch is worse than a warning.
    $distTime = (Get-Item $distIndex).LastWriteTimeUtc
    $newestSrc = Get-ChildItem (Join-Path $root 'frontend\src') -Recurse -File |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    $srcTime = $newestSrc.LastWriteTimeUtc
    $pkgTime = (Get-Item (Join-Path $root 'frontend\package.json')).LastWriteTimeUtc
    if ($pkgTime -gt $srcTime) { $srcTime = $pkgTime }
    if ($srcTime -gt $distTime) {
        Write-Warning "UI sources are newer than the built dist - rerun with -Build to refresh."
    }
}

# --- Open the browser once the backend responds. -----------------------------
$null = Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "$u/api/health"
            Start-Process $u
            return
        } catch { Start-Sleep -Seconds 1 }
    }
} -ArgumentList $url

# --- Run the backend in the foreground (Ctrl+C stops it). --------------------
Step "Starting backend at $url (Ctrl+C to stop) ..."
& $venvPython -m uvicorn --app-dir (Join-Path $root 'backend') app.main:app --host 127.0.0.1 --port $Port
