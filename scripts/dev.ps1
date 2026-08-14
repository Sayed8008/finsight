# Start the FinSight backend and desktop client together (Windows, PowerShell).
#
#     .\scripts\dev.ps1            start both
#     .\scripts\dev.ps1 backend    start only the API
#     .\scripts\dev.ps1 client     start only the desktop client
#
# The backend is stopped automatically when this script exits.

param(
    [ValidateSet('both', 'backend', 'client')]
    [string]$Mode = 'both'
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Error @"
Virtual environment not found at $ProjectRoot\.venv
Create it with:
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
"@
    exit 1
}

$backend = $null

function Start-Backend {
    Write-Host 'Starting API on http://127.0.0.1:8000  (docs at /docs)'
    $script:backend = Start-Process -FilePath $VenvPython `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload' `
        -WorkingDirectory (Join-Path $ProjectRoot 'backend') `
        -NoNewWindow -PassThru
}

function Wait-ForBackend {
    Write-Host -NoNewline 'Waiting for the API to become ready'
    foreach ($_ in 1..40) {
        try {
            Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 1 -UseBasicParsing | Out-Null
            Write-Host ' ready.'
            return
        }
        catch {
            Write-Host -NoNewline '.'
            Start-Sleep -Milliseconds 250
        }
    }
    Write-Host ' timed out (starting the client anyway).'
}

function Start-Client {
    Write-Host 'Starting desktop client'
    & $VenvPython -m client.main
}

try {
    switch ($Mode) {
        'backend' {
            Start-Backend
            Wait-Process -Id $backend.Id
        }
        'client' {
            Start-Client
        }
        'both' {
            Start-Backend
            Wait-ForBackend
            Start-Client
        }
    }
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Write-Host "Stopping backend (pid $($backend.Id))..."
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
