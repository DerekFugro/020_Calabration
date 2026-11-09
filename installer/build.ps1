# build.ps1 - make Setup.exe for the van PCs.
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Needs: uv, git, Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Output: installer\Output\SurveyorCalibration_Setup_<version>.exe
param([switch]$Test)   # -Test: build from uncommitted code (version gets "-modified"); never release that
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# 1. version = date of the last commit + commit id; refuse uncommitted code in src
$dirty = git status --porcelain --untracked-files=no -- src main.py
if ($dirty -and -not $Test) { throw "Commit your changes first - the installer must match a git commit.`n$dirty" }
$hash = (git log -1 --format=%h).Trim()
$date = (git log -1 --format=%cs).Trim()            # 2026-11-06
$num  = $date -replace '-', '.'                     # 2026.11.06
$version = "$num-$hash"
if ($dirty) { $version += "-modified" }
Set-Content -Path VERSION -Value "$version" -Encoding ascii -NoNewline
Write-Host "Version $version"

try {
    # native tools print warnings on stderr; Windows PowerShell must not treat that as a failure
    $ErrorActionPreference = "Continue"
    # 2. the app folder (no Python needed on the van)
    uv pip install -q -r requirements.txt -r installer\requirements-build.txt
    uv run pyinstaller --noconfirm --clean --distpath installer\dist --workpath installer\build installer\SurveyorCalibration.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed" }

    # 3. Setup.exe
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found - winget install JRSoftware.InnoSetup" }
    & $iscc "/DAppVersion=$version" "/DAppNumber=$num" installer\SurveyorCalibration.iss
    if ($LASTEXITCODE) { throw "Inno Setup failed" }
    Get-ChildItem installer\Output\*.exe | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Write-Host "Made $($_.FullName)" }
} finally {
    Remove-Item VERSION -ErrorAction SilentlyContinue   # the git checkout uses the commit, not a VERSION file
}
