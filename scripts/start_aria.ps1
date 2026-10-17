$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
try {
    Set-Location -LiteralPath $projectRoot
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host 'Preparing ARIA. The first start needs Python 3.12 and internet access.'
        & py -3.12 -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12, then run Start ARIA again.' }
    }
    $backendRequirements = Join-Path $projectRoot 'aria_backend\requirements.txt'
    $desktopRequirements = Join-Path $projectRoot 'aria_desktop\requirements.txt'
    $dependencyHash = (Get-FileHash -LiteralPath $backendRequirements).Hash + (Get-FileHash -LiteralPath $desktopRequirements).Hash
    $stamp = Join-Path $projectRoot '.venv\aria-requirements.sha256'
    $installedHash = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { '' }
    if ($installedHash -ne $dependencyHash) {
        Write-Host 'Checking app dependencies. This can take a few minutes on the first start.'
        & $pythonPath -m pip install --disable-pip-version-check -r $backendRequirements -r $desktopRequirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection and run Start ARIA again.' }
        Set-Content -LiteralPath $stamp -Value $dependencyHash
    }
    & $pythonPath (Join-Path $projectRoot 'scripts\launch_aria.py')
    exit $LASTEXITCODE
} catch {
    Write-Host ('ARIA could not start: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
