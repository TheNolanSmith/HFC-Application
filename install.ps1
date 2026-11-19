# HFC Model Refresh - one-time install. Re-run any time to update packages or rebuild the shortcut.
# Usage (from this folder):   powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "`n== HFC Model Refresh install ==" -ForegroundColor Yellow

# 1. Python (3.10+). Prefer the py launcher.
$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "py -3", "python")) {
    try {
        $v = & ([scriptblock]::Create("$cand -c `"import sys;print(sys.version_info[:2]>=(3,10))`"")) 2>$null
        if ($v -eq "True") { $py = $cand; break }
    } catch {}
}
if (-not $py) { throw "Python 3.10+ not found. Install it from python.org (tick 'Add to PATH') and re-run." }
Write-Host "Using $py"

# 2. Virtual environment + packages
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    & ([scriptblock]::Create("$py -m venv .venv"))
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
Write-Host "Installing packages (first run takes a few minutes)..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed - see output above." }

# 3. Settings file (never overwritten)
if (-not (Test-Path "config\settings.yaml")) {
    Copy-Item "config\settings.example.yaml" "config\settings.yaml"
    Write-Host "Created config\settings.yaml (starts in demo mode)."
}
if (-not (Test-Path "config\models.csv")) {
    Copy-Item "config\models.example.csv" "config\models.csv"
    Write-Host "Created config\models.csv - list your L3 / L2 workbooks there (or on the Models page)."
}

# 4. Desktop shortcut (handles OneDrive-redirected Desktop)
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "HFC Model Refresh.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
$sc.Arguments = "`"$(Join-Path $Root 'launcher.py')`""
$sc.WorkingDirectory = $Root
$sc.IconLocation = Join-Path $Root "assets\hfc_refresh.ico"
$sc.Description = "HFC Model Refresh - coordinate L3 / L2 model updates from Snowflake"
$sc.Save()
Write-Host "Desktop shortcut created: $lnk" -ForegroundColor Green

Write-Host "`nDone. Double-click 'HFC Model Refresh' on your desktop." -ForegroundColor Green
Write-Host "It opens in demo mode - go to Settings to enter Snowflake details and turn demo off.`n"
