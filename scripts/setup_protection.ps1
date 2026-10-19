$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$previousLocalOnly = $env:LOCAL_ONLY
try {
    Set-Location -LiteralPath $projectRoot
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Run Start ARIA once to prepare Python, then close ARIA and run this setup.'
    }
    Write-Host 'Installing CPU audio protection dependencies and trusted AudioSeal weights.'
    & $pythonPath -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'CPU dependencies could not be installed.' }
    & $pythonPath -m pip install -r (Join-Path $projectRoot 'aria_backend\requirements-watermark.txt')
    if ($LASTEXITCODE -ne 0) { throw 'AudioSeal dependencies could not be installed.' }
    $env:LOCAL_ONLY = 'false'
    & $pythonPath (Join-Path $projectRoot 'aria_backend\scripts\prepare_safety_models.py') --allow-downloads --feature watermark
    if ($LASTEXITCODE -ne 0) { throw 'AudioSeal weights could not be prepared.' }
    Write-Host 'Protection installed. Restart ARIA. Generated audio must pass detection before playback.'
} catch {
    Write-Host ('Protection setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    $env:LOCAL_ONLY = $previousLocalOnly
}
