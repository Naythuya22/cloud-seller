# Launch AdminSeller Streamlit app (no manual cd / venv / pip each time)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$venvPython = Join-Path $Root '.venv\Scripts\python.exe'
$venvPip    = Join-Path $Root '.venv\Scripts\pip.exe'
$streamlit  = Join-Path $Root '.venv\Scripts\streamlit.exe'

if (-not (Test-Path $venvPython)) {
    Write-Host 'Creating virtual environment...' -ForegroundColor Cyan
    & python -m venv (Join-Path $Root '.venv')
    if (-not (Test-Path $venvPip)) {
        Write-Error 'python -m venv failed. Is Python installed and on PATH?'
        exit 1
    }
    Write-Host 'Installing dependencies (first run)...' -ForegroundColor Cyan
    & $venvPip install -r (Join-Path $Root 'requirements.txt')
}

if (-not (Test-Path $streamlit)) {
    Write-Host 'streamlit missing; installing requirements...' -ForegroundColor Yellow
    & $venvPip install -r (Join-Path $Root 'requirements.txt')
}

& $streamlit run (Join-Path $Root 'app.py')
